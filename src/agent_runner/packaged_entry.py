from __future__ import annotations

import os
from pathlib import Path

from agent_runner.app_paths import DEFAULT_ARTIFACTS_DIR, resolve_runtime_paths
from agent_runner.models import ProviderKind
from agent_runner.ui import UiSettings, launch_ui


def main() -> int:
    repo_env = os.environ.get("AGENT_RUNNER_REPO", "").strip()
    repo_path = Path(repo_env).expanduser() if repo_env else None
    runtime = resolve_runtime_paths(repo_path=repo_path, artifacts_dir=DEFAULT_ARTIFACTS_DIR)
    settings = UiSettings(
        repo_path=runtime.repo_path,
        artifacts_dir=runtime.artifacts_dir,
        settings_path=runtime.settings_path,
        packaged_mode=runtime.packaged_mode,
        provider=ProviderKind.CODEX,
        codex_bin="codex",
        model="gpt-5.3-codex",
        ollama_host="http://127.0.0.1:11434",
        extra_access_dir=None,
        max_step_retries=2,
        phase_timeout_seconds=240,
        check_commands=[],
        dry_run=False,
    )
    return launch_ui(settings)


if __name__ == "__main__":
    raise SystemExit(main())
