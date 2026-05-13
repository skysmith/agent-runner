from __future__ import annotations

import base64
import binascii
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


FIELD_STATION_MODES = {"family", "maker", "business", "real-estate", "demo", "codex"}
PERMISSION_LANES = {"read-only", "draft-only", "workspace-write", "full-power"}
JOB_STATUSES = {"draft", "queued", "running", "needs_approval", "needs_review", "succeeded", "failed", "cancelled"}
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}
CAPTURE_SOURCES = {
    "typed",
    "voice",
    "magic_button",
    "physical_button",
    "camera",
    "upload",
    "owner_briefing",
    "review_follow_up",
    "review_revision",
    "station_event",
}
BRIEFING_SOURCE_KINDS = {"gmail", "shopify", "inventory", "calendar", "docs", "manual", "real_estate"}
CAPTURE_ASSET_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_CAPTURE_ASSET_BYTES = 8 * 1024 * 1024
DATA_URL_PATTERN = re.compile(r"^data:(?P<mime>[-\w.+/]+);base64,(?P<body>.+)$", re.DOTALL)


def timestamp_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def make_orchestration_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def normalize_field_station_mode(value: str | None) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    return text if text in FIELD_STATION_MODES else "maker"


def normalize_permission_lane(value: str | None) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    if text == "readonly":
        text = "read-only"
    if text == "draft":
        text = "draft-only"
    return text if text in PERMISSION_LANES else "read-only"


def normalize_job_provider(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"fake", "codex"} else "fake"


def normalize_capture_source(value: str | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in CAPTURE_SOURCES else "typed"


def normalize_briefing_source_kind(value: str | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in BRIEFING_SOURCE_KINDS else "manual"


def preview_text(value: str, *, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)].rstrip()}..."


