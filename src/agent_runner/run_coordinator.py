from __future__ import annotations

import threading


class RunCoordinator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_workspace_id: str | None = None

    def try_start(self, workspace_id: str) -> bool:
        with self._lock:
            if self._active_workspace_id is not None:
                return False
            self._active_workspace_id = workspace_id
            return True

    def finish(self, workspace_id: str) -> None:
        with self._lock:
            if self._active_workspace_id == workspace_id:
                self._active_workspace_id = None

    def active_workspace_id(self) -> str | None:
        with self._lock:
            return self._active_workspace_id
