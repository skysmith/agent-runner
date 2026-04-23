from __future__ import annotations

import subprocess
from pathlib import Path

from agent_runner.server_info import detect_tailscale_serve_url, server_info


def test_server_info_prefers_tailscale_serve_url_for_localhost_bind(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agent_runner.server_info.detect_lan_ip", lambda: "192.168.0.10")
    monkeypatch.setattr("agent_runner.server_info.detect_tailscale_ip", lambda: "100.125.227.124")
    monkeypatch.setattr(
        "agent_runner.server_info.detect_tailscale_serve_url",
        lambda port: "https://demo.tailnet.ts.net" if port == 8765 else None,
    )

    payload = server_info("127.0.0.1", 8765, repo_path=tmp_path)

    assert payload["localhost_only"] is True
    assert payload["lan_url"] is None
    assert payload["tailscale_url"] == "https://demo.tailnet.ts.net"
    assert payload["reachable_urls"] == [
        "http://127.0.0.1:8765",
        "https://demo.tailnet.ts.net",
    ]


def test_server_info_falls_back_to_tailscale_ip_for_public_bind(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agent_runner.server_info.detect_lan_ip", lambda: "192.168.0.10")
    monkeypatch.setattr("agent_runner.server_info.detect_tailscale_ip", lambda: "100.125.227.124")
    monkeypatch.setattr("agent_runner.server_info.detect_tailscale_serve_url", lambda port: None)

    payload = server_info("0.0.0.0", 8765, repo_path=tmp_path)

    assert payload["localhost_only"] is False
    assert payload["lan_url"] == "http://192.168.0.10:8765"
    assert payload["tailscale_url"] == "http://100.125.227.124:8765"
    assert payload["reachable_urls"] == [
        "http://127.0.0.1:8765",
        "http://192.168.0.10:8765",
        "http://100.125.227.124:8765",
    ]


def test_detect_tailscale_serve_url_matches_proxy_port(monkeypatch) -> None:
    monkeypatch.setattr("agent_runner.server_info.shutil.which", lambda name: "/usr/local/bin/tailscale")

    def fake_run(args, *, text, capture_output, check, timeout):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                "https://skys-macbook-pro.tail988b22.ts.net (tailnet only)\n"
                "|-- / proxy http://127.0.0.1:8765\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("agent_runner.server_info.subprocess.run", fake_run)

    assert detect_tailscale_serve_url(8765) == "https://skys-macbook-pro.tail988b22.ts.net"
    assert detect_tailscale_serve_url(8766) is None
