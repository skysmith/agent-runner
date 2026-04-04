from __future__ import annotations

import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable


def read_head_commit(repo_path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=1.5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    head = result.stdout.strip()
    return head or None


def read_build_label(repo_path: Path) -> str | None:
    try:
        count_result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=1.5,
        )
    except Exception:
        return None
    if count_result.returncode != 0:
        return None
    build_number = count_result.stdout.strip()
    head = read_head_commit(repo_path)
    if build_number:
        if head:
            return f"Build {build_number} ({head[:7]})"
        return f"Build {build_number}"
    try:
        package_version = version("secret-agent")
    except PackageNotFoundError:
        return None
    return f"Version {package_version}"


class CommitUpdateSignal:
    def __init__(
        self,
        repo_path: Path,
        read_head: Callable[[Path], str | None] = read_head_commit,
    ) -> None:
        self.repo_path = repo_path
        self._read_head = read_head
        self._startup_head = self._safe_read_head()
        self._update_available = False

    def poll(self) -> bool:
        if self._update_available:
            return True
        current_head = self._safe_read_head()
        if current_head is None or self._startup_head is None:
            return False
        if current_head != self._startup_head:
            self._update_available = True
        return self._update_available

    def _safe_read_head(self) -> str | None:
        try:
            return self._read_head(self.repo_path)
        except Exception:
            return None