class FieldStationOrchestrationStore:
    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir
        self.root = workspace_dir / "field-station"
        self.manifest_path = self.root / "orchestration.json"
        self.artifacts_dir = self.root / "artifacts"
        self.capture_assets_dir = self.root / "capture-assets"

    def snapshot(self) -> dict[str, object]:
        payload = self._load()
        return {
            "captures": list(payload["captures"]),
            "missions": list(payload["missions"]),
            "jobs": list(payload["jobs"]),
            "reviews": list(payload["reviews"]),
            "briefing_sources": list(payload["briefing_sources"]),
            "events": list(payload["events"])[-80:],
        }

    def create_capture(
        self,
        *,
        workspace_id: str,
        mode: str | None,
        text: str,
        source: str | None = None,
        attachments: list[dict[str, object]] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        clean_text = text.strip()
        clean_attachments = _clean_attachment_list(attachments)
        if not clean_text and not clean_attachments:
            raise ValueError("Capture text or attachment is required.")
        payload = self._load()
        now = timestamp_now()
        capture = {
            "id": make_orchestration_id("capture"),
            "workspace_id": workspace_id,
            "mode": normalize_field_station_mode(mode),
            "source": normalize_capture_source(source),
            "text": clean_text,
            "attachments": clean_attachments,
            "metadata": dict(metadata or {}),
            "status": "captured",
            "created_at": now,
            "updated_at": now,
        }
        payload["captures"].append(capture)
        payload["events"].append(
            self._event(
                "capture.created",
                {
                    "capture_id": capture["id"],
                    "workspace_id": workspace_id,
                    "source": capture["source"],
                },
            )
        )
        self._save(payload)
        return capture

    def write_capture_asset(
        self,
        *,
        workspace_id: str,
        data_url: str,
        file_name: str | None = None,
        label: str | None = None,
        source: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        mime_type, content = _decode_data_url(data_url)
        if mime_type not in CAPTURE_ASSET_MIME_TYPES:
            raise ValueError(f"Unsupported capture asset type: {mime_type}.")
        if len(content) > MAX_CAPTURE_ASSET_BYTES:
            raise ValueError("Capture asset is too large.")
        asset_id = make_orchestration_id("asset")
        extension = _extension_for_mime(mime_type)
        file_path = self.capture_assets_dir / f"{asset_id}{extension}"
        self.capture_assets_dir.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)
        now = timestamp_now()
        attachment = {
            "id": asset_id,
            "kind": "image",
            "label": (label or file_name or "capture image").strip() or "capture image",
            "source": normalize_capture_source(source),
            "path": str(file_path.relative_to(self.workspace_dir)),
            "mime_type": mime_type,
            "size_bytes": len(content),
            "created_at": now,
            "metadata": dict(metadata or {}),
        }
        payload = self._load()
        payload["events"].append(
            self._event(
                "capture_asset.created",
                {
                    "asset_id": asset_id,
                    "workspace_id": workspace_id,
                    "path": attachment["path"],
                    "mime_type": mime_type,
                    "size_bytes": len(content),
                },
            )
        )
        self._save(payload)
        return attachment

    def create_briefing_source(
        self,
        *,
        workspace_id: str,
        kind: str | None,
        label: str,
        summary: str | None = None,
        sample_items: list[dict[str, object]] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        clean_label = label.strip()
        if not clean_label:
            raise ValueError("Briefing source label is required.")
        payload = self._load()
        now = timestamp_now()
        source = {
            "id": make_orchestration_id("source"),
            "workspace_id": workspace_id,
            "kind": normalize_briefing_source_kind(kind),
            "label": clean_label,
            "status": "ready",
            "permission_lane": "read-only",
            "summary": (summary or "").strip(),
            "sample_items": _clean_briefing_items(sample_items),
            "metadata": dict(metadata or {}),
            "created_at": now,
            "updated_at": now,
        }
        payload["briefing_sources"].append(source)
        payload["events"].append(
            self._event(
                "briefing_source.created",
                {
                    "source_id": source["id"],
                    "workspace_id": workspace_id,
                    "kind": source["kind"],
                },
            )
        )
        self._save(payload)
        return source

    def create_mission(
        self,
        *,
        workspace_id: str,
        conversation_id: str | None,
        source: str | None,
        mode: str | None,
        goal: str,
        target: str | None = None,
        permission_lane: str | None = None,
        expected_output: str | None = None,
        requires_approval: bool = True,
        capture_id: str | None = None,
    ) -> dict[str, object]:
        clean_goal = goal.strip()
        if not clean_goal:
            raise ValueError("Mission goal cannot be empty.")
        payload = self._load()
        now = timestamp_now()
        capture = None
        if capture_id:
            capture = self._find(payload["captures"], capture_id, "Capture")
        mission = {
            "id": make_orchestration_id("mission"),
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "source": (source or "field_station").strip() or "field_station",
            "mode": normalize_field_station_mode(mode),
            "goal": clean_goal,
            "target": (target or "").strip() or None,
            "permission_lane": normalize_permission_lane(permission_lane),
            "expected_output": (expected_output or "artifact").strip() or "artifact",
            "requires_approval": bool(requires_approval),
            "capture_id": capture_id if capture is not None else None,
            "capture_snapshot": dict(capture) if capture is not None else None,
            "status": "draft",
            "created_at": now,
            "updated_at": now,
        }
        payload["missions"].append(mission)
        payload["events"].append(
            self._event(
                "mission.created",
                {
                    "mission_id": mission["id"],
                    "workspace_id": workspace_id,
                    "capture_id": mission["capture_id"],
                },
            )
        )
        self._save(payload)
        return mission

    def create_job(
        self,
        *,
        workspace_id: str,
        mission_id: str,
        provider: str | None = None,
    ) -> dict[str, object]:
        payload = self._load()
        mission = self._find(payload["missions"], mission_id, "Mission")
        now = timestamp_now()
        job = {
            "id": make_orchestration_id("job"),
            "workspace_id": workspace_id,
            "mission_id": mission_id,
            "provider": normalize_job_provider(provider),
            "status": "queued",
            "queue_position": None,
            "started_at": None,
            "completed_at": None,
            "cancel_requested_at": None,
            "input_snapshot": {
                "mode": mission.get("mode"),
                "goal": mission.get("goal"),
                "target": mission.get("target"),
                "permission_lane": mission.get("permission_lane"),
                "expected_output": mission.get("expected_output"),
                "capture_id": mission.get("capture_id"),
            },
            "artifact_ids": [],
            "review_id": None,
            "error": None,
            "result_metadata": {},
            "created_at": now,
            "updated_at": now,
        }
        mission["status"] = "queued"
        mission["updated_at"] = now
        payload["jobs"].append(job)
        payload["events"].append(self._event("job.queued", {"job_id": job["id"], "mission_id": mission_id, "workspace_id": workspace_id}))
        self._save(payload)
        return job

    def get_mission(self, mission_id: str) -> dict[str, object]:
        payload = self._load()
        return dict(self._find(payload["missions"], mission_id, "Mission"))

    def get_job(self, job_id: str) -> dict[str, object]:
        payload = self._load()
        return dict(self._find(payload["jobs"], job_id, "Job"))

    def update_job(self, job_id: str, **changes: object) -> dict[str, object]:
        payload = self._load()
        job = self._find(payload["jobs"], job_id, "Job")
        status = str(changes.get("status") or job.get("status") or "").strip()
        if status and status not in JOB_STATUSES:
            raise ValueError(f"Unsupported job status: {status}.")
        now = timestamp_now()
        job.update(changes)
        job["updated_at"] = now
        if status in TERMINAL_JOB_STATUSES or status == "needs_review":
            job["completed_at"] = job.get("completed_at") or now
        mission = self._find(payload["missions"], str(job["mission_id"]), "Mission")
        if status:
            mission["status"] = status
            mission["updated_at"] = now
        payload["events"].append(
            self._event(
                f"job.{status or 'updated'}",
                {"job_id": job_id, "mission_id": job["mission_id"], "workspace_id": job["workspace_id"]},
            )
        )
        self._save(payload)
        return dict(job)

    def request_cancel_job(self, job_id: str) -> dict[str, object]:
        payload = self._load()
        job = self._find(payload["jobs"], job_id, "Job")
        status = str(job.get("status") or "")
        now = timestamp_now()
        if status in TERMINAL_JOB_STATUSES:
            return dict(job)
        job["cancel_requested_at"] = now
        job["status"] = "cancelled"
        job["completed_at"] = now
        job["updated_at"] = now
        mission = self._find(payload["missions"], str(job["mission_id"]), "Mission")
        mission["status"] = "cancelled"
        mission["updated_at"] = now
        payload["events"].append(self._event("job.cancelled", {"job_id": job_id, "mission_id": job["mission_id"], "workspace_id": job["workspace_id"]}))
        self._save(payload)
        return dict(job)

    def complete_fake_job(self, job_id: str) -> dict[str, object]:
        job = self.get_job(job_id)
        if str(job.get("status")) == "cancelled":
            return dict(job)
        mission = self.get_mission(str(job["mission_id"]))
        title = _display_title(str(mission.get("mode") or ""), str(mission.get("expected_output") or "artifact"))
        artifact_markdown = "\n".join(
            [
                f"# {title}",
                "",
                f"Mission: {mission['goal']}",
                f"Mode: {mission['mode']}",
                f"Permission lane: {mission['permission_lane']}",
                "",
                "This fake-provider artifact proves the Field Station can queue work, keep the interface responsive, and return a reviewable result.",
                "",
            ]
        )
        return self.complete_job_with_artifact(
            job_id,
            title=title,
            summary=f"Prepared a fake-provider Field Station artifact for: {preview_text(str(mission['goal']), limit=90)}",
            artifact_markdown=artifact_markdown,
            evidence=[
                f"Mode: {mission['mode']}",
                f"Permission lane: {mission['permission_lane']}",
                f"Expected output: {mission['expected_output']}",
            ],
            risks=["Fake provider output is a workflow placeholder, not a final AI result."],
            suggested_next_action="Approve this placeholder, or route a real Codex/model worker after the UI loop feels right.",
            metadata={"provider": "fake"},
        )

    def complete_job_with_artifact(
        self,
        job_id: str,
        *,
        title: str,
        summary: str,
        artifact_markdown: str,
        evidence: list[str] | None = None,
        risks: list[str] | None = None,
        suggested_next_action: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload = self._load()
        job = self._find(payload["jobs"], job_id, "Job")
        if str(job.get("status")) == "cancelled":
            return dict(job)
        mission = self._find(payload["missions"], str(job["mission_id"]), "Mission")
        clean_title = title.strip() or _display_title(str(mission.get("mode") or ""), str(mission.get("expected_output") or "artifact"))
        clean_summary = summary.strip() or f"Prepared Field Station artifact for: {preview_text(str(mission.get('goal') or ''), limit=90)}"
        artifact = self._write_artifact(markdown=artifact_markdown, fallback_title=clean_title)
        review = {
            "id": make_orchestration_id("review"),
            "workspace_id": job["workspace_id"],
            "mission_id": mission["id"],
            "job_id": job["id"],
            "title": clean_title,
            "summary": clean_summary,
            "artifact_ids": [artifact["id"]],
            "artifact_paths": [artifact["path"]],
            "evidence": _clean_string_list(evidence),
            "risks": _clean_string_list(risks),
            "suggested_next_action": (suggested_next_action or "").strip() or "Review and approve the artifact, then decide the next job.",
            "status": "pending",
            "created_at": timestamp_now(),
            "reviewed_at": None,
        }
        now = timestamp_now()
        job["status"] = "needs_review"
        job["completed_at"] = now
        job["updated_at"] = now
        job["artifact_ids"] = [artifact["id"]]
        job["review_id"] = review["id"]
        job["result_metadata"] = dict(metadata or {})
        mission["status"] = "needs_review"
        mission["updated_at"] = now
        payload["reviews"].append(review)
        payload["events"].append(
            self._event(
                "review.created",
                {
                    "review_id": review["id"],
                    "job_id": job_id,
                    "artifact_id": artifact["id"],
                    "workspace_id": job["workspace_id"],
                },
            )
        )
        self._save(payload)
        return dict(job)

    def approve_review(self, review_id: str) -> dict[str, object]:
        payload = self._load()
        review = self._find(payload["reviews"], review_id, "Review")
        now = timestamp_now()
        review["status"] = "approved"
        review["reviewed_at"] = now
        job = self._find(payload["jobs"], str(review["job_id"]), "Job")
        job["status"] = "succeeded"
        job["updated_at"] = now
        job["completed_at"] = job.get("completed_at") or now
        mission = self._find(payload["missions"], str(review["mission_id"]), "Mission")
        mission["status"] = "succeeded"
        mission["updated_at"] = now
        payload["events"].append(self._event("review.approved", {"review_id": review_id, "job_id": job["id"], "workspace_id": job["workspace_id"]}))
        self._save(payload)
        return dict(review)

    def record_station_event(
        self,
        *,
        workspace_id: str,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        manifest = self._load()
        event = self._event(
            event_type.strip() or "station.event",
            {
                "workspace_id": workspace_id,
                **dict(payload or {}),
            },
        )
        manifest["events"].append(event)
        self._save(manifest)
        return dict(event)

    def _write_artifact(self, *, markdown: str, fallback_title: str) -> dict[str, str]:
        artifact_id = make_orchestration_id("artifact")
        file_name = f"{artifact_id}.md"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = self.artifacts_dir / file_name
        clean_markdown = markdown.strip()
        if not clean_markdown:
            clean_markdown = f"# {fallback_title}\n\nNo artifact body was returned."
        artifact_path.write_text(clean_markdown + "\n", encoding="utf-8")
        return {
            "id": artifact_id,
            "path": str(artifact_path.relative_to(self.workspace_dir)),
        }

    def _load(self) -> dict[str, list[dict[str, object]]]:
        if not self.manifest_path.exists():
            return self._empty()
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()
        if not isinstance(raw, dict):
            return self._empty()
        return {
            "captures": _as_dict_list(raw.get("captures")),
            "missions": _as_dict_list(raw.get("missions")),
            "jobs": _as_dict_list(raw.get("jobs")),
            "reviews": _as_dict_list(raw.get("reviews")),
            "briefing_sources": _as_dict_list(raw.get("briefing_sources")),
            "events": _as_dict_list(raw.get("events")),
        }

    def _save(self, payload: dict[str, list[dict[str, object]]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temp_path = self.manifest_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temp_path, self.manifest_path)

    def _event(self, event_type: str, payload: dict[str, object]) -> dict[str, object]:
        return {
            "id": make_orchestration_id("evt"),
            "type": event_type,
            "created_at": timestamp_now(),
            "payload": payload,
        }

    def _empty(self) -> dict[str, list[dict[str, object]]]:
        return {"captures": [], "missions": [], "jobs": [], "reviews": [], "briefing_sources": [], "events": []}

    def _find(self, items: list[dict[str, object]], item_id: str, label: str) -> dict[str, object]:
        for item in items:
            if str(item.get("id") or "") == item_id:
                return item
        raise KeyError(f"{label} not found: {item_id}")


def _as_dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _clean_string_list(value: list[str] | None) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _clean_briefing_items(value: list[dict[str, object]] | None) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, object]] = []
    for raw in value[:12]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("label") or raw.get("subject") or "").strip()
        detail = str(raw.get("detail") or raw.get("summary") or raw.get("body") or "").strip()
        urgency = str(raw.get("urgency") or raw.get("status") or "").strip()
        if not title and not detail:
            continue
        item: dict[str, object] = {
            "title": title or "Briefing item",
            "detail": detail,
        }
        if urgency:
            item["urgency"] = urgency
        items.append(item)
    return items


def _clean_attachment_list(value: list[dict[str, object]] | None) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    attachments: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or item.get("type") or "").strip() or "attachment"
        label = str(item.get("label") or item.get("name") or kind).strip()
        path = str(item.get("path") or item.get("url") or "").strip()
        attachment: dict[str, object] = {
            "kind": kind,
            "label": label,
        }
        for key in ("id", "source", "mime_type", "created_at"):
            text = str(item.get(key) or "").strip()
            if text:
                attachment[key] = text
        size_bytes = item.get("size_bytes")
        if isinstance(size_bytes, int) and size_bytes >= 0:
            attachment["size_bytes"] = size_bytes
        if path:
            attachment["path"] = path
        if isinstance(item.get("metadata"), dict):
            attachment["metadata"] = dict(item["metadata"])
        attachments.append(attachment)
    return attachments


def _decode_data_url(data_url: str) -> tuple[str, bytes]:
    match = DATA_URL_PATTERN.match(str(data_url or "").strip())
    if not match:
        raise ValueError("Capture asset must be a base64 data URL.")
    mime_type = match.group("mime").lower()
    try:
        content = base64.b64decode(match.group("body"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Capture asset data is not valid base64.") from exc
    return mime_type, content


def _extension_for_mime(mime_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(mime_type, ".bin")


def _display_title(mode: str, expected_output: str) -> str:
    return f"{mode} {expected_output}".replace("-", " ").replace("_", " ").title()
