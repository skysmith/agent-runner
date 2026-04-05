from __future__ import annotations

import json
import base64
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import time
from threading import Event
from pathlib import Path

from agent_runner.codex_client import CodexExecResult
from agent_runner.http_api import create_server
from agent_runner.models import ProviderKind
from agent_runner.service import AgentRunnerService, ServiceConfig


class FakePhaseClient:
    def run(self, request) -> CodexExecResult:
        return CodexExecResult(
            payload={"message": "API reply"},
            raw_jsonl="",
            stderr="",
            return_code=0,
        )


class GatePhaseClient:
    def __init__(self, gate: Event):
        self.gate = gate

    def run(self, request) -> CodexExecResult:
        self.gate.wait(timeout=2)
        return CodexExecResult(
            payload={"message": "API reply"},
            raw_jsonl="",
            stderr="",
            return_code=0,
        )


def test_api_lists_workspaces_and_posts_message(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    created = service.create_conversation("workspace-1", title="Daily thread")
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"

        workspaces = _get_json(f"{base}/api/workspaces")
        assert workspaces["workspaces"][0]["id"] == "workspace-1"
        server_info = _get_json(f"{base}/api/server-info")
        assert server_info["localhost_url"].startswith("http://127.0.0.1:")
        assert server_info["server_kind"] == "agent_runner_web"
        assert server_info["repo_path"] == str(tmp_path.resolve())

        response = _post_json(
            f"{base}/api/conversations/{created['id']}/messages",
            {"content": "Ping from phone", "mode": "message", "workspace_id": "workspace-1"},
        )
        assert response["accepted"] is True

        conversation = _get_json(f"{base}/api/conversations/{created['id']}?workspace_id=workspace-1")
        assert conversation["messages"][0]["role"] == "user"
        _wait_for(lambda: _get_json(f"{base}/api/run-status")["state"] in {"succeeded", "failed"})

        retry = _post_json(f"{base}/api/runs/retry-last", {})
        assert retry["accepted"] is True

        all_conversations = _get_json(f"{base}/api/conversations")
        assert created["id"] in [conversation["id"] for conversation in all_conversations["conversations"]]
    finally:
        server.shutdown()
        server.server_close()


def test_mobile_routes_render(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    created = service.create_conversation("workspace-1", title="Phone thread")
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        response = urllib.request.urlopen(
            f"{base}/m/conversations/{created['id']}?workspace_id=workspace-1"
        ).read().decode("utf-8")
        assert "Type into the same thread from your phone" in response
        assert "window.setInterval(() => window.location.reload(), 5000);" not in response
    finally:
        server.shutdown()
        server.server_close()


def test_root_route_renders_desktop_web_app(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    service.create_conversation("workspace-1", title="Desktop thread")
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        response = urllib.request.urlopen(base).read().decode("utf-8")
        assert "<!doctype html>" in response.lower()
        assert "settings-modal" in response
        assert "menu-button" in response
        assert "/api/conversations" in response
        assert "build-badge" in response
    finally:
        server.shutdown()
        server.server_close()


def test_workspace_define_and_active_repositories_endpoints(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    repo = tmp_path / "finance-dashboard"
    _init_git_repo(repo)
    service = _make_service(tmp_path)
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        created = _post_json(
            f"{base}/api/workspaces",
            {
                "id": "personal-finance-dashboard",
                "display_name": "Personal Finance Dashboard",
                "repo_path": str(repo),
            },
        )
        assert created["id"] == "personal-finance-dashboard"
        assert created["display_name"] == "Personal Finance Dashboard"
        assert created["repo_path"] == str(repo)

        active = _get_json(
            f"{base}/api/repositories/active?root={urllib.parse.quote(str(tmp_path))}&limit=5"
        )
        assert isinstance(active["repositories"], list)
        assert any(item["repo_path"] == str(repo) for item in active["repositories"])
    finally:
        server.shutdown()
        server.server_close()


def test_studio_game_endpoints_create_preview_and_publish(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        created = _post_json(
            f"{base}/api/studio/games",
            {
                "game_title": "Moon Mango Jump",
                "template_kind": "platformer",
                "theme_prompt": "A playful moonlit jungle.",
            },
        )
        workspace = created["workspace"]
        assert workspace["workspace_kind"] == "studio_game"
        studio = _get_json(f"{base}/api/workspaces/{workspace['id']}/studio")
        assert studio["workspace"]["template_kind"] == "platformer"
        preview_html = urllib.request.urlopen(f"{base}{workspace['preview_url']}").read().decode("utf-8")
        assert "Alcove Studio" in preview_html
        published = _post_json(f"{base}/api/workspaces/{workspace['id']}/studio/publish", {})
        assert published["publish_state"] == "published"
        public_html = urllib.request.urlopen(f"{base}{published['publish_url']}").read().decode("utf-8")
        assert "Moon Mango Jump" in public_html
    finally:
        server.shutdown()
        server.server_close()


def test_generic_studio_endpoints_create_web_data_and_docs_workspaces(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"

        web = _post_json(
            f"{base}/api/studio/workspaces",
            {
                "workspace_kind": "studio_web",
                "artifact_title": "Northstar Site",
                "template_kind": "landing-page",
                "theme_prompt": "A calm premium launch page.",
            },
        )["workspace"]
        assert web["workspace_kind"] == "studio_web"
        assert web["artifact_title"] == "Northstar Site"
        web_html = urllib.request.urlopen(f"{base}{web['preview_url']}").read().decode("utf-8")
        assert "Game Studio" not in web_html
        assert "Web Studio" in web_html

        data = _post_json(
            f"{base}/api/studio/workspaces",
            {
                "workspace_kind": "studio_data",
                "artifact_title": "Revenue Atlas",
                "template_kind": "dashboard",
            },
        )["workspace"]
        data_html = urllib.request.urlopen(f"{base}{data['preview_url']}").read().decode("utf-8")
        assert "Data Studio" in data_html

        docs = _post_json(
            f"{base}/api/studio/workspaces",
            {
                "workspace_kind": "studio_docs",
                "artifact_title": "Northstar Docs",
                "template_kind": "docs-site",
            },
        )["workspace"]
        docs_html = urllib.request.urlopen(f"{base}{docs['preview_url']}").read().decode("utf-8")
        assert "Docs Studio" in docs_html
    finally:
        server.shutdown()
        server.server_close()


def test_preview_rewrites_absolute_dist_asset_paths_for_imported_vite_projects(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    imported_repo = tmp_path / "gnome-roundup"
    dist = imported_repo / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><script type="module" src="/assets/app.js"></script><link rel="stylesheet" href="/assets/app.css">',
        encoding="utf-8",
    )
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (assets / "app.css").write_text("body{}", encoding="utf-8")

    service = _make_service(tmp_path)
    service.define_workspace(
        "gnome-roundup",
        display_name="Gnome Roundup",
        repo_path=str(imported_repo),
        workspace_kind="studio_game",
        artifact_title="Gnome Roundup",
        template_kind="phaser-vite",
        preview_url="/studio/preview/gnome-roundup/dist/index.html",
        preview_state="ready",
        publish_state="draft",
    )
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        preview_html = urllib.request.urlopen(f"{base}/studio/preview/gnome-roundup/dist/index.html").read().decode("utf-8")
        assert 'src="./assets/app.js"' in preview_html
        assert 'href="./assets/app.css"' in preview_html
    finally:
        server.shutdown()
        server.server_close()


def test_settings_and_ollama_models_endpoints(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        settings = _get_json(f"{base}/api/settings")
        assert settings["provider"] in {"codex", "ollama"}
        updated = _patch_json(
            f"{base}/api/settings",
            {
                "provider": "ollama",
                "model": "llama3.1:8b",
                "planner_model": "qwen2.5:7b",
                "builder_model": "qwen2.5-coder:7b",
                "reviewer_model": "llama3.1:8b",
                "max_step_retries": 3,
                "phase_timeout_seconds": 180,
            },
        )
        assert updated["provider"] == "ollama"
        assert updated["model"] == "llama3.1:8b"
        assert updated["planner_model"] == "qwen2.5:7b"
        models = _get_json(f"{base}/api/providers/ollama/models")
        assert "available" in models and "models" in models and "message" in models
    finally:
        server.shutdown()
        server.server_close()


def test_mobile_route_returns_html_error_page_on_unexpected_error(tmp_path: Path) -> None:
    class BrokenService:
        def list_workspaces(self):
            raise AttributeError("boom")

    server = create_server(BrokenService(), "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            urllib.request.urlopen(f"{base}/m")
        except urllib.error.HTTPError as exc:
            assert exc.code == 500
            body = exc.read().decode("utf-8")
            assert "Something went wrong" in body
            assert "boom" in body
        else:
            raise AssertionError("Expected companion route to return 500")
    finally:
        server.shutdown()
        server.server_close()


def test_recover_endpoint_rejects_when_run_active(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    gate = Event()
    service = _make_service(tmp_path, phase_client=GatePhaseClient(gate))
    created = service.create_conversation("workspace-1", title="Busy thread")
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        _post_json(
            f"{base}/api/conversations/{created['id']}/messages",
            {"content": "Keep running", "mode": "message", "workspace_id": "workspace-1"},
        )
        _wait_for(lambda: _get_json(f"{base}/api/run-status")["state"] in {"starting", "running", "stopping"})

        request = urllib.request.Request(
            f"{base}/api/runs/recover",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request)
        except urllib.error.HTTPError as exc:
            assert exc.code == 409
            payload = json.loads(exc.read().decode("utf-8"))
            assert "Run is active" in payload.get("detail", "")
        else:
            raise AssertionError("Expected recover endpoint to return 409 while active")
    finally:
        gate.set()
        server.shutdown()
        server.server_close()


def test_events_endpoint_returns_append_only_items(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    created = service.create_conversation("workspace-1", title="Events thread")
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        _post_json(
            f"{base}/api/conversations/{created['id']}/messages",
            {"content": "event ping", "mode": "message", "workspace_id": "workspace-1"},
        )
        _wait_for(lambda: _get_json(f"{base}/api/run-status")["state"] in {"succeeded", "failed"})

        first = _get_json(f"{base}/api/events/since?cursor=0&limit=5")
        assert "events" in first
        assert "next_cursor" in first
        assert isinstance(first["events"], list)
        if first["events"]:
            assert "id" in first["events"][-1]
            follow = _get_json(f"{base}/api/events/since?cursor={first['next_cursor']}&limit=5")
            assert isinstance(follow["events"], list)
    finally:
        server.shutdown()
        server.server_close()


def test_message_endpoint_accepts_multipart_screenshot_upload(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    created = service.create_conversation("workspace-1", title="Screenshot thread")
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        payload = {
            "content": "Please inspect this",
            "mode": "message",
            "workspace_id": "workspace-1",
        }
        files = [
            (
                "attachments",
                "screen.png",
                "image/png",
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00",
            )
        ]
        response = _post_multipart(
            f"{base}/api/conversations/{created['id']}/messages",
            fields=payload,
            files=files,
        )
        assert response["accepted"] is True
        conversation = _get_json(f"{base}/api/conversations/{created['id']}?workspace_id=workspace-1")
        message = conversation["messages"][0]["content"]
        assert "Please inspect this" in message
        assert "Attached screenshot files (local paths):" in message
        assert "/.agent-runner/uploads/workspace-1/" in message
        uploads_dir = tmp_path / ".agent-runner" / "uploads" / "workspace-1" / created["id"]
        assert uploads_dir.exists()
        assert len(list(uploads_dir.glob("*"))) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_clear_chat_endpoint_resets_messages(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    created = service.create_conversation("workspace-1", title="Clearable thread")
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        _post_json(
            f"{base}/api/conversations/{created['id']}/messages",
            {"content": "Need to reset context", "mode": "message", "workspace_id": "workspace-1"},
        )
        _wait_for(lambda: _get_json(f"{base}/api/run-status")["state"] in {"succeeded", "failed"})
        cleared = _post_json(
            f"{base}/api/conversations/{created['id']}/clear",
            {"workspace_id": "workspace-1"},
        )
        assert cleared["id"] == created["id"]
        assert cleared["messages"] == []
        conversation = _get_json(f"{base}/api/conversations/{created['id']}?workspace_id=workspace-1")
        assert conversation["messages"] == []
    finally:
        server.shutdown()
        server.server_close()


def test_password_protected_server_requires_basic_auth(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    server = create_server(service, "127.0.0.1", 0, access_password="jungleboogie")
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"

        try:
            urllib.request.urlopen(f"{base}/api/run-status")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("Expected 401 without auth")

        token = base64.b64encode(b"phone:jungleboogie").decode("ascii")
        req = urllib.request.Request(
            f"{base}/api/run-status",
            headers={"Authorization": f"Basic {token}"},
        )
        with urllib.request.urlopen(req) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert "state" in payload
        req = urllib.request.Request(
            f"{base}/api/server-info",
            headers={"Authorization": f"Basic {token}"},
        )
        with urllib.request.urlopen(req) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["build_label"] == "1"
        assert payload["server_kind"] == "agent_runner_web"
    finally:
        server.shutdown()
        server.server_close()


def test_server_info_includes_local_token_when_repo_dirty(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("dirty\n")
    service = _make_service(tmp_path)
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        payload = _get_json(f"{base}/api/server-info")
        assert len(payload["build_label"]) == 3
        assert payload["repo_name"] == tmp_path.name
    finally:
        server.shutdown()
        server.server_close()


def test_connections_endpoint_reports_local_url_and_phone_unavailable_by_default(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        payload = _get_json(f"{base}/api/connections")
        assert payload["local_url"].startswith("http://127.0.0.1:")
        assert payload["phone_enabled"] is False
        assert payload["phone_url"] is None
    finally:
        server.shutdown()
        server.server_close()


def test_phone_qr_endpoint_returns_svg_when_tailscale_phone_url_available(tmp_path: Path, monkeypatch) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    monkeypatch.setattr(
        "agent_runner.http_api.server_info",
        lambda host, port, repo_path=None, build_label=None: {
            "server_kind": "agent_runner_web",
            "bind_host": host,
            "bind_port": port,
            "localhost_url": f"http://127.0.0.1:{port}",
            "lan_url": None,
            "tailscale_url": f"http://demo-tailnet.ts.net:{port}",
            "localhost_only": False,
            "reachable_urls": [f"http://127.0.0.1:{port}", f"http://demo-tailnet.ts.net:{port}"],
            "repo_path": str(repo_path) if repo_path is not None else None,
            "repo_name": tmp_path.name,
            "build_label": build_label,
        },
    )
    server = create_server(service, "0.0.0.0", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(f"{base}/api/connections/phone-qr.svg") as response:
            body = response.read().decode("utf-8")
            content_type = response.headers["Content-Type"]
        assert "image/svg+xml" in content_type
        assert "<svg" in body
    finally:
        server.shutdown()
        server.server_close()


def test_context_endpoint_updates_assistant_mode_and_page_context(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    created = service.create_conversation("workspace-1", title="Context thread")
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        request = urllib.request.Request(
            f"{base}/api/conversations/{created['id']}/context",
            data=json.dumps(
                {
                    "workspace_id": "workspace-1",
                    "assistant_mode": "ops",
                    "page_context": {"route": "/finance/inventory", "filters": {"window": "7d"}},
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["assistant_mode"] == "ops"
        assert payload["page_context"]["route"] == "/finance/inventory"
        assert payload["page_context"]["adapter"] == "inventory"

        context = _get_json(
            f"{base}/api/conversations/{created['id']}/context?workspace_id=workspace-1"
        )
        assert context["assistant_mode"] == "ops"
        assert context["page_context"]["filters"]["window"] == "7d"
    finally:
        server.shutdown()
        server.server_close()


def test_message_endpoint_rejects_loop_mode_without_dev_capability(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    created = service.create_conversation("workspace-1", title="Guarded thread")
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        request = urllib.request.Request(
            f"{base}/api/conversations/{created['id']}/messages",
            data=json.dumps(
                {
                    "workspace_id": "workspace-1",
                    "assistant_mode": "ask",
                    "mode": "loop",
                    "content": "attempt blocked loop",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request)
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            payload = json.loads(exc.read().decode("utf-8"))
            assert "requires dev assistant capability mode" in payload["detail"].lower()
        else:
            raise AssertionError("Expected loop mode request to be rejected in ask mode")
    finally:
        server.shutdown()
        server.server_close()


def _init_git_repo(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Codex"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "codex@example.com"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("test repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)


def _make_service(tmp_path: Path, phase_client=None) -> AgentRunnerService:
    return AgentRunnerService(
        ServiceConfig(
            repo_path=tmp_path,
            artifacts_dir=tmp_path / ".agent-runner",
            settings_path=tmp_path / ".agent-runner" / "app-settings.json",
            provider=ProviderKind.CODEX,
            codex_bin="codex",
            model="gpt-5.3-codex",
            ollama_host="http://127.0.0.1:11434",
            extra_access_dir=None,
            max_step_retries=2,
            phase_timeout_seconds=10,
            check_commands=[],
            dry_run=False,
        ),
        phase_client=phase_client or FakePhaseClient(),
    )


def _start(server) -> None:
    import threading
    import time

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def _patch_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_multipart(url: str, *, fields: dict[str, str], files: list[tuple[str, str, str, bytes]]) -> dict:
    boundary = "----agent-runner-test-boundary"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for field_name, filename, mime, data in files:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {mime}\r\n\r\n".encode("utf-8"),
                data,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for condition")
