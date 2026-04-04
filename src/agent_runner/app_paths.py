from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "agent-runner"
DEFAULT_ARTIFACTS_DIR = Path(".agent-runner")


def is_packaged_runtime() -> bool:
    return bool(getattr(sys, "frozen", False) or os.environ.get("AGENT_RUNNER_PACKAGED") == "1")


def app_support_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_NAME


def default_repo_path() -> Path:
    env_repo = os.environ.get("AGENT_RUNNER_REPO", "").strip()
    if env_repo:
        return Path(env_repo).expanduser().resolve()
    if is_packaged_runtime():
        return Path.home().resolve()
    return Path.cwd().resolve()


def resolve_artifacts_dir(repo_path: Path, requested: Path) -> Path:
    if requested != DEFAULT_ARTIFACTS_DIR:
        return requested.resolve()
    if is_packaged_runtime():
        return (app_support_dir() / "artifacts").resolve()
    return (repo_path / DEFAULT_ARTIFACTS_DIR).resolve()


def resolve_settings_path(repo_path: Path) -> Path:
    if is_packaged_runtime():
        return (app_support_dir() / "app-settings.json").resolve()
    return (repo_path / ".agent-runner" / "app-settings.json").resolve()


@dataclass(slots=True)
class RuntimePaths:
    repo_path: Path
    artifacts_dir: Path
    settings_path: Path
    packaged_mode: bool


def resolve_runtime_paths(repo_path: Path | None, artifacts_dir: Path) -> RuntimePaths:
    resolved_repo = (repo_path or default_repo_path()).resolve()
    return RuntimePaths(
        repo_path=resolved_repo,
        artifacts_dir=resolve_artifacts_dir(resolved_repo, artifacts_dir),
        settings_path=resolve_settings_path(resolved_repo),
        packaged_mode=is_packaged_runtime(),
    )
