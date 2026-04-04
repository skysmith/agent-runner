from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_runner.codex_client import CodexExecResult
from agent_runner.models import ProviderKind
from agent_runner.runner import AgentRunner, RunnerConfig


def _task_file(tmp_path: Path) -> Path:
    path = tmp_path / "task.md"
    path.write_text(
        """# task
Implement feature X

# success
- feature works
- tests pass

# checks
echo ok
""",
        encoding="utf-8",
    )
    return path


def test_runner_success(monkeypatch, tmp_path: Path) -> None:
    task_file = _task_file(tmp_path)
    repo = tmp_path
    artifacts = tmp_path / ".agent-runner"

    responses: list[dict[str, Any]] = [
        {
            "assumptions": [],
            "steps": [
                {
                    "id": "s1",
                    "title": "Do it",
                    "instructions": "Make the change",
                    "done_criteria": ["done"],
                    "dependencies": [],
                }
            ],
        },
        {
            "status": "ok",
            "summary": "implemented",
            "files_touched": ["a.py"],
            "commands_run": ["pytest -q"],
            "notes": [],
        },
        {
            "verdict": "pass",
            "task_complete": True,
            "step_complete": True,
            "issues": [],
            "guidance": "",
        },
    ]

    def fake_codex_json(**kwargs):
        payload = responses.pop(0)
        return CodexExecResult(payload=payload, raw_jsonl='{"final_output":{}}', stderr="", return_code=0)

    monkeypatch.setattr("agent_runner.providers.ProviderRouter.run", lambda self, request: fake_codex_json())
    monkeypatch.setattr("agent_runner.runner.run_checks", lambda commands, repo_path: [])

    config = RunnerConfig(
        task_file=task_file,
        repo_path=repo,
        artifacts_dir=artifacts,
        max_step_retries=1,
    )
    outcome = AgentRunner(config).run()
    assert outcome.ok is True
    assert outcome.reason == "success"
    assert outcome.final_message == "implemented"
    assert len(outcome.step_runs) == 1


def test_runner_retry_then_fail(monkeypatch, tmp_path: Path) -> None:
    task_file = _task_file(tmp_path)
    repo = tmp_path
    artifacts = tmp_path / ".agent-runner"

    responses: list[dict[str, Any]] = [
        {
            "assumptions": [],
            "steps": [
                {
                    "id": "s1",
                    "title": "Do it",
                    "instructions": "Make the change",
                    "done_criteria": ["done"],
                    "dependencies": [],
                }
            ],
        },
        {
            "status": "needs-work",
            "summary": "partial",
            "files_touched": ["a.py"],
            "commands_run": [],
            "notes": [],
        },
        {
            "verdict": "fail",
            "task_complete": False,
            "step_complete": False,
            "issues": ["missing tests"],
            "guidance": "add tests",
        },
        {
            "status": "still-bad",
            "summary": "partial again",
            "files_touched": ["a.py"],
            "commands_run": [],
            "notes": [],
        },
        {
            "verdict": "fail",
            "task_complete": False,
            "step_complete": False,
            "issues": ["still broken"],
            "guidance": "fix logic",
        },
    ]

    def fake_codex_json(**kwargs):
        payload = responses.pop(0)
        return CodexExecResult(payload=payload, raw_jsonl='{"final_output":{}}', stderr="", return_code=0)

    monkeypatch.setattr("agent_runner.providers.ProviderRouter.run", lambda self, request: fake_codex_json())
    monkeypatch.setattr("agent_runner.runner.run_checks", lambda commands, repo_path: [])

    config = RunnerConfig(
        task_file=task_file,
        repo_path=repo,
        artifacts_dir=artifacts,
        max_step_retries=1,
    )
    outcome = AgentRunner(config).run()
    assert outcome.ok is False
    assert "failed after retries" in outcome.reason
    assert "still broken" in outcome.final_message
    assert len(outcome.step_runs) == 2


