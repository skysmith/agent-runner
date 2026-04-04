from __future__ import annotations

from pathlib import Path

from agent_runner.codex_client import CodexExecResult
from agent_runner.runner import AgentRunner, RunnerConfig


def test_runner_injects_conversation_context(monkeypatch, tmp_path: Path) -> None:
    prompts: list[str] = []
    responses = [
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

    def fake_run(self, request):
        prompts.append(request.prompt)
        return CodexExecResult(payload=responses.pop(0), raw_jsonl='{"final_output":{}}', stderr="", return_code=0)

    task_file = tmp_path / "task.md"
    task_file.write_text("# task\nDo the thing\n\n# success\n- done\n", encoding="utf-8")

    monkeypatch.setattr("agent_runner.providers.ProviderRouter.run", fake_run)
    monkeypatch.setattr("agent_runner.runner.run_checks", lambda commands, repo_path: [])
    monkeypatch.setattr("agent_runner.runner.detect_repo_checks", lambda repo_path: [])

    outcome = AgentRunner(
        RunnerConfig(
            task_file=task_file,
            repo_path=tmp_path,
            artifacts_dir=tmp_path / ".agent-runner",
            conversation_context="ACTIVE CONVERSATION\nUSER: earlier context",
        )
    ).run()

    assert outcome.ok is True
    assert any("CONVERSATION CONTEXT:" in prompt for prompt in prompts)
    assert any("earlier context" in prompt for prompt in prompts)
