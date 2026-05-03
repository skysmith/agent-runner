from __future__ import annotations

from typing import Any


TEXT_FIELD_ALIASES = {
    "channel": ("channel", "source", "transport"),
    "thread_key": ("thread_key", "external_thread_key", "conversation_key"),
    "participant_name": ("participant_name", "contact_name", "display_name"),
    "participant_handle": ("participant_handle", "contact_handle", "phone_number", "email", "handle"),
    "relationship": ("relationship",),
    "goal": ("goal", "task_goal"),
    "summary": ("summary", "memory_summary"),
}

LIST_FIELD_ALIASES = {
    "open_loops": ("open_loops", "open_questions", "pending_items"),
    "facts": ("facts", "known_facts"),
    "reply_style": ("reply_style", "style_notes"),
}


def normalize_thread_context(raw: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, object] = {}
    for key, aliases in TEXT_FIELD_ALIASES.items():
        value = _first_text(raw, aliases)
        if value:
            normalized[key] = value
    for key, aliases in LIST_FIELD_ALIASES.items():
        items = _first_list(raw, aliases)
        if items:
            normalized[key] = items
    return normalized


def merge_thread_context(base: dict[str, object] | None, update: dict[str, object] | None) -> dict[str, object]:
    merged = normalize_thread_context(base)
    if not isinstance(update, dict):
        return merged
    merged.update(normalize_thread_context(update))
    return merged


def suggest_thread_title(thread_context: dict[str, object] | None) -> str | None:
    normalized = normalize_thread_context(thread_context)
    participant_name = str(normalized.get("participant_name") or "").strip()
    if participant_name:
        return participant_name
    participant_handle = str(normalized.get("participant_handle") or "").strip()
    if participant_handle:
        return participant_handle
    channel = str(normalized.get("channel") or "").strip()
    thread_key = str(normalized.get("thread_key") or "").strip()
    if channel and thread_key:
        return f"{channel}:{thread_key}"
    return None


def render_thread_context_block(thread_context: dict[str, object] | None) -> str:
    normalized = normalize_thread_context(thread_context)
    if not normalized:
        return ""
    lines = ["THREAD CONTEXT:"]
    for key in ("channel", "thread_key", "participant_name", "participant_handle", "relationship", "goal", "summary"):
        value = str(normalized.get(key) or "").strip()
        if value:
            lines.append(f"- {key}: {value}")
    for key, label in (
        ("open_loops", "open_loops"),
        ("facts", "facts"),
        ("reply_style", "reply_style"),
    ):
        values = normalized.get(key)
        if not isinstance(values, list) or not values:
            continue
        lines.append(f"- {label}:")
        for item in values:
            item_text = str(item).strip()
            if item_text:
                lines.append(f"  - {item_text}")
    return "\n".join(lines).strip()


def _first_text(raw: dict[str, object], aliases: tuple[str, ...]) -> str | None:
    for alias in aliases:
        value = raw.get(alias)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_list(raw: dict[str, object], aliases: tuple[str, ...]) -> list[str]:
    for alias in aliases:
        value = raw.get(alias)
        items = _clean_list(value)
        if items:
            return items
    return []


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    items: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items
