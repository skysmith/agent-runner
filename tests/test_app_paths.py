from __future__ import annotations

from pathlib import Path

from agent_runner.app_paths import resolve_runtime_paths


def test_resolve_runtime_paths_dev_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AGENT_RUNNER_PACKAGED", raising=False)
    monkeypatch.setattr("agent_runner.app_paths.sys.frozen", False, raising=False)

    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True)
    paths = resolve_runtime_paths(repo_path=repo_path, artifacts_dir=Path(".agent-runner"))

    assert paths.packaged_mode is False
    assert paths.repo_path == repo_path.resolve()
    assert paths.artifacts_dir == (repo_path / ".agent-runner").resolve()
    assert paths.settings_path == (repo_path / ".agent-runner" / "app-settings.json").resolve()


def test_resolve_runtime_paths_packaged_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_RUNNER_PACKAGED", "1")
    monkeypatch.setattr("agent_runner.app_paths.Path.home", lambda: tmp_path)

    repo_path = tmp_path / "project"
    repo_path.mkdir(parents=True)
    paths = resolve_runtime_paths(repo_path=repo_path, artifacts_dir=Path(".agent-runner"))

    assert paths.packaged_mode is True
    assert paths.repo_path == repo_path.resolve()
    assert paths.artifacts_dir == (tmp_path / "Library" / "Application Support" / "agent-runner" / "artifacts").resolve()
    assert paths.settings_path == (tmp_path / "Library" / "Application Support" / "agent-runner" / "app-settings.json").resolve()
