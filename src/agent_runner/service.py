from __future__ import annotations

from collections import deque
from copy import deepcopy
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from .context_assembler import ContextAssembler
from .conversation_store import ConversationStore, WorkspaceConversationController
from .doctor import run_doctor
from .image_workflow import (
    ImageTo3DProvider,
    ImageToVideoProvider,
    ImageWorkflowProvider,
    ImageWorkflowStore,
    describe_reference_image,
    default_image_to_3d_provider,
    default_image_to_video_provider,
    default_image_workflow_provider,
    generate_images_for_provider,
    generate_candidates_with_auto_refine,
    image_generation_count_options,
    image_generation_pass_options,
    image_generation_size_profiles,
    image_reuse_strength,
    normalize_auto_refine_config,
    normalize_image_generation_count,
    normalize_image_generation_passes,
    normalize_image_generation_size_profile_id,
    normalize_image_reuse_mode,
    zimage_lora_options,
)
from .models import AssistantCapabilityMode, AppSettings, ChecksPolicy, ConversationRecord, ProviderKind, RunMode
from .page_context import normalize_page_context
from .providers import (
    ExecutionRequest,
    PhaseExecutionClient,
    ProviderRouter,
    extract_prompt_screenshot_paths,
    infer_provider_for_model,
    model_supports_images,
    probe_ollama,
)
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
from .thread_context import merge_thread_context, normalize_thread_context, suggest_thread_title

ServiceEventCallback = Callable[[str, str], None]
ACTION_REQUEST_PATTERN = re.compile(
    r"\b(add|adjust|apply|change|continue|edit|fix|implement|improve|make|patch|prevent|refactor|remove|rename|replace|set|stop|tweak|update|wire)\b"
)
READ_ONLY_MESSAGE_PATTERN = re.compile(
    r"\b(analy[sz]e|describe|explain|inspect|review|summari[sz]e|tell me|walk me through|what|why|how)\b"
)
KNOWN_STUDIO_KINDS = frozenset({"studio_game", "studio_web", "studio_data", "studio_docs", "studio_image", "studio_video"})


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
    image_export_root: Path | None = None


@dataclass(slots=True)
class QueuedMessageRequest:
    workspace_id: str
    conversation_id: str
    content: str
    mode: RunMode
    assistant_mode: AssistantCapabilityMode
    page_context: dict[str, object]
    provider: ProviderKind
    model: str
    workspace_repo_path: Path
    max_step_retries: int | None = None
    event_callback: ServiceEventCallback | None = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    queued_at: str = field(default_factory=lambda: _timestamp_now())

    def status_payload(self, *, position: int) -> dict[str, object]:
        preview = " ".join(self.content.split())
        if len(preview) > 120:
            preview = f"{preview[:117].rstrip()}..."
        return {
            "id": self.request_id,
            "workspace_id": self.workspace_id,
            "conversation_id": self.conversation_id,
            "mode": str(self.mode),
            "assistant_mode": str(self.assistant_mode),
            "queued_at": self.queued_at,
            "position": position,
            "content_preview": preview,
        }


@dataclass(slots=True)
class QueuedImageGenerationRequest:
    workspace_id: str
    prompt: str
    count: int
    prompt_context: str | None = None
    auto_refine: dict[str, object] | None = None
    size_profile_id: str | None = None
    passes: int | None = None
    lora_name: str | None = None
    lora_strength: float | None = None
    composition_source_image_id: str | None = None
    remix_mode: str | None = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    queued_at: str = field(default_factory=lambda: _timestamp_now())
    started_at: str | None = None

    def status_payload(self, *, state: str, position: int | None = None) -> dict[str, object]:
        preview = " ".join(self.prompt.split())
        if len(preview) > 120:
            preview = f"{preview[:117].rstrip()}..."
        payload: dict[str, object] = {
            "id": self.request_id,
            "workspace_id": self.workspace_id,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
            "state": state,
            "prompt_preview": preview,
            "count": self.count,
            "auto_refine_enabled": bool((self.auto_refine or {}).get("enabled")),
            "size_profile_id": normalize_image_generation_size_profile_id(self.size_profile_id),
            "passes": normalize_image_generation_passes(self.passes),
            "lora_name": self.lora_name,
            "lora_strength": self.lora_strength,
            "composition_source_image_id": self.composition_source_image_id,
            "remix_mode": normalize_image_reuse_mode(self.remix_mode) if self.composition_source_image_id else None,
        }
        if position is not None:
            payload["position"] = position
        return payload


