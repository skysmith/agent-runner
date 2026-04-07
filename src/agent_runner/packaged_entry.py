from __future__ import annotations

import argparse
import os
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from agent_runner.app_paths import DEFAULT_ARTIFACTS_DIR, resolve_runtime_paths
from agent_runner.http_api import create_server
from agent_runner.macos_wrapper import (
    LaunchAgentManager,
    LaunchAgentSpec,
    MacOSWrapperBridge,
    app_bundle_path,
    copy_connection_url,
    install_open_in_alcove_quick_action,
    is_macos,
    launch_agent_label,
    launch_agent_path,
    load_wrapper_state,
    local_api_request,
    open_browser_for_state,
    open_url,
    prune_stale_launch_agents,
    resolve_wrapper_password,
    save_wrapper_state,
    wait_for_server,
    wrapper_log_dir,
)
from agent_runner.models import ProviderKind
from agent_runner.server_info import server_info
from agent_runner.service import AgentRunnerService, ServiceConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Alcove macOS wrapper entrypoint")
    parser.add_argument("--service", action="store_true", help="Run the browser-first web service foreground process.")
    parser.add_argument("--open-folder", type=Path, default=None, help="Import a folder into Alcove and open it.")
    parser.add_argument(
        "--control",
        choices=[
            "copy-local-url",
            "copy-phone-url",
            "install-quick-action",
            "open-browser",
            "open-current-workspace",
            "restart-service",
            "stop-run",
        ],
        default=None,
        help="Perform a wrapper control action against the background service.",
    )
    parser.add_argument("targets", nargs="*", help="Optional file/folder targets passed from Finder or Open With.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    wrapper_executable = _wrapper_executable_path()
    wrapper_bundle = _wrapper_app_bundle(wrapper_executable)
    requested_repo = _requested_repo_path(wrapper_bundle)
    runtime = resolve_runtime_paths(repo_path=requested_repo, artifacts_dir=DEFAULT_ARTIFACTS_DIR)
    state_root = runtime.settings_path.parent
    host = os.environ.get("AGENT_RUNNER_WEB_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = int(os.environ.get("AGENT_RUNNER_WEB_PORT", "8765"))
    password = resolve_wrapper_password(
        repo_path=runtime.repo_path,
        explicit_password=os.environ.get("AGENT_RUNNER_WEB_PASSWORD"),
    )

    open_folder = args.open_folder or _first_folder_target(args.targets)

    if args.control:
        return _run_control_action(
            action=args.control,
            runtime_repo=runtime.repo_path,
            state_root=state_root,
            wrapper_executable=wrapper_executable,
            wrapper_bundle=wrapper_bundle,
            host=host,
            port=port,
            password=password,
        )

    if args.service:
        return _run_service_mode(
            runtime=runtime,
            wrapper_executable=wrapper_executable,
            wrapper_bundle=wrapper_bundle,
            host=host,
            port=port,
            password=password,
        )

    if wrapper_bundle is not None and is_macos():
        return _run_launcher_mode(
            runtime_repo=runtime.repo_path,
            state_root=state_root,
            wrapper_executable=wrapper_executable,
            wrapper_bundle=wrapper_bundle,
            host=host,
            port=port,
            password=password,
            open_folder=open_folder,
        )

    return _run_service_mode(
        runtime=runtime,
        wrapper_executable=wrapper_executable,
        wrapper_bundle=wrapper_bundle,
        host=host,
        port=port,
        password=password,
        open_browser=True,
    )


def _run_service_mode(
    *,
    runtime,
    wrapper_executable: Path,
    wrapper_bundle: Path | None,
    host: str,
    port: int,
    password: str | None,
    open_browser: bool = False,
) -> int:
    service = _build_service(runtime)
    server = create_server(service, host=host, port=port, access_password=password)
    info = _server_payload(host, server.server_port, repo_path=runtime.repo_path)
    bridge = MacOSWrapperBridge(
        state_root=runtime.settings_path.parent,
        app_bundle=wrapper_bundle,
        executable_path=wrapper_executable,
        repo_path=runtime.repo_path,
        password_enabled=bool(password),
    )
    bridge.initialize(server_info_payload=info, run_status=service.get_run_status())
    service.add_event_listener(bridge.handle_event)

    if wrapper_bundle is not None:
        save_wrapper_state(
            runtime.settings_path.parent,
            {
                **load_wrapper_state(runtime.settings_path.parent),
                "app_bundle": str(wrapper_bundle),
                "binary_path": str(wrapper_executable),
                "repo_path": str(runtime.repo_path.resolve()),
                "password_enabled": bool(password),
                "server_info": info,
                "run_status": service.get_run_status(),
            },
        )
        _launch_menu_bar_helper(wrapper_bundle)

    if open_browser:
        open_url(str(info["local_url"]))

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.shutdown()
        server.server_close()
    return 0


def _run_launcher_mode(
    *,
    runtime_repo: Path,
    state_root: Path,
    wrapper_executable: Path,
    wrapper_bundle: Path,
    host: str,
    port: int,
    password: str | None,
    open_folder: Path | None,
) -> int:
    prune_stale_launch_agents(executable_path=wrapper_executable, repo_path=runtime_repo)
    label = launch_agent_label(runtime_repo)
    logs_dir = wrapper_log_dir(state_root)
    agent = LaunchAgentManager()
    spec = LaunchAgentSpec(
        label=label,
        plist_path=launch_agent_path(label),
        executable_path=wrapper_executable,
        stdout_path=logs_dir / "launch-agent.log",
        stderr_path=logs_dir / "launch-agent-error.log",
        host=host,
        port=port,
        repo_path=runtime_repo,
        app_bundle=wrapper_bundle,
    )
    try:
        info = wait_for_server(
            base_url=f"http://127.0.0.1:{port}",
            password=password,
            expected_repo=runtime_repo,
            timeout_seconds=1.0,
        )
    except Exception:
        agent.ensure_running(spec)
        info = wait_for_server(
            base_url=f"http://127.0.0.1:{port}",
            password=password,
            expected_repo=runtime_repo,
            timeout_seconds=12.0,
        )

    install_open_in_alcove_quick_action(app_bundle=wrapper_bundle)
    _launch_menu_bar_helper(wrapper_bundle)

    workspace_id = None
    conversation_id = None
    if open_folder is not None:
        imported = local_api_request(
            base_url=str(info["localhost_url"]),
            path="/api/workspaces/import-folder",
            method="POST",
            password=password,
            payload={"repo_path": str(open_folder.resolve())},
        )
        workspace_id = str(imported.get("id") or "").strip() or None
        conversation_id = str(imported.get("active_conversation_id") or "").strip() or None
        save_wrapper_state(
            state_root,
            {
                **load_wrapper_state(state_root),
                "preferred_workspace_id": workspace_id,
                "preferred_conversation_id": conversation_id,
            },
        )

    url = _browser_url(
        base_url=str(info["localhost_url"]),
        workspace_id=workspace_id,
        conversation_id=conversation_id,
    )
    open_url(url)
    if _should_hold_launcher_open():
        _hold_launcher_open()
    return 0


def _run_control_action(
    *,
    action: str,
    runtime_repo: Path,
    state_root: Path,
    wrapper_executable: Path,
    wrapper_bundle: Path | None,
    host: str,
    port: int,
    password: str | None,
) -> int:
    if action == "install-quick-action":
        if wrapper_bundle is None:
            raise SystemExit("Quick Action install requires an app bundle.")
        install_open_in_alcove_quick_action(app_bundle=wrapper_bundle)
        return 0
    if action == "copy-local-url":
        return 0 if copy_connection_url(state_root, kind="local") else 1
    if action == "copy-phone-url":
        return 0 if copy_connection_url(state_root, kind="phone") else 1
    if action == "open-browser":
        return 0 if open_browser_for_state(state_root, prefer_current_workspace=False) else 1
    if action == "open-current-workspace":
        return 0 if open_browser_for_state(state_root, prefer_current_workspace=True) else 1
    if action == "restart-service":
        if wrapper_bundle is None:
            return 1
        label = launch_agent_label(runtime_repo)
        logs_dir = wrapper_log_dir(state_root)
        spec = LaunchAgentSpec(
            label=label,
            plist_path=launch_agent_path(label),
            executable_path=wrapper_executable,
            stdout_path=logs_dir / "launch-agent.log",
            stderr_path=logs_dir / "launch-agent-error.log",
            host=host,
            port=port,
            repo_path=runtime_repo,
            app_bundle=wrapper_bundle,
        )
        manager = LaunchAgentManager()
        if manager.is_loaded(spec):
            manager.restart(spec)
        else:
            manager.ensure_running(spec)
        return 0

    info = wait_for_server(
        base_url=f"http://127.0.0.1:{port}",
        password=password,
        expected_repo=runtime_repo,
        timeout_seconds=4.0,
    )
    if action == "stop-run":
        local_api_request(
            base_url=str(info["localhost_url"]),
            path="/api/runs/stop-safely",
            method="POST",
            password=password,
            payload={},
        )
        return 0
    return 1


def _build_service(runtime) -> AgentRunnerService:
    return AgentRunnerService(
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


def _server_payload(host: str, port: int, *, repo_path: Path) -> dict[str, Any]:
    payload = server_info(host, port, repo_path=repo_path)
    payload["local_url"] = str(payload["localhost_url"])
    phone_url = str(payload.get("tailscale_url") or "").strip()
    payload["phone_url"] = phone_url or None
    payload["phone_enabled"] = bool(phone_url)
    return payload


def _wrapper_executable_path() -> Path:
    explicit = os.environ.get("AGENT_RUNNER_WRAPPER_EXECUTABLE", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return Path(os.path.realpath(os.path.expanduser(os.path.expandvars(os.fspath(os.sys.executable))))).resolve()


def _wrapper_app_bundle(executable_path: Path) -> Path | None:
    explicit = os.environ.get("AGENT_RUNNER_APP_BUNDLE", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return app_bundle_path(executable_path)


def _requested_repo_path(app_bundle: Path | None) -> Path | None:
    repo_env = os.environ.get("AGENT_RUNNER_REPO", "").strip()
    if not repo_env:
        if app_bundle is None:
            return None
        resource_path = app_bundle / "Contents" / "Resources" / "repo-path"
        try:
            repo_text = resource_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not repo_text:
            return None
        return Path(repo_text).expanduser()
    return Path(repo_env).expanduser()


def _first_folder_target(targets: list[str]) -> Path | None:
    for raw in targets:
        text = raw.strip()
        if not text:
            continue
        candidate = Path(text).expanduser()
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _launch_menu_bar_helper(app_bundle: Path) -> None:
    helper = app_bundle / "Contents" / "Resources" / "AlcoveMenuBar.app"
    if not helper.exists():
        return
    subprocess.run(["open", "-g", str(helper)], check=False)


def _should_hold_launcher_open() -> bool:
    return os.environ.get("AGENT_RUNNER_KEEP_DOCK_OPEN", "0").strip() == "1"


def _hold_launcher_open() -> None:
    stop_event = threading.Event()
    previous_handlers: dict[int, Any] = {}

    def _request_stop(signum, _frame) -> None:  # type: ignore[no-untyped-def]
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _request_stop)
        except (AttributeError, ValueError):
            continue

    try:
        while not stop_event.wait(1.0):
            pass
    finally:
        for signum, handler in previous_handlers.items():
            try:
                signal.signal(signum, handler)
            except (AttributeError, ValueError):
                continue


def _browser_url(*, base_url: str, workspace_id: str | None, conversation_id: str | None) -> str:
    params: dict[str, str] = {}
    if workspace_id:
        params["workspace_id"] = workspace_id
    if conversation_id:
        params["conversation_id"] = conversation_id
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


if __name__ == "__main__":
    raise SystemExit(main())
