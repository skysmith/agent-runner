from __future__ import annotations

import os
import shutil
from pathlib import Path


_COMMON_USER_BIN_DIRS = (
    Path.home() / ".npm-global" / "bin",
    Path.home() / ".local" / "bin",
    Path.home() / ".volta" / "bin",
    Path.home() / ".yarn" / "bin",
    Path.home() / ".cargo" / "bin",
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)


def resolve_executable_path(command: str) -> str | None:
    text = command.strip()
    if not text:
        return None
    if os.sep in text or (os.altsep and os.altsep in text):
        candidate = Path(text).expanduser()
        return str(candidate) if _is_executable(candidate) else None

    resolved = shutil.which(text)
    if resolved:
        return resolved

    for directory in _COMMON_USER_BIN_DIRS:
        candidate = directory / text
        if _is_executable(candidate):
            return str(candidate)
    return None


def extend_path_with_user_bins(current_path: str | None = None) -> str:
    parts = [segment for segment in (current_path or "").split(os.pathsep) if segment]
    seen = {segment for segment in parts}
    for directory in _COMMON_USER_BIN_DIRS:
        text = str(directory)
        if text in seen or not directory.exists():
            continue
        parts.append(text)
        seen.add(text)
    return os.pathsep.join(parts)


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)
