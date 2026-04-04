from pathlib import Path

import pytest

from agent_runner.task_parser import parse_task_file, parse_task_text


def test_parse_task_file_basic(tmp_path: Path) -> None:
    task_file = tmp_path / "task.md"
    task_file.write_text(
        """# task
Add a dashboard card

# constraints
- keep existing style

# success
- card renders
- tests pass

# checks
pytest -q
""",
        encoding="utf-8",
    )
    spec = parse_task_file(task_file)
    assert spec.task == "Add a dashboard card"
    assert spec.constraints == ["keep existing style"]
    assert spec.success_criteria == ["card renders", "tests pass"]
    assert spec.checks == ["pytest -q"]


def test_parse_task_requires_task_and_success(tmp_path: Path) -> None:
    task_file = tmp_path / "task.md"
    task_file.write_text("# task\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing '# task'"):
        parse_task_file(task_file)

    task_file.write_text("# task\nDo work\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing '# success'"):
        parse_task_file(task_file)


def test_parse_task_text_generates_defaults() -> None:
    spec = parse_task_text("Summarize project docs")
    assert spec.task == "Summarize project docs"
    assert spec.constraints == []
    assert spec.checks == []
    assert len(spec.success_criteria) == 2
