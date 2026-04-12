from __future__ import annotations

from pathlib import Path

import pytest

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


def test_clear_conversation_resets_messages_summary_and_title(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / ".agent-runner" / "workspaces")
    controller = WorkspaceConversationController(store, "workspace-1")
    record = controller.active_conversation()

    controller.append_message(role="user", content="Investigate dashboard regression")
    controller.append_message(role="assistant", content="Working on it")
    controller.update_summary(record.id, "Earlier summary")

    cleared = controller.clear_conversation(record.id)

    assert cleared.title == DEFAULT_CONVERSATION_TITLE
    assert cleared.messages == []
    assert cleared.summary is None
    assert cleared.archived_at is None


def test_archive_and_restore_conversation_keeps_history_but_hides_from_active_metadata(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / ".agent-runner" / "workspaces")
    controller = WorkspaceConversationController(store, "workspace-1")
    record = controller.active_conversation()

    controller.append_message(role="user", content="Preserve this thread")
    archived, fallback = controller.archive_conversation(record.id)

    assert archived.archived_at is not None
    assert archived.messages[0].content == "Preserve this thread"
    assert archived.id not in [item.id for item in controller.metadata()]
    assert archived.id in [item.id for item in controller.metadata(include_archived=True)]
    assert fallback.id != archived.id

    restored = controller.restore_conversation(archived.id)

    assert restored.archived_at is None
    assert restored.messages[0].content == "Preserve this thread"
    assert controller.state.active_conversation_id == restored.id
    assert restored.id in [item.id for item in controller.metadata()]


def test_workspace_profile_round_trip(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / ".agent-runner" / "workspaces")
    controller = WorkspaceConversationController(store, "workspace-1")
    controller.set_workspace_profile(
        display_name="Clementine Kids",
        repo_path="/Users/sky/Documents/codex/business/clementine-kids",
        workspace_kind="studio_game",
        artifact_title="Moon Mango Jump",
        template_kind="platformer",
        game_title="Moon Mango Jump",
        theme_prompt="A playful moonlit jungle.",
        preview_url="/studio/preview/moon-mango-jump/index.html",
        preview_state="ready",
        publish_url="/play/moon-mango-jump/index.html",
        publish_state="published",
        publish_slug="moon-mango-jump",
    )

    reloaded = store.load_workspace_state("workspace-1")
    assert reloaded.display_name == "Clementine Kids"
    assert reloaded.repo_path == "/Users/sky/Documents/codex/business/clementine-kids"
    assert reloaded.workspace_kind == "studio_game"
    assert reloaded.artifact_title == "Moon Mango Jump"
    assert reloaded.template_kind == "platformer"
    assert reloaded.game_title == "Moon Mango Jump"
    assert reloaded.preview_state == "ready"
    assert reloaded.publish_slug == "moon-mango-jump"


def test_derive_conversation_title_uses_first_non_empty_line() -> None:
    title = derive_conversation_title("\n\nInvestigate dashboard regression\nwith extra details")
    assert title == "Investigate dashboard regression"


def test_store_rejects_unsafe_workspace_ids(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / ".agent-runner" / "workspaces")

    with pytest.raises(ValueError):
        WorkspaceConversationController(store, "../../outside-workspace")
