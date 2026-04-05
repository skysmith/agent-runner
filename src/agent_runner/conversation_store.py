from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import AssistantCapabilityMode, ConversationMessage, ConversationRecord, WorkspaceSessionState

DEFAULT_CONVERSATION_TITLE = "New conversation"


class ConversationStore:
    def __init__(self, root: Path):
        self.root = root

    def load_workspace_state(self, workspace_id: str) -> WorkspaceSessionState:
        path = self._workspace_state_path(workspace_id)
        if not path.exists():
            return WorkspaceSessionState(workspace_id=workspace_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return WorkspaceSessionState(workspace_id=workspace_id)
        if not isinstance(raw, dict):
            return WorkspaceSessionState(workspace_id=workspace_id)
        return WorkspaceSessionState(
            workspace_id=str(raw.get("workspace_id", workspace_id)),
            active_conversation_id=_optional_text(raw.get("active_conversation_id")),
            conversation_ids=_as_string_list(raw.get("conversation_ids")),
            conversations_panel_collapsed=bool(raw.get("conversations_panel_collapsed", False)),
            display_name=_optional_text(raw.get("display_name")),
            repo_path=_optional_text(raw.get("repo_path")),
            workspace_kind=_workspace_kind_from_raw(raw.get("workspace_kind")),
            artifact_title=_optional_text(raw.get("artifact_title")) or _optional_text(raw.get("game_title")),
            template_kind=_optional_text(raw.get("template_kind")),
            game_title=_optional_text(raw.get("game_title")),
            theme_prompt=_optional_text(raw.get("theme_prompt")),
            preview_url=_optional_text(raw.get("preview_url")),
            preview_state=_optional_text(raw.get("preview_state")),
            publish_url=_optional_text(raw.get("publish_url")),
            publish_state=_optional_text(raw.get("publish_state")),
            publish_slug=_optional_text(raw.get("publish_slug")),
        )

    def save_workspace_state(self, state: WorkspaceSessionState) -> None:
        self._atomic_write_json(self._workspace_state_path(state.workspace_id), {
            "workspace_id": state.workspace_id,
            "active_conversation_id": state.active_conversation_id,
            "conversation_ids": list(state.conversation_ids),
            "conversations_panel_collapsed": state.conversations_panel_collapsed,
            "display_name": state.display_name,
            "repo_path": state.repo_path,
            "workspace_kind": state.workspace_kind,
            "artifact_title": state.artifact_title,
            "template_kind": state.template_kind,
            "game_title": state.game_title,
            "theme_prompt": state.theme_prompt,
            "preview_url": state.preview_url,
            "preview_state": state.preview_state,
            "publish_url": state.publish_url,
            "publish_state": state.publish_state,
            "publish_slug": state.publish_slug,
        })

    def list_conversations(self, workspace_id: str) -> list[ConversationRecord]:
        conversations_dir = self._conversations_dir(workspace_id)
        if not conversations_dir.exists():
            return []
        records: list[ConversationRecord] = []
        for path in sorted(conversations_dir.glob("*.json")):
            record = self.load_conversation(path.stem, workspace_id=workspace_id)
            if record is not None:
                records.append(record)
        return records

    def load_conversation(self, conversation_id: str, *, workspace_id: str) -> ConversationRecord | None:
        path = self._conversation_path(workspace_id, conversation_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        return _conversation_from_json(raw, conversation_id=conversation_id, workspace_id=workspace_id)

    def save_conversation(self, record: ConversationRecord) -> None:
        payload = asdict(record)
        self._atomic_write_json(self._conversation_path(record.workspace_id, record.id), payload)

    def delete_conversation(self, workspace_id: str, conversation_id: str) -> None:
        path = self._conversation_path(workspace_id, conversation_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return

    def create_conversation(self, workspace_id: str, *, title: str = DEFAULT_CONVERSATION_TITLE) -> ConversationRecord:
        now = _timestamp_now()
        return ConversationRecord(
            id=uuid4().hex,
            workspace_id=workspace_id,
            title=title,
            created_at=now,
            updated_at=now,
            assistant_mode=AssistantCapabilityMode.ASK,
            page_context={},
            summary=None,
            messages=[],
        )

    def ensure_workspace(self, workspace_id: str) -> WorkspaceSessionState:
        state = self.load_workspace_state(workspace_id)
        records = {record.id: record for record in self.list_conversations(workspace_id)}
        state.conversation_ids = [cid for cid in state.conversation_ids if cid in records]
        if not state.conversation_ids and records:
            state.conversation_ids = _sorted_conversation_ids(records.values())
        if state.active_conversation_id not in state.conversation_ids:
            state.active_conversation_id = state.conversation_ids[0] if state.conversation_ids else None
        if state.active_conversation_id is None:
            record = self.create_conversation(workspace_id)
            self.save_conversation(record)
            state.active_conversation_id = record.id
            state.conversation_ids = [record.id]
        self.save_workspace_state(state)
        return state

    def _workspace_dir(self, workspace_id: str) -> Path:
        return self.root / workspace_id

    def _workspace_state_path(self, workspace_id: str) -> Path:
        return self._workspace_dir(workspace_id) / "workspace_state.json"

    def _conversations_dir(self, workspace_id: str) -> Path:
        return self._workspace_dir(workspace_id) / "conversations"

    def _conversation_path(self, workspace_id: str, conversation_id: str) -> Path:
        return self._conversations_dir(workspace_id) / f"{conversation_id}.json"

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + f".{uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, path)


class WorkspaceConversationController:
    def __init__(self, store: ConversationStore, workspace_id: str):
        self.store = store
        self.workspace_id = workspace_id
        self.state = store.ensure_workspace(workspace_id)
        self._records: dict[str, ConversationRecord] = {
            record.id: record for record in store.list_conversations(workspace_id)
        }
        self._normalize_after_load()

    def metadata(self) -> list[ConversationRecord]:
        return [self._records[cid] for cid in self.state.conversation_ids if cid in self._records]

    def reload(self) -> None:
        self.state = self.store.ensure_workspace(self.workspace_id)
        self._records = {
            record.id: record for record in self.store.list_conversations(self.workspace_id)
        }
        self._normalize_after_load()

    def active_conversation(self) -> ConversationRecord:
        active_id = self.state.active_conversation_id
        if active_id and active_id in self._records:
            return self._records[active_id]
        self._normalize_after_load()
        return self._records[self.state.active_conversation_id]

    def set_panel_collapsed(self, collapsed: bool) -> None:
        if self.state.conversations_panel_collapsed == collapsed:
            return
        self.state.conversations_panel_collapsed = collapsed
        self.store.save_workspace_state(self.state)

    def set_workspace_profile(
        self,
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
    ) -> WorkspaceSessionState:
        clean_name = self.state.display_name if display_name is None else ((display_name or "").strip() or None)
        clean_repo_path = self.state.repo_path if repo_path is None else ((repo_path or "").strip() or None)
        clean_kind = _workspace_kind_from_raw(workspace_kind if workspace_kind is not None else self.state.workspace_kind)
        clean_template = self.state.template_kind if template_kind is None else ((template_kind or "").strip() or None)
        if artifact_title is None and game_title is None:
            clean_artifact_title = self.state.artifact_title or self.state.game_title
        else:
            clean_artifact_title = ((artifact_title or game_title or "").strip() or None)
        clean_theme = self.state.theme_prompt if theme_prompt is None else ((theme_prompt or "").strip() or None)
        clean_preview_url = self.state.preview_url if preview_url is None else ((preview_url or "").strip() or None)
        clean_preview_state = self.state.preview_state if preview_state is None else ((preview_state or "").strip() or None)
        clean_publish_url = self.state.publish_url if publish_url is None else ((publish_url or "").strip() or None)
        clean_publish_state = self.state.publish_state if publish_state is None else ((publish_state or "").strip() or None)
        clean_publish_slug = self.state.publish_slug if publish_slug is None else ((publish_slug or "").strip() or None)
        if (
            self.state.display_name == clean_name
            and self.state.repo_path == clean_repo_path
            and self.state.workspace_kind == clean_kind
            and self.state.artifact_title == clean_artifact_title
            and self.state.template_kind == clean_template
            and self.state.game_title == clean_artifact_title
            and self.state.theme_prompt == clean_theme
            and self.state.preview_url == clean_preview_url
            and self.state.preview_state == clean_preview_state
            and self.state.publish_url == clean_publish_url
            and self.state.publish_state == clean_publish_state
            and self.state.publish_slug == clean_publish_slug
        ):
            return self.state
        self.state.display_name = clean_name
        self.state.repo_path = clean_repo_path
        self.state.workspace_kind = clean_kind
        self.state.artifact_title = clean_artifact_title
        self.state.template_kind = clean_template
        self.state.game_title = clean_artifact_title
        self.state.theme_prompt = clean_theme
        self.state.preview_url = clean_preview_url
        self.state.preview_state = clean_preview_state
        self.state.publish_url = clean_publish_url
        self.state.publish_state = clean_publish_state
        self.state.publish_slug = clean_publish_slug
        self.store.save_workspace_state(self.state)
        return self.state

    def create_conversation(self) -> ConversationRecord:
        record = self.store.create_conversation(self.workspace_id)
        self._records[record.id] = record
        self.state.active_conversation_id = record.id
        self._resort_state()
        self.store.save_conversation(record)
        self.store.save_workspace_state(self.state)
        return record

    def select_conversation(self, conversation_id: str) -> ConversationRecord:
        if conversation_id not in self._records:
            raise KeyError(conversation_id)
        self.state.active_conversation_id = conversation_id
        self.store.save_workspace_state(self.state)
        return self._records[conversation_id]

    def rename_conversation(self, conversation_id: str, title: str) -> ConversationRecord:
        record = self._records[conversation_id]
        clean_title = title.strip() or DEFAULT_CONVERSATION_TITLE
        record.title = clean_title
        record.updated_at = _timestamp_now()
        self._save_record(record)
        return record

    def delete_conversation(self, conversation_id: str) -> ConversationRecord:
        if conversation_id not in self._records:
            raise KeyError(conversation_id)
        was_active = self.state.active_conversation_id == conversation_id
        self.store.delete_conversation(self.workspace_id, conversation_id)
        self._records.pop(conversation_id, None)
        self.state.conversation_ids = [cid for cid in self.state.conversation_ids if cid != conversation_id]
        if not self.state.conversation_ids:
            fallback = self.store.create_conversation(self.workspace_id)
            self._records[fallback.id] = fallback
            self.state.conversation_ids = [fallback.id]
            self.state.active_conversation_id = fallback.id
            self.store.save_conversation(fallback)
        elif was_active or self.state.active_conversation_id not in self._records:
            self.state.active_conversation_id = self.state.conversation_ids[0]
        self.store.save_workspace_state(self.state)
        return self.active_conversation()

    def clear_conversation(self, conversation_id: str) -> ConversationRecord:
        if conversation_id not in self._records:
            raise KeyError(conversation_id)
        record = self._records[conversation_id]
        record.messages = []
        record.summary = None
        record.updated_at = _timestamp_now()
        self._save_record(record)
        return record

    def set_assistant_context(
        self,
        conversation_id: str,
        *,
        assistant_mode: AssistantCapabilityMode | None = None,
        page_context: dict[str, object] | None = None,
    ) -> ConversationRecord:
        if conversation_id not in self._records:
            raise KeyError(conversation_id)
        record = self._records[conversation_id]
        changed = False
        if assistant_mode is not None and record.assistant_mode != assistant_mode:
            record.assistant_mode = assistant_mode
            changed = True
        if page_context is not None and record.page_context != page_context:
            record.page_context = dict(page_context)
            changed = True
        if changed:
            record.updated_at = _timestamp_now()
            self._save_record(record)
        return record

    def append_message(
        self,
        *,
        role: str,
        content: str,
        run_id: str | None = None,
        phase: str | None = None,
    ) -> ConversationRecord:
        record = self.active_conversation()
        text = content.strip()
        if not text:
            return record
        message = ConversationMessage(
            id=uuid4().hex,
            conversation_id=record.id,
            role=role,
            content=text,
            created_at=_timestamp_now(),
            run_id=run_id,
            phase=phase,
        )
        record.messages.append(message)
        if role == "user" and _should_autotitle(record.title, len(record.messages)):
            record.title = derive_conversation_title(text)
        record.updated_at = message.created_at
        if record.summary and len(record.messages) < 8:
            record.summary = None
        self._save_record(record)
        return record

    def update_summary(self, conversation_id: str, summary: str | None) -> ConversationRecord:
        record = self._records[conversation_id]
        record.summary = summary.strip() if summary else None
        self._save_record(record)
        return record

    def _save_record(self, record: ConversationRecord) -> None:
        self._records[record.id] = record
        self._resort_state()
        self.store.save_conversation(record)
        self.store.save_workspace_state(self.state)

    def _resort_state(self) -> None:
        ordered = sorted(
            self._records.values(),
            key=lambda record: (record.updated_at, record.created_at, record.id),
            reverse=True,
        )
        self.state.conversation_ids = [record.id for record in ordered]
        if self.state.active_conversation_id not in self.state.conversation_ids and self.state.conversation_ids:
            self.state.active_conversation_id = self.state.conversation_ids[0]

    def _normalize_after_load(self) -> None:
        if not self._records:
            record = self.store.create_conversation(self.workspace_id)
            self._records[record.id] = record
            self.store.save_conversation(record)
        self._resort_state()
        if self.state.active_conversation_id not in self._records:
            self.state.active_conversation_id = self.state.conversation_ids[0]
        self.store.save_workspace_state(self.state)


def derive_conversation_title(message_text: str, max_len: int = 60) -> str:
    first_line = next((line.strip() for line in message_text.splitlines() if line.strip()), "")
    if not first_line:
        return DEFAULT_CONVERSATION_TITLE
    compact = " ".join(first_line.split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 1].rstrip() + "…"


def build_transcript(messages: list[ConversationMessage]) -> str:
    lines: list[str] = []
    for message in messages:
        label = message.role.upper()
        lines.append(f"{label}:\n{message.content.strip()}")
    return "\n\n".join(lines).strip()


def synthesize_summary(messages: list[ConversationMessage], max_chars: int = 900) -> str:
    if not messages:
        return ""
    lines: list[str] = []
    for message in messages:
        text = " ".join(message.content.split())
        if not text:
            continue
        snippet = text[:180].rstrip()
        prefix = "User" if message.role == "user" else "Assistant" if message.role == "assistant" else "System"
        lines.append(f"- {prefix}: {snippet}")
        candidate = "\n".join(lines)
        if len(candidate) >= max_chars:
            break
    summary = "\n".join(lines).strip()
    return summary[:max_chars].rstrip()


def _conversation_from_json(raw: dict[str, Any], *, conversation_id: str, workspace_id: str) -> ConversationRecord:
    messages_raw = raw.get("messages")
    messages: list[ConversationMessage] = []
    if isinstance(messages_raw, list):
        for item in messages_raw:
            if not isinstance(item, dict):
                continue
            messages.append(
                ConversationMessage(
                    id=str(item.get("id") or uuid4().hex),
                    conversation_id=str(item.get("conversation_id") or conversation_id),
                    role=str(item.get("role") or "assistant"),
                    content=str(item.get("content") or ""),
                    created_at=str(item.get("created_at") or _timestamp_now()),
                    run_id=_optional_text(item.get("run_id")),
                    phase=_optional_text(item.get("phase")),
                )
            )
    return ConversationRecord(
        id=str(raw.get("id") or conversation_id),
        workspace_id=str(raw.get("workspace_id") or workspace_id),
        title=str(raw.get("title") or DEFAULT_CONVERSATION_TITLE),
        created_at=str(raw.get("created_at") or _timestamp_now()),
        updated_at=str(raw.get("updated_at") or _timestamp_now()),
        assistant_mode=_assistant_mode_from_raw(raw.get("assistant_mode")),
        page_context=_object_dict(raw.get("page_context")),
        summary=_optional_text(raw.get("summary")),
        messages=messages,
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _assistant_mode_from_raw(value: object) -> AssistantCapabilityMode:
    if value is None:
        return AssistantCapabilityMode.ASK
    try:
        return AssistantCapabilityMode(str(value).strip().lower())
    except ValueError:
        return AssistantCapabilityMode.ASK


def _workspace_kind_from_raw(value: object) -> str:
    text = str(value or "standard").strip().lower()
    return text if text in {"standard", "studio_game", "studio_web", "studio_data", "studio_docs"} else "standard"


def _sorted_conversation_ids(records: list[ConversationRecord]) -> list[str]:
    return [record.id for record in sorted(records, key=lambda record: (record.updated_at, record.created_at, record.id), reverse=True)]


def _should_autotitle(title: str, message_count: int) -> bool:
    return message_count == 1 and title.strip().lower() == DEFAULT_CONVERSATION_TITLE.lower()


def _timestamp_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
