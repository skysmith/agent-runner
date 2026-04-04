from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .conversation_store import build_transcript, synthesize_summary
from .models import ConversationRecord, ProviderKind, RunMode
from .prompt_context import load_mind_map, render_mind_map_block

DEFAULT_CONTEXT_CHAR_CAP = 12000
DEFAULT_RECENT_MESSAGE_COUNT = 8
DEFAULT_SUMMARY_SOURCE_COUNT = 10


@dataclass(slots=True)
class EffectiveContext:
    system_context: str
    conversation_context: str
    current_input: str

    @property
    def context_text(self) -> str:
        parts = [self.system_context.strip(), self.conversation_context.strip(), self.current_input.strip()]
        return "\n\n".join(part for part in parts if part)


class ContextAssembler:
    def __init__(
        self,
        *,
        context_char_cap: int = DEFAULT_CONTEXT_CHAR_CAP,
        recent_message_count: int = DEFAULT_RECENT_MESSAGE_COUNT,
        summary_source_count: int = DEFAULT_SUMMARY_SOURCE_COUNT,
    ):
        self.context_char_cap = max(100, context_char_cap)
        self.recent_message_count = max(2, recent_message_count)
        self.summary_source_count = max(2, summary_source_count)

    def build_for_message(
        self,
        *,
        repo_path: Path,
        provider: ProviderKind,
        model: str,
        run_mode: RunMode,
        conversation: ConversationRecord,
        current_input: str,
    ) -> EffectiveContext:
        return EffectiveContext(
            system_context=self._system_context(
                repo_path=repo_path,
                provider=provider,
                model=model,
                run_mode=run_mode,
            ),
            conversation_context=self._conversation_context(conversation),
            current_input=f"CURRENT USER MESSAGE:\n{current_input.strip()}",
        )

    def build_for_loop(
        self,
        *,
        repo_path: Path,
        provider: ProviderKind,
        model: str,
        run_mode: RunMode,
        conversation: ConversationRecord,
        current_input: str,
    ) -> EffectiveContext:
        return EffectiveContext(
            system_context=self._system_context(
                repo_path=repo_path,
                provider=provider,
                model=model,
                run_mode=run_mode,
            ),
            conversation_context=self._conversation_context(conversation),
            current_input=f"LATEST USER DIRECTIVE:\n{current_input.strip()}",
        )

    def refresh_summary(self, conversation: ConversationRecord) -> str | None:
        transcript = build_transcript(conversation.messages)
        if len(transcript) <= self.context_char_cap:
            return None
        head = conversation.messages[:-self.recent_message_count]
        if not head:
            return None
        source = head[-self.summary_source_count :]
        return synthesize_summary(source) or None

    def _system_context(self, *, repo_path: Path, provider: ProviderKind, model: str, run_mode: RunMode) -> str:
        mind_map_block = render_mind_map_block(load_mind_map(repo_path)).strip()
        lines = [
            "WORKSPACE CONTEXT:",
            f"- repo_path: {repo_path}",
            f"- provider: {provider}",
            f"- model: {model}",
            f"- run_mode: {run_mode}",
        ]
        if mind_map_block:
            lines.extend(["", mind_map_block])
        return "\n".join(lines).strip()

    def _conversation_context(self, conversation: ConversationRecord) -> str:
        transcript = build_transcript(conversation.messages)
        if not transcript:
            return f"ACTIVE CONVERSATION:\n- title: {conversation.title}\n- no prior messages yet"
        if len(transcript) <= self.context_char_cap:
            return f"ACTIVE CONVERSATION ({conversation.title}):\n{transcript}"
        recent = conversation.messages[-self.recent_message_count :]
        summary = (conversation.summary or "").strip()
        if not summary:
            summary = synthesize_summary(conversation.messages[:-self.recent_message_count])
        parts = [f"ACTIVE CONVERSATION ({conversation.title}):"]
        if summary:
            parts.extend(["SUMMARY OF EARLIER MESSAGES:", summary])
        recent_text = build_transcript(recent)
        if recent_text:
            parts.extend(["RECENT MESSAGES:", recent_text])
        return "\n".join(parts).strip()
