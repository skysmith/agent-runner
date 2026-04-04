from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .artifacts import ArtifactStore
from .check_detection import detect_repo_checks
from .models import ProviderKind, RunOutcome, StepRun
from .prompt_context import load_mind_map
from .providers import ProviderRouter, ExecutionRequest, PhaseExecutionClient
from .prompts import (
    builder_prompt,
    builder_schema,
    parse_builder_result,
    parse_planner_result,
    parse_reviewer_result,
    planner_prompt,
    planner_schema,
    reviewer_prompt,
    reviewer_schema,
)
from .task_parser import parse_task_file, parse_task_text
from .verify import run_checks


@dataclass(slots=True)
class RunnerConfig:
    task_file: Path | None
    repo_path: Path
    artifacts_dir: Path
    task_text: str | None = None
    conversation_context: str = ""
    codex_bin: str = "codex"
    provider: ProviderKind = ProviderKind.CODEX
    model: str = "gpt-5.3-codex"
    ollama_host: str = "http://127.0.0.1:11434"
    extra_access_dir: Path | None = None
    max_step_retries: int = 2
    check_commands: list[str] | None = None
    dry_run: bool = False
    phase_timeout_seconds: int = 240
    progress: bool = True
    status_callback: Callable[[str], None] | None = None
    stop_requested: Callable[[], bool] | None = None


