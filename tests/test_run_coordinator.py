from pathlib import Path

from agent_runner.run_coordinator import RunCoordinator


def test_single_active_workspace_enforced() -> None:
    coordinator = RunCoordinator()
    assert coordinator.try_start("ws-1") is True
    assert coordinator.try_start("ws-2") is False
    assert coordinator.active_workspace_id() == "ws-1"
    coordinator.finish("ws-1")
    assert coordinator.try_start("ws-2") is True


def test_stale_lock_is_cleared_when_status_is_idle(tmp_path: Path) -> None:
    coordinator = RunCoordinator(tmp_path)
    (tmp_path / "active-run.lock").write_text("", encoding="utf-8")
    (tmp_path / "run-status.json").write_text(
        '{"state":"idle","workspace_id":null,"step":"Idle"}',
        encoding="utf-8",
    )

    assert coordinator.try_start("ws-1") is True
    assert coordinator.active_workspace_id() == "ws-1"


def test_finish_clears_lock_after_status_already_returns_to_idle(tmp_path: Path) -> None:
    coordinator = RunCoordinator(tmp_path)

    assert coordinator.try_start("ws-1") is True
    coordinator.update_status(
        state="idle",
        workspace_id=None,
        conversation_id=None,
        mode=None,
        step="Idle",
        error="",
        stop_requested=False,
    )

    coordinator.finish("ws-1")

    assert not (tmp_path / "active-run.lock").exists()
    assert coordinator.get_status().state == "idle"


def test_stale_heartbeat_lock_is_marked_failed_and_recovered(tmp_path: Path) -> None:
    coordinator = RunCoordinator(tmp_path, heartbeat_stale_seconds=1)
    (tmp_path / "active-run.lock").write_text("", encoding="utf-8")
    (tmp_path / "run-status.json").write_text(
        (
            "{"
            '"state":"running",'
            '"workspace_id":"ws-1",'
            '"step":"Working",'
            '"heartbeat_at":"2000-01-01T00:00:00+00:00"'
            "}"
        ),
        encoding="utf-8",
    )

    status = coordinator.get_status()
    assert status.state == "failed"
    assert "Recovered stale run" in status.last_error
    assert not (tmp_path / "active-run.lock").exists()
