from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RunStatus:
    state: str = "idle"
    workspace_id: str | None = None
    conversation_id: str | None = None
    mode: str | None = None
    step: str = "Idle"
    error: str = ""
    last_error: str = ""
    started_at: str | None = None
    updated_at: str | None = None
    heartbeat_at: str | None = None
    finished_at: str | None = None
    run_id: str | None = None
    last_prompt: str | None = None
    stop_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "workspace_id": self.workspace_id,
            "conversation_id": self.conversation_id,
            "mode": self.mode,
            "step": self.step,
            "error": self.error,
            "last_error": self.last_error or self.error,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "heartbeat_at": self.heartbeat_at,
            "finished_at": self.finished_at,
            "run_id": self.run_id,
            "last_prompt": self.last_prompt,
            "stop_requested": self.stop_requested,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunStatus":
        raw_error = str(payload.get("error", "")).strip()
        raw_last_error = str(payload.get("last_error", "")).strip()
        merged_error = raw_last_error or raw_error
        return cls(
            state=str(payload.get("state", "idle")),
            workspace_id=_optional_text(payload.get("workspace_id")),
            conversation_id=_optional_text(payload.get("conversation_id")),
            mode=_optional_text(payload.get("mode")),
            step=str(payload.get("step", "Idle")),
            error=merged_error,
            last_error=merged_error,
            started_at=_optional_text(payload.get("started_at")),
            updated_at=_optional_text(payload.get("updated_at")),
            heartbeat_at=_optional_text(payload.get("heartbeat_at")),
            finished_at=_optional_text(payload.get("finished_at")),
            run_id=_optional_text(payload.get("run_id")),
            last_prompt=_optional_text(payload.get("last_prompt")),
            stop_requested=bool(payload.get("stop_requested", False)),
        )