class AgentRunnerService:
    DEFAULT_WEB_WORKSPACE_ID = "default"

    def __init__(
        self,
        config: ServiceConfig,
        *,
        phase_client: PhaseExecutionClient | None = None,
        context_assembler: ContextAssembler | None = None,
        coordinator: RunCoordinator | None = None,
        image_workflow_provider: ImageWorkflowProvider | None = None,
        image_to_3d_provider: ImageTo3DProvider | None = None,
        image_to_video_provider: ImageToVideoProvider | None = None,
    ) -> None:
        self.config = config
        self.phase_client = phase_client or ProviderRouter()
        self.context_assembler = context_assembler or ContextAssembler()
        self.conversation_store = ConversationStore(config.settings_path.parent / "workspaces")
        self.coordinator = coordinator or RunCoordinator(config.settings_path.parent)
        defaults = AppSettings(
            provider=config.provider,
            model=config.model,
            openai_model=config.model if config.provider == ProviderKind.CODEX else AppSettings().openai_model,
            open_source_model=config.model if config.provider == ProviderKind.OLLAMA else None,
            codex_bin=config.codex_bin,
            ollama_host=config.ollama_host,
            extra_access_dir=config.extra_access_dir,
            max_step_retries=config.max_step_retries,
            phase_timeout_seconds=config.phase_timeout_seconds,
            default_checks=list(config.check_commands),
        )
        self.app_settings = load_app_settings(config.settings_path, defaults)
        discovered_models: list[str] | None = None
        if not (self.app_settings.open_source_model or "").strip():
            discovered_models = probe_ollama(self.app_settings.ollama_host).models
        self._synchronize_runtime_settings(discovered_models=discovered_models)
        self._event_lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._next_event_id = 1
        self._max_events = 2000
        self._event_listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._queue_lock = threading.Lock()
        self._pending_runs: deque[QueuedMessageRequest] = deque()
        self._image_generation_queue_lock = threading.Lock()
        self._pending_image_generations: deque[QueuedImageGenerationRequest] = deque()
        self._active_image_generation: QueuedImageGenerationRequest | None = None
        self._image_generation_errors: dict[str, str] = {}
        self._image_workflow_lock = threading.Lock()
        self._image_workflow_provider = image_workflow_provider or default_image_workflow_provider()
        self._image_to_3d_provider = image_to_3d_provider or default_image_to_3d_provider()
        self._image_to_video_provider = image_to_video_provider or default_image_to_video_provider()

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

    def list_conversations(self, workspace_id: str, *, include_archived: bool = False) -> list[dict[str, object]]:
        controller = self._controller(workspace_id)
        return [self._record_payload(record) for record in controller.metadata(include_archived=include_archived)]

    def list_all_conversations(self, *, include_archived: bool = False) -> list[dict[str, object]]:
        conversations: list[dict[str, object]] = []
        for workspace in self.list_workspaces():
            workspace_id = str(workspace["id"])
            conversations.extend(self.list_conversations(workspace_id, include_archived=include_archived))
        conversations.sort(
            key=lambda record: (
                str(record.get("updated_at", "")),
                str(record.get("created_at", "")),
                str(record.get("id", "")),
            ),
            reverse=True,
        )
        return conversations

    def create_conversation(
        self,
        workspace_id: str,
        *,
        title: str | None = None,
        thread_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        controller = self._controller(workspace_id)
        record = controller.create_conversation()
        normalized_thread_context = normalize_thread_context(thread_context)
        effective_title = title or suggest_thread_title(normalized_thread_context)
        if effective_title:
            record = controller.rename_conversation(record.id, effective_title)
        if normalized_thread_context:
            record = controller.set_assistant_context(record.id, thread_context=normalized_thread_context)
        payload = self._record_payload(record)
        self._emit_event(
            "conversation.created",
            {
                "workspace_id": workspace_id,
                "conversation_id": record.id,
                "title": record.title,
                "has_thread_context": bool(record.thread_context),
            },
        )
        return payload

    def create_web_conversation(self, *, title: str | None = None) -> dict[str, object]:
        return self.create_conversation(self.DEFAULT_WEB_WORKSPACE_ID, title=title)

    def deliver_external_message(
        self,
        *,
        workspace_id: str,
        content: str,
        thread_context: dict[str, object],
        mode: RunMode,
        assistant_mode: AssistantCapabilityMode | None = None,
        page_context: dict[str, object] | None = None,
        provider: ProviderKind | None = None,
        model: str | None = None,
        max_step_retries: int | None = None,
        event_callback: ServiceEventCallback | None = None,
    ) -> dict[str, object]:
        normalized_thread_context = normalize_thread_context(thread_context)
        channel = str(normalized_thread_context.get("channel") or "").strip()
        thread_key = str(normalized_thread_context.get("thread_key") or "").strip()
        if not channel or not thread_key:
            raise ValueError("External message delivery requires thread_context.channel and thread_context.thread_key.")
        controller = self._controller(workspace_id)
        matched = self._find_conversation_for_thread(
            controller,
            channel=channel,
            thread_key=thread_key,
        )
        created_conversation = False
        restored_conversation = False
        if matched is None:
            created = self.create_conversation(
                workspace_id,
                thread_context=normalized_thread_context,
            )
            conversation_id = str(created["id"])
            created_conversation = True
        else:
            if matched.archived_at:
                matched = controller.restore_conversation(matched.id)
                restored_conversation = True
            conversation_id = matched.id
        response = self.send_message(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            content=content,
            mode=mode,
            assistant_mode=assistant_mode,
            page_context=page_context,
            thread_context=normalized_thread_context,
            provider=provider,
            model=model,
            max_step_retries=max_step_retries,
            event_callback=event_callback,
        )
        response["created_conversation"] = created_conversation
        response["restored_conversation"] = restored_conversation
        response["thread_context"] = normalized_thread_context
        return response

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
        preview_url = None if kind == "studio_image" else f"/studio/preview/{workspace_id}/index.html"
        preview_state = "native" if kind == "studio_image" else "ready"
        controller = self._controller(workspace_id)
        controller.set_workspace_profile(
            display_name=project.artifact_title,
            repo_path=str(project.repo_path),
            workspace_kind=project.workspace_kind,
            artifact_title=project.artifact_title,
            template_kind=project.template_kind,
            theme_prompt=project.theme_prompt,
            preview_url=preview_url,
            preview_state=preview_state,
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
        if controller.state.workspace_kind == "studio_image":
            controller.set_workspace_profile(preview_url=None, preview_state="native")
            payload = self.ensure_workspace(workspace_id)
            self._emit_event(
                "workspace.updated",
                {
                    "workspace_id": workspace_id,
                    "preview_state": "native",
                    "preview_url": None,
                },
            )
            return payload
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
        if controller.state.workspace_kind == "studio_image":
            raise ValueError("Image Studio publish is not available yet.")
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

    def get_image_workflow_snapshot(self, workspace_id: str) -> dict[str, object]:
        self._require_image_workspace(workspace_id)
        generation_profiles = image_generation_size_profiles()
        generation_counts = image_generation_count_options()
        generation_passes = image_generation_pass_options()
        with self._image_workflow_lock:
            store = self._image_store(workspace_id)
            selected_image_id = store.selected_image_id()
            assets = store.list_assets()
            jobs_3d = store.list_jobs(job_type="image_to_3d")
            jobs_video = store.list_jobs(job_type="image_to_video")
        generation_queue = self._image_generation_queue_payload(workspace_id=workspace_id)
        jobs_by_source: dict[str, list[dict[str, object]]] = {}
        video_jobs_by_source: dict[str, list[dict[str, object]]] = {}
        job_items: list[dict[str, object]] = []
        video_job_items: list[dict[str, object]] = []
        for job in jobs_3d:
            artifacts = {
                key: self._image_workflow_file_url(workspace_id, relative_path)
                for key, relative_path in job.artifacts.items()
            }
            display_status = _image_workflow_job_display_status(job.status)
            job_item = {
                "id": job.id,
                "job_type": "image_to_3d",
                "created_at": job.created_at,
                "updated_at": job.updated_at,
                "source_image_id": job.source_image_id,
                "status": display_status,
                "provider": job.provider,
                "provider_job_id": job.external_job_id,
                "prompt_context": job.prompt_context,
                "artifacts": artifacts,
                "preview_url": artifacts.get("preview_svg") or artifacts.get("preview_png"),
                "downloads": [
                    {"key": key, "label": label, "url": artifacts[key]}
                    for key, label in (
                        ("input_png", "Input PNG"),
                        ("preview_png", "Preview PNG"),
                        ("glb", "GLB"),
                        ("metadata_json", "Metadata"),
                    )
                    if key in artifacts
                ],
                "metadata": dict(job.metadata),
                "error": job.error,
            }
            jobs_by_source.setdefault(job.source_image_id, []).append(job_item)
            job_items.append(job_item)
        for job in jobs_video:
            artifacts = {
                key: self._image_workflow_file_url(workspace_id, relative_path)
                for key, relative_path in job.artifacts.items()
            }
            display_status = _image_workflow_job_display_status(job.status)
            job_item = {
                "id": job.id,
                "job_type": "image_to_video",
                "created_at": job.created_at,
                "updated_at": job.updated_at,
                "source_image_id": job.source_image_id,
                "status": display_status,
                "provider": job.provider,
                "provider_job_id": job.external_job_id,
                "prompt_context": job.prompt_context,
                "artifacts": artifacts,
                "preview_url": artifacts.get("poster_png"),
                "clip_url": artifacts.get("mp4"),
                "downloads": [
                    {"key": key, "label": label, "url": artifacts[key]}
                    for key, label in (
                        ("input_png", "Input PNG"),
                        ("poster_png", "Poster PNG"),
                        ("mp4", "MP4"),
                        ("metadata_json", "Metadata"),
                    )
                    if key in artifacts
                ],
                "metadata": dict(job.metadata),
                "error": job.error,
            }
            video_jobs_by_source.setdefault(job.source_image_id, []).append(job_item)
            video_job_items.append(job_item)
        image_items: list[dict[str, object]] = []
        for asset in assets:
            related_jobs = jobs_by_source.get(asset.id, [])
            related_video_jobs = video_jobs_by_source.get(asset.id, [])
            review_loop = asset.metadata.get("review_loop") if isinstance(asset.metadata.get("review_loop"), dict) else None
            image_items.append(
                {
                    "id": asset.id,
                    "created_at": asset.created_at,
                    "updated_at": asset.updated_at,
                    "label": asset.label,
                    "source": asset.source,
                    "mime_type": asset.mime_type,
                    "prompt": asset.prompt,
                    "prompt_context": asset.prompt_context,
                    "url": self._image_workflow_file_url(workspace_id, asset.relative_path),
                    "selected": asset.id == selected_image_id,
                    "metadata": dict(asset.metadata),
                    "related_job_count": len(related_jobs),
                    "latest_job_status": related_jobs[0]["status"] if related_jobs else None,
                    "three_d_ready": any(item["status"] == "succeeded" for item in related_jobs),
                    "related_video_job_count": len(related_video_jobs),
                    "latest_video_job_status": related_video_jobs[0]["status"] if related_video_jobs else None,
                    "video_ready": any(item["status"] == "succeeded" for item in related_video_jobs),
                    "review_status": str(review_loop.get("status", "")).strip() if review_loop else None,
                    "review_score": review_loop.get("overall_score") if review_loop else None,
                    "review_attempts": review_loop.get("attempt_count") if review_loop else None,
                    "review_notes": str(review_loop.get("notes", "")).strip() if review_loop else None,
                }
            )
        return {
            "provider": self._image_workflow_provider.name,
            "video_provider": self._image_to_video_provider.name,
            "worker_available": True,
            "selected_image_id": selected_image_id,
            "images": image_items,
            "jobs": job_items,
            "video_jobs": video_job_items,
            "generation_queue": generation_queue,
            "generation_profiles": generation_profiles,
            "generation_count_options": generation_counts,
            "generation_pass_options": generation_passes,
            "lora_options": zimage_lora_options(),
            "library_folder_path": store.snapshot().get("library_folder_path"),
            "default_generation_count": normalize_image_generation_count(None),
            "default_generation_profile_id": normalize_image_generation_size_profile_id(None),
            "default_generation_passes": normalize_image_generation_passes(None),
            "help_text": "Image Studio is the supported home for image generation in Alcove. Generate or upload candidates here, describe a reference, use saved images as references, and keep iterating without leaving the workspace.",
            "generation_help": "Smaller local aspect presets are the reliable path on this Mac. Pick a previous image to use as a reference, then use Match or Remix to decide how tightly the next run should follow it.",
            "failure_copy": "That image workflow step failed. Try a cleaner silhouette, stronger lighting, or a more isolated subject.",
            "auto_refine_help": "Optional judge-and-retry loop. Uses local Ollama vision and text models to critique one candidate, rewrite the prompt, and retry a few times.",
        }

    def generate_image_candidates(
        self,
        *,
        workspace_id: str,
        prompt: str,
        count: int = 1,
        prompt_context: str | None = None,
        auto_refine: dict[str, object] | None = None,
        size_profile_id: str | None = None,
        passes: int | None = None,
        lora_name: str | None = None,
        lora_strength: float | None = None,
        composition_source_image_id: str | None = None,
        remix_mode: str | None = None,
    ) -> dict[str, object]:
        try:
            return self._generate_image_candidates_now(
                workspace_id=workspace_id,
                prompt=prompt,
                count=count,
                prompt_context=prompt_context,
                auto_refine=auto_refine,
                size_profile_id=size_profile_id,
                passes=passes,
                lora_name=lora_name,
                lora_strength=lora_strength,
                composition_source_image_id=composition_source_image_id,
                remix_mode=remix_mode,
            )
        except Exception as exc:
            with self._image_generation_queue_lock:
                self._image_generation_errors[workspace_id] = str(exc)
            raise

    def queue_image_generation(
        self,
        *,
        workspace_id: str,
        prompt: str,
        count: int = 1,
        prompt_context: str | None = None,
        auto_refine: dict[str, object] | None = None,
        size_profile_id: str | None = None,
        passes: int | None = None,
        lora_name: str | None = None,
        lora_strength: float | None = None,
        composition_source_image_id: str | None = None,
        remix_mode: str | None = None,
    ) -> dict[str, object]:
        self._require_image_workspace(workspace_id)
        prompt_text = prompt.strip()
        if not prompt_text:
            raise ValueError("Image prompts cannot be empty.")
        request = QueuedImageGenerationRequest(
            workspace_id=workspace_id,
            prompt=prompt_text,
            count=normalize_image_generation_count(count),
            prompt_context=(prompt_context or "").strip() or None,
            auto_refine=auto_refine,
            size_profile_id=normalize_image_generation_size_profile_id(size_profile_id),
            passes=normalize_image_generation_passes(passes),
            lora_name=_normalize_zimage_lora_name(lora_name),
            lora_strength=_normalize_lora_strength(lora_strength),
            composition_source_image_id=(composition_source_image_id or "").strip() or None,
            remix_mode=normalize_image_reuse_mode(remix_mode) if composition_source_image_id else None,
        )
        queued = False
        queue_position = 0
        should_start_now = False
        with self._image_generation_queue_lock:
            self._image_generation_errors.pop(workspace_id, None)
            if self._active_image_generation is None and not self._pending_image_generations:
                request.started_at = _timestamp_now()
                self._active_image_generation = request
                should_start_now = True
            else:
                self._pending_image_generations.append(request)
                queued = True
                queue_position = len(self._pending_image_generations)
        if should_start_now:
            self._emit_event(
                "image-workflow.updated",
                {
                    "workspace_id": workspace_id,
                    "kind": "generation-started",
                    "request_id": request.request_id,
                },
            )
            self._start_image_generation_request(request)
        else:
            self._emit_event(
                "image-workflow.updated",
                {
                    "workspace_id": workspace_id,
                    "kind": "generation-queued",
                    "request_id": request.request_id,
                    "queue_position": queue_position,
                },
            )
        return {
            "accepted": True,
            "workspace_id": workspace_id,
            "request_id": request.request_id,
            "queued": queued,
            "queue_position": queue_position,
            "image_workflow": self.get_image_workflow_snapshot(workspace_id),
        }

    def upload_image_asset(
        self,
        *,
        workspace_id: str,
        file_name: str,
        mime_type: str,
        data: bytes,
        prompt_context: str | None = None,
    ) -> dict[str, object]:
        self._require_image_workspace(workspace_id)
        if not mime_type.startswith("image/"):
            raise ValueError("Only image uploads are supported.")
        if len(data) > 20 * 1024 * 1024:
            raise ValueError("Each uploaded image must be 20MB or smaller.")
        with self._image_workflow_lock:
            store = self._image_store(workspace_id)
            store.add_uploaded_asset(
                file_name=file_name,
                mime_type=mime_type,
                data=data,
                prompt_context=prompt_context,
            )
        self._emit_event(
            "image-workflow.updated",
            {
                "workspace_id": workspace_id,
                "kind": "uploaded",
            },
        )
        return self.get_image_workflow_snapshot(workspace_id)

    def import_image_asset_from_path(
        self,
        *,
        workspace_id: str,
        image_path: str,
        prompt_context: str | None = None,
    ) -> dict[str, object]:
        self._require_image_workspace(workspace_id)
        candidate = Path(image_path).expanduser()
        if not candidate.exists() or not candidate.is_file():
            raise FileNotFoundError(str(candidate))
        mime_type, _ = mimetypes.guess_type(str(candidate))
        resolved_mime = str(mime_type or "").strip().lower()
        if not resolved_mime.startswith("image/"):
            raise ValueError("Only image files can be imported into Image Studio.")
        data = candidate.read_bytes()
        return self.upload_image_asset(
            workspace_id=workspace_id,
            file_name=candidate.name,
            mime_type=resolved_mime,
            data=data,
            prompt_context=prompt_context,
        )

    def open_image_asset_folder(self, *, workspace_id: str) -> dict[str, object]:
        self._require_image_workspace(workspace_id)
        with self._image_workflow_lock:
            store = self._image_store(workspace_id)
            folder_path = store.assets_dir.resolve() if store.assets_dir.is_symlink() else store.assets_dir
            folder_path.mkdir(parents=True, exist_ok=True)
        _open_local_path(folder_path)
        return {
            "workspace_id": workspace_id,
            "folder_path": str(folder_path),
            "opened": True,
        }

    def set_image_library_folder(self, *, workspace_id: str, folder_path: str) -> dict[str, object]:
        self._require_image_workspace(workspace_id)
        requested = Path(str(folder_path or "").strip()).expanduser()
        if not str(requested).strip():
            raise ValueError("Choose a folder for the image library.")
        with self._image_workflow_lock:
            store = self._image_store(workspace_id)
            resolved = store.set_library_folder(requested)
        self._emit_event(
            "image-workflow.updated",
            {
                "workspace_id": workspace_id,
                "kind": "library-folder-updated",
                "folder_path": str(resolved),
            },
        )
        return self.get_image_workflow_snapshot(workspace_id)

    def delete_image_asset(self, *, workspace_id: str, image_id: str) -> dict[str, object]:
        self._require_image_workspace(workspace_id)
        resolved_image_id = str(image_id or "").strip()
        if not resolved_image_id:
            raise ValueError("Choose an image before asking Alcove to delete it.")
        self._ensure_image_asset_not_queued_for_generation(workspace_id=workspace_id, image_id=resolved_image_id)
        with self._image_workflow_lock:
            store = self._image_store(workspace_id)
            active_jobs = [
                job
                for job in store.list_jobs()
                if job.source_image_id == resolved_image_id and job.status not in {"succeeded", "failed", "canceled"}
            ]
            if active_jobs:
                raise ValueError("This image still has active 3D or video work. Let it finish before deleting it.")
            deleted = store.delete_asset(resolved_image_id)
        self._emit_event(
            "image-workflow.updated",
            {
                "workspace_id": workspace_id,
                "kind": "deleted",
                "image_id": resolved_image_id,
                "deleted_job_count": int(deleted.get("deleted_job_count") or 0),
            },
        )
        return self.get_image_workflow_snapshot(workspace_id)

    def describe_image_reference(
        self,
        *,
        workspace_id: str,
        source_image_id: str | None = None,
        prompt_context: str | None = None,
    ) -> dict[str, object]:
        self._require_image_workspace(workspace_id)
        with self._image_workflow_lock:
            store = self._image_store(workspace_id)
            resolved_source = source_image_id or store.selected_image_id()
            if not resolved_source:
                raise ValueError("Choose an image before asking Alcove to describe it.")
            asset = store.get_asset(resolved_source)
            image_path = store.asset_path(asset)
        description = describe_reference_image(
            image_path=image_path,
            ollama_host=self.app_settings.ollama_host or self.config.ollama_host,
            prompt_context=prompt_context or asset.prompt_context or asset.prompt,
            preferred_vision_model=self.app_settings.vision_model,
            preferred_prompt_model=self.app_settings.open_source_model or self.app_settings.model,
        )
        self._emit_event(
            "image-workflow.updated",
            {
                "workspace_id": workspace_id,
                "kind": "reference-described",
                "source_image_id": resolved_source,
            },
        )
        return {
            "source_image_id": resolved_source,
            "reference": description,
            "image_workflow": self.get_image_workflow_snapshot(workspace_id),
        }

    def _resolve_image_generation_context(
        self,
        *,
        workspace_id: str,
        size_profile_id: str | None,
        composition_source_image_id: str | None,
        remix_mode: str | None,
    ) -> dict[str, object]:
        context: dict[str, object] = {
            "size_profile_id": normalize_image_generation_size_profile_id(size_profile_id),
            "composition_source_image_id": None,
            "composition_source_label": None,
            "composition_source_kind": None,
            "seed": None,
            "seed_reused": False,
            "init_image_path": None,
            "remix_mode": None,
            "strength": None,
        }
        resolved_source_id = (composition_source_image_id or "").strip()
        if not resolved_source_id:
            return context
        with self._image_workflow_lock:
            store = self._image_store(workspace_id)
            asset = store.get_asset(resolved_source_id)
            asset_path = store.asset_path(asset)
        resolved_remix_mode = normalize_image_reuse_mode(remix_mode)
        seed_value = _coerce_int(asset.metadata.get("seed"))
        context.update(
            {
                "composition_source_image_id": asset.id,
                "composition_source_label": asset.label,
                "composition_source_kind": asset.source,
                "seed": seed_value,
                "seed_reused": seed_value is not None,
                "init_image_path": asset_path,
                "remix_mode": resolved_remix_mode,
                "strength": image_reuse_strength(resolved_remix_mode),
            }
        )
        return context

    def _annotate_generated_candidates(
        self,
        candidates: list[object],
        *,
        generation_context: dict[str, object],
    ) -> list[object]:
        profile_id = normalize_image_generation_size_profile_id(generation_context.get("size_profile_id"))
        profile = image_generation_size_profiles()
        selected_profile = next((item for item in profile if str(item.get("id")) == profile_id), None)
        for candidate in candidates:
            metadata = dict(getattr(candidate, "metadata", {}) or {})
            metadata.setdefault("size_profile_id", profile_id)
            if selected_profile is not None:
                metadata.setdefault("width", int(selected_profile["width"]))
                metadata.setdefault("height", int(selected_profile["height"]))
                metadata.setdefault("aspect_ratio", str(selected_profile["aspect_ratio"]))
            composition_source_image_id = generation_context.get("composition_source_image_id")
            if composition_source_image_id:
                metadata["composition_source_image_id"] = composition_source_image_id
                metadata["composition_source_label"] = generation_context.get("composition_source_label")
                metadata["composition_source_kind"] = generation_context.get("composition_source_kind")
                metadata["seed_reused"] = bool(generation_context.get("seed_reused"))
                metadata["generation_mode"] = generation_context.get("remix_mode") or "match"
                metadata["init_image_used"] = True
                if generation_context.get("strength") is not None:
                    metadata["remix_strength"] = generation_context.get("strength")
                if generation_context.get("seed") is not None:
                    metadata.setdefault("composition_seed", generation_context.get("seed"))
            else:
                metadata.setdefault("generation_mode", "fresh")
                metadata.setdefault("init_image_used", False)
            candidate.metadata = metadata
        return candidates

    def _generate_image_candidates_now(
        self,
        *,
        workspace_id: str,
        prompt: str,
        count: int = 1,
        prompt_context: str | None = None,
        auto_refine: dict[str, object] | None = None,
        size_profile_id: str | None = None,
        passes: int | None = None,
        lora_name: str | None = None,
        lora_strength: float | None = None,
        composition_source_image_id: str | None = None,
        remix_mode: str | None = None,
    ) -> dict[str, object]:
        self._require_image_workspace(workspace_id)
        prompt_text = prompt.strip()
        if not prompt_text:
            raise ValueError("Image prompts cannot be empty.")
        auto_refine_config = normalize_auto_refine_config(auto_refine)
        resolved_size_profile_id = normalize_image_generation_size_profile_id(size_profile_id)
        resolved_passes = normalize_image_generation_passes(passes)
        resolved_lora_name = _normalize_zimage_lora_name(lora_name)
        resolved_lora_strength = _normalize_lora_strength(lora_strength)
        prompt_for_generation = _prompt_with_lora(prompt_text, resolved_lora_name, resolved_lora_strength)
        ollama_host = self.app_settings.ollama_host or self.config.ollama_host
        generation_context = self._resolve_image_generation_context(
            workspace_id=workspace_id,
            size_profile_id=resolved_size_profile_id,
            composition_source_image_id=composition_source_image_id,
            remix_mode=remix_mode,
        )
        generation_started_at = time.perf_counter()
        if auto_refine_config.enabled:
            candidates = generate_candidates_with_auto_refine(
                self._image_workflow_provider,
                prompt=prompt_for_generation,
                prompt_context=prompt_context,
                ollama_host=ollama_host,
                auto_refine=auto_refine_config,
                size_profile_id=generation_context["size_profile_id"],
                passes=resolved_passes,
                seed=generation_context["seed"],
                init_image_path=generation_context["init_image_path"],
                remix_mode=generation_context["remix_mode"],
                strength=generation_context["strength"],
                composition_source_image_id=generation_context["composition_source_image_id"],
            )
        else:
            candidates = generate_images_for_provider(
                self._image_workflow_provider,
                prompt=prompt_for_generation,
                count=normalize_image_generation_count(count),
                size_profile_id=generation_context["size_profile_id"],
                passes=resolved_passes,
                seed=generation_context["seed"],
                init_image_path=generation_context["init_image_path"],
                remix_mode=generation_context["remix_mode"],
                strength=generation_context["strength"],
                composition_source_image_id=generation_context["composition_source_image_id"],
            )
        generation_duration_ms = int((time.perf_counter() - generation_started_at) * 1000)
        for candidate in candidates:
            metadata = dict(getattr(candidate, "metadata", {}) or {})
            metadata.setdefault("generation_duration_ms", generation_duration_ms)
            if resolved_lora_name:
                metadata.setdefault("lora_name", resolved_lora_name)
                metadata.setdefault("lora_strength", resolved_lora_strength)
            candidate.metadata = metadata
        candidates = self._annotate_generated_candidates(
            candidates,
            generation_context=generation_context,
        )
        with self._image_workflow_lock:
            store = self._image_store(workspace_id)
            store.add_generated_assets(
                prompt=prompt_text,
                prompt_context=prompt_context,
                candidates=candidates,
            )
        with self._image_generation_queue_lock:
            self._image_generation_errors.pop(workspace_id, None)
        self._emit_event(
            "image-workflow.updated",
            {
                "workspace_id": workspace_id,
                "kind": "generated",
            },
        )
        return self.get_image_workflow_snapshot(workspace_id)

    def _start_image_generation_request(self, request: QueuedImageGenerationRequest) -> None:
        worker = threading.Thread(
            target=self._run_image_generation_request,
            args=(request,),
            daemon=True,
        )
        worker.start()

    def _run_image_generation_request(self, request: QueuedImageGenerationRequest) -> None:
        try:
            self._generate_image_candidates_now(
                workspace_id=request.workspace_id,
                prompt=request.prompt,
                count=request.count,
                prompt_context=request.prompt_context,
                auto_refine=request.auto_refine,
                size_profile_id=request.size_profile_id,
                passes=request.passes,
                lora_name=request.lora_name,
                lora_strength=request.lora_strength,
                composition_source_image_id=request.composition_source_image_id,
                remix_mode=request.remix_mode,
            )
        except Exception as exc:
            with self._image_generation_queue_lock:
                self._image_generation_errors[request.workspace_id] = str(exc)
            self._emit_event(
                "image-workflow.updated",
                {
                    "workspace_id": request.workspace_id,
                    "kind": "generation-failed",
                    "request_id": request.request_id,
                    "error": str(exc),
                },
            )
        finally:
            next_request: QueuedImageGenerationRequest | None = None
            with self._image_generation_queue_lock:
                if self._active_image_generation and self._active_image_generation.request_id == request.request_id:
                    self._active_image_generation = None
                if self._pending_image_generations:
                    next_request = self._pending_image_generations.popleft()
                    next_request.started_at = _timestamp_now()
                    self._active_image_generation = next_request
            self._emit_event(
                "image-workflow.updated",
                {
                    "workspace_id": request.workspace_id,
                    "kind": "generation-queue-updated",
                    "request_id": request.request_id,
                },
            )
            if next_request is not None:
                self._emit_event(
                    "image-workflow.updated",
                    {
                        "workspace_id": next_request.workspace_id,
                        "kind": "generation-started",
                        "request_id": next_request.request_id,
                    },
                )
                self._start_image_generation_request(next_request)

    def _ensure_image_asset_not_queued_for_generation(self, *, workspace_id: str, image_id: str) -> None:
        with self._image_generation_queue_lock:
            active = self._active_image_generation
            if (
                active is not None
                and active.workspace_id == workspace_id
                and str(active.composition_source_image_id or "").strip() == image_id
            ):
                raise ValueError("This image is being used as a reference for an active image run. Let it finish before deleting it.")
            for pending in self._pending_image_generations:
                if pending.workspace_id != workspace_id:
                    continue
                if str(pending.composition_source_image_id or "").strip() == image_id:
                    raise ValueError("This image is queued as a reference for a pending image run. Let it finish or clear the queue before deleting it.")

    def make_image_3d(
        self,
        *,
        workspace_id: str,
        source_image_id: str | None = None,
        prompt_context: str | None = None,
    ) -> dict[str, object]:
        self._require_image_workspace(workspace_id)
        with self._image_workflow_lock:
            store = self._image_store(workspace_id)
            resolved_source = source_image_id or store.selected_image_id()
            if not resolved_source:
                raise ValueError("Choose an image before asking Alcove to make it 3D.")
            job = store.create_image_to_3d_job(
                source_image_id=resolved_source,
                provider=self._image_to_3d_provider.name,
                prompt_context=prompt_context,
            )
        self._emit_event(
            "image-workflow.updated",
            {
                "workspace_id": workspace_id,
                "kind": "job-created",
                "job_type": "image_to_3d",
                "job_id": job.id,
                "source_image_id": job.source_image_id,
            },
        )
        threading.Thread(
            target=self._run_image_to_3d_job,
            args=(workspace_id, job.id),
            daemon=True,
        ).start()
        return {
            "job_id": job.id,
            "workflow": self.get_image_workflow_snapshot(workspace_id),
        }

    def animate_image(
        self,
        *,
        workspace_id: str,
        source_image_id: str | None = None,
        prompt_context: str | None = None,
    ) -> dict[str, object]:
        self._require_image_workspace(workspace_id)
        with self._image_workflow_lock:
            store = self._image_store(workspace_id)
            resolved_source = source_image_id or store.selected_image_id()
            if not resolved_source:
                raise ValueError("Choose an image before asking Alcove to animate it.")
            asset = store.get_asset(resolved_source)
            resolved_prompt_context = (
                (prompt_context or "").strip()
                or (asset.prompt_context or "").strip()
                or (asset.prompt or "").strip()
                or "Preserve the source image composition and subject while adding subtle natural motion, stable framing, and gentle scene movement."
            )
            job = store.create_image_to_video_job(
                source_image_id=resolved_source,
                provider=self._image_to_video_provider.name,
                prompt_context=resolved_prompt_context,
            )
        self._emit_event(
            "image-workflow.updated",
            {
                "workspace_id": workspace_id,
                "kind": "job-created",
                "job_type": "image_to_video",
                "job_id": job.id,
                "source_image_id": job.source_image_id,
            },
        )
        threading.Thread(
            target=self._run_image_to_video_job,
            args=(workspace_id, job.id),
            daemon=True,
        ).start()
        return {
            "job_id": job.id,
            "workflow": self.get_image_workflow_snapshot(workspace_id),
        }

    def import_workspace_from_path(
        self,
        repo_path: str,
        *,
        display_name: str | None = None,
        workspace_kind: str | None = None,
    ) -> dict[str, object]:
        normalized_repo = _normalize_repo_input_path(repo_path)
        if not normalized_repo.exists() or not normalized_repo.is_dir():
            raise ValueError(f"Workspace repo path does not exist: {normalized_repo}")

        existing_id = self._workspace_id_for_repo_path(normalized_repo)
        folder_name = (display_name or normalized_repo.name).strip() or normalized_repo.name or "workspace"
        workspace_id = existing_id or self._unique_workspace_id(folder_name)
        profile = self._import_workspace_profile(
            repo_path=normalized_repo,
            workspace_id=workspace_id,
            display_name=folder_name,
            preferred_workspace_kind=workspace_kind,
        )

        workspace = self.define_workspace(
            workspace_id,
            display_name=folder_name,
            repo_path=str(normalized_repo),
            workspace_kind=str(profile["workspace_kind"] or "standard"),
            artifact_title=profile["artifact_title"],
            template_kind=profile["template_kind"],
            preview_url=profile["preview_url"],
            preview_state=profile["preview_state"],
            publish_state=profile["publish_state"],
        )

        if self._is_studio_workspace_kind(workspace.get("workspace_kind")):
            controller = self._controller(workspace_id)
            record = controller.active_conversation()
            controller.set_assistant_context(record.id, assistant_mode=AssistantCapabilityMode.DEV)

        return workspace

    def pick_local_folder_path(self) -> str:
        if sys.platform != "darwin":
            raise ValueError("Native folder picker is currently available on macOS only.")
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'POSIX path of (choose folder with prompt "Choose a local project folder to import into Alcove:")',
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            if "-128" in detail or "User canceled" in detail:
                raise ValueError("Folder selection cancelled.")
            raise ValueError(f"Could not open native folder picker: {detail or 'unknown error'}")
        selected = (result.stdout or "").strip()
        if not selected:
            raise ValueError("Folder selection cancelled.")
        return selected

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

    def rename_workspace(self, workspace_id: str, *, display_name: str) -> dict[str, object]:
        controller = self._require_workspace_controller(workspace_id)
        controller.set_workspace_profile(display_name=display_name)
        active = controller.active_conversation()
        payload = self._workspace_payload(controller, updated_at=active.updated_at, title=active.title)
        self._emit_event(
            "workspace.updated",
            {
                "workspace_id": workspace_id,
                "display_name": payload.get("display_name"),
            },
        )
        return payload

    def delete_workspace(self, workspace_id: str) -> dict[str, object]:
        self._require_workspace_controller(workspace_id)
        status = self.coordinator.get_status()
        if status.workspace_id == workspace_id and status.state in {"starting", "running", "stopping"}:
            raise RuntimeError("Stop the active run before deleting this workspace.")
        with self._queue_lock:
            if any(item.workspace_id == workspace_id for item in self._pending_runs):
                raise RuntimeError("Remove or finish queued work before deleting this workspace.")
        self.conversation_store.delete_workspace(workspace_id)
        self._emit_event(
            "workspace.deleted",
            {
                "workspace_id": workspace_id,
            },
        )
        return {
            "ok": True,
            "workspace_id": workspace_id,
            "deleted": True,
        }

    def get_conversation(self, conversation_id: str, *, workspace_id: str | None = None) -> dict[str, object]:
        record, resolved_workspace_id = self._find_conversation(conversation_id, workspace_id=workspace_id)
        controller = self._controller(resolved_workspace_id)
        if not record.archived_at:
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
        payload = self._record_payload(fallback)
        payload["active_conversation_id"] = fallback.id
        return payload

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
        payload = self._record_payload(cleared, include_messages=True)
        payload["active_conversation_id"] = cleared.id
        return payload

    def archive_conversation(self, conversation_id: str, *, workspace_id: str | None = None) -> dict[str, object]:
        record, resolved_workspace_id = self._find_conversation(conversation_id, workspace_id=workspace_id)
        controller = self._controller(resolved_workspace_id)
        archived, fallback = controller.archive_conversation(record.id)
        self._emit_event(
            "conversation.archived",
            {
                "workspace_id": resolved_workspace_id,
                "conversation_id": archived.id,
                "active_conversation_id": fallback.id,
            },
        )
        return {
            "conversation": self._record_payload(archived),
            "active_conversation": self._record_payload(fallback),
            "active_conversation_id": fallback.id,
        }

    def restore_conversation(self, conversation_id: str, *, workspace_id: str | None = None) -> dict[str, object]:
        record, resolved_workspace_id = self._find_conversation(conversation_id, workspace_id=workspace_id)
        controller = self._controller(resolved_workspace_id)
        restored = controller.restore_conversation(record.id)
        self._emit_event(
            "conversation.restored",
            {
                "workspace_id": resolved_workspace_id,
                "conversation_id": restored.id,
                "active_conversation_id": restored.id,
            },
        )
        payload = self._record_payload(restored)
        payload["active_conversation_id"] = restored.id
        return payload

    def send_message(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        content: str,
        mode: RunMode,
        assistant_mode: AssistantCapabilityMode | None = None,
        page_context: dict[str, object] | None = None,
        thread_context: dict[str, object] | None = None,
        provider: ProviderKind | None = None,
        model: str | None = None,
        max_step_retries: int | None = None,
        event_callback: ServiceEventCallback | None = None,
    ) -> dict[str, object]:
        clean_text = content.strip()
        if not clean_text:
            raise ValueError("Message content cannot be empty.")

        controller = self._controller(workspace_id)
        normalized_page_context = normalize_page_context(page_context)
        normalized_thread_context = normalize_thread_context(thread_context)
        controller.select_conversation(conversation_id)
        active_record = controller.active_conversation()
        effective_thread_context = merge_thread_context(active_record.thread_context, normalized_thread_context)
        if assistant_mode is not None or page_context is not None or thread_context is not None:
            controller.set_assistant_context(
                conversation_id,
                assistant_mode=assistant_mode,
                page_context=normalized_page_context if page_context is not None else None,
                thread_context=effective_thread_context if thread_context is not None else None,
            )
        active_record = controller.active_conversation()
        effective_assistant_mode = active_record.assistant_mode
        effective_page_context = deepcopy(active_record.page_context)
        effective_thread_context = deepcopy(active_record.thread_context)
        workspace_repo_path = self._workspace_repo_path(workspace_id)
        if mode == RunMode.LOOP and effective_assistant_mode != AssistantCapabilityMode.DEV:
            raise ValueError("Loop mode requires dev assistant capability mode.")
        resolved_provider, resolved_model = self._effective_provider_and_model(provider=provider, model=model)
        request = QueuedMessageRequest(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            content=clean_text,
            mode=mode,
            assistant_mode=effective_assistant_mode,
            page_context=effective_page_context,
            provider=resolved_provider,
            model=resolved_model,
            workspace_repo_path=workspace_repo_path,
            max_step_retries=max_step_retries,
            event_callback=event_callback,
        )
        queued = False
        queue_position = 0
        should_start_now = False
        with self._queue_lock:
            if self._pending_runs:
                self._pending_runs.append(request)
                queued = True
                queue_position = len(self._pending_runs)
            elif self.coordinator.try_start(
                workspace_id,
                conversation_id=conversation_id,
                mode=str(mode),
                run_id=request.request_id,
                last_prompt=clean_text,
            ):
                should_start_now = True
            else:
                self._pending_runs.append(request)
                queued = True
                queue_position = len(self._pending_runs)

        if queued:
            self._emit_run_event("run.queued")
        elif should_start_now:
            self._start_message_request(request)

        return {
            "accepted": True,
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "mode": str(mode),
            "assistant_mode": str(effective_assistant_mode),
            "has_thread_context": bool(effective_thread_context),
            "queued": queued,
            "queue_position": queue_position,
        }

    def update_conversation_context(
        self,
        conversation_id: str,
        *,
        workspace_id: str | None = None,
        assistant_mode: AssistantCapabilityMode | None = None,
        page_context: dict[str, object] | None = None,
        thread_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        record, resolved_workspace_id = self._find_conversation(conversation_id, workspace_id=workspace_id)
        controller = self._controller(resolved_workspace_id)
        normalized_thread_context = normalize_thread_context(thread_context)
        updated = controller.set_assistant_context(
            record.id,
            assistant_mode=assistant_mode,
            page_context=normalize_page_context(page_context) if page_context is not None else None,
            thread_context=merge_thread_context(record.thread_context, normalized_thread_context) if thread_context is not None else None,
        )
        self._emit_event(
            "conversation.updated",
            {
                "workspace_id": resolved_workspace_id,
                "conversation_id": updated.id,
                "assistant_mode": str(updated.assistant_mode),
                "has_page_context": bool(updated.page_context),
                "has_thread_context": bool(updated.thread_context),
            },
        )
        return self._record_payload(updated, include_messages=True)

    def stop_run(self) -> dict[str, object]:
        status = self.coordinator.get_status()
        if status.state not in {"starting", "running", "stopping"}:
            return self.get_run_status()
        updated = self.coordinator.request_stop().to_dict()
        self._emit_run_event("run.stop_requested", status=updated)
        return self.get_run_status()

    def recover_run(self) -> dict[str, object]:
        status = self.coordinator.get_status()
        if status.state in {"starting", "running", "stopping"}:
            raise RuntimeError("Run is active. Stop it before running stale recovery.")
        recovered = self.coordinator.recover_stale_run().to_dict()
        self._emit_run_event("run.recovered", status=recovered)
        return self.get_run_status()

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
        status = self.coordinator.get_status().to_dict()
        queued_runs = self._queued_runs_payload()
        status["queue_count"] = len(queued_runs)
        status["queued_runs"] = queued_runs
        return status

    def get_settings(self) -> dict[str, object]:
        settings = self.app_settings
        self._synchronize_runtime_settings()
        resolved_context_char_cap, context_char_cap_source = self.context_assembler.resolved_context_char_cap(
            provider=settings.provider,
            model=settings.model,
            configured_context_char_cap=settings.context_char_cap,
        )
        return {
            "provider": str(settings.provider),
            "model": settings.model,
            "openai_model": settings.openai_model,
            "open_source_model": settings.open_source_model,
            "codex_bin": settings.codex_bin,
            "ollama_host": settings.ollama_host,
            "context_char_cap": settings.context_char_cap,
            "arcade_repo_path": str(settings.arcade_repo_path) if settings.arcade_repo_path is not None else None,
            "resolved_context_char_cap": resolved_context_char_cap,
            "context_char_cap_source": context_char_cap_source,
        }

    def get_setup_status(self) -> dict[str, object]:
        report = run_doctor(
            codex_bin=self.app_settings.codex_bin,
            repo_path=self.config.repo_path,
        )
        return report.to_dict()

    def update_settings(self, payload: dict[str, object]) -> dict[str, object]:
        settings = self.app_settings
        provider_text = str(payload.get("provider", settings.provider)).strip().lower()
        if provider_text == str(ProviderKind.OLLAMA):
            settings.provider = ProviderKind.OLLAMA
        elif provider_text == str(ProviderKind.CODEX):
            settings.provider = ProviderKind.CODEX
        openai_model = str(payload.get("openai_model", settings.openai_model)).strip()
        if openai_model:
            settings.openai_model = openai_model
        open_source_model = str(payload.get("open_source_model", settings.open_source_model or "")).strip()
        settings.open_source_model = open_source_model or settings.open_source_model
        legacy_model = str(payload.get("model", "")).strip()
        if legacy_model:
            inferred_provider = infer_provider_for_model(legacy_model, settings.provider)
            if inferred_provider == ProviderKind.CODEX:
                settings.openai_model = legacy_model
            else:
                settings.open_source_model = legacy_model
        ollama_host = str(payload.get("ollama_host", settings.ollama_host)).strip()
        if ollama_host:
            settings.ollama_host = ollama_host
        if "context_char_cap" in payload:
            context_char_cap = payload.get("context_char_cap")
            settings.context_char_cap = None if context_char_cap in {None, ""} else max(100, int(context_char_cap))
        if "arcade_repo_path" in payload:
            arcade_repo_text = str(payload.get("arcade_repo_path") or "").strip()
            settings.arcade_repo_path = Path(arcade_repo_text).expanduser() if arcade_repo_text else None
        self._synchronize_runtime_settings()
        save_app_settings(self.config.settings_path, settings)
        return self.get_settings()

    def list_ollama_models(self) -> dict[str, object]:
        result = probe_ollama(self.app_settings.ollama_host)
        self._synchronize_runtime_settings(discovered_models=result.models)
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
        queued_runs = self._queued_runs_payload(
            workspace_id=resolved_workspace_id,
            conversation_id=conversation_id,
        )
        payload = {
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
                "queue_count": status.get("queue_count", 0),
            },
            "latest_result": {
                "phase": latest.phase if latest else None,
                "content": latest.content if latest else "",
                "created_at": latest.created_at if latest else None,
            },
            "queue": {
                "count": len(queued_runs),
                "items": queued_runs,
                "global_count": status.get("queue_count", 0),
            },
            "summary": extracted.get("summary", ""),
            "changed_files": extracted.get("changed_files", []),
            "checks": extracted.get("checks", {}),
            "artifacts_path": extracted.get("artifacts_path"),
        }
        if resolved_workspace_id:
            try:
                controller = self._controller(resolved_workspace_id)
            except Exception:
                controller = None
            if controller and controller.state.workspace_kind == "studio_image":
                payload["image_workflow"] = self.get_image_workflow_snapshot(resolved_workspace_id)
        return payload

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

    def add_event_listener(self, listener: Callable[[str, dict[str, Any]], None]) -> None:
        self._event_listeners.append(listener)

    def _run_background_interaction(
        self,
        workspace_id: str,
        conversation_id: str,
        prompt: str,
        mode: RunMode,
        effective_context,
        assistant_mode: AssistantCapabilityMode,
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
            execute_dev_message = self._should_execute_dev_message(
                assistant_mode=assistant_mode,
                prompt=prompt,
                provider=provider,
                model=model,
            )
            self.coordinator.update_status(
                state="running",
                step=(
                    "Starting dev pass"
                    if mode == RunMode.MESSAGE and execute_dev_message
                    else ("Sending message" if mode == RunMode.MESSAGE else "Starting loop")
                ),
                error="",
                last_error="",
            )
            self._emit_run_event("run.state_changed")
            if mode == RunMode.MESSAGE and not execute_dev_message:
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
                ollama_host=global_settings.ollama_host,
                extra_access_dir=global_settings.extra_access_dir,
                max_step_retries=(
                    0
                    if mode == RunMode.MESSAGE
                    else max(0, max_step_retries if max_step_retries is not None else global_settings.max_step_retries)
                ),
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
            if event_callback:
                event_callback("error", str(exc))
        finally:
            heartbeat_stop.set()
            self._finish_active_run(workspace_id)

    def _start_message_request(self, request: QueuedMessageRequest) -> None:
        controller = self._controller(request.workspace_id)
        controller.select_conversation(request.conversation_id)
        user_record = controller.append_message(role="user", content=request.content)
        self._refresh_summary_if_needed(
            controller,
            user_record.id,
            provider=request.provider,
            model=request.model,
        )
        active_record = controller.active_conversation()
        effective_thread_context = deepcopy(active_record.thread_context)
        effective_context = (
            self.context_assembler.build_for_loop(
                repo_path=request.workspace_repo_path,
                provider=request.provider,
                model=request.model,
                run_mode=request.mode,
                conversation=active_record,
                current_input=request.content,
                assistant_mode=request.assistant_mode,
                page_context=request.page_context,
                thread_context=effective_thread_context,
                configured_context_char_cap=self.app_settings.context_char_cap,
            )
            if request.mode == RunMode.LOOP
            else self.context_assembler.build_for_message(
                repo_path=request.workspace_repo_path,
                provider=request.provider,
                model=request.model,
                run_mode=request.mode,
                conversation=active_record,
                current_input=request.content,
                assistant_mode=request.assistant_mode,
                page_context=request.page_context,
                thread_context=effective_thread_context,
                configured_context_char_cap=self.app_settings.context_char_cap,
            )
        )
        self.coordinator.update_status(
            state="starting",
            workspace_id=request.workspace_id,
            conversation_id=request.conversation_id,
            mode=str(request.mode),
            step="Sending message" if request.mode == RunMode.MESSAGE else "Getting ready",
            error="",
            last_error="",
            stop_requested=False,
        )
        self._emit_run_event("run.started")
        self._emit_event(
            "conversation.updated",
            {
                "workspace_id": request.workspace_id,
                "conversation_id": request.conversation_id,
            },
        )
        worker = threading.Thread(
            target=self._run_background_interaction,
            args=(
                request.workspace_id,
                request.conversation_id,
                request.content,
                request.mode,
                effective_context,
                request.assistant_mode,
                request.provider,
                request.model,
                request.max_step_retries,
                request.event_callback,
                request.workspace_repo_path,
            ),
            daemon=True,
        )
        worker.start()

    def _finish_active_run(self, workspace_id: str) -> None:
        next_request: QueuedMessageRequest | None = None
        with self._queue_lock:
            self.coordinator.finish(workspace_id)
            if self._pending_runs:
                candidate = self._pending_runs.popleft()
                if self.coordinator.try_start(
                    candidate.workspace_id,
                    conversation_id=candidate.conversation_id,
                    mode=str(candidate.mode),
                    run_id=candidate.request_id,
                    last_prompt=candidate.content,
                ):
                    next_request = candidate
                else:
                    self._pending_runs.appendleft(candidate)
        if next_request is not None:
            self._start_message_request(next_request)

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
        response_model = self._effective_message_model(
            provider=provider,
            model=model,
            prompt=effective_context.current_input,
        )
        response_provider = infer_provider_for_model(response_model, provider)
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["message"],
            "properties": {"message": {"type": "string"}},
        }
        response = self.phase_client.run(
            ExecutionRequest(
                provider=response_provider,
                codex_bin=self.app_settings.codex_bin,
                model=response_model,
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

    def _effective_message_model(self, *, provider: ProviderKind, model: str, prompt: str) -> str:
        if provider != ProviderKind.OLLAMA:
            return model
        if not extract_prompt_screenshot_paths(prompt):
            return model
        if model_supports_images(model):
            return model
        discovered = probe_ollama(self.app_settings.ollama_host)
        for candidate in discovered.models:
            if model_supports_images(candidate):
                return candidate
        vision_model = (self.app_settings.vision_model or "").strip()
        if vision_model and model_supports_images(vision_model):
            return vision_model
        return model

    def _should_execute_dev_message(
        self,
        *,
        assistant_mode: AssistantCapabilityMode,
        prompt: str,
        provider: ProviderKind,
        model: str,
    ) -> bool:
        if assistant_mode != AssistantCapabilityMode.DEV:
            return False
        if not _looks_like_action_request(prompt):
            return False
        return True

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
            notes = [note.strip() for note in step_run.build_result.notes if note.strip()]
            if notes:
                change_lines.extend(notes[:4])
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
        provider, model = self._effective_provider_and_model()
        self._refresh_summary_if_needed(
            controller,
            record.id,
            provider=provider,
            model=model,
        )
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
        resolved_provider = provider or self.app_settings.provider
        if model:
            return infer_provider_for_model(model, resolved_provider), model
        resolved_model = self._default_model_for_provider(resolved_provider)
        if resolved_provider == ProviderKind.OLLAMA and not resolved_model:
            discovered = probe_ollama(self.app_settings.ollama_host)
            if discovered.models:
                self.app_settings.open_source_model = discovered.models[0]
                self.app_settings.model = discovered.models[0]
                resolved_model = discovered.models[0]
        return resolved_provider, resolved_model

    def _default_model_for_provider(self, provider: ProviderKind) -> str:
        if provider == ProviderKind.CODEX:
            return (self.app_settings.openai_model or "").strip() or "gpt-5.3-codex"
        open_source_model = (self.app_settings.open_source_model or "").strip()
        if open_source_model:
            return open_source_model
        if infer_provider_for_model(self.app_settings.model, self.app_settings.provider) == ProviderKind.OLLAMA:
            return self.app_settings.model
        return ""

    def _synchronize_runtime_settings(self, *, discovered_models: list[str] | None = None) -> bool:
        settings = self.app_settings
        changed = False
        openai_model = (settings.openai_model or "").strip()
        if not openai_model:
            legacy = settings.model if infer_provider_for_model(settings.model, settings.provider) == ProviderKind.CODEX else ""
            settings.openai_model = legacy or "gpt-5.3-codex"
            changed = True
        open_source_model = (settings.open_source_model or "").strip()
        if not open_source_model:
            legacy = settings.model if infer_provider_for_model(settings.model, settings.provider) == ProviderKind.OLLAMA else ""
            if legacy:
                settings.open_source_model = legacy
                open_source_model = legacy
                changed = True
            elif discovered_models:
                settings.open_source_model = discovered_models[0]
                open_source_model = settings.open_source_model
                changed = True
        resolved_model = self._default_model_for_provider(settings.provider)
        if settings.model != resolved_model:
            settings.model = resolved_model
            changed = True
        return changed

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

    def _require_workspace_controller(self, workspace_id: str) -> WorkspaceConversationController:
        if not self.conversation_store.workspace_exists(workspace_id):
            raise KeyError(workspace_id)
        return self._controller(workspace_id)

    def _workspace_id_for_repo_path(self, repo_path: Path) -> str | None:
        expected = repo_path.resolve()
        for workspace in self.list_workspaces():
            raw_repo = str(workspace.get("repo_path") or "").strip()
            if not raw_repo:
                continue
            try:
                candidate = Path(raw_repo).expanduser().resolve()
            except OSError:
                continue
            if candidate == expected:
                return str(workspace["id"])
        return None

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

    def image_workflow_file(self, workspace_id: str, relative_path: str) -> Path:
        self._require_image_workspace(workspace_id)
        with self._image_workflow_lock:
            store = self._image_store(workspace_id)
            return store.workflow_file(relative_path)

    def _is_studio_workspace_kind(self, workspace_kind: str | None) -> bool:
        return str(workspace_kind or "").startswith("studio_")

    def _require_image_workspace(self, workspace_id: str) -> WorkspaceConversationController:
        controller = self._controller(workspace_id)
        if controller.state.workspace_kind != "studio_image":
            raise ValueError("Workspace is not an Alcove Image Studio workspace.")
        return controller

    def _image_store(self, workspace_id: str) -> ImageWorkflowStore:
        return ImageWorkflowStore(
            self.conversation_store.workspace_dir(workspace_id),
            asset_export_root=self.config.image_export_root,
        )

    def _image_workflow_file_url(self, workspace_id: str, relative_path: str) -> str:
        clean = relative_path.strip().lstrip("/")
        return f"/workspace-media/{workspace_id}/{clean}"

    def _run_image_to_3d_job(self, workspace_id: str, job_id: str) -> None:
        started = time.perf_counter()
        poll_interval_seconds = 0.1
        try:
            with self._image_workflow_lock:
                store = self._image_store(workspace_id)
                job = store.get_job(job_id)
                asset = store.get_asset(job.source_image_id)
                image_path = store.asset_path(asset)
                output_dir = store.workspace_dir / job.output_dir
            provider_job_id = self._image_to_3d_provider.create_job(
                image_path=image_path,
                output_dir=output_dir,
                prompt_context=job.prompt_context,
            )
            with self._image_workflow_lock:
                self._image_store(workspace_id).update_job(job_id, external_job_id=provider_job_id)
            last_display_status = "queued"
            while True:
                update = self._image_to_3d_provider.get_job_status(provider_job_id)
                raw_status = str(update.status or "").strip() or "queued"
                display_status = _image_workflow_job_display_status(raw_status)
                with self._image_workflow_lock:
                    current_job = self._image_store(workspace_id).get_job(job_id)
                    if (
                        current_job.status != raw_status
                        or current_job.external_job_id != provider_job_id
                        or (update.metadata and dict(current_job.metadata) != dict(update.metadata))
                    ):
                        self._image_store(workspace_id).update_job(
                            job_id,
                            status=raw_status,
                            external_job_id=provider_job_id,
                            metadata=update.metadata if update.metadata else None,
                        )
                if display_status not in {"succeeded", "failed"} and display_status != last_display_status:
                    self._emit_image_to_3d_status(workspace_id, job_id, display_status)
                    last_display_status = display_status
                if display_status == "succeeded":
                    if not update.artifacts:
                        raise RuntimeError("3D provider marked the job succeeded without returning artifacts.")
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    metadata = dict(update.metadata)
                    metadata.setdefault("duration_ms", duration_ms)
                    with self._image_workflow_lock:
                        store = self._image_store(workspace_id)
                        store.save_job_artifact_paths(job_id, update.artifacts, metadata=metadata)
                        store.update_job(job_id, status=raw_status, metadata=metadata)
                    self._emit_image_to_3d_status(workspace_id, job_id, "succeeded")
                    break
                if display_status == "failed":
                    failure_message = str(update.error or "3D generation failed.").strip() or "3D generation failed."
                    with self._image_workflow_lock:
                        self._image_store(workspace_id).update_job(
                            job_id,
                            status=raw_status,
                            metadata=update.metadata if update.metadata else None,
                            error=failure_message,
                        )
                    self._emit_image_to_3d_status(workspace_id, job_id, "failed", error=failure_message)
                    break
                time.sleep(poll_interval_seconds)
        except Exception as exc:
            with self._image_workflow_lock:
                try:
                    self._image_store(workspace_id).update_job(job_id, status="failed", error=str(exc))
                except Exception:
                    pass
            self._emit_image_to_3d_status(workspace_id, job_id, "failed", error=str(exc))

    def _emit_image_to_3d_status(self, workspace_id: str, job_id: str, status: str, *, error: str | None = None) -> None:
        payload: dict[str, object] = {
            "workspace_id": workspace_id,
            "kind": "job-status",
            "job_type": "image_to_3d",
            "job_id": job_id,
            "status": status,
        }
        if error:
            payload["error"] = error
        self._emit_event("image-workflow.updated", payload)

    def _run_image_to_video_job(self, workspace_id: str, job_id: str) -> None:
        started = time.perf_counter()
        poll_interval_seconds = 0.1
        try:
            with self._image_workflow_lock:
                store = self._image_store(workspace_id)
                job = store.get_job(job_id)
                asset = store.get_asset(job.source_image_id)
                image_path = store.asset_path(asset)
                output_dir = store.workspace_dir / job.output_dir
            provider_job_id = self._image_to_video_provider.create_job(
                image_path=image_path,
                output_dir=output_dir,
                prompt_context=job.prompt_context,
            )
            with self._image_workflow_lock:
                self._image_store(workspace_id).update_job(job_id, external_job_id=provider_job_id)
            last_display_status = "queued"
            while True:
                update = self._image_to_video_provider.get_job_status(provider_job_id)
                raw_status = str(update.status or "").strip() or "queued"
                display_status = _image_workflow_job_display_status(raw_status)
                with self._image_workflow_lock:
                    current_job = self._image_store(workspace_id).get_job(job_id)
                    if (
                        current_job.status != raw_status
                        or current_job.external_job_id != provider_job_id
                        or (update.metadata and dict(current_job.metadata) != dict(update.metadata))
                    ):
                        self._image_store(workspace_id).update_job(
                            job_id,
                            status=raw_status,
                            external_job_id=provider_job_id,
                            metadata=update.metadata if update.metadata else None,
                        )
                if display_status not in {"succeeded", "failed"} and display_status != last_display_status:
                    self._emit_image_to_video_status(workspace_id, job_id, display_status)
                    last_display_status = display_status
                if display_status == "succeeded":
                    if not update.artifacts:
                        raise RuntimeError("Video provider marked the job succeeded without returning artifacts.")
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    metadata = dict(update.metadata)
                    metadata.setdefault("duration_ms", duration_ms)
                    with self._image_workflow_lock:
                        store = self._image_store(workspace_id)
                        store.save_job_artifact_paths(job_id, update.artifacts, metadata=metadata)
                        store.update_job(job_id, status=raw_status, metadata=metadata)
                    self._emit_image_to_video_status(workspace_id, job_id, "succeeded")
                    break
                if display_status == "failed":
                    failure_message = str(update.error or "Video generation failed.").strip() or "Video generation failed."
                    with self._image_workflow_lock:
                        self._image_store(workspace_id).update_job(
                            job_id,
                            status=raw_status,
                            metadata=update.metadata if update.metadata else None,
                            error=failure_message,
                        )
                    self._emit_image_to_video_status(workspace_id, job_id, "failed", error=failure_message)
                    break
                time.sleep(poll_interval_seconds)
        except Exception as exc:
            with self._image_workflow_lock:
                try:
                    self._image_store(workspace_id).update_job(job_id, status="failed", error=str(exc))
                except Exception:
                    pass
            self._emit_image_to_video_status(workspace_id, job_id, "failed", error=str(exc))

    def _emit_image_to_video_status(self, workspace_id: str, job_id: str, status: str, *, error: str | None = None) -> None:
        payload: dict[str, object] = {
            "workspace_id": workspace_id,
            "kind": "job-status",
            "job_type": "image_to_video",
            "job_id": job_id,
            "status": status,
        }
        if error:
            payload["error"] = error
        self._emit_event("image-workflow.updated", payload)

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

    def _import_workspace_profile(
        self,
        *,
        repo_path: Path,
        workspace_id: str,
        display_name: str,
        preferred_workspace_kind: str | None,
    ) -> dict[str, str | None]:
        package_json = _read_package_json(repo_path / "package.json")
        studio_manifest = _read_studio_manifest(repo_path)
        requested_kind = str(preferred_workspace_kind or "").strip().lower()
        manifest_kind = str(studio_manifest.get("workspace_kind") or "").strip().lower()
        manifest_template = _optional_text(studio_manifest.get("template_kind"))
        preview_relative_path = _detect_preview_entry_path(repo_path, package_json)
        has_phaser = _package_uses_dependency(package_json, "phaser")

        if requested_kind in KNOWN_STUDIO_KINDS:
            studio_kind = requested_kind
        elif manifest_kind in KNOWN_STUDIO_KINDS:
            studio_kind = manifest_kind
        elif preview_relative_path:
            studio_kind = "studio_game" if has_phaser else "studio_web"
        else:
            studio_kind = ""

        if not studio_kind:
            return {
                "workspace_kind": "standard",
                "artifact_title": None,
                "template_kind": None,
                "preview_url": None,
                "preview_state": None,
                "publish_state": None,
            }

        if not preview_relative_path:
            preview_relative_path = _default_preview_entry_path(repo_path, package_json)
        if manifest_template and manifest_kind == studio_kind:
            template_kind = normalize_template_kind(studio_kind, manifest_template)
        else:
            template_kind = "phaser-vite" if studio_kind == "studio_game" else "imported"
        preview_state = "ready" if preview_relative_path and (repo_path / preview_relative_path).exists() else "draft"
        preview_url = (
            f"/studio/preview/{workspace_id}/{preview_relative_path}"
            if preview_relative_path
            else None
        )
        return {
            "workspace_kind": studio_kind,
            "artifact_title": display_name,
            "template_kind": template_kind,
            "preview_url": preview_url,
            "preview_state": preview_state,
            "publish_state": "draft",
        }

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

    def _refresh_summary_if_needed(
        self,
        controller: WorkspaceConversationController,
        conversation_id: str,
        *,
        provider: ProviderKind,
        model: str,
    ) -> None:
        record = controller.active_conversation()
        if record.id != conversation_id:
            return
        summary = self.context_assembler.refresh_summary(
            record,
            provider=provider,
            model=model,
            configured_context_char_cap=self.app_settings.context_char_cap,
        )
        if summary != record.summary:
            controller.update_summary(conversation_id, summary)

    def _find_conversation_for_thread(
        self,
        controller: WorkspaceConversationController,
        *,
        channel: str,
        thread_key: str,
    ) -> ConversationRecord | None:
        for record in controller.metadata(include_archived=True):
            normalized = normalize_thread_context(record.thread_context)
            if normalized.get("channel") == channel and normalized.get("thread_key") == thread_key:
                return record
        return None

    def _record_payload(self, record: ConversationRecord, *, include_messages: bool = False) -> dict[str, object]:
        workspace = self.ensure_workspace(record.workspace_id)
        provider, model = self._effective_provider_and_model()
        context_window = self.context_assembler.conversation_metrics(
            record,
            provider=provider,
            model=model,
            configured_context_char_cap=self.app_settings.context_char_cap,
        )
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
            "thread_context": dict(record.thread_context),
            "summary": record.summary,
            "preview": self._conversation_preview(record),
            "workspace_kind": workspace.get("workspace_kind", "standard"),
            "archived_at": record.archived_at,
            "is_archived": bool(record.archived_at),
            "context_window": context_window,
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
            "conversation_count": len(controller.metadata()),
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
        if status is None:
            payload_status = self.get_run_status()
        else:
            queued_runs = self._queued_runs_payload()
            payload_status = {
                **status,
                "queue_count": len(queued_runs),
                "queued_runs": queued_runs,
            }
        payload = {
            "status": payload_status,
        }
        self._emit_event(event_type, payload)

    def _queued_runs_payload(
        self,
        *,
        workspace_id: str | None = None,
        conversation_id: str | None = None,
    ) -> list[dict[str, object]]:
        with self._queue_lock:
            queued = list(self._pending_runs)
        payloads: list[dict[str, object]] = []
        for position, item in enumerate(queued, start=1):
            if workspace_id and item.workspace_id != workspace_id:
                continue
            if conversation_id and item.conversation_id != conversation_id:
                continue
            payloads.append(item.status_payload(position=position))
        return payloads

    def _image_generation_queue_payload(self, *, workspace_id: str | None = None) -> dict[str, object]:
        with self._image_generation_queue_lock:
            active = self._active_image_generation
            queued = list(self._pending_image_generations)
            last_error = self._image_generation_errors.get(workspace_id or "")
        active_payload: dict[str, object] | None = None
        if active is not None and (workspace_id is None or active.workspace_id == workspace_id):
            active_payload = active.status_payload(state="running", position=0)
        payloads: list[dict[str, object]] = []
        for position, item in enumerate(queued, start=1):
            if workspace_id and item.workspace_id != workspace_id:
                continue
            payloads.append(item.status_payload(state="queued", position=position))
        return {
            "active": active_payload,
            "items": payloads,
            "count": len(payloads),
            "running": active_payload is not None,
            "last_error": last_error,
        }

    def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        listeners = list(self._event_listeners)
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
        for listener in listeners:
            try:
                listener(event_type, payload)
            except Exception:
                continue

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


def _image_workflow_job_display_status(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"queued", "running", "succeeded", "failed"}:
        return text
    if text in {"preparing_input", "postprocessing"}:
        return "running"
    if text == "canceled":
        return "failed"
    return text or "queued"


def _open_local_path(path: Path) -> None:
    target = Path(path).expanduser().resolve()
    if sys.platform == "darwin":
        cmd = ["open", str(target)]
    elif os.name == "nt":
        cmd = ["explorer", str(target)]
    else:
        cmd = ["xdg-open", str(target)]
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip() or f"command exited with {completed.returncode}"
        raise RuntimeError(f"Could not open {target}: {detail}")


def _looks_like_action_request(prompt: str) -> bool:
    text = prompt.strip().lower()
    if not text:
        return False
    if re.fullmatch(r"(continue|go ahead|keep going|carry on|please continue|yes)", text):
        return True
    if ACTION_REQUEST_PATTERN.search(text):
        return True
    return bool(not READ_ONLY_MESSAGE_PATTERN.search(text) and "please" in text)


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


def _normalize_repo_input_path(raw: str) -> Path:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("Workspace repo path cannot be empty.")
    if text.startswith("file://"):
        parsed = urlparse(text)
        text = unquote(parsed.path or "")
    return Path(text).expanduser().resolve()


def _read_package_json(package_json_path: Path) -> dict[str, object]:
    try:
        payload = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _package_uses_dependency(package_json: dict[str, object], name: str) -> bool:
    for section_name in ("dependencies", "devDependencies"):
        section = package_json.get(section_name)
        if isinstance(section, dict) and name in section:
            return True
    return False


def _package_has_build_script(package_json: dict[str, object]) -> bool:
    scripts = package_json.get("scripts")
    return isinstance(scripts, dict) and bool(str(scripts.get("build") or "").strip())


def _detect_preview_entry_path(repo_path: Path, package_json: dict[str, object]) -> str | None:
    for relative in ("dist/index.html", "index.html"):
        if (repo_path / relative).exists():
            return relative
    if _package_has_build_script(package_json):
        return "dist/index.html"
    return None


def _default_preview_entry_path(repo_path: Path, package_json: dict[str, object]) -> str | None:
    return _detect_preview_entry_path(repo_path, package_json)


def _read_studio_manifest(repo_path: Path) -> dict[str, object]:
    try:
        payload = json.loads((repo_path / "alcove-studio.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _coerce_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_zimage_lora_name(value: object | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    available = {str(item.get("name") or "") for item in zimage_lora_options()}
    if text not in available:
        raise ValueError(f"Unknown Z-Image LoRA: {text}")
    return text


def _normalize_lora_strength(value: object | None) -> float:
    try:
        parsed = float(value) if value is not None else 0.75
    except (TypeError, ValueError):
        parsed = 0.75
    return min(max(parsed, 0.0), 2.0)


def _prompt_with_lora(prompt: str, lora_name: str | None, lora_strength: float) -> str:
    if not lora_name:
        return prompt
    if f"<lora:{lora_name}:" in prompt:
        return prompt
    return f"{prompt} <lora:{lora_name}:{lora_strength:g}>"