class AgentRunner:
    def __init__(self, config: RunnerConfig, phase_client: PhaseExecutionClient | None = None):
        self.config = config
        self.store = ArtifactStore(config.artifacts_dir)
        self.phase_client = phase_client or ProviderRouter()

    def run(self) -> RunOutcome:
        self._log(f"Build number: {self.store.build_number}")
        self._log(f"Starting run in repo: {self.config.repo_path}")
        self._log(f"Using provider: {self.config.provider}")
        self._log(f"Using model: {self.config.model}")
        mind_map_text = load_mind_map(self.config.repo_path)
        if self.config.extra_access_dir:
            self._log(f"Extra access dir: {self.config.extra_access_dir}")
        if self.config.task_text:
            task = parse_task_text(self.config.task_text)
        elif self.config.task_file:
            task = parse_task_file(self.config.task_file)
        else:
            raise ValueError("Either task_file or task_text must be provided.")

        if self.config.check_commands is None:
            check_cmds = list(task.checks or detect_repo_checks(self.config.repo_path))
        else:
            check_cmds = list(self.config.check_commands)
        self._log(f"Selected checks: {check_cmds if check_cmds else 'none'}")

        self.store.write_json("task.json", task)
        self.store.write_json("checks/selected.json", {"commands": check_cmds})
        if self._should_stop():
            return self._stopped_outcome([], None)

        self._log("Phase: planner")
        planner_exec = self.phase_client.run(
            ExecutionRequest(
                provider=self.config.provider,
                codex_bin=self.config.codex_bin,
                model=self.config.model,
                prompt=planner_prompt(
                    task,
                    mind_map_text=mind_map_text,
                    conversation_context=self.config.conversation_context,
                ),
                schema=planner_schema(),
                repo_path=self.config.repo_path,
                extra_access_dir=self.config.extra_access_dir,
                ollama_host=self.config.ollama_host,
                dry_run=self.config.dry_run,
                timeout_seconds=self.config.phase_timeout_seconds,
                phase_name="planner",
            )
        )
        if self.config.dry_run:
            planner_payload = {
                "assumptions": ["dry run with single synthetic step"],
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Dry run placeholder",
                        "instructions": "No-op",
                        "done_criteria": ["No-op complete"],
                        "dependencies": [],
                    }
                ],
            }
        else:
            planner_payload = planner_exec.payload
            self.store.write_text("planner/events.jsonl", planner_exec.raw_jsonl)

        planner = parse_planner_result(planner_payload)
        self.store.write_json("planner/result.json", planner_payload)
        self._log(f"Planner produced {len(planner.steps)} step(s)")
        if self._should_stop():
            return self._stopped_outcome([], planner)

        step_runs: list[StepRun] = []
        prior_feedback: str | None = None
        for step in planner.steps:
            completed_step = False
            for attempt in range(1, self.config.max_step_retries + 2):
                if self._should_stop():
                    return self._stopped_outcome(step_runs, planner)
                self._log(f"Step {step.id} attempt {attempt}: builder")
                build_exec = self.phase_client.run(
                    ExecutionRequest(
                        provider=self.config.provider,
                        codex_bin=self.config.codex_bin,
                        model=self.config.model,
                        prompt=builder_prompt(
                            task,
                            step,
                            prior_feedback,
                            mind_map_text=mind_map_text,
                            conversation_context=self.config.conversation_context,
                        ),
                        schema=builder_schema(),
                        repo_path=self.config.repo_path,
                        extra_access_dir=self.config.extra_access_dir,
                        ollama_host=self.config.ollama_host,
                        dry_run=self.config.dry_run,
                        timeout_seconds=self.config.phase_timeout_seconds,
                        phase_name=f"builder ({step.id} attempt {attempt})",
                    )
                )
                if self.config.dry_run:
                    build_payload = {
                        "status": "ok",
                        "summary": "dry-run build",
                        "files_touched": [],
                        "commands_run": [],
                        "notes": [],
                    }
                else:
                    build_payload = build_exec.payload
                    self.store.write_text(f"steps/{step.id}/attempt-{attempt}/builder-events.jsonl", build_exec.raw_jsonl)
                build_result = parse_builder_result(build_payload)
                if self._should_stop():
                    run_record = StepRun(
                        step_id=step.id,
                        attempt=attempt,
                        build_result=build_result,
                        check_results=[],
                        review_result=parse_reviewer_result(
                            {
                                "verdict": "stopped",
                                "task_complete": False,
                                "step_complete": False,
                                "issues": [],
                                "guidance": "Run stopped by user.",
                            }
                        ),
                    )
                    step_runs.append(run_record)
                    return self._stopped_outcome(step_runs, planner)

                check_results = run_checks(check_cmds, self.config.repo_path) if check_cmds else []
                if check_results:
                    self._log(
                        "Checks: "
                        + ", ".join(f"{c.command}={'ok' if c.ok else 'fail'}" for c in check_results)
                    )
                if self._should_stop():
                    return self._stopped_outcome(step_runs, planner)

                self._log(f"Step {step.id} attempt {attempt}: reviewer")
                reviewer_exec = self.phase_client.run(
                    ExecutionRequest(
                        provider=self.config.provider,
                        codex_bin=self.config.codex_bin,
                        model=self.config.model,
                        prompt=reviewer_prompt(
                            task,
                            step,
                            build_result,
                            check_results,
                            mind_map_text=mind_map_text,
                            conversation_context=self.config.conversation_context,
                        ),
                        schema=reviewer_schema(),
                        repo_path=self.config.repo_path,
                        extra_access_dir=self.config.extra_access_dir,
                        ollama_host=self.config.ollama_host,
                        dry_run=self.config.dry_run,
                        timeout_seconds=self.config.phase_timeout_seconds,
                        phase_name=f"reviewer ({step.id} attempt {attempt})",
                    )
                )
                if self.config.dry_run:
                    reviewer_payload = {
                        "verdict": "pass",
                        "task_complete": True,
                        "step_complete": True,
                        "issues": [],
                        "guidance": "dry-run",
                    }
                else:
                    reviewer_payload = reviewer_exec.payload
                    self.store.write_text(
                        f"steps/{step.id}/attempt-{attempt}/reviewer-events.jsonl",
                        reviewer_exec.raw_jsonl,
                    )
                review_result = parse_reviewer_result(reviewer_payload)

                run_record = StepRun(
                    step_id=step.id,
                    attempt=attempt,
                    build_result=build_result,
                    check_results=check_results,
                    review_result=review_result,
                )
                step_runs.append(run_record)

                attempt_path = f"steps/{step.id}/attempt-{attempt}"
                self.store.write_json(f"{attempt_path}/build.json", build_payload)
                self.store.write_json(f"{attempt_path}/review.json", reviewer_payload)
                self.store.write_json(
                    f"{attempt_path}/checks.json",
                    [
                        {
                            "command": c.command,
                            "return_code": c.return_code,
                            "stdout": c.stdout,
                            "stderr": c.stderr,
                            "ok": c.ok,
                        }
                        for c in check_results
                    ],
                )

                checks_ok = all(c.ok for c in check_results) if check_results else True
                if review_result.step_complete and checks_ok:
                    self._log(f"Step {step.id} complete")
                    completed_step = True
                    prior_feedback = None
                    break
                self._log(f"Step {step.id} needs retry: {review_result.guidance}")
                prior_feedback = "\n".join(review_result.issues + [review_result.guidance]).strip()

            if not completed_step:
                final_message = self._compose_failure_message(step_runs)
                outcome = RunOutcome(
                    ok=False,
                    reason=f"Step '{step.id}' failed after retries.",
                    step_runs=step_runs,
                    planner_result=planner,
                    final_message=final_message,
                )
                self.store.write_json("final_outcome.json", outcome)
                self._log(f"Final message: {outcome.final_message}")
                return outcome

        last_review = step_runs[-1].review_result if step_runs else None
        task_complete = bool(last_review and last_review.task_complete)
        final_message = self._compose_success_message(step_runs, task_complete)
        outcome = RunOutcome(
            ok=task_complete,
            reason="success" if task_complete else "Reviewer did not mark task complete.",
            step_runs=step_runs,
            planner_result=planner,
            final_message=final_message,
        )
        self.store.write_json("final_outcome.json", outcome)
        self._log(f"Run finished: {outcome.reason}")
        self._log(f"Final message: {outcome.final_message}")
        return outcome

    def _should_stop(self) -> bool:
        return bool(self.config.stop_requested and self.config.stop_requested())

    def _stopped_outcome(self, step_runs: list[StepRun], planner) -> RunOutcome:
        outcome = RunOutcome(
            ok=False,
            reason="Stopped by user.",
            step_runs=step_runs,
            planner_result=planner,
            final_message="Run stopped safely. You can continue from this workspace when ready.",
        )
        self.store.write_json("final_outcome.json", outcome)
        self._log("Run finished: stopped")
        self._log(f"Final message: {outcome.final_message}")
        return outcome

    def _log(self, message: str) -> None:
        if self.config.status_callback:
            self.config.status_callback(message)
        if self.config.progress:
            print(f"[agent-runner] {message}", file=sys.stderr)

    def _compose_success_message(self, step_runs: list[StepRun], task_complete: bool) -> str:
        if not step_runs:
            return "No execution steps were produced."
        last = step_runs[-1]
        if task_complete:
            base = (last.build_result.summary or "").strip() or "Task completed successfully."
            return base
        guidance = (last.review_result.guidance or "").strip()
        if guidance:
            return guidance
        return "Run finished without a reviewer-confirmed completion."

    def _compose_failure_message(self, step_runs: list[StepRun]) -> str:
        if not step_runs:
            return "Run failed before any step execution."
        last = step_runs[-1]
        issues = [i.strip() for i in last.review_result.issues if i.strip()]
        guidance = (last.review_result.guidance or "").strip()
        if issues and guidance:
            return f"{'; '.join(issues)}. Next: {guidance}"
        if issues:
            return "; ".join(issues)
        if guidance:
            return guidance
        return "Step failed after retries."
