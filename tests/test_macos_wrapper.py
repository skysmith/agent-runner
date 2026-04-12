from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agent_runner.macos_wrapper import (
    LaunchAgentManager,
    LaunchAgentSpec,
    MacOSWrapperBridge,
    capture_native_speech,
    install_open_in_alcove_quick_action,
    launch_agent_label,
    load_wrapper_state,
    native_speech_available,
    native_speech_helper_path,
    open_browser_for_state,
    prune_stale_launch_agents,
    save_wrapper_state,
    wrapper_log_dir,
)


def test_launch_agent_label_is_repo_scoped(tmp_path: Path) -> None:
    first = launch_agent_label(tmp_path / "repo-a")
    second = launch_agent_label(tmp_path / "repo-b")

    assert first.startswith("local.alcove.web.")
    assert second.startswith("local.alcove.web.")
    assert first != second


def test_launch_agent_manager_writes_service_plist(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    logs = wrapper_log_dir(tmp_path)
    spec = LaunchAgentSpec(
        label=launch_agent_label(repo),
        plist_path=tmp_path / "agent.plist",
        executable_path=tmp_path / "Alcove",
        stdout_path=logs / "out.log",
        stderr_path=logs / "err.log",
        host="0.0.0.0",
        port=8765,
        repo_path=repo,
        app_bundle=tmp_path / "Alcove.app",
    )

    LaunchAgentManager().write_plist(spec)
    payload = spec.plist_path.read_text(encoding="utf-8")

    assert "<string>--service</string>" in payload
    assert "AGENT_RUNNER_WEB_HOST" in payload
    assert "AGENT_RUNNER_WEB_PORT" in payload
    assert str(repo) in payload
    assert str(spec.executable_path) in payload


def test_install_open_in_alcove_quick_action_writes_workflow(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agent_runner.macos_wrapper.Path.home", lambda: tmp_path)
    app_bundle = tmp_path / "Applications" / "Alcove.app"
    app_bundle.mkdir(parents=True)

    workflow = install_open_in_alcove_quick_action(app_bundle=app_bundle)

    info_plist = (workflow / "Contents" / "Info.plist").read_text(encoding="utf-8")
    document = (workflow / "Contents" / "Resources" / "document.wflow").read_text(encoding="utf-8")
    assert "public.folder" in info_plist
    assert "Run Shell Script" in document
    assert "--open-folder" in document
    assert str(app_bundle) in document


def test_prune_stale_launch_agents_removes_mismatched_repo_service(monkeypatch, tmp_path: Path) -> None:
    launch_agents_dir = tmp_path / "Library" / "LaunchAgents"
    launch_agents_dir.mkdir(parents=True)
    monkeypatch.setattr("agent_runner.macos_wrapper.Path.home", lambda: tmp_path)

    executable = tmp_path / "Alcove.app" / "Contents" / "MacOS" / "Alcove"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o755)

    stale_plist = launch_agents_dir / "local.alcove.web.stale.plist"
    stale_plist.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>local.alcove.web.stale</string>
  <key>ProgramArguments</key>
  <array>
    <string>{executable}</string>
    <string>--service</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>AGENT_RUNNER_REPO</key>
    <string>{repo}</string>
  </dict>
</dict>
</plist>
""".format(executable=executable, repo=tmp_path / "wrong-repo"),
        encoding="utf-8",
    )

    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    removed = prune_stale_launch_agents(
        executable_path=executable,
        repo_path=tmp_path / "right-repo",
        runner=fake_run,
    )

    assert removed == [stale_plist]
    assert not stale_plist.exists()
    assert calls == [["launchctl", "bootout", f"gui/{os.getuid()}/local.alcove.web.stale"]]


def test_open_browser_for_state_prefers_current_workspace(monkeypatch, tmp_path: Path) -> None:
    save_wrapper_state(
        tmp_path,
        {
            "server_info": {"local_url": "http://127.0.0.1:8765"},
            "preferred_workspace_id": "saved-workspace",
            "preferred_conversation_id": "saved-conversation",
            "run_status": {
                "workspace_id": "active-workspace",
                "conversation_id": "active-conversation",
            },
        },
    )

    opened: list[str] = []
    monkeypatch.setattr("agent_runner.macos_wrapper.open_url", lambda url: opened.append(url))

    result = open_browser_for_state(tmp_path, prefer_current_workspace=True)

    assert result == "http://127.0.0.1:8765?workspace_id=active-workspace&conversation_id=active-conversation"
    assert opened == [result]


def test_native_speech_helper_uses_app_bundle_path(tmp_path: Path) -> None:
    app_bundle = tmp_path / "Alcove.app"
    helper = app_bundle / "Contents" / "MacOS" / "AlcoveNativeSpeech"
    helper.parent.mkdir(parents=True)
    helper.write_text("", encoding="utf-8")
    helper.chmod(0o755)

    resolved = native_speech_helper_path(app_bundle=app_bundle)

    assert resolved == helper.resolve()
    assert native_speech_available(app_bundle=app_bundle) is True


def test_capture_native_speech_runs_helper_and_parses_output(tmp_path: Path) -> None:
    app_bundle = tmp_path / "Alcove.app"
    helper = app_bundle / "Contents" / "MacOS" / "AlcoveNativeSpeech"
    helper.parent.mkdir(parents=True)
    helper.write_text("", encoding="utf-8")
    helper.chmod(0o755)

    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout='{"transcript":"hello there","locale":"en-US"}\n',
            stderr="",
        )

    payload = capture_native_speech(
        app_bundle=app_bundle,
        locale="en-US",
        runner=fake_run,
    )

    assert calls == [[str(helper.resolve()), "--locale", "en-US"]]
    assert payload["transcript"] == "hello there"
    assert payload["provider"] == "macos-native"


def test_wrapper_bridge_updates_state_and_open_target(monkeypatch, tmp_path: Path) -> None:
    notification_calls: list[tuple[dict[str, object], str | None]] = []
    power_calls: list[dict[str, object]] = []

    class FakeNotifications:
        def update(self, status, *, workspace_name=None):
            notification_calls.append((dict(status), workspace_name))

    class FakePower:
        def update(self, status):
            power_calls.append(dict(status))

        def stop(self):
            power_calls.append({"state": "stopped"})

    monkeypatch.setattr("agent_runner.macos_wrapper.NotificationManager", FakeNotifications)
    monkeypatch.setattr("agent_runner.macos_wrapper.PowerAssertionManager", FakePower)

    bridge = MacOSWrapperBridge(
        state_root=tmp_path,
        app_bundle=tmp_path / "Alcove.app",
        executable_path=tmp_path / "Alcove",
        repo_path=tmp_path / "repo",
        password_enabled=True,
    )

    bridge.initialize(
        server_info_payload={"local_url": "http://127.0.0.1:8765"},
        run_status={"state": "idle", "workspace_id": None, "step": "Idle"},
    )
    bridge.remember_open_target(workspace_id="workspace-1", conversation_id="conversation-1")
    bridge.handle_event(
        "run.failed",
        {
            "status": {
                "state": "failed",
                "workspace_id": "workspace-1",
                "step": "Needs attention",
                "last_error": "boom",
            }
        },
    )
    bridge.shutdown()

    payload = load_wrapper_state(tmp_path)
    assert payload["preferred_workspace_id"] == "workspace-1"
    assert payload["preferred_conversation_id"] == "conversation-1"
    assert payload["run_status"]["state"] == "failed"
    assert payload["workspace_name"] == "workspace-1"
    assert notification_calls[-1][0]["state"] == "failed"
    assert power_calls[0]["state"] == "idle"
    assert power_calls[-1]["state"] == "stopped"
