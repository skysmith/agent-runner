from __future__ import annotations

import json
import re
import subprocess
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .context_assembler import ContextAssembler
from .conversation_store import ConversationStore, WorkspaceConversationController
from .models import AssistantCapabilityMode, AppSettings, ChecksPolicy, ConversationRecord, ProviderKind, RunMode
from .page_context import normalize_page_context
from .providers import ExecutionRequest, PhaseExecutionClient, ProviderRouter, probe_ollama
from .run_coordinator import RunCoordinator, RunStatus
from .runner import AgentRunner, RunnerConfig
from .settings_store import load_app_settings, save_app_settings
from .studio import (
    create_studio_project,
    normalize_template_kind,
    normalize_workspace_kind,
    publish_studio_project,
    slugify_workspace_id,
    studio_actions,
    studio_placeholder,
    studio_summary_prompt,
    studio_welcome_message,
)

ServiceEventCallback = Callable[[str, str], None]


@dataclass(slots=True)
class ServiceConfig:
    repo_path: Path
    artifacts_dir: Path
    settings_path: Path
    provider: ProviderKind
    codex_bin: str
    model: str
    ollama_host: str
    extra_access_dir: Path | None
    max_step_retries: int
    phase_timeout_seconds: int
    check_commands: list[str]
    dry_run: bool


