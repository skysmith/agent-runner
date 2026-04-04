from __future__ import annotations

import sys

from agent_runner.run_coordinator import RunCoordinator
from agent_runner.ui import WorkspaceApp


def test_trigger_update_reload_when_idle_reloads_immediately() -> None:
    app = WorkspaceApp.__new__(WorkspaceApp)
    app.coordinator = RunCoordinator()
    app.reload_queued = False

    reload_calls: list[object] = []
    app._sync_update_badges = lambda: None
    app._reload_process = lambda parent: reload_calls.append(parent)

    parent = object()
    WorkspaceApp.trigger_update_reload(app, parent=parent)

    assert app.reload_queued is False
    assert reload_calls == [parent]


def test_trigger_update_reload_when_active_queues_without_reloading() -> None:
    app = WorkspaceApp.__new__(WorkspaceApp)
    app.coordinator = RunCoordinator()
    app.coordinator.try_start("workspace-1")
    app.reload_queued = False

    sync_calls: list[str] = []
    reload_calls: list[object] = []
    app._sync_update_badges = lambda: sync_calls.append("sync")
    app._reload_process = lambda parent: reload_calls.append(parent)

    parent = object()
    WorkspaceApp.trigger_update_reload(app, parent=parent)
    WorkspaceApp.trigger_update_reload(app, parent=parent)

    assert app.reload_queued is True
    assert sync_calls == ["sync"]
    assert reload_calls == []


def test_finish_workspace_run_triggers_queued_reload_after_completion() -> None:
    app = WorkspaceApp.__new__(WorkspaceApp)
    app.coordinator = RunCoordinator()
    app.coordinator.try_start("workspace-1")
    app.reload_queued = True
    app.root = object()

    sync_calls: list[str] = []
    reload_calls: list[object] = []
    app._sync_update_badges = lambda: sync_calls.append("sync")
    app._reload_process = lambda parent: reload_calls.append(parent)

    WorkspaceApp.finish_workspace_run(app, "workspace-1")

    assert app.reload_queued is False
    assert sync_calls == ["sync"]
    assert reload_calls == [app.root]


def test_reload_process_in_packaged_mode_execs_binary(monkeypatch) -> None:
    class RootStub:
        def __init__(self) -> None:
            self.scheduled = None

        def after(self, delay, fn) -> None:
            self.scheduled = (delay, fn)
            fn()

    app = WorkspaceApp.__new__(WorkspaceApp)
    app.bootstrap = type("B", (), {"packaged_mode": True, "repo_path": None})()
    app.root = RootStub()

    calls: list[tuple[str, list[str]]] = []

    def fake_execv(path, args):
        calls.append((path, list(args)))

    monkeypatch.setattr("os.execv", fake_execv)
    monkeypatch.setattr(sys, "executable", "/tmp/agent-runner-binary")

    WorkspaceApp._reload_process(app, parent=object())

    assert calls == [("/tmp/agent-runner-binary", ["/tmp/agent-runner-binary"])]
