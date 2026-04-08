from __future__ import annotations

from pathlib import Path

from agent_runner.context_assembler import ContextAssembler
from agent_runner.models import ConversationMessage, ConversationRecord, ProviderKind, RunMode


def _message(idx: int, role: str, content: str) -> ConversationMessage:
    return ConversationMessage(
        id=f"m-{idx}",
        conversation_id="conv-1",
        role=role,
        content=content,
        created_at="2026-04-04T12:00:00-06:00",
    )


def test_short_conversation_includes_full_history(tmp_path: Path) -> None:
    assembler = ContextAssembler(context_char_cap=500)
    conversation = ConversationRecord(
        id="conv-1",
        workspace_id="workspace-1",
        title="Short thread",
        created_at="2026-04-04T12:00:00-06:00",
        updated_at="2026-04-04T12:00:00-06:00",
        messages=[_message(1, "user", "hello"), _message(2, "assistant", "hi there")],
    )

    context = assembler.build_for_message(
        repo_path=tmp_path,
        provider=ProviderKind.CODEX,
        model="gpt-5.3-codex",
        run_mode=RunMode.MESSAGE,
        conversation=conversation,
        current_input="next question",
    )

    assert "USER:\nhello" in context.conversation_context
    assert "ASSISTANT:\nhi there" in context.conversation_context
    assert "CURRENT USER MESSAGE:\nnext question" in context.current_input


def test_long_conversation_uses_summary_and_recent_messages(tmp_path: Path) -> None:
    assembler = ContextAssembler(context_char_cap=120, recent_message_count=2)
    conversation = ConversationRecord(
        id="conv-1",
        workspace_id="workspace-1",
        title="Long thread",
        created_at="2026-04-04T12:00:00-06:00",
        updated_at="2026-04-04T12:00:00-06:00",
        summary="Earlier summary",
        messages=[
            _message(1, "user", "a" * 80),
            _message(2, "assistant", "b" * 80),
            _message(3, "user", "recent user"),
            _message(4, "assistant", "recent assistant"),
        ],
    )

    context = assembler.build_for_loop(
        repo_path=tmp_path,
        provider=ProviderKind.CODEX,
        model="gpt-5.3-codex",
        run_mode=RunMode.LOOP,
        conversation=conversation,
        current_input="ship it",
    )

    assert "SUMMARY OF EARLIER MESSAGES:" in context.conversation_context
    assert "Earlier summary" in context.conversation_context
    assert "RECENT MESSAGES:" in context.conversation_context
    assert "recent user" in context.conversation_context
    assert "LATEST USER DIRECTIVE:\nship it" in context.current_input


def test_codex_context_metrics_use_larger_default_budget() -> None:
    assembler = ContextAssembler()
    conversation = ConversationRecord(
        id="conv-1",
        workspace_id="workspace-1",
        title="Codex thread",
        created_at="2026-04-04T12:00:00-06:00",
        updated_at="2026-04-04T12:00:00-06:00",
        messages=[_message(1, "user", "hello there")],
    )

    metrics = assembler.conversation_metrics(
        conversation,
        provider=ProviderKind.CODEX,
        model="gpt-5.4",
    )

    assert metrics["context_char_cap"] == 100000
    assert metrics["cap_source"] == "provider-default"
    assert metrics["summary_active"] is False
