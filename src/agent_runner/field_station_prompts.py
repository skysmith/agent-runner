from __future__ import annotations

from dataclasses import dataclass

from .orchestration import normalize_field_station_mode


@dataclass(frozen=True, slots=True)
class FieldStationPromptPack:
    mode: str
    label: str
    default_expected_output: str
    role: str
    output_brief: str
    guardrails: tuple[str, ...]


FIELD_STATION_PROMPT_PACKS: dict[str, FieldStationPromptPack] = {
    "family": FieldStationPromptPack(
        mode="family",
        label="Family",
        default_expected_output="kid_story",
        role="You are Alcove in family mode: warm, playful, concrete, and safe for kids.",
        output_brief="Create a family-friendly creative artifact that a parent can use right away.",
        guardrails=(
            "Keep it age-flexible and kind.",
            "Do not encourage unsafe tools, risky physical activity, or unsupervised online behavior.",
            "Prefer short sections, playful names, and one easy next action.",
        ),
    ),
    "maker": FieldStationPromptPack(
        mode="maker",
        label="Maker",
        default_expected_output="project_plan",
        role="You are Alcove in maker mode: practical shop assistant, project archivist, and calm garage wizard.",
        output_brief="Turn the messy idea into a buildable plan with materials, steps, risks, and next actions.",
        guardrails=(
            "Prefer boring, staged, buildable steps over spectacle.",
            "Call out safety, supervision, missing parts, and assumptions.",
            "Keep the plan useful for a real table, garage, or kid project.",
        ),
    ),
    "business": FieldStationPromptPack(
        mode="business",
        label="Business",
        default_expected_output="owner_briefing",
        role="You are Alcove in business mode: a practical owner-operator assistant for small businesses.",
        output_brief="Create a brief that helps the owner decide what needs attention and what can wait.",
        guardrails=(
            "Do not claim that emails, refunds, orders, payments, or customer messages were sent.",
            "Separate facts, assumptions, drafts, and decisions.",
            "Keep recommendations approval-first and non-hypey.",
        ),
    ),
    "real-estate": FieldStationPromptPack(
        mode="real-estate",
        label="Real Estate",
        default_expected_output="transaction_brief",
        role="You are Alcove in real estate mode: deadline-aware, careful, and client-service oriented.",
        output_brief="Create a transaction or client follow-up artifact with dates, decisions, and draft language when useful.",
        guardrails=(
            "Do not give legal advice or claim that signatures, notices, or contract actions were completed.",
            "Flag deadline uncertainty and missing source documents.",
            "Keep client-facing drafts calm, clear, and approval-first.",
        ),
    ),
    "demo": FieldStationPromptPack(
        mode="demo",
        label="Demo",
        default_expected_output="client_demo_explanation",
        role="You are Alcove in demo mode: a grounded AI consulting explainer for local businesses.",
        output_brief="Explain the practical workflow opportunity, the approval loop, and a starter implementation path.",
        guardrails=(
            "Avoid AI hype and vague strategy language.",
            "Anchor the explanation in one messy corner of real work.",
            "Make the offer feel small, useful, and buildable.",
        ),
    ),
    "codex": FieldStationPromptPack(
        mode="codex",
        label="Codex",
        default_expected_output="codex_handoff",
        role="You are Alcove in Codex mode: a precise engineering handoff writer.",
        output_brief="Create a Codex-ready handoff with goal, context, files or areas to inspect, implementation steps, and verification.",
        guardrails=(
            "Keep implementation instructions specific enough for another Codex session to start.",
            "Separate known facts from assumptions.",
            "Include verification commands or checks when they are knowable.",
        ),
    ),
}


def field_station_prompt_pack(mode: object | None) -> FieldStationPromptPack:
    return FIELD_STATION_PROMPT_PACKS[normalize_field_station_mode(str(mode or ""))]


def default_expected_output_for_mode(mode: object | None) -> str:
    return field_station_prompt_pack(mode).default_expected_output


