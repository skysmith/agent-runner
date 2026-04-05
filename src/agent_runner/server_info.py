from __future__ import annotations

import socket
import subprocess
import shutil
from typing import Any


def server_info(bind_host: str, bind_port: int) -> dict[str, Any]:
    localhost_url = f"http://127.0.0.1:{bind_port}"
    host_text = bind_host.strip() or "0.0.0.0"
    localhost_only = is_localhost_bind(host_text)
    lan_ip = detect_lan_ip()
    lan_url = f"http://{lan_ip}:{bind_port}" if lan_ip else None
    tailscale_ip = detect_tailscale_ip()
    tailscale_url = f"http://{tailscale_ip}:{bind_port}" if tailscale_ip else None

    reachable = [localhost_url]
    if not localhost_only and lan_url:
        reachable.append(lan_url)
    if not localhost_only and tailscale_url and tailscale_url not in reachable:
        reachable.append(tailscale_url)

    return {
        "bind_host": host_text,
        "bind_port": bind_port,
        "localhost_url": localhost_url,
        "lan_url": None if localhost_only else lan_url,
        "tailscale_url": None if localhost_only else tailscale_url,
        "localhost_only": localhost_only,
        "reachable_urls": reachable,
    }


def is_localhost_bind(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def detect_lan_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()

    if not ip or ip.startswith("127."):
        return None
    return ip


def detect_tailscale_ip() -> str | None:
    tailscale_bin = shutil.which("tailscale")
    if not tailscale_bin:
        return None
    try:
        proc = subprocess.run(
            [tailscale_bin, "ip", "-4"],
            text=True,
            capture_output=True,
            check=False,
            timeout=1.5,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("100."):
            return text
    return None
