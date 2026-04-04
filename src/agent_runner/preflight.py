from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import ProviderKind
from .prompt_context import load_mind_map, render_mind_map_block
from .providers import ExecutionRequest, ProviderRouter


@dataclass(slots=True)
class ClarifyPromptResult:
    summary: str
    questions: list[str]


def generate_clarifying_questions(
    *,
    provider_router: ProviderRouter,
    provider: ProviderKind,
    model: str,
    prompt: str,
    repo_path: Path,
    codex_bin: str,
    extra_access_dir: Path | None,
    ollama_host: str,
    timeout_seconds: int,
    dry_run: bool,
) -> ClarifyPromptResult:
    if dry_run:
        return ClarifyPromptResult(summary="Dry run request.", questions=[])
    mind_map_block = render_mind_map_block(load_mind_map(repo_path))
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "questions"],
        "properties": {
            "summary": {"type": "string"},
            "questions": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 2,
            },
        },
    }
    clarify_prompt = (
        "You help prepare coding tasks before execution. "
        "Read the user's brain dump, summarize it in one short sentence, and ask zero, one, or two short clarifying "
        "questions only if the answers would materially improve execution quality. "
        "Do not ask questions if the task is already specific enough. "
        "Return JSON matching the schema.\n"
        f"{mind_map_block}\n"
        f"USER REQUEST:\n{prompt}\n"
    )
    result = provider_router.run(
        ExecutionRequest(
            provider=provider,
            model=model,
            prompt=clarify_prompt,
            schema=schema,
            repo_path=repo_path,
            phase_name="clarify",
            timeout_seconds=timeout_seconds,
            codex_bin=codex_bin,
            extra_access_dir=extra_access_dir,
            ollama_host=ollama_host,
            dry_run=dry_run,
        )
    )
    summary = str(result.payload.get("summary", "")).strip()
    questions_raw = result.payload.get("questions", [])
    questions = [q.strip() for q in questions_raw if isinstance(q, str) and q.strip()]
    return ClarifyPromptResult(summary=summary, questions=questions[:2])