def field_station_worker_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "title",
            "summary",
            "artifact_markdown",
            "evidence",
            "risks",
            "suggested_next_action",
        ],
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "artifact_markdown": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
            "suggested_next_action": {"type": "string"},
        },
    }


def build_field_station_worker_prompt(
    *,
    workspace_id: str,
    mission: dict[str, object],
    job: dict[str, object],
    workspace_title: str,
) -> str:
    pack = field_station_prompt_pack(mission.get("mode"))
    goal = str(mission.get("goal") or "").strip()
    target = str(mission.get("target") or "").strip() or "No specific target was provided."
    permission_lane = str(mission.get("permission_lane") or "read-only")
    expected_output = str(mission.get("expected_output") or pack.default_expected_output)
    capture = mission.get("capture_snapshot") if isinstance(mission.get("capture_snapshot"), dict) else {}
    capture_id = str(capture.get("id") or mission.get("capture_id") or "").strip() or "No capture id."
    capture_source = str(capture.get("source") or mission.get("source") or "").strip() or "unknown"
    capture_text = str(capture.get("text") or goal).strip() or "No capture text was provided."
    capture_attachments = _attachment_summary(capture.get("attachments"))
    briefing_context = _briefing_context(capture.get("metadata"))
    guardrails = "\n".join(f"- {item}" for item in pack.guardrails)
    return f"""You are generating a saved artifact for Alcove Field Station.

Return JSON only, matching the provided schema. Do not edit files. Do not run commands.

Workspace:
- id: {workspace_id}
- title: {workspace_title}

Mission:
- id: {mission.get("id")}
- job id: {job.get("id")}
- mode: {pack.label}
- permission lane: {permission_lane}
- expected output: {expected_output}
- target: {target}
- messy goal: {goal}

Capture:
- id: {capture_id}
- source: {capture_source}
- text: {capture_text}
- attachments: {capture_attachments}

Read-only briefing sources:
{briefing_context}

Role:
{pack.role}

Output brief:
{pack.output_brief}

Guardrails:
{guardrails}

Artifact requirements:
- `artifact_markdown` must be a complete markdown artifact that can be saved as-is.
- Start the markdown with a clear H1 title.
- Include practical sections, not just prose.
- Make it useful for real life this week.
- If the input is underspecified, state assumptions and give a next-question section.

Approval boundary:
- This job may draft, summarize, plan, and recommend.
- It must not claim that external actions were completed.
- Anything customer-facing, financial, contractual, email-sending, order-changing, or hardware-moving remains human-approved.
"""


def _attachment_summary(value: object) -> str:
    if not isinstance(value, list) or not value:
        return "none"
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("kind") or "attachment").strip()
        mime_type = str(item.get("mime_type") or "").strip()
        path = str(item.get("path") or "").strip()
        detail = ", ".join(part for part in [mime_type, path] if part)
        lines.append(f"{label}{f' ({detail})' if detail else ''}")
    return "; ".join(lines) or "none"


def _briefing_context(metadata: object) -> str:
    if not isinstance(metadata, dict):
        return "none"
    sources = metadata.get("briefing_sources")
    if not isinstance(sources, list) or not sources:
        return "none"
    lines: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        label = str(source.get("label") or "Briefing source").strip()
        kind = str(source.get("kind") or "manual").strip()
        lane = str(source.get("permission_lane") or "read-only").strip()
        summary = str(source.get("summary") or "").strip()
        lines.append(f"- {label} ({kind}, {lane}): {summary or 'No summary provided.'}")
        sample_items = source.get("sample_items")
        if isinstance(sample_items, list):
            for item in sample_items[:5]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "Item").strip()
                detail = str(item.get("detail") or "").strip()
                urgency = str(item.get("urgency") or "").strip()
                parts = [title]
                if urgency:
                    parts.append(f"urgency: {urgency}")
                if detail:
                    parts.append(detail)
                lines.append(f"  - {' | '.join(parts)}")
    return "\n".join(lines) if lines else "none"
