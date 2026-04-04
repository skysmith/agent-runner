from __future__ import annotations

from .models import BuildResult, CheckResult, PlanStep, PlannerResult, ReviewResult, TaskSpec
from .prompt_context import render_mind_map_block


def planner_prompt(task: TaskSpec, mind_map_text: str = "", conversation_context: str = "") -> str:
    constraints = "\n".join(f"- {c}" for c in task.constraints) or "- none"
    success = "\n".join(f"- {c}" for c in task.success_criteria)
    checks = "\n".join(f"- {c}" for c in task.checks) or "- none"
    mind_map_block = render_mind_map_block(mind_map_text)
    conversation_block = _render_conversation_block(conversation_context)
    return f"""You are the PLANNER.
Create a concise implementation plan for this task as ordered, actionable steps.
{mind_map_block}
{conversation_block}

TASK:
{task.task}

CONSTRAINTS:
{constraints}

SUCCESS CRITERIA:
{success}

CHECKS:
{checks}

Return only JSON matching the provided schema.
"""


def builder_prompt(
    task: TaskSpec,
    step: PlanStep,
    prior_feedback: str | None,
    mind_map_text: str = "",
    conversation_context: str = "",
) -> str:
    constraints = "\n".join(f"- {c}" for c in task.constraints) or "- none"
    success = "\n".join(f"- {c}" for c in task.success_criteria)
    step_done = "\n".join(f"- {c}" for c in step.done_criteria) or "- none"
    feedback = prior_feedback.strip() if prior_feedback else "none"
    mind_map_block = render_mind_map_block(mind_map_text)
    conversation_block = _render_conversation_block(conversation_context)
    return f"""You are the BUILDER.
Implement exactly this step in the repository.
{mind_map_block}
{conversation_block}

TASK:
{task.task}

STEP:
id: {step.id}
title: {step.title}
instructions: {step.instructions}
done_criteria:
{step_done}

CONSTRAINTS:
{constraints}

SUCCESS CRITERIA:
{success}

REVIEWER FEEDBACK FROM LAST ATTEMPT:
{feedback}

Run commands as needed.
At the end, return only JSON matching the schema.
"""


def reviewer_prompt(
    task: TaskSpec,
    step: PlanStep,
    build: BuildResult,
    checks: list[CheckResult],
    mind_map_text: str = "",
    conversation_context: str = "",
) -> str:
    checks_blob = "\n".join(
        f"- cmd: {c.command}\n  code: {c.return_code}\n  stdout: {truncate(c.stdout)}\n  stderr: {truncate(c.stderr)}"
        for c in checks
    ) or "- none"
    success = "\n".join(f"- {c}" for c in task.success_criteria)
    step_done = "\n".join(f"- {c}" for c in step.done_criteria) or "- none"
    mind_map_block = render_mind_map_block(mind_map_text)
    conversation_block = _render_conversation_block(conversation_context)
    return f"""You are the REVIEWER.
Decide if this step is complete and whether the full task is complete.
{mind_map_block}
{conversation_block}

TASK:
{task.task}

STEP:
id: {step.id}
title: {step.title}
done_criteria:
{step_done}

SUCCESS CRITERIA:
{success}

BUILDER RESULT:
status: {build.status}
summary: {build.summary}
files_touched: {build.files_touched}
commands_run: {build.commands_run}
notes: {build.notes}

CHECK RESULTS:
{checks_blob}

Return only JSON matching the provided schema.
"""


def planner_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["steps", "assumptions"],
        "properties": {
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "steps": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "title", "instructions", "done_criteria", "dependencies"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "title": {"type": "string", "minLength": 1},
                        "instructions": {"type": "string", "minLength": 1},
                        "done_criteria": {"type": "array", "items": {"type": "string"}},
                        "dependencies": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    }


def builder_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "summary", "files_touched", "commands_run", "notes"],
        "properties": {
            "status": {"type": "string"},
            "summary": {"type": "string"},
            "files_touched": {"type": "array", "items": {"type": "string"}},
            "commands_run": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "array", "items": {"type": "string"}},
        },
    }


def reviewer_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdict", "task_complete", "step_complete", "issues", "guidance"],
        "properties": {
            "verdict": {"type": "string"},
            "task_complete": {"type": "boolean"},
            "step_complete": {"type": "boolean"},
            "issues": {"type": "array", "items": {"type": "string"}},
            "guidance": {"type": "string"},
        },
    }


def parse_planner_result(payload: dict) -> PlannerResult:
    steps = [
        PlanStep(
            id=s["id"],
            title=s["title"],
            instructions=s["instructions"],
            done_criteria=list(s.get("done_criteria", [])),
            dependencies=list(s.get("dependencies", [])),
        )
        for s in payload["steps"]
    ]
    return PlannerResult(steps=steps, assumptions=list(payload["assumptions"]))


def parse_builder_result(payload: dict) -> BuildResult:
    return BuildResult(
        status=payload["status"],
        summary=payload["summary"],
        files_touched=list(payload["files_touched"]),
        commands_run=list(payload["commands_run"]),
        notes=list(payload.get("notes", [])),
    )


def parse_reviewer_result(payload: dict) -> ReviewResult:
    return ReviewResult(
        verdict=payload["verdict"],
        task_complete=bool(payload["task_complete"]),
        step_complete=bool(payload["step_complete"]),
        issues=list(payload["issues"]),
        guidance=payload["guidance"],
    )


def truncate(text: str, max_len: int = 280) -> str:
    text = text.strip().replace("\n", "\\n")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _render_conversation_block(conversation_context: str) -> str:
    text = conversation_context.strip()
    if not text:
        return ""
    return f"\nCONVERSATION CONTEXT:\n{text}\n"
