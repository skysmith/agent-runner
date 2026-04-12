from __future__ import annotations

import pytest

from agent_runner.cli import _require_password_for_public_bind, build_parser


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
