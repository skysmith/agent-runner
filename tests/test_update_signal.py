from __future__ import annotations

from pathlib import Path

from agent_runner.update_signal import CommitUpdateSignal


def test_commit_update_signal_no_badge_when_head_unchanged() -> None:
    calls: list[str] = []

    def fake_read_head(_: Path) -> str | None:
        calls.append("called")
        return "abc123"

    signal = CommitUpdateSignal(repo_path=Path("."), read_head=fake_read_head)
    assert signal.poll() is False
    assert signal.poll() is False
    assert len(calls) >= 3


def test_commit_update_signal_detects_new_commit() -> None:
    heads = iter(["abc123", "abc123", "def456"])

    def fake_read_head(_: Path) -> str | None:
        return next(heads)

    signal = CommitUpdateSignal(repo_path=Path("."), read_head=fake_read_head)
    assert signal.poll() is False
    assert signal.poll() is True
    assert signal.poll() is True


def test_commit_update_signal_handles_missing_head() -> None:
    heads = iter([None, "def456", "ghi789"])

    def fake_read_head(_: Path) -> str | None:
        return next(heads)

    signal = CommitUpdateSignal(repo_path=Path("."), read_head=fake_read_head)
    assert signal.poll() is False
    assert signal.poll() is False
