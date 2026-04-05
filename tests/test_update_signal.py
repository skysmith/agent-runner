from __future__ import annotations

import subprocess
from pathlib import Path

from agent_runner.update_signal import CommitUpdateSignal, read_build_label, read_worktree_token


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


def test_read_build_label_includes_local_token_when_dirty(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("changed\n")
    label = read_build_label(tmp_path)
    assert label is not None
    assert len(label) == 3
    assert label.isalnum()


def test_read_build_label_returns_build_number_when_clean(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    assert read_build_label(tmp_path) == "1"


def test_read_worktree_token_none_when_clean(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    assert read_worktree_token(tmp_path) is None


def _init_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Codex"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "codex@example.com"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("test repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
