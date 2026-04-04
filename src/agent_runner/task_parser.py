from __future__ import annotations

import re
from pathlib import Path

from .models import TaskSpec

_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(?P<name>.+?)\s*$")


def parse_task_file(path: Path) -> TaskSpec:
    raw = path.read_text(encoding="utf-8")
    sections = _split_sections(raw)
    task = _join_lines(sections.get("task", []))
    success_lines = _normalize_list_lines(sections.get("success", []))
    constraints = _normalize_list_lines(sections.get("constraints", []))
    checks = _normalize_list_lines(sections.get("checks", []))

    if not task:
        raise ValueError("Task file is missing '# task' content.")
    if not success_lines:
        raise ValueError("Task file is missing '# success' criteria.")

    return TaskSpec(
        task=task,
        constraints=constraints,
        success_criteria=success_lines,
        checks=checks,
        source_path=path.resolve(),
    )


def parse_task_text(task_text: str, source: str = "<inline-task>") -> TaskSpec:
    text = task_text.strip()
    if not text:
        raise ValueError("Inline task text cannot be empty.")

    return TaskSpec(
        task=text,
        constraints=[],
        success_criteria=[
            "Task requirements are satisfied.",
            "Relevant verification checks pass.",
        ],
        checks=[],
        source_path=Path(source),
    )


def _split_sections(raw: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in raw.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            current = match.group("name").strip().lower()
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line.rstrip())
    return sections


def _normalize_list_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue
        cleaned = re.sub(r"^[-*]\s+", "", cleaned).strip()
        if cleaned:
            out.append(cleaned)
    return out


def _join_lines(lines: list[str]) -> str:
    text = "\n".join(line.strip() for line in lines if line.strip()).strip()
    return text