class RunCoordinator:
    ACTIVE_STATES = {"starting", "running", "stopping"}
    TERMINAL_STATES = {"idle", "succeeded", "failed"}

    def __init__(self, state_dir: Path | None = None, *, heartbeat_stale_seconds: int = 120) -> None:
        self._lock = threading.Lock()
        self._state_dir = state_dir
        self._active_workspace_id: str | None = None
        self._heartbeat_stale_seconds = max(5, heartbeat_stale_seconds)

    def try_start(
        self,
        workspace_id: str,
        *,
        conversation_id: str | None = None,
        mode: str | None = None,
        run_id: str | None = None,
        last_prompt: str | None = None,
    ) -> bool:
        with self._lock:
            if self._state_dir is None:
                if self._active_workspace_id is not None:
                    return False
                self._active_workspace_id = workspace_id
                return True

            self._state_dir.mkdir(parents=True, exist_ok=True)
            self._recover_locked_state_if_needed()
            try:
                fd = os.open(self._lock_path(), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return False
            else:
                os.close(fd)
            now = _timestamp_now()
            status = RunStatus(
                state="starting",
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                mode=mode,
                step="Starting run",
                error="",
                last_error="",
                started_at=now,
                updated_at=now,
                heartbeat_at=now,
                finished_at=None,
                run_id=run_id,
                last_prompt=last_prompt,
                stop_requested=False,
            )
            self._write_status(status)
            self._active_workspace_id = workspace_id
            return True

    def finish(self, workspace_id: str) -> None:
        with self._lock:
            if self._state_dir is None:
                if self._active_workspace_id == workspace_id:
                    self._active_workspace_id = None
                return
            self._recover_locked_state_if_needed()
            status = self._read_status()
            lock_path = Path(self._lock_path())
            should_release = status.workspace_id == workspace_id or (
                lock_path.exists() and status.state in self.TERMINAL_STATES
            )
            if not should_release:
                return
            next_status = status
            if status.workspace_id == workspace_id and status.state in self.ACTIVE_STATES:
                now = _timestamp_now()
                next_status = RunStatus.from_dict(
                    {
                        **status.to_dict(),
                        "state": "failed",
                        "step": "Run ended unexpectedly",
                        "error": status.last_error or "Run ended unexpectedly",
                        "last_error": status.last_error or "Run ended unexpectedly",
                        "updated_at": now,
                        "finished_at": now,
                        "stop_requested": False,
                    }
                )
                self._write_status(next_status)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
            self._active_workspace_id = None

    def active_workspace_id(self) -> str | None:
        with self._lock:
            if self._state_dir is not None:
                status = self._get_status_locked()
                if status.state in self.ACTIVE_STATES and Path(self._lock_path()).exists():
                    return status.workspace_id
                return None
            return self._active_workspace_id

    def get_status(self) -> RunStatus:
        if self._state_dir is None:
            state = "running" if self._active_workspace_id else "idle"
            return RunStatus(
                state=state,
                workspace_id=self._active_workspace_id,
                step="Working" if self._active_workspace_id else "Idle",
            )
        with self._lock:
            return self._get_status_locked()

    def update_status(self, **changes: Any) -> RunStatus:
        with self._lock:
            status = self._get_status_locked()
            payload = status.to_dict()
            payload.update(changes)
            now = _timestamp_now()
            payload["updated_at"] = now

            next_state = str(payload.get("state", "idle"))
            if next_state in self.ACTIVE_STATES:
                payload["heartbeat_at"] = now
                payload["finished_at"] = None
                payload.setdefault("started_at", now)
            elif next_state in {"succeeded", "failed"}:
                payload["finished_at"] = payload.get("finished_at") or now
            elif next_state == "idle":
                payload["finished_at"] = payload.get("finished_at") or now

            if "error" in changes and "last_error" not in changes:
                payload["last_error"] = payload["error"]
            if "last_error" in changes and "error" not in changes:
                payload["error"] = payload["last_error"]

            new_status = RunStatus.from_dict(payload)
            self._write_status(new_status)
            if new_status.state in self.ACTIVE_STATES:
                self._active_workspace_id = new_status.workspace_id
            else:
                self._active_workspace_id = None
                self._release_lock_if_present()
            return new_status

    def request_stop(self) -> RunStatus:
        status = self.get_status()
        if status.state not in self.ACTIVE_STATES:
            return status
        return self.update_status(
            state="stopping",
            stop_requested=True,
            step="Stopping safely",
        )

    def stop_requested(self) -> bool:
        return self.get_status().stop_requested

    def touch_heartbeat(self) -> RunStatus:
        status = self.get_status()
        if status.state not in self.ACTIVE_STATES:
            return status
        return self.update_status()

    def recover_stale_run(self) -> RunStatus:
        with self._lock:
            self._recover_locked_state_if_needed(force=True)
            return self._read_status()

    def _lock_path(self) -> str:
        return str(self._state_dir / "active-run.lock")

    def _status_path(self) -> Path:
        return self._state_dir / "run-status.json"

    def _write_status(self, status: RunStatus) -> None:
        if self._state_dir is None:
            return
        path = self._status_path()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(status.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, path)

    def _get_status_locked(self) -> RunStatus:
        self._recover_locked_state_if_needed()
        status = self._read_status()
        if status.state in self.TERMINAL_STATES:
            self._release_lock_if_present()
        if status.state in self.ACTIVE_STATES and Path(self._lock_path()).exists():
            self._active_workspace_id = status.workspace_id
        else:
            self._active_workspace_id = None
        return status

    def _read_status(self) -> RunStatus:
        path = self._status_path()
        if not path.exists():
            return RunStatus()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return RunStatus()
        if not isinstance(raw, dict):
            return RunStatus()
        return RunStatus.from_dict(raw)

    def _recover_locked_state_if_needed(self, *, force: bool = False) -> None:
        if self._state_dir is None:
            return
        lock_path = Path(self._lock_path())
        if not lock_path.exists():
            return

        status = self._read_status()
        if status.state in self.TERMINAL_STATES:
            self._release_lock_if_present()
            self._active_workspace_id = None
            return

        if status.state not in self.ACTIVE_STATES:
            self._mark_run_failed(status, reason="Recovered inconsistent run lock.")
            self._release_lock_if_present()
            self._active_workspace_id = None
            return

        if force:
            self._mark_run_failed(status, reason="Recovered stale run via manual cleanup.")
            self._release_lock_if_present()
            self._active_workspace_id = None
            return

        heartbeat_source = status.heartbeat_at or status.updated_at or status.started_at
        heartbeat_time = _parse_timestamp(heartbeat_source)
        if heartbeat_time is None:
            self._mark_run_failed(status, reason="Recovered stale run with missing heartbeat.")
            self._release_lock_if_present()
            self._active_workspace_id = None
            return

        stale_after = timedelta(seconds=self._heartbeat_stale_seconds)
        if datetime.now(timezone.utc) - heartbeat_time > stale_after:
            self._mark_run_failed(status, reason="Recovered stale run after heartbeat timeout.")
            self._release_lock_if_present()
            self._active_workspace_id = None

    def _mark_run_failed(self, status: RunStatus, *, reason: str) -> None:
        now = _timestamp_now()
        failed = RunStatus.from_dict(
            {
                **status.to_dict(),
                "state": "failed",
                "step": "Needs attention",
                "error": status.last_error or reason,
                "last_error": status.last_error or reason,
                "stop_requested": False,
                "updated_at": now,
                "finished_at": now,
            }
        )
        self._write_status(failed)

    def _release_lock_if_present(self) -> None:
        if self._state_dir is None:
            return
        lock_path = Path(self._lock_path())
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