def test_runner_uses_detected_checks_when_none_declared(monkeypatch, tmp_path: Path) -> None:
    task_file = tmp_path / "task.md"
    task_file.write_text(
        """# task
Implement feature Y

# success
- done
""",
        encoding="utf-8",
    )

    responses: list[dict[str, Any]] = [
        {
            "assumptions": [],
            "steps": [
                {
                    "id": "s1",
                    "title": "Do it",
                    "instructions": "Make the change",
                    "done_criteria": ["done"],
                    "dependencies": [],
                }
            ],
        },
        {
            "status": "ok",
            "summary": "implemented",
            "files_touched": [],
            "commands_run": [],
            "notes": [],
        },
        {
            "verdict": "pass",
            "task_complete": True,
            "step_complete": True,
            "issues": [],
            "guidance": "",
        },
    ]
    seen_checks: list[list[str]] = []

    def fake_codex_json(**kwargs):
        payload = responses.pop(0)
        return CodexExecResult(payload=payload, raw_jsonl='{"final_output":{}}', stderr="", return_code=0)

    def fake_run_checks(commands, repo_path):
        seen_checks.append(list(commands))
        return []

    monkeypatch.setattr("agent_runner.providers.ProviderRouter.run", lambda self, request: fake_codex_json())
    monkeypatch.setattr("agent_runner.runner.run_checks", fake_run_checks)
    monkeypatch.setattr("agent_runner.runner.detect_repo_checks", lambda repo_path: ["pytest -q"])

    config = RunnerConfig(
        task_file=task_file,
        repo_path=tmp_path,
        artifacts_dir=tmp_path / ".agent-runner",
        max_step_retries=1,
    )
    outcome = AgentRunner(config).run()
    assert outcome.ok is True
    assert seen_checks == [["pytest -q"]]


def test_runner_respects_explicit_empty_check_list(monkeypatch, tmp_path: Path) -> None:
    task_file = _task_file(tmp_path)
    responses: list[dict[str, Any]] = [
        {
            "assumptions": [],
            "steps": [
                {
                    "id": "s1",
                    "title": "Do it",
                    "instructions": "Make the change",
                    "done_criteria": ["done"],
                    "dependencies": [],
                }
            ],
        },
        {
            "status": "ok",
            "summary": "implemented",
            "files_touched": [],
            "commands_run": [],
            "notes": [],
        },
        {
            "verdict": "pass",
            "task_complete": True,
            "step_complete": True,
            "issues": [],
            "guidance": "",
        },
    ]
    seen_checks: list[list[str]] = []

    def fake_codex_json(**kwargs):
        payload = responses.pop(0)
        return CodexExecResult(payload=payload, raw_jsonl='{"final_output":{}}', stderr="", return_code=0)

    def fake_run_checks(commands, repo_path):
        seen_checks.append(list(commands))
        return []

    monkeypatch.setattr("agent_runner.providers.ProviderRouter.run", lambda self, request: fake_codex_json())
    monkeypatch.setattr("agent_runner.runner.run_checks", fake_run_checks)
    monkeypatch.setattr("agent_runner.runner.detect_repo_checks", lambda repo_path: ["pytest -q"])

    config = RunnerConfig(
        task_file=task_file,
        repo_path=tmp_path,
        artifacts_dir=tmp_path / ".agent-runner",
        max_step_retries=1,
        check_commands=[],
    )
    outcome = AgentRunner(config).run()
    assert outcome.ok is True
    assert seen_checks == []


def test_runner_supports_inline_task_text(monkeypatch, tmp_path: Path) -> None:
    responses: list[dict[str, Any]] = [
        {
            "assumptions": [],
            "steps": [
                {
                    "id": "s1",
                    "title": "Do it",
                    "instructions": "Make the change",
                    "done_criteria": ["done"],
                    "dependencies": [],
                }
            ],
        },
        {
            "status": "ok",
            "summary": "implemented",
            "files_touched": [],
            "commands_run": [],
            "notes": [],
        },
        {
            "verdict": "pass",
            "task_complete": True,
            "step_complete": True,
            "issues": [],
            "guidance": "",
        },
    ]

    def fake_codex_json(**kwargs):
        payload = responses.pop(0)
        return CodexExecResult(payload=payload, raw_jsonl='{"final_output":{}}', stderr="", return_code=0)

    monkeypatch.setattr("agent_runner.providers.ProviderRouter.run", lambda self, request: fake_codex_json())
    monkeypatch.setattr("agent_runner.runner.run_checks", lambda commands, repo_path: [])
    monkeypatch.setattr("agent_runner.runner.detect_repo_checks", lambda repo_path: [])

    config = RunnerConfig(
        task_file=None,
        task_text="Check docs and summarize.",
        repo_path=tmp_path,
        artifacts_dir=tmp_path / ".agent-runner",
        max_step_retries=1,
    )
    outcome = AgentRunner(config).run()
    assert outcome.ok is True


