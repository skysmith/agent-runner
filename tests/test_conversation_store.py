from __future__ import annotations

from pathlib import Path

from agent_runner.conversation_store import (
    ConversationStore,
    DEFAULT_CONVERSATION_TITLE,
    WorkspaceConversationController,
    derive_conversation_title,
)


def test_store_round_trip_and_delete(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / ".agent-runner" / "workspaces")
    controller = WorkspaceConversationController(store, "workspace-1")

    record = controller.active_conversation()
    controller.append_message(role="user", content="Check the repo architecture")
    controller.append_message(role="assistant", content="Here is the summary")

    reloaded = store.load_conversation(record.id, workspace_id="workspace-1")
    assert reloaded is not None
    assert [message.role for message in reloaded.messages] == ["user", "assistant"]
    assert reloaded.title == "Check the repo architecture"

    controller.delete_conversation(record.id)
    assert store.load_conversation(record.id, workspace_id="workspace-1") is None


def test_workspace_migration_creates_default_conversation(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / ".agent-runner" / "workspaces")
    workspace_dir = tmp_path / ".agent-runner" / "workspaces" / "workspace-1"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "workspace_state.json").write_text('{"workspace_id": "workspace-1"}', encoding="utf-8")

    state = store.ensure_workspace("workspace-1")

    assert state.active_conversation_id is not None
    assert len(state.conversation_ids) == 1
    conversation = store.load_conversation(state.active_conversation_id, workspace_id="workspace-1")
    assert conversation is not None
    assert conversation.title == DEFAULT_CONVERSATION_TITLE


def test_controller_delete_active_conversation_selects_fallback(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / ".agent-runner" / "workspaces")
    controller = WorkspaceConversationController(store, "workspace-1")
    first = controller.active_conversation()
    second = controller.create_conversation()

    controller.select_conversation(first.id)
    fallback = controller.delete_conversation(first.id)

    assert fallback.id == second.id
    assert controller.state.active_conversation_id == second.id


def test_derive_conversation_title_uses_first_non_empty_line() -> None:
    title = derive_conversation_title("\n\nInvestigate dashboard regression\nwith extra details")
    assert title == "Investigate dashboard regression"
