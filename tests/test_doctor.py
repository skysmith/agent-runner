from __future__ import annotations

import subprocess
from pathlib import Path

from agent_runner.doctor import render_doctor_report, run_doctor


def test_run_doctor_reports_success(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr("agent_runner.doctor.resolve_executable_path", lambda name: f"/usr/local/bin/{name}")

    def fake_run(*args, **kwargs):
        captured["args"] = args[0]
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="Logged in with ChatGPT\n",
            stderr="",
        )

    monkeypatch.setattr(
        "agent_runner.doctor.subprocess.run",
        fake_run,
    )

    report = run_doctor(repo_path=tmp_path)

    assert report.ok is True
    assert captured["args"] == ["/usr/local/bin/codex", "login", "status"]
    rendered = render_doctor_report(report)
    assert "[PASS] Codex CLI" in rendered
    assert "Next: `alcove web`" in rendered


def test_run_doctor_reports_missing_codex(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agent_runner.doctor.resolve_executable_path", lambda name: None)

    report = run_doctor(repo_path=tmp_path)

    assert report.ok is False
    rendered = render_doctor_report(report)
    assert "[FAIL] Codex CLI" in rendered
    assert "Install Codex CLI" in rendered
    assert "Fix the failed checks above" in rendered


def test_run_doctor_reports_login_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agent_runner.doctor.resolve_executable_path", lambda name: f"/usr/local/bin/{name}")
    monkeypatch.setattr(
        "agent_runner.doctor.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="",
            stderr="Not logged in\n",
        ),
    )

    report = run_doctor(repo_path=tmp_path)

    assert report.ok is False
    rendered = render_doctor_report(report)
    assert "[FAIL] Codex authentication" in rendered
    assert "Run `codex login`" in rendered
