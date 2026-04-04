from agent_runner.run_coordinator import RunCoordinator


def test_single_active_workspace_enforced() -> None:
    coordinator = RunCoordinator()
    assert coordinator.try_start("ws-1") is True
    assert coordinator.try_start("ws-2") is False
    assert coordinator.active_workspace_id() == "ws-1"
    coordinator.finish("ws-1")
    assert coordinator.try_start("ws-2") is True
