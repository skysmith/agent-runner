from __future__ import annotations

import hashlib
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
    dirty_token = read_worktree_token(repo_path)
    if dirty_token:
        return dirty_token[-3:]
    if build_number:
        return build_number
    try:
        package_version = version("secret-agent")
    except PackageNotFoundError:
        return None
    return package_version


def read_worktree_token(repo_path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--porcelain", "-z"],
            capture_output=True,
            text=False,
            check=False,
            timeout=1.5,
        )
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout:
        return None

    digest = hashlib.sha1()
    entries = [entry for entry in result.stdout.split(b"\x00") if entry]
    pending_old_path: bytes | None = None
    for entry in entries:
        if pending_old_path is not None:
            pending_old_path = None
            continue
        status = entry[:2].decode("utf-8", "replace")
        path_text = entry[3:].decode("utf-8", "replace")
        path = Path(path_text)
        digest.update(status.encode("utf-8", "replace"))
        digest.update(b"\x00")
        digest.update(path_text.encode("utf-8", "replace"))
        digest.update(b"\x00")
        full_path = repo_path / path
        if full_path.is_file():
            try:
                digest.update(full_path.read_bytes())
            except Exception:
                pass
        elif full_path.exists():
            digest.update(str(full_path.stat().st_mtime_ns).encode("ascii", "ignore"))
        else:
            digest.update(b"missing")
        if status[0] in {"R", "C"}:
            pending_old_path = entry
    return digest.hexdigest()[:6]


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
