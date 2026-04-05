from __future__ import annotations

from agent_runner.cli import build_parser


def test_serve_defaults_to_network_bind() -> None:
    args = build_parser().parse_args(["serve"])
    assert args.host == "0.0.0.0"


def test_web_defaults_to_localhost_bind() -> None:
    args = build_parser().parse_args(["web"])
    assert args.host == "127.0.0.1"


def test_web_accepts_password_flag() -> None:
    args = build_parser().parse_args(["web", "--password", "secret"])
    assert args.password == "secret"