class AgentRunnerService:
    DEFAULT_WEB_WORKSPACE_ID = "default"

    def __init__(
        self,
        config: ServiceConfig,
        *,
        phase_client: PhaseExecutionClient | None = None,
        context_assembler: ContextAssembler | None = None,
        coordinator: RunCoordinator | None = None,
    ) -> None:
        self.config = config
        self.phase_client = phase_client or ProviderRouter()
        self.context_assembler = context_assembler or ContextAssembler()
        self.conversation_store = ConversationStore(config.settings_path.parent / "workspaces")
        self.coordinator = coordinator or RunCoordinator(config.settings_path.parent)
        defaults = AppSettings(
            provider=config.provider,
            model=config.model,
            codex_bin=config.codex_bin,
            ollama_host=config.ollama_host,
            extra_access_dir=config.extra_access_dir,
            max_step_retries=config.max_step_retries,
            phase_timeout_seconds=config.phase_timeout_seconds,
            default_checks=list(config.check_commands),
        )
        self.app_settings = load_app_settings(config.settings_path, defaults)
        self._event_lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._next_event_id = 1
        self._max_events = 2000

    def list_workspaces(self) -> list[dict[str, object]]:
        root = self.conversation_store.root
        workspaces: list[dict[str, object]] = []
        if root.exists():
            for path in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name):
                controller = WorkspaceConversationController(self.conversation_store, path.name)
                active = controller.active_conversation()
                workspaces.append(self._workspace_payload(controller, updated_at=active.updated_at, title=active.title))
        return workspaces

    def ensure_workspace(self, workspace_id: str) -> dict[str, object]:
        controller = self._controller(workspace_id)
        active = controller.active_conversation()
        return self._workspace_payload(controller, updated_at=active.updated_at)

    def list_conversations(self, workspace_id: str) -> list[dict[str, object]]:
        controller = self._controller(workspace_id)
        return [self._record_payload(record) for record in controller.metadata()]

    def list_all_conversations(self) -> list[dict[str, object]]:
        conversations: list[dict[str, object]] = []
        for workspace in self.list_workspaces():
            workspace_id = str(workspace["id"])
            conversations.extend(self.list_conversations(workspace_id))
        conversations.sort(
            key=lambda record: (
                str(record.get("updated_at", "")),
                str(record.get("created_at", "")),
                str(record.get("id", "")),
            ),
            reverse=True,
        )
        return conversations

    def create_conversation(self, workspace_id: str, *, title: str | None = None) -> dict[str, object]:
        controller = self._controller(workspace_id)
        record = controller.create_conversation()
        if title:
            record = controller.rename_conversation(record.id, title)
        payload = self._record_payload(record)
        self._emit_event(
            "conversation.created",
            {
                "workspace_id": workspace_id,
                "conversation_id": record.id,
                "title": record.title,
            },
        )
        return payload

    def create_web_conversation(self, *, title: str | None = None) -> dict[str, object]:
        return self.create_conversation(self.DEFAULT_WEB_WORKSPACE_ID, title=title)

    def create_studio_game(
        self,
        *,
        game_title: str,
        template_kind: str,
        theme_prompt: str | None = None,
    ) -> dict[str, object]:
        return self.create_studio_workspace(
            workspace_kind="studio_game",
            artifact_title=game_title,
            template_kind=template_kind,
            theme_prompt=theme_prompt,
        )

    def create_studio_workspace(
        self,
        *,
        workspace_kind: str,
        artifact_title: str,
        template_kind: str,
        theme_prompt: str | None = None,
    ) -> dict[str, object]:
        kind = normalize_workspace_kind(workspace_kind)
        title = artifact_title.strip() or "New Studio"
        workspace_id = self._unique_workspace_id(title)
        project = create_studio_project(
            root=self._studio_projects_root(),
            workspace_id=workspace_id,
            workspace_kind=kind,
            artifact_title=title,
            template_kind=normalize_template_kind(kind, template_kind),
            theme_prompt=theme_prompt,
        )
        preview_url = f"/studio/preview/{workspace_id}/index.html"
        controller = self._controller(workspace_id)
        controller.set_workspace_profile(
            display_name=project.artifact_title,
            repo_path=str(project.repo_path),
            workspace_kind=project.workspace_kind,
            artifact_title=project.artifact_title,
            template_kind=project.template_kind,
            theme_prompt=project.theme_prompt,
            preview_url=preview_url,
            preview_state="ready",
            publish_state="draft",
        )
        record = controller.active_conversation()
        controller.rename_conversation(record.id, f"{project.artifact_title} Studio")
        controller.set_assistant_context(record.id, assistant_mode=AssistantCapabilityMode.DEV)
        controller.append_message(
            role="assistant",
            content=studio_welcome_message(project),
            phase="message",
        )
        self._emit_event(
            "workspace.created",
            {
                "workspace_id": workspace_id,
                "workspace_kind": project.workspace_kind,
                "artifact_title": project.artifact_title,
                "template_kind": project.template_kind,
            },
        )
        workspace = self.ensure_workspace(workspace_id)
        conversation = self.get_conversation(str(workspace["active_conversation_id"]), workspace_id=workspace_id)
        return {
            "workspace": workspace,
            "conversation": conversation,
        }

    def get_studio_workspace(self, workspace_id: str) -> dict[str, object]:
        controller = self._controller(workspace_id)
        if not self._is_studio_workspace_kind(controller.state.workspace_kind):
            raise ValueError("Workspace is not an Alcove Studio workspace.")
        conversation = self.get_conversation(str(controller.state.active_conversation_id), workspace_id=workspace_id)
        return {
            "workspace": self.ensure_workspace(workspace_id),
            "conversation": conversation,
            "actions": studio_actions(controller.state.workspace_kind),
            "advanced": {
                "repo_path": controller.state.repo_path,
                "workspace_id": workspace_id,
                "workspace_kind": controller.state.workspace_kind,
                "template_kind": controller.state.template_kind,
            },
        }

    def refresh_studio_preview(self, workspace_id: str) -> dict[str, object]:
        controller = self._controller(workspace_id)
        if not self._is_studio_workspace_kind(controller.state.workspace_kind):
            raise ValueError("Workspace is not an Alcove Studio workspace.")
        repo_path = self._workspace_repo_path(workspace_id)
        self._prepare_studio_preview(workspace_id, repo_path)
        preview_relative_path = self._studio_entry_relative_path(workspace_id)
        preview_state = "ready" if (repo_path / preview_relative_path).exists() else "error"
        controller.set_workspace_profile(
            preview_url=f"/studio/preview/{workspace_id}/{preview_relative_path}",
            preview_state=preview_state,
        )
        payload = self.ensure_workspace(workspace_id)
        self._emit_event(
            "workspace.updated",
            {
                "workspace_id": workspace_id,
                "preview_state": preview_state,
                "preview_url": payload.get("preview_url"),
            },
        )
        return payload

    def publish_studio_game(self, workspace_id: str) -> dict[str, object]:
        return self.publish_studio_workspace(workspace_id)

    def publish_studio_workspace(self, workspace_id: str) -> dict[str, object]:
        controller = self._controller(workspace_id)
        if not self._is_studio_workspace_kind(controller.state.workspace_kind):
            raise ValueError("Workspace is not an Alcove Studio workspace.")
        repo_path = self._workspace_repo_path(workspace_id)
        slug = controller.state.publish_slug or slugify_workspace_id(controller.state.artifact_title or workspace_id)
        preview_relative_path = self._studio_entry_relative_path(workspace_id)
        publish_studio_project(source_repo=repo_path, publish_root=self._published_games_root(), publish_slug=slug)
        publish_url = f"/play/{slug}/{preview_relative_path}"
        controller.set_workspace_profile(
            publish_slug=slug,
            publish_url=publish_url,
            publish_state="published",
        )
        payload = self.ensure_workspace(workspace_id)
        self._emit_event(
            "workspace.updated",
            {
                "workspace_id": workspace_id,
                "publish_state": "published",
                "publish_url": publish_url,
            },
        )
        return payload

    def define_workspace(
        self,
        workspace_id: str,
        *,
        display_name: str | None = None,
        repo_path: str | None = None,
        workspace_kind: str | None = None,
        artifact_title: str | None = None,
        template_kind: str | None = None,
        game_title: str | None = None,
        theme_prompt: str | None = None,
        preview_url: str | None = None,
        preview_state: str | None = None,
        publish_url: str | None = None,
        publish_state: str | None = None,
        publish_slug: str | None = None,
    ) -> dict[str, object]:
        controller = self._controller(workspace_id)
        controller.set_workspace_profile(
            display_name=display_name,
            repo_path=repo_path,
            workspace_kind=workspace_kind,
            artifact_title=artifact_title,
            template_kind=template_kind,
            game_title=game_title,
            theme_prompt=theme_prompt,
            preview_url=preview_url,
            preview_state=preview_state,
            publish_url=publish_url,
            publish_state=publish_state,
            publish_slug=publish_slug,
        )
        active = controller.active_conversation()
        self._emit_event(
            "workspace.updated",
            {
                "workspace_id": workspace_id,
                "display_name": controller.state.display_name or workspace_id,
                "repo_path": controller.state.repo_path,
                "active_conversation_id": active.id,
                "workspace_kind": controller.state.workspace_kind,
            },
        )
        return self.ensure_workspace(workspace_id)

    def get_conversation(self, conversation_id: str, *, workspace_id: str | None = None) -> dict[str, object]:
        record, resolved_workspace_id = self._find_conversation(conversation_id, workspace_id=workspace_id)
        controller = self._controller(resolved_workspace_id)
        controller.select_conversation(record.id)
        return self._record_payload(record, include_messages=True)

    def rename_conversation(self, conversation_id: str, *, workspace_id: str | None, title: str) -> dict[str, object]:
        record, resolved_workspace_id = self._find_conversation(conversation_id, workspace_id=workspace_id)
        controller = self._controller(resolved_workspace_id)
        updated = controller.rename_conversation(record.id, title)
        self._emit_event(
            "conversation.updated",
            {
                "workspace_id": resolved_workspace_id,
                "conversation_id": updated.id,
                "title": updated.title,
            },
        )
        return self._record_payload(updated)

    def delete_conversation(self, conversation_id: str, *, workspace_id: str | None = None) -> dict[str, object]:
        record, resolved_workspace_id = self._find_conversation(conversation_id, workspace_id=workspace_id)
        controller = self._controller(resolved_workspace_id)
        fallback = controller.delete_conversation(record.id)
        self._emit_event(
            "conversation.deleted",
            {
                "workspace_id": resolved_workspace_id,
                "conversation_id": record.id,
                "fallback_conversation_id": fallback.id,
            },
        )
        return self._record_payload(fallback)

    def clear_conversation(self, conversation_id: str, *, workspace_id: str | None = None) -> dict[str, object]:
        record, resolved_workspace_id = self._find_conversation(conversation_id, workspace_id=workspace_id)
        controller = self._controller(resolved_workspace_id)
        cleared = controller.clear_conversation(record.id)
        self._emit_event(
            "conversation.updated",
            {
                "workspace_id": resolved_workspace_id,
                "conversation_id": cleared.id,
                "cleared": True,
            },
        )
        return self._record_payload(cleared, include_messages=True)

    def send_message(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        content: str,
        mode: RunMode,
        assistant_mode: AssistantCapabilityMode | None = None,
        page_context: dict[str, object] | None = None,
        provider: ProviderKind | None = None,
        model: str | None = None,
        max_step_retries: int | None = None,
        event_callback: ServiceEventCallback | None = None,
    ) -> dict[str, object]:
        clean_text = content.strip()
        if not clean_text:
            raise ValueError("Message content cannot be empty.")
        if not self.coordinator.try_start(
            workspace_id,
            conversation_id=conversation_id,
            mode=str(mode),
            run_id=str(uuid.uuid4()),
            last_prompt=clean_text,
        ):
            status = self.coordinator.get_status()
            raise RuntimeError(
                f"Another workspace is running ({status.workspace_id or 'unknown'}). Please wait for it to finish."
            )

        controller = self._controller(workspace_id)
        normalized_page_context = normalize_page_context(page_context)
        controller.select_conversation(conversation_id)
        if assistant_mode is not None or page_context is not None:
            controller.set_assistant_context(
                conversation_id,
                assistant_mode=assistant_mode,
                page_context=normalized_page_context if page_context is not None else None,
            )
        active_record = controller.active_conversation()
        effective_assistant_mode = active_record.assistant_mode
        effective_page_context = active_record.page_context
        workspace_repo_path = self._workspace_repo_path(workspace_id)
        if mode == RunMode.LOOP and effective_assistant_mode != AssistantCapabilityMode.DEV:
            self.coordinator.finish(workspace_id)
            raise ValueError("Loop mode requires dev assistant capability mode.")

        user_record = controller.append_message(role="user", content=clean_text)
        self._refresh_summary_if_needed(controller, user_record.id)
        resolved_provider, resolved_model = self._effective_provider_and_model(provider=provider, model=model)
        effective_context = (
            self.context_assembler.build_for_loop(
                repo_path=workspace_repo_path,
                provider=resolved_provider,
                model=resolved_model,
                run_mode=mode,
                conversation=active_record,
                current_input=clean_text,
                assistant_mode=effective_assistant_mode,
                page_context=effective_page_context,
            )
            if mode == RunMode.LOOP
            else self.context_assembler.build_for_message(
                repo_path=workspace_repo_path,
                provider=resolved_provider,
                model=resolved_model,
                run_mode=mode,
                conversation=active_record,
                current_input=clean_text,
                assistant_mode=effective_assistant_mode,
                page_context=effective_page_context,
            )
        )

        self.coordinator.update_status(
            state="starting",
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            mode=str(mode),
            step="Sending message" if mode == RunMode.MESSAGE else "Getting ready",
            error="",
            last_error="",
            stop_requested=False,
        )
        self._emit_run_event("run.started")
        self._emit_event(
            "conversation.updated",
            {
                "workspace_id": workspace_id,
                "conversation_id": conversation_id,
            },
        )

        worker = threading.Thread(
            target=self._run_background_interaction,
            args=(
                workspace_id,
                conversation_id,
                clean_text,
                mode,
                effective_context,
                resolved_provider,
                resolved_model,
                max_step_retries,
                event_callback,
                workspace_repo_path,
            ),
            daemon=True,
        )
        worker.start()
        return {
            "accepted": True,
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "mode": str(mode),
            "assistant_mode": str(effective_assistant_mode),
        }

    def update_conversation_context(
        self,
        conversation_id: str,
        *,
        workspace_id: str | None = None,
        assistant_mode: AssistantCapabilityMode | None = None,
        page_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        record, resolved_workspace_id = self._find_conversation(conversation_id, workspace_id=workspace_id)
        controller = self._controller(resolved_workspace_id)
        updated = controller.set_assistant_context(
            record.id,
            assistant_mode=assistant_mode,
            page_context=normalize_page_context(page_context) if page_context is not None else None,
        )
        self._emit_event(
            "conversation.updated",
            {
                "workspace_id": resolved_workspace_id,
                "conversation_id": updated.id,
                "assistant_mode": str(updated.assistant_mode),
                "has_page_context": bool(updated.page_context),
            },
        )
        return self._record_payload(updated, include_messages=True)

    def stop_run(self) -> dict[str, object]:
        status = self.coordinator.get_status()
        if status.state not in {"starting", "running", "stopping"}:
            return status.to_dict()
        updated = self.coordinator.request_stop().to_dict()
        self._emit_run_event("run.stop_requested", status=updated)
        return updated

    def recover_run(self) -> dict[str, object]:
        status = self.coordinator.get_status()
        if status.state in {"starting", "running", "stopping"}:
            raise RuntimeError("Run is active. Stop it before running stale recovery.")
        recovered = self.coordinator.recover_stale_run().to_dict()
        self._emit_run_event("run.recovered", status=recovered)
        return recovered

    def retry_last_prompt(self) -> dict[str, object]:
        status = self.coordinator.get_status()
        if status.state in {"starting", "running", "stopping"}:
            raise RuntimeError("A run is already active. Stop it before retrying.")

        workspace_id, conversation_id = self._resolve_retry_target(status)
        conversation = self.get_conversation(conversation_id, workspace_id=workspace_id)
        messages = conversation.get("messages", [])
        last_user_text = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                last_user_text = str(message.get("content", "")).strip()
                if last_user_text:
                    break
        if not last_user_text:
            raise ValueError("Could not find a previous user prompt to retry.")

        requested_mode = status.mode or str(RunMode.MESSAGE)
        try:
            mode = RunMode(requested_mode)
        except ValueError:
            mode = RunMode.MESSAGE

        return self.send_message(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            content=last_user_text,
            mode=mode,
        )

    def get_run_status(self) -> dict[str, object]:
        return self.coordinator.get_status().to_dict()

    def get_settings(self) -> dict[str, object]:
        settings = self.app_settings
        return {
            "provider": str(settings.provider),
            "model": settings.model,
            "planner_model": settings.planner_model,
            "builder_model": settings.builder_model,
            "reviewer_model": settings.reviewer_model,
            "ollama_host": settings.ollama_host,
            "max_step_retries": settings.max_step_retries,
            "phase_timeout_seconds": settings.phase_timeout_seconds,
        }

    def update_settings(self, payload: dict[str, object]) -> dict[str, object]:
        settings = self.app_settings
        provider_text = str(payload.get("provider", settings.provider)).strip().lower()
        if provider_text == str(ProviderKind.OLLAMA):
            settings.provider = ProviderKind.OLLAMA
        elif provider_text == str(ProviderKind.CODEX):
            settings.provider = ProviderKind.CODEX
        model = str(payload.get("model", settings.model)).strip()
        if model:
            settings.model = model
        settings.planner_model = _optional_text(payload.get("planner_model"), settings.planner_model)
        settings.builder_model = _optional_text(payload.get("builder_model"), settings.builder_model)
        settings.reviewer_model = _optional_text(payload.get("reviewer_model"), settings.reviewer_model)
        ollama_host = str(payload.get("ollama_host", settings.ollama_host)).strip()
        if ollama_host:
            settings.ollama_host = ollama_host
        retries = payload.get("max_step_retries")
        if retries is not None:
            settings.max_step_retries = max(0, int(retries))
        timeout = payload.get("phase_timeout_seconds")
        if timeout is not None:
            settings.phase_timeout_seconds = max(30, int(timeout))
        save_app_settings(self.config.settings_path, settings)
        return self.get_settings()

    def list_ollama_models(self) -> dict[str, object]:
        result = probe_ollama(self.app_settings.ollama_host)
        return {
            "available": result.available,
            "models": result.models,
            "message": result.message,
            "host": self.app_settings.ollama_host,
        }

    def get_review_snapshot(
        self,
        *,
        conversation_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, object]:
        status = self.get_run_status()
        record: ConversationRecord | None = None
        resolved_workspace_id: str | None = workspace_id
        if conversation_id:
            try:
                record, resolved_workspace_id = self._find_conversation(
                    conversation_id,
                    workspace_id=workspace_id,
                )
            except KeyError:
                record = None
        latest = self._latest_operational_message(record)
        extracted = self._extract_review_fields(latest)
        return {
            "conversation_id": conversation_id,
            "workspace_id": resolved_workspace_id,
            "run": {
                "state": status.get("state"),
                "mode": status.get("mode"),
                "step": status.get("step"),
                "run_id": status.get("run_id"),
                "started_at": status.get("started_at"),
                "updated_at": status.get("updated_at"),
                "heartbeat_at": status.get("heartbeat_at"),
                "finished_at": status.get("finished_at"),
                "stop_requested": status.get("stop_requested"),
                "active_workspace_id": status.get("workspace_id"),
                "active_conversation_id": status.get("conversation_id"),
                "last_error": status.get("last_error") or status.get("error"),
            },
            "latest_result": {
                "phase": latest.phase if latest else None,
                "content": latest.content if latest else "",
                "created_at": latest.created_at if latest else None,
            },
            "summary": extracted.get("summary", ""),
            "changed_files": extracted.get("changed_files", []),
            "checks": extracted.get("checks", {}),
            "artifacts_path": extracted.get("artifacts_path"),
        }

    def list_events_since(self, cursor: str | None = None, *, limit: int = 100) -> dict[str, object]:
        with self._event_lock:
            start_id = _parse_cursor(cursor)
            bounded_limit = min(max(1, limit), 500)
            events = [event for event in self._events if int(event["id"]) > start_id][:bounded_limit]
            next_cursor = cursor or "0"
            if events:
                next_cursor = str(events[-1]["id"])
            elif self._events:
                next_cursor = str(self._events[-1]["id"])
            return {
                "events": events,
                "next_cursor": next_cursor,
            }

    def _run_background_interaction(
        self,
        workspace_id: str,
        conversation_id: str,
        prompt: str,
        mode: RunMode,
        effective_context,
        provider: ProviderKind,
        model: str,
        max_step_retries: int | None,
        event_callback: ServiceEventCallback | None,
        workspace_repo_path: Path,
    ) -> None:
        heartbeat_stop = threading.Event()
        heartbeat_worker = threading.Thread(
            target=self._heartbeat_loop,
            args=(heartbeat_stop,),
            daemon=True,
        )
        heartbeat_worker.start()
        try:
            self.coordinator.update_status(
                state="running",
                step="Sending message" if mode == RunMode.MESSAGE else "Starting loop",
                error="",
                last_error="",
            )
            self._emit_run_event("run.state_changed")
            if mode == RunMode.MESSAGE:
                self._run_message_mode(
                    workspace_id=workspace_id,
                    conversation_id=conversation_id,
                    provider=provider,
                    model=model,
                    effective_context=effective_context,
                    workspace_repo_path=workspace_repo_path,
                )
                if event_callback:
                    event_callback("message_done", "Complete")
                return

            global_settings = self.app_settings
            check_commands = (
                list(self.config.check_commands)
                if self.config.check_commands
                else (
                    list(global_settings.default_checks)
                    if global_settings.checks_policy == ChecksPolicy.CUSTOM
                    else None
                )
            )
            config = RunnerConfig(
                task_file=None,
                task_text=prompt,
                repo_path=workspace_repo_path,
                artifacts_dir=self.config.artifacts_dir,
                codex_bin=global_settings.codex_bin,
                provider=provider,
                model=model,
                planner_model=global_settings.planner_model,
                builder_model=global_settings.builder_model,
                reviewer_model=global_settings.reviewer_model,
                ollama_host=global_settings.ollama_host,
                extra_access_dir=global_settings.extra_access_dir,
                max_step_retries=max(0, max_step_retries if max_step_retries is not None else global_settings.max_step_retries),
                phase_timeout_seconds=global_settings.phase_timeout_seconds,
                check_commands=check_commands,
                conversation_context=effective_context.conversation_context,
                dry_run=self.config.dry_run,
                progress=False,
                status_callback=lambda msg: self._handle_runner_status(msg, event_callback),
                stop_requested=self.coordinator.stop_requested,
            )
            runner = AgentRunner(config)
            outcome = runner.run()
            self._append_loop_result(
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                outcome=outcome,
                artifacts_dir=str(runner.store.run_dir),
                build_number=runner.store.build_number,
            )
            self._refresh_preview_after_run(workspace_id)
            self.coordinator.update_status(
                state="succeeded" if outcome.ok else "failed",
                step="Complete" if outcome.ok else "Needs attention",
                error="" if outcome.ok else outcome.reason,
                last_error="" if outcome.ok else outcome.reason,
                stop_requested=False,
            )
            self._emit_run_event("run.succeeded" if outcome.ok else "run.failed")
            self.coordinator.finish(workspace_id)
            if event_callback:
                event_callback("done", outcome.final_message or outcome.reason or "Complete")
        except Exception as exc:
            self._append_assistant_message(
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                text=f"Run failed.\n\nReason: {exc}",
                phase="error",
            )
            self.coordinator.update_status(
                state="failed",
                step="Needs attention",
                error=str(exc),
                last_error=str(exc),
                stop_requested=False,
            )
            self._emit_run_event("run.failed")
            self.coordinator.finish(workspace_id)
            if event_callback:
                event_callback("error", str(exc))
        finally:
            heartbeat_stop.set()

    def _run_message_mode(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        provider: ProviderKind,
        model: str,
        effective_context,
        workspace_repo_path: Path,
    ) -> None:
        self._handle_runner_status("Phase: message", None)
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["message"],
            "properties": {"message": {"type": "string"}},
        }
        response = self.phase_client.run(
            ExecutionRequest(
                provider=provider,
                codex_bin=self.app_settings.codex_bin,
                model=model,
                prompt=(
                    "You are a concise coding assistant for this repository. "
                    "Respond to the user's message directly. Do not perform iterative planning/build/review loops. "
                    "Return JSON matching schema.\n\n"
                    f"{effective_context.system_context}\n\n"
                    f"{effective_context.conversation_context}\n\n"
                    f"{effective_context.current_input}\n"
                ),
                schema=schema,
                repo_path=workspace_repo_path,
                extra_access_dir=self.app_settings.extra_access_dir,
                ollama_host=self.app_settings.ollama_host,
                dry_run=self.config.dry_run,
                timeout_seconds=self.app_settings.phase_timeout_seconds,
                phase_name="message",
            )
        )
        message = str(response.payload.get("message", "")).strip()
        if not message:
            message = json.dumps(response.payload, indent=2, sort_keys=True)
        self._append_assistant_message(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            text=f"Message response received.\n\n{message}" if message else "Message response received.",
            phase="message",
        )
        self._refresh_preview_after_run(workspace_id)
        self.coordinator.update_status(
            state="succeeded",
            step="Complete",
            error="",
            last_error="",
            stop_requested=False,
        )
        self._emit_run_event("run.succeeded")
        self.coordinator.finish(workspace_id)

    def _append_loop_result(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        outcome,
        artifacts_dir: str,
        build_number: int | None,
    ) -> None:
        check_results = []
        change_lines: list[str] = []
        for step_run in getattr(outcome, "step_runs", []):
            summary = step_run.build_result.summary.strip()
            if summary:
                change_lines.append(f"{step_run.step_id}: {summary}")
            files = step_run.build_result.files_touched
            if files:
                preview = ", ".join(files[:3])
                suffix = "..." if len(files) > 3 else ""
                change_lines.append(f"Updated {len(files)} file(s): {preview}{suffix}")
            commands = step_run.build_result.commands_run
            if commands:
                change_lines.append(f"Ran {len(commands)} command(s) to do the work.")
            check_results.extend(step_run.check_results)
        if getattr(outcome, "ok", False):
            if getattr(outcome, "final_message", ""):
                change_lines.insert(0, f"Result: {outcome.final_message}")
        else:
            reason = getattr(outcome, "reason", "Run failed.")
            change_lines.insert(0, f"Needs attention: {reason}")
        if not change_lines:
            change_lines = ["Run finished with no reported changes."]
        if isinstance(build_number, int):
            change_lines.insert(0, f"Build number: {build_number}")
        if artifacts_dir:
            change_lines.append(f"Artifacts: {artifacts_dir}")
        if check_results:
            passed = sum(1 for c in check_results if c.ok)
            failed = sum(1 for c in check_results if not c.ok)
            change_lines.append(f"Checks: {passed} passed, {failed} failed")
        self._append_assistant_message(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            text="\n".join(change_lines),
            phase="loop-final",
        )

    def _append_assistant_message(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        text: str,
        phase: str,
    ) -> None:
        controller = self._controller(workspace_id)
        controller.select_conversation(conversation_id)
        record = controller.append_message(role="assistant", content=text, phase=phase)
        self._refresh_summary_if_needed(controller, record.id)
        self._emit_event(
            "conversation.updated",
            {
                "workspace_id": workspace_id,
                "conversation_id": conversation_id,
            },
        )

    def _handle_runner_status(self, message: str, event_callback: ServiceEventCallback | None) -> None:
        step = "Working"
        if "Phase: planner" in message:
            step = "Understanding your request"
        elif "Phase: message" in message:
            step = "Sending message"
        elif "builder" in message:
            step = "Making updates"
        elif "reviewer" in message:
            step = "Checking the result"
        elif "Run finished:" in message:
            step = "Wrapping up"
        status = self.coordinator.get_status()
        if status.state in {"starting", "running", "stopping"}:
            if status.step != step or status.state != "running" or status.error or status.last_error:
                self.coordinator.update_status(
                    state="running",
                    step=step,
                    error="",
                    last_error="",
                )
                self._emit_run_event("run.step_changed")
        if event_callback:
            event_callback("status", message)

    def _heartbeat_loop(self, stop_event: threading.Event) -> None:
        while not stop_event.wait(5.0):
            status = self.coordinator.get_status()
            if status.state not in {"starting", "running", "stopping"}:
                return
            self.coordinator.touch_heartbeat()

    def _effective_provider_and_model(
        self,
        *,
        provider: ProviderKind | None = None,
        model: str | None = None,
    ) -> tuple[ProviderKind, str]:
        return provider or self.app_settings.provider, model or self.app_settings.model

    def _refresh_preview_after_run(self, workspace_id: str) -> None:
        controller = self._controller(workspace_id)
        if not self._is_studio_workspace_kind(controller.state.workspace_kind):
            return
        repo_path = self._workspace_repo_path(workspace_id)
        preview_relative_path = self._studio_entry_relative_path(workspace_id)
        preview_state = "ready" if (repo_path / preview_relative_path).exists() else "error"
        controller.set_workspace_profile(
            preview_url=f"/studio/preview/{workspace_id}/{preview_relative_path}",
            preview_state=preview_state,
        )
        self._emit_event(
            "workspace.updated",
            {
                "workspace_id": workspace_id,
                "preview_url": controller.state.preview_url,
                "preview_state": controller.state.preview_state,
            },
        )

    def _workspace_repo_path(self, workspace_id: str) -> Path:
        controller = self._controller(workspace_id)
        configured = (controller.state.repo_path or "").strip()
        if not configured:
            return self.config.repo_path
        resolved = Path(configured).expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(f"Workspace repo path does not exist: {resolved}")
        return resolved

    def list_active_repositories(
        self,
        *,
        root: Path | None = None,
        limit: int = 12,
    ) -> list[dict[str, object]]:
        scan_root = (root or (Path.home() / "Documents" / "codex")).expanduser().resolve()
        if not scan_root.exists() or not scan_root.is_dir():
            raise ValueError(f"Repository scan root does not exist: {scan_root}")
        bounded_limit = min(max(1, limit), 50)
        candidates: list[dict[str, object]] = []
        seen_repos: set[Path] = set()
        for git_dir in scan_root.rglob(".git"):
            if not git_dir.is_dir():
                continue
            repo = git_dir.parent.resolve()
            if repo in seen_repos:
                continue
            seen_repos.add(repo)
            if _is_hidden_relative(repo, scan_root):
                continue
            metadata = _repo_activity_metadata(repo)
            if metadata is None:
                continue
            candidates.append(metadata)
        candidates.sort(
            key=lambda item: (
                int(item.get("activity_score", 0)),
                int(item.get("recent_commits_7d", 0)),
                int(item.get("recent_commits_30d", 0)),
                str(item.get("last_commit_at", "")),
            ),
            reverse=True,
        )
        return candidates[:bounded_limit]

    def _controller(self, workspace_id: str) -> WorkspaceConversationController:
        return WorkspaceConversationController(self.conversation_store, workspace_id)

    def studio_preview_file(self, workspace_id: str, relative_path: str) -> Path:
        controller = self._controller(workspace_id)
        if not self._is_studio_workspace_kind(controller.state.workspace_kind):
            raise ValueError("Workspace is not an Alcove Studio workspace.")
        repo_path = self._workspace_repo_path(workspace_id).resolve()
        candidate = (repo_path / relative_path).resolve()
        if candidate != repo_path and repo_path not in candidate.parents:
            raise ValueError("Invalid preview path.")
        if not candidate.exists() or not candidate.is_file():
            raise FileNotFoundError(relative_path)
        return candidate

    def published_game_file(self, publish_slug: str, relative_path: str) -> Path:
        root = self._published_games_root().resolve()
        game_root = (root / publish_slug).resolve()
        candidate = (game_root / relative_path).resolve()
        if game_root != root and root not in game_root.parents:
            raise ValueError("Invalid publish path.")
        if candidate != game_root and game_root not in candidate.parents:
            raise ValueError("Invalid publish path.")
        if not candidate.exists() or not candidate.is_file():
            raise FileNotFoundError(relative_path)
        return candidate

    def _is_studio_workspace_kind(self, workspace_kind: str | None) -> bool:
        return str(workspace_kind or "").startswith("studio_")

    def _studio_entry_relative_path(self, workspace_id: str) -> str:
        controller = self._controller(workspace_id)
        preview_url = str(controller.state.preview_url or "").strip()
        prefix = f"/studio/preview/{workspace_id}/"
        if preview_url.startswith(prefix):
            relative = preview_url[len(prefix):].strip().lstrip("/")
            if relative:
                return relative
        return "index.html"

    def _prepare_studio_preview(self, workspace_id: str, repo_path: Path) -> None:
        preview_relative_path = self._studio_entry_relative_path(workspace_id)
        package_json_path = repo_path / "package.json"
        if not package_json_path.exists():
            return
        if not preview_relative_path.startswith("dist/"):
            return
        scripts = self._package_scripts(package_json_path)
        build_script = str(scripts.get("build") or "").strip()
        if not build_script:
            return
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=repo_path,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Build failed").strip()
            raise ValueError(f"Could not build Studio preview: {detail}")

    def _package_scripts(self, package_json_path: Path) -> dict[str, object]:
        try:
            payload = json.loads(package_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        scripts = payload.get("scripts")
        if not isinstance(scripts, dict):
            return {}
        return {str(key): value for key, value in scripts.items()}

    def _find_conversation(
        self,
        conversation_id: str,
        *,
        workspace_id: str | None,
    ) -> tuple[ConversationRecord, str]:
        if workspace_id:
            record = self.conversation_store.load_conversation(conversation_id, workspace_id=workspace_id)
            if record is None:
                raise KeyError(conversation_id)
            return record, workspace_id
        for workspace in self.list_workspaces():
            workspace_name = str(workspace["id"])
            record = self.conversation_store.load_conversation(conversation_id, workspace_id=workspace_name)
            if record is not None:
                return record, workspace_name
        raise KeyError(conversation_id)

    def _resolve_retry_target(self, status: RunStatus) -> tuple[str, str]:
        if status.workspace_id and status.conversation_id:
            return status.workspace_id, status.conversation_id
        conversations = self.list_all_conversations()
        if not conversations:
            raise ValueError("No conversation exists yet. Start a chat first.")
        latest = conversations[0]
        return str(latest["workspace_id"]), str(latest["id"])

    def _refresh_summary_if_needed(self, controller: WorkspaceConversationController, conversation_id: str) -> None:
        record = controller.active_conversation()
        if record.id != conversation_id:
            return
        summary = self.context_assembler.refresh_summary(record)
        if summary != record.summary:
            controller.update_summary(conversation_id, summary)

    def _record_payload(self, record: ConversationRecord, *, include_messages: bool = False) -> dict[str, object]:
        workspace = self.ensure_workspace(record.workspace_id)
        payload = {
            "id": record.id,
            "workspace_id": record.workspace_id,
            "workspace_display_name": workspace.get("display_name") or record.workspace_id,
            "workspace_repo_path": workspace.get("repo_path"),
            "title": record.title,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "assistant_mode": str(record.assistant_mode),
            "page_context": dict(record.page_context),
            "summary": record.summary,
            "preview": self._conversation_preview(record),
            "workspace_kind": workspace.get("workspace_kind", "standard"),
        }
        if include_messages:
            payload["messages"] = [asdict(message) for message in record.messages]
        else:
            payload["message_count"] = len(record.messages)
        return payload

    def _conversation_preview(self, record: ConversationRecord) -> str:
        if not record.messages:
            return "No messages yet."
        latest = record.messages[-1]
        content = latest.content.strip()
        if latest.role == "assistant" and latest.phase == "message":
            content = content.removeprefix("Message response received.\n\n").strip()
        content = " ".join(part.strip() for part in content.splitlines() if part.strip())
        if not content:
            return "No preview available."
        preview = f"You: {content}" if latest.role == "user" else content
        return preview[:96].rstrip() + ("…" if len(preview) > 96 else "")

    def _workspace_payload(
        self,
        controller: WorkspaceConversationController,
        *,
        updated_at: str,
        title: str | None = None,
    ) -> dict[str, object]:
        return {
            "id": controller.workspace_id,
            "display_name": controller.state.display_name or controller.workspace_id,
            "repo_path": controller.state.repo_path,
            "active_conversation_id": controller.state.active_conversation_id,
            "conversation_count": len(controller.state.conversation_ids),
            "conversations_panel_collapsed": controller.state.conversations_panel_collapsed,
            "updated_at": updated_at,
            "title": title,
            "workspace_kind": controller.state.workspace_kind,
            "artifact_title": controller.state.artifact_title or controller.state.game_title,
            "template_kind": controller.state.template_kind,
            "game_title": controller.state.artifact_title or controller.state.game_title,
            "theme_prompt": controller.state.theme_prompt,
            "preview_url": controller.state.preview_url,
            "preview_state": controller.state.preview_state,
            "publish_url": controller.state.publish_url,
            "publish_state": controller.state.publish_state,
            "publish_slug": controller.state.publish_slug,
        }

    def _studio_projects_root(self) -> Path:
        root = self.config.settings_path.parent / "studio-projects"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _published_games_root(self) -> Path:
        root = self.config.settings_path.parent / "studio-published"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _unique_workspace_id(self, title: str) -> str:
        base = slugify_workspace_id(title)
        candidate = base
        existing = {str(item["id"]) for item in self.list_workspaces()}
        index = 2
        while candidate in existing:
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    def _emit_run_event(self, event_type: str, *, status: dict[str, object] | None = None) -> None:
        payload = {
            "status": status if status is not None else self.get_run_status(),
        }
        self._emit_event(event_type, payload)

    def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        with self._event_lock:
            event = {
                "id": str(self._next_event_id),
                "timestamp": _timestamp_now(),
                "type": event_type,
                "payload": payload,
            }
            self._next_event_id += 1
            self._events.append(event)
            if len(self._events) > self._max_events:
                overflow = len(self._events) - self._max_events
                self._events = self._events[overflow:]

    def _latest_operational_message(self, record: ConversationRecord | None):
        if record is None:
            return None
        for message in reversed(record.messages):
            if message.role != "assistant":
                continue
            if message.phase in {"loop-final", "error", "message"}:
                return message
        return None

    def _extract_review_fields(self, message) -> dict[str, object]:
        if message is None:
            return {
                "summary": "",
                "changed_files": [],
                "checks": {},
                "artifacts_path": None,
            }
        summary = ""
        changed_files: list[str] = []
        checks: dict[str, int] = {}
        artifacts_path: str | None = None
        for raw_line in message.content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("Result: ") or line.startswith("Needs attention: "):
                if not summary:
                    summary = line
                continue
            if line.startswith("Updated ") and "file(s):" in line:
                _, _, value = line.partition("file(s):")
                for chunk in value.split(","):
                    item = chunk.strip()
                    if item:
                        changed_files.append(item.rstrip("."))
                continue
            if line.startswith("Checks: "):
                checks_payload = line.removeprefix("Checks: ").strip()
                for chunk in checks_payload.split(","):
                    part = chunk.strip()
                    if part.endswith(" passed"):
                        number = part.removesuffix(" passed").strip()
                        if number.isdigit():
                            checks["passed"] = int(number)
                    elif part.endswith(" failed"):
                        number = part.removesuffix(" failed").strip()
                        if number.isdigit():
                            checks["failed"] = int(number)
                continue
            if line.startswith("Artifacts: "):
                artifacts_path = line.removeprefix("Artifacts: ").strip()
        if not summary:
            summary = message.content.strip().splitlines()[0] if message.content.strip() else ""
        return {
            "summary": summary,
            "changed_files": changed_files,
            "checks": checks,
            "artifacts_path": artifacts_path,
        }


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    text = cursor.strip()
    if not text:
        return 0
    try:
        value = int(text)
    except ValueError:
        return 0
    return max(0, value)


def _optional_text(value: object, fallback: str | None = None) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return fallback


def _repo_activity_metadata(repo_path: Path) -> dict[str, object] | None:
    try:
        last_commit_ts = _git_text(repo_path, ["log", "-1", "--format=%ct"])
    except RuntimeError:
        return None
    if not last_commit_ts.isdigit():
        return None
    try:
        last_commit_at = datetime.fromtimestamp(int(last_commit_ts), tz=timezone.utc)
    except (OverflowError, ValueError):
        return None
    recent_7d = _git_int(repo_path, ["rev-list", "--count", "--since=7.days", "HEAD"])
    recent_30d = _git_int(repo_path, ["rev-list", "--count", "--since=30.days", "HEAD"])
    dirty_count = len(_git_lines(repo_path, ["status", "--porcelain"]))
    age_days = max(0, int((datetime.now(timezone.utc) - last_commit_at).total_seconds() // 86400))
    activity_score = (recent_7d * 4) + (recent_30d * 2) + max(0, 14 - age_days) + min(dirty_count, 20)
    return {
        "repo_path": str(repo_path),
        "repo_name": repo_path.name,
        "workspace_id": _slugify_workspace_id(repo_path.name),
        "last_commit_at": last_commit_at.replace(microsecond=0).isoformat(),
        "recent_commits_7d": recent_7d,
        "recent_commits_30d": recent_30d,
        "dirty_count": dirty_count,
        "activity_score": activity_score,
    }


def _git_text(repo_path: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "git command failed").strip())
    return result.stdout.strip()


def _git_int(repo_path: Path, args: list[str]) -> int:
    text = _git_text(repo_path, args)
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        return 0


def _git_lines(repo_path: Path, args: list[str]) -> list[str]:
    text = _git_text(repo_path, args)
    return [line for line in text.splitlines() if line.strip()]


def _is_hidden_relative(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part.startswith(".") and part != ".git" for part in rel.parts)


def _slugify_workspace_id(raw: str) -> str:
    return slugify_workspace_id(raw) or AgentRunnerService.DEFAULT_WEB_WORKSPACE_ID
