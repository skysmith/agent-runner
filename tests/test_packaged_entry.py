from __future__ import annotations

from pathlib import Path

from agent_runner import packaged_entry


def test_requested_repo_path_reads_bundle_resource(tmp_path: Path) -> None:
    app_bundle = tmp_path / "Alcove.app"
    resource_dir = app_bundle / "Contents" / "Resources"
    resource_dir.mkdir(parents=True)
    expected_repo = tmp_path / "workspace"
    expected_repo.mkdir()
    (resource_dir / "repo-path").write_text(str(expected_repo), encoding="utf-8")

    result = packaged_entry._requested_repo_path(app_bundle)

    assert result == expected_repo


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
