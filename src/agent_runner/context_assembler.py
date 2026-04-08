from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

from .conversation_store import build_transcript, synthesize_summary
from .models import AssistantCapabilityMode, ConversationRecord, ProviderKind, RunMode
from .prompt_context import load_mind_map, render_mind_map_block

DEFAULT_CONTEXT_CHAR_CAP = 12000
DEFAULT_CODEX_CONTEXT_CHAR_CAP = 100000
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
        context_char_cap: int | None = None,
        recent_message_count: int = DEFAULT_RECENT_MESSAGE_COUNT,
        summary_source_count: int = DEFAULT_SUMMARY_SOURCE_COUNT,
    ):
        self.context_char_cap = self._normalize_context_char_cap(context_char_cap)
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
        assistant_mode: AssistantCapabilityMode | None = None,
        page_context: dict[str, object] | None = None,
        configured_context_char_cap: int | None = None,
    ) -> EffectiveContext:
        context_char_cap, _ = self.resolved_context_char_cap(
            provider=provider,
            model=model,
            configured_context_char_cap=configured_context_char_cap,
        )
        return EffectiveContext(
            system_context=self._system_context(
                repo_path=repo_path,
                provider=provider,
                model=model,
                run_mode=run_mode,
                assistant_mode=assistant_mode or conversation.assistant_mode,
                page_context=page_context if page_context is not None else conversation.page_context,
            ),
            conversation_context=self._conversation_context(
                conversation,
                context_char_cap=context_char_cap,
            ),
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
        assistant_mode: AssistantCapabilityMode | None = None,
        page_context: dict[str, object] | None = None,
        configured_context_char_cap: int | None = None,
    ) -> EffectiveContext:
        context_char_cap, _ = self.resolved_context_char_cap(
            provider=provider,
            model=model,
            configured_context_char_cap=configured_context_char_cap,
        )
        return EffectiveContext(
            system_context=self._system_context(
                repo_path=repo_path,
                provider=provider,
                model=model,
                run_mode=run_mode,
                assistant_mode=assistant_mode or conversation.assistant_mode,
                page_context=page_context if page_context is not None else conversation.page_context,
            ),
            conversation_context=self._conversation_context(
                conversation,
                context_char_cap=context_char_cap,
            ),
            current_input=f"LATEST USER DIRECTIVE:\n{current_input.strip()}",
        )

    def resolved_context_char_cap(
        self,
        *,
        provider: ProviderKind,
        model: str,
        configured_context_char_cap: int | None = None,
    ) -> tuple[int, str]:
        cap = self._normalize_context_char_cap(configured_context_char_cap)
        if cap is None:
            cap = self.context_char_cap
        if cap is not None:
            return cap, "manual"
        if provider == ProviderKind.CODEX or self._looks_like_codex_model(model):
            return DEFAULT_CODEX_CONTEXT_CHAR_CAP, "provider-default"
        return DEFAULT_CONTEXT_CHAR_CAP, "default"

    def conversation_metrics(
        self,
        conversation: ConversationRecord,
        *,
        provider: ProviderKind,
        model: str,
        configured_context_char_cap: int | None = None,
    ) -> dict[str, object]:
        context_char_cap, cap_source = self.resolved_context_char_cap(
            provider=provider,
            model=model,
            configured_context_char_cap=configured_context_char_cap,
        )
        transcript = build_transcript(conversation.messages)
        context_text = self._conversation_context(conversation, context_char_cap=context_char_cap)
        transcript_chars = len(transcript)
        context_chars = len(context_text)
        summary_active = transcript_chars > context_char_cap and bool(
            conversation.messages[:-self.recent_message_count]
        )
        return {
            "transcript_chars": transcript_chars,
            "context_chars": context_chars,
            "approx_tokens": math.ceil(context_chars / 4) if context_chars else 0,
            "context_char_cap": context_char_cap,
            "summary_active": summary_active,
            "cap_source": cap_source,
        }

    def refresh_summary(
        self,
        conversation: ConversationRecord,
        *,
        provider: ProviderKind,
        model: str,
        configured_context_char_cap: int | None = None,
    ) -> str | None:
        context_char_cap, _ = self.resolved_context_char_cap(
            provider=provider,
            model=model,
            configured_context_char_cap=configured_context_char_cap,
        )
        transcript = build_transcript(conversation.messages)
        if len(transcript) <= context_char_cap:
            return None
        head = conversation.messages[:-self.recent_message_count]
        if not head:
            return None
        source = head[-self.summary_source_count :]
        return synthesize_summary(source) or None

    def _system_context(
        self,
        *,
        repo_path: Path,
        provider: ProviderKind,
        model: str,
        run_mode: RunMode,
        assistant_mode: AssistantCapabilityMode,
        page_context: dict[str, object],
    ) -> str:
        mind_map_block = render_mind_map_block(load_mind_map(repo_path)).strip()
        lines = [
            "WORKSPACE CONTEXT:",
            f"- repo_path: {repo_path}",
            f"- provider: {provider}",
            f"- model: {model}",
            f"- run_mode: {run_mode}",
            f"- assistant_mode: {assistant_mode}",
            "",
            "CAPABILITY CONTRACT:",
        ]
        if assistant_mode == AssistantCapabilityMode.ASK:
            lines.extend(
                [
                    "- ask mode: read-only explanations, comparisons, and analysis.",
                    "- do not propose or perform destructive or mutating production actions.",
                ]
            )
        elif assistant_mode == AssistantCapabilityMode.OPS:
            lines.extend(
                [
                    "- ops mode: bounded operational workflows and summaries are allowed.",
                    "- prioritize reversible actions and clearly call out risk.",
                ]
            )
        else:
            lines.extend(
                [
                    "- dev mode: deeper engineering workflows are allowed.",
                    "- still explain risks before high-impact actions.",
                ]
            )
        if page_context:
            lines.extend(
                [
                    "",
                    "PAGE CONTEXT (JSON):",
                    json.dumps(page_context, indent=2, sort_keys=True)[:4000],
                ]
            )
        if mind_map_block:
            lines.extend(["", mind_map_block])
        return "\n".join(lines).strip()

    def _conversation_context(self, conversation: ConversationRecord, *, context_char_cap: int) -> str:
        transcript = build_transcript(conversation.messages)
        if not transcript:
            return f"ACTIVE CONVERSATION:\n- title: {conversation.title}\n- no prior messages yet"
        if len(transcript) <= context_char_cap:
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

    @staticmethod
    def _normalize_context_char_cap(value: int | None) -> int | None:
        if value is None:
            return None
        return max(100, int(value))

    @staticmethod
    def _looks_like_codex_model(model: str) -> bool:
        normalized = str(model or "").strip().lower()
        return normalized.startswith("gpt-5") or "codex" in normalized
