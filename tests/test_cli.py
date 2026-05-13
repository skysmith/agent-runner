from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_runner.cli import _load_env_defaults, _require_password_for_public_bind, build_parser
from agent_runner.models import AppSettings
from agent_runner.settings_store import load_app_settings, save_app_settings


def test_serve_defaults_to_network_bind() -> None:
    args = build_parser().parse_args(["serve"])
    assert args.host == "0.0.0.0"


def test_web_defaults_to_localhost_bind() -> None:
    args = build_parser().parse_args(["web"])
    assert args.host == "127.0.0.1"


def test_web_accepts_password_flag() -> None:
    args = build_parser().parse_args(["web", "--password", "secret"])
    assert args.password == "secret"


def test_public_bind_requires_password() -> None:
    with pytest.raises(ValueError, match="requires --password whenever --host is not localhost"):
        _require_password_for_public_bind(
            host="0.0.0.0",
            password=None,
            command="alcove serve",
        )


def test_localhost_bind_does_not_require_password() -> None:
    _require_password_for_public_bind(
        host="127.0.0.1",
        password=None,
        command="alcove serve",
    )


def test_public_bind_allows_password() -> None:
    _require_password_for_public_bind(
        host="0.0.0.0",
        password="secret",
        command="alcove serve",
    )


def test_doctor_uses_current_directory_by_default() -> None:
    args = build_parser().parse_args(["doctor"])
    assert args.codex_bin == "codex"


def test_arcade_accepts_repo_override() -> None:
    args = build_parser().parse_args(["arcade", "--repo", "/tmp/example"])
    assert str(args.repo) == "/tmp/example"


def test_load_env_defaults_reads_repo_env_local(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ALCOVE_REALTIME_VOICE", raising=False)
    (tmp_path / ".env.local").write_text(
        "OPENAI_API_KEY=sk-local-test\nexport ALCOVE_REALTIME_VOICE='marin'\n",
        encoding="utf-8",
    )

    _load_env_defaults(repo=tmp_path)

    assert os.environ["OPENAI_API_KEY"] == "sk-local-test"
    assert os.environ["ALCOVE_REALTIME_VOICE"] == "marin"


def test_load_env_defaults_does_not_override_existing_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-existing-test")
    (tmp_path / ".env.local").write_text("OPENAI_API_KEY=sk-local-test\n", encoding="utf-8")

    _load_env_defaults(repo=tmp_path)

    assert os.environ["OPENAI_API_KEY"] == "sk-existing-test"


def test_resolve_arcade_launch_context_prefers_installed_wrapper_state(monkeypatch, tmp_path) -> None:
    wrapper_root = tmp_path / "wrapper"
    wrapper_root.mkdir()
    (wrapper_root / "wrapper-runtime.json").write_text("{}", encoding="utf-8")
    runtime_repo = tmp_path / "lab" / "scratchpad" / "agent-runner-fresh-onboarding"
    runtime_repo.mkdir(parents=True)

    monkeypatch.setattr("agent_runner.cli.app_support_dir", lambda: wrapper_root)
    monkeypatch.setattr("agent_runner.cli.wrapper_state_path", lambda root: root / "wrapper-runtime.json")
    monkeypatch.setattr(
        "agent_runner.cli.load_wrapper_state",
        lambda root: {
            "repo_path": str(runtime_repo),
            "server_info": {"bind_port": 9988},
        },
    )
    monkeypatch.setattr(
        "agent_runner.cli.resolve_runtime_paths",
        lambda repo_path, artifacts_dir: type(
            "RuntimePaths",
            (),
            {
                "repo_path": tmp_path / "fallback-repo",
                "settings_path": tmp_path / "fallback-repo" / ".agent-runner" / "app-settings.json",
            },
        )(),
    )
    monkeypatch.setattr("agent_runner.cli.resolve_wrapper_password", lambda repo_path, explicit_password: "pw")

    resolved_repo, state_root, port, password = _require_arcade_context_helper()

    assert resolved_repo == runtime_repo
    assert state_root == wrapper_root
    assert port == 9988
    assert password == "pw"


def test_app_settings_round_trip_arcade_repo_path(tmp_path: Path) -> None:
    settings_path = tmp_path / "app-settings.json"
    settings = AppSettings(arcade_repo_path=Path("/tmp/arcade"))

    save_app_settings(settings_path, settings)
    loaded = load_app_settings(settings_path, AppSettings())

    assert loaded.arcade_repo_path == Path("/tmp/arcade")


def _require_arcade_context_helper():
    from agent_runner.cli import _resolve_arcade_launch_context

    return _resolve_arcade_launch_context(
        repo=None,
        artifacts_dir=Path(".agent-runner"),
        port=None,
        password=None,
    )
