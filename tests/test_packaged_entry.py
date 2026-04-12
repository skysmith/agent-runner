from __future__ import annotations

from pathlib import Path

from agent_runner import packaged_entry
from agent_runner.macos_wrapper import load_wrapper_state, save_wrapper_state


def test_requested_repo_path_reads_bundle_resource(tmp_path: Path) -> None:
    app_bundle = tmp_path / "Alcove.app"
    resource_dir = app_bundle / "Contents" / "Resources"
    resource_dir.mkdir(parents=True)
    expected_repo = tmp_path / "workspace"
    expected_repo.mkdir()
    (resource_dir / "repo-path").write_text(str(expected_repo), encoding="utf-8")

    result = packaged_entry._requested_repo_path(app_bundle)

    assert result == expected_repo


def test_launcher_args_ignore_process_serial_number() -> None:
    result = packaged_entry._launcher_args(["-psn_0_12345", "--open-folder", "/tmp/example"])

    assert result == ["--open-folder", "/tmp/example"]


def test_first_folder_target_accepts_file_urls(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = packaged_entry._first_folder_target([f"file://localhost{workspace.as_posix()}"])

    assert result == workspace


def test_run_launcher_mode_keeps_dock_process_alive(monkeypatch, tmp_path: Path) -> None:
    ensured_specs: list[object] = []
    opened_urls: list[str] = []
    held_open: list[bool] = []

    class FakeAgentManager:
        def ensure_running(self, spec) -> None:
            ensured_specs.append(spec)

    def fake_wait_for_server(**kwargs):
        return {"localhost_url": "http://127.0.0.1:8765"}

    monkeypatch.setattr(packaged_entry, "LaunchAgentManager", lambda: FakeAgentManager())
    monkeypatch.setattr(packaged_entry, "prune_stale_launch_agents", lambda **kwargs: [])
    monkeypatch.setattr(packaged_entry, "wait_for_server", fake_wait_for_server)
    monkeypatch.setattr(packaged_entry, "install_open_in_alcove_quick_action", lambda app_bundle: tmp_path / "workflow")
    monkeypatch.setattr(packaged_entry, "_launch_menu_bar_helper", lambda app_bundle: None)
    monkeypatch.setattr(packaged_entry, "open_url", lambda url: opened_urls.append(url))
    monkeypatch.setattr(packaged_entry, "_hold_launcher_open", lambda: held_open.append(True))

    result = packaged_entry._run_launcher_mode(
        runtime_repo=tmp_path / "repo",
        state_root=tmp_path / "state",
        wrapper_executable=tmp_path / "Alcove",
        wrapper_bundle=tmp_path / "Alcove.app",
        host="0.0.0.0",
        port=8765,
        password=None,
        open_folder=None,
    )

    assert result == 0
    assert ensured_specs == []
    assert opened_urls == ["http://127.0.0.1:8765"]
    assert held_open == []


def test_run_launcher_mode_can_keep_dock_open_when_enabled(monkeypatch, tmp_path: Path) -> None:
    held_open: list[bool] = []

    class FakeAgentManager:
        def ensure_running(self, spec) -> None:
            return None

    monkeypatch.setattr(packaged_entry, "LaunchAgentManager", lambda: FakeAgentManager())
    monkeypatch.setattr(packaged_entry, "prune_stale_launch_agents", lambda **kwargs: [])
    monkeypatch.setattr(
        packaged_entry,
        "wait_for_server",
        lambda **kwargs: {"localhost_url": "http://127.0.0.1:8765"},
    )
    monkeypatch.setattr(packaged_entry, "install_open_in_alcove_quick_action", lambda app_bundle: tmp_path / "workflow")
    monkeypatch.setattr(packaged_entry, "_launch_menu_bar_helper", lambda app_bundle: None)
    monkeypatch.setattr(packaged_entry, "open_url", lambda url: None)
    monkeypatch.setattr(packaged_entry, "_hold_launcher_open", lambda: held_open.append(True))
    monkeypatch.setenv("AGENT_RUNNER_KEEP_DOCK_OPEN", "1")

    result = packaged_entry._run_launcher_mode(
        runtime_repo=tmp_path / "repo",
        state_root=tmp_path / "state",
        wrapper_executable=tmp_path / "Alcove",
        wrapper_bundle=tmp_path / "Alcove.app",
        host="0.0.0.0",
        port=8765,
        password=None,
        open_folder=None,
    )

    assert result == 0
    assert held_open == [True]


def test_run_launcher_mode_imports_open_folder_and_remembers_workspace(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opened_urls: list[str] = []
    imported_payloads: list[dict[str, object]] = []

    class FakeAgentManager:
        def ensure_running(self, spec) -> None:
            return None

    monkeypatch.setattr(packaged_entry, "LaunchAgentManager", lambda: FakeAgentManager())
    monkeypatch.setattr(packaged_entry, "prune_stale_launch_agents", lambda **kwargs: [])
    monkeypatch.setattr(
        packaged_entry,
        "wait_for_server",
        lambda **kwargs: {"localhost_url": "http://127.0.0.1:8765"},
    )
    monkeypatch.setattr(packaged_entry, "install_open_in_alcove_quick_action", lambda app_bundle: tmp_path / "workflow")
    monkeypatch.setattr(packaged_entry, "_launch_menu_bar_helper", lambda app_bundle: None)
    monkeypatch.setattr(packaged_entry, "open_url", lambda url: opened_urls.append(url))

    def fake_local_api_request(**kwargs):
        imported_payloads.append(dict(kwargs))
        return {"id": "workspace-1", "active_conversation_id": "conversation-1"}

    monkeypatch.setattr(packaged_entry, "local_api_request", fake_local_api_request)

    result = packaged_entry._run_launcher_mode(
        runtime_repo=tmp_path / "repo",
        state_root=tmp_path / "state",
        wrapper_executable=tmp_path / "Alcove",
        wrapper_bundle=tmp_path / "Alcove.app",
        host="0.0.0.0",
        port=8765,
        password=None,
        open_folder=workspace,
    )

    assert result == 0
    assert imported_payloads == [
        {
            "base_url": "http://127.0.0.1:8765",
            "path": "/api/workspaces/import-folder",
            "method": "POST",
            "password": None,
            "payload": {"repo_path": str(workspace.resolve())},
        }
    ]
    assert opened_urls == [
        "http://127.0.0.1:8765?workspace_id=workspace-1&conversation_id=conversation-1"
    ]
    payload = load_wrapper_state(tmp_path / "state")
    assert payload["preferred_workspace_id"] == "workspace-1"
    assert payload["preferred_conversation_id"] == "conversation-1"


def test_open_current_workspace_control_action_opens_workspace_repo_path(monkeypatch, tmp_path: Path) -> None:
    runtime_repo = tmp_path / "runtime"
    runtime_repo.mkdir()
    workspace_repo = tmp_path / "workspace"
    workspace_repo.mkdir()
    state_root = tmp_path / "state"
    save_wrapper_state(
        state_root,
        {
            "preferred_workspace_id": "workspace-1",
            "repo_path": str(runtime_repo),
        },
    )

    opened: list[str] = []

    monkeypatch.setattr(
        packaged_entry,
        "wait_for_server",
        lambda **kwargs: {"localhost_url": "http://127.0.0.1:8765"},
    )
    monkeypatch.setattr(
        packaged_entry,
        "local_api_request",
        lambda **kwargs: {"repo_path": str(workspace_repo)},
    )
    monkeypatch.setattr(packaged_entry, "open_url", lambda url: opened.append(url))

    result = packaged_entry._run_control_action(
        action="open-current-workspace",
        runtime_repo=runtime_repo,
        state_root=state_root,
        wrapper_executable=tmp_path / "Alcove",
        wrapper_bundle=tmp_path / "Alcove.app",
        host="0.0.0.0",
        port=8765,
        password=None,
    )

    assert result == 0
    assert opened == [str(workspace_repo)]


def test_open_current_workspace_control_action_falls_back_to_runtime_repo(monkeypatch, tmp_path: Path) -> None:
    runtime_repo = tmp_path / "runtime"
    runtime_repo.mkdir()
    state_root = tmp_path / "state"
    save_wrapper_state(
        state_root,
        {
            "repo_path": str(runtime_repo),
        },
    )

    opened: list[str] = []
    monkeypatch.setattr(packaged_entry, "open_url", lambda url: opened.append(url))

    result = packaged_entry._run_control_action(
        action="open-current-workspace",
        runtime_repo=runtime_repo,
        state_root=state_root,
        wrapper_executable=tmp_path / "Alcove",
        wrapper_bundle=tmp_path / "Alcove.app",
        host="0.0.0.0",
        port=8765,
        password=None,
    )

    assert result == 0
    assert opened == [str(runtime_repo)]
