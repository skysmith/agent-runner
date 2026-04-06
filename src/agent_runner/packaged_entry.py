from __future__ import annotations

import os
import webbrowser
from pathlib import Path

from agent_runner.app_paths import DEFAULT_ARTIFACTS_DIR, resolve_runtime_paths
from agent_runner.http_api import create_server
from agent_runner.models import ProviderKind
from agent_runner.server_info import server_info
from agent_runner.service import AgentRunnerService, ServiceConfig


def main() -> int:
    repo_env = os.environ.get("AGENT_RUNNER_REPO", "").strip()
    repo_path = Path(repo_env).expanduser() if repo_env else None
    runtime = resolve_runtime_paths(repo_path=repo_path, artifacts_dir=DEFAULT_ARTIFACTS_DIR)
    host = os.environ.get("AGENT_RUNNER_WEB_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = int(os.environ.get("AGENT_RUNNER_WEB_PORT", "8765"))
    password = (os.environ.get("AGENT_RUNNER_WEB_PASSWORD", "").strip() or None)

    service = AgentRunnerService(
        ServiceConfig(
            repo_path=runtime.repo_path,
            artifacts_dir=runtime.artifacts_dir,
            settings_path=runtime.settings_path,
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
    )
    server = create_server(service, host=host, port=port, access_password=password)
    info = server_info(host, server.server_port)
    try:
        webbrowser.open(info["localhost_url"])
    except Exception:
        pass
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