def test_runner_passes_selected_provider(monkeypatch, tmp_path: Path) -> None:
    task_file = _task_file(tmp_path)
    seen_provider: list[ProviderKind] = []
    responses: list[dict[str, Any]] = [
        {
            "assumptions": [],
            "steps": [
                {
                    "id": "s1",
                    "title": "Do it",
                    "instructions": "Make the change",
                    "done_criteria": ["done"],
                    "dependencies": [],
                }
            ],
        },
        {"status": "ok", "summary": "implemented", "files_touched": [], "commands_run": [], "notes": []},
        {"verdict": "pass", "task_complete": True, "step_complete": True, "issues": [], "guidance": ""},
    ]

    def fake_run(self, request):
        seen_provider.append(request.provider)
        payload = responses.pop(0)
        return CodexExecResult(payload=payload, raw_jsonl='{"final_output":{}}', stderr="", return_code=0)

    monkeypatch.setattr("agent_runner.providers.ProviderRouter.run", fake_run)
    monkeypatch.setattr("agent_runner.runner.run_checks", lambda commands, repo_path: [])

    config = RunnerConfig(
        task_file=task_file,
        repo_path=tmp_path,
        artifacts_dir=tmp_path / ".agent-runner",
        provider=ProviderKind.OLLAMA,
        model="llama3.2",
    )
    outcome = AgentRunner(config).run()
    assert outcome.ok is True
    assert seen_provider == [ProviderKind.OLLAMA, ProviderKind.OLLAMA, ProviderKind.OLLAMA]


def test_runner_can_stop_safely_before_execution(monkeypatch, tmp_path: Path) -> None:
    task_file = _task_file(tmp_path)
    responses: list[dict[str, Any]] = [
        {
            "assumptions": [],
            "steps": [
                {
                    "id": "s1",
                    "title": "Do it",
                    "instructions": "Make the change",
                    "done_criteria": ["done"],
                    "dependencies": [],
                }
            ],
        }
    ]

    def fake_run(self, request):
        payload = responses.pop(0)
        return CodexExecResult(payload=payload, raw_jsonl='{"final_output":{}}', stderr="", return_code=0)

    monkeypatch.setattr("agent_runner.providers.ProviderRouter.run", fake_run)
    monkeypatch.setattr("agent_runner.runner.run_checks", lambda commands, repo_path: [])

    calls = {"count": 0}

    def stop_requested() -> bool:
        calls["count"] += 1
        return calls["count"] >= 2

    config = RunnerConfig(
        task_file=task_file,
        repo_path=tmp_path,
        artifacts_dir=tmp_path / ".agent-runner",
        stop_requested=stop_requested,
    )
    outcome = AgentRunner(config).run()
    assert outcome.ok is False
    assert outcome.reason == "Stopped by user."
    assert "stopped safely" in outcome.final_message.lower()


def test_runner_includes_mind_map_in_prompts(monkeypatch, tmp_path: Path) -> None:
    task_file = _task_file(tmp_path)
    (tmp_path / "mind-map.md").write_text("# Mind Map\nPrefer calm UI.", encoding="utf-8")
    prompts_seen: list[str] = []
    responses: list[dict[str, Any]] = [
        {
            "assumptions": [],
            "steps": [
                {
                    "id": "s1",
                    "title": "Do it",
                    "instructions": "Make the change",
                    "done_criteria": ["done"],
                    "dependencies": [],
                }
            ],
        },
        {"status": "ok", "summary": "implemented", "files_touched": [], "commands_run": [], "notes": []},
        {"verdict": "pass", "task_complete": True, "step_complete": True, "issues": [], "guidance": ""},
    ]

    def fake_run(self, request):
        prompts_seen.append(request.prompt)
        payload = responses.pop(0)
        return CodexExecResult(payload=payload, raw_jsonl='{"final_output":{}}', stderr="", return_code=0)

    monkeypatch.setattr("agent_runner.providers.ProviderRouter.run", fake_run)
    monkeypatch.setattr("agent_runner.runner.run_checks", lambda commands, repo_path: [])

    config = RunnerConfig(
        task_file=task_file,
        repo_path=tmp_path,
        artifacts_dir=tmp_path / ".agent-runner",
        max_step_retries=1,
    )
    outcome = AgentRunner(config).run()
    assert outcome.ok is True
    assert any("OPERATING MIND MAP:" in prompt for prompt in prompts_seen)
    assert any("Prefer calm UI." in prompt for prompt in prompts_seen)
