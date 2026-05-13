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

import agent_runner.http_api as http_api
from agent_runner.codex_client import CodexExecResult
from agent_runner.http_api import MAX_JSON_BODY_BYTES, create_server
from agent_runner.image_workflow import MockImageTo3DProvider, MockImageToVideoProvider, default_mock_provider
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


def test_api_external_message_upserts_thread_context_conversation(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"

        first = _post_json(
            f"{base}/api/external/messages",
            {
                "workspace_id": "workspace-1",
                "content": "Hey, did you send the link?",
                "mode": "message",
                "thread_context": {
                    "channel": "sms",
                    "thread_key": "+14352137423",
                    "participant_name": "Taylor",
                    "open_loops": ["Send the preview link"],
                },
            },
            expected_status=202,
        )
        second = _post_json(
            f"{base}/api/external/messages",
            {
                "workspace_id": "workspace-1",
                "content": "Following up on that preview.",
                "mode": "message",
                "thread_context": {
                    "channel": "sms",
                    "thread_key": "+14352137423",
                    "participant_name": "Taylor",
                },
            },
            expected_status=202,
        )

        assert first["created_conversation"] is True
        assert second["created_conversation"] is False
        assert first["conversation_id"] == second["conversation_id"]
        conversation = _get_json(
            f"{base}/api/conversations/{first['conversation_id']}?workspace_id=workspace-1"
        )
        assert conversation["thread_context"]["channel"] == "sms"
        assert conversation["thread_context"]["participant_name"] == "Taylor"
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
        assert "function updateRunChip" in response
        assert "window.setInterval(updateRunChip, 1000);" in response
        assert "function studioWorkspaceLinks" in response
        assert "function copyStudioWorkspaceLink" in response
        assert "Current Project" in response
        assert "Copy Phone Game Link" in response
    finally:
        server.shutdown()
        server.server_close()


def test_private_intake_route_renders_alcove_delivery_form(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        response = urllib.request.urlopen(
            f"{base}/intake?workspace_id=skyler-intake"
        ).read().decode("utf-8")
        assert "Private Intake" in response
        assert "Send to Alcove" in response
        assert "/api/external/messages" in response
        assert "skyler-intake" in response
    finally:
        server.shutdown()
        server.server_close()


def test_root_route_preserves_run_mode_preferences_in_web_ui(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    service.create_conversation("workspace-1", title="Studio thread")
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        response = urllib.request.urlopen(base).read().decode("utf-8")
        assert "alcove-composer-mode-preferences" in response
        assert "function applyComposerMode" in response
        assert "syncAssistantModeUI('dev');" in response
        assert "await setMode('message');" not in response
        assert "document.getElementById('composer-mode').value = 'message';" not in response
    finally:
        server.shutdown()
        server.server_close()


def test_image_workflow_endpoints_generate_upload_and_serve_artifacts(tmp_path: Path, monkeypatch) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    monkeypatch.setattr(
        "agent_runner.service.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    created = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Figurine Lab",
        template_kind="image-gen",
    )
    workspace_id = str(created["workspace"]["id"])
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"

        generated = _post_json(
            f"{base}/api/workspaces/{workspace_id}/image-workflow/generate",
            {"prompt": "A toy robot figurine", "count": 2, "passes": 20},
        )
        assert generated["accepted"] is True
        _wait_for(lambda: len(_get_json(f"{base}/api/workspaces/{workspace_id}/image-workflow")["images"]) == 2)
        generated_workflow = _get_json(f"{base}/api/workspaces/{workspace_id}/image-workflow")
        assert generated_workflow["generation_count_options"] == [1, 2, 3, 4]
        assert generated_workflow["default_generation_count"] == 1
        assert generated_workflow["generation_pass_options"] == [2, 4, 8, 10, 12, 16, 20]
        assert generated_workflow["default_generation_passes"] == 2
        image_url = generated_workflow["images"][0]["url"]
        assert image_url.startswith(f"/workspace-media/{workspace_id}/")

        opened = _post_json(
            f"{base}/api/workspaces/{workspace_id}/image-workflow/open-folder",
            {},
        )
        assert opened["opened"] is True
        assert (
            opened["folder_path"].endswith("/Generations")
            or "/Generations/" in opened["folder_path"]
            or opened["folder_path"].endswith("/image-workflow/assets")
        )

        uploaded = _post_multipart(
            f"{base}/api/workspaces/{workspace_id}/image-workflow/assets",
            fields={},
            files=[("asset", "upload.png", "image/png", b"mock-image-bytes")],
        )
        assert any(item["source"] == "upload" for item in uploaded["images"])

        dropped_path = tmp_path / "finder-drop.png"
        dropped_path.write_bytes(b"mock-image-bytes")
        imported = _post_json(
            f"{base}/api/workspaces/{workspace_id}/image-workflow/import-path",
            {"image_path": str(dropped_path)},
        )
        assert any(item["label"] == "finder-drop" for item in imported["images"])

        animated = _post_json(
            f"{base}/api/workspaces/{workspace_id}/image-workflow/animate",
            {"source_image_id": generated_workflow["selected_image_id"]},
        )
        assert animated["job_id"].startswith("job_")

        started = _post_json(
            f"{base}/api/workspaces/{workspace_id}/image-workflow/make-3d",
            {"source_image_id": generated_workflow["selected_image_id"]},
        )
        assert started["job_id"].startswith("job_")

        _wait_for(
            lambda: any(
                item["status"] == "succeeded"
                for item in _get_json(f"{base}/api/workspaces/{workspace_id}/image-workflow")["jobs"]
            )
        )
        _wait_for(
            lambda: any(
                item["status"] == "succeeded"
                for item in _get_json(f"{base}/api/workspaces/{workspace_id}/image-workflow")["video_jobs"]
            )
        )
        workflow = _get_json(f"{base}/api/workspaces/{workspace_id}/image-workflow")
        assert workflow["video_jobs"][0]["artifacts"]["mp4"].startswith(
            f"/workspace-media/{workspace_id}/outputs/image_to_video/"
        )
        assert workflow["video_jobs"][0]["artifacts"]["poster_png"].startswith(
            f"/workspace-media/{workspace_id}/outputs/image_to_video/"
        )
        assert workflow["video_jobs"][0]["artifacts"]["metadata_json"].startswith(
            f"/workspace-media/{workspace_id}/outputs/image_to_video/"
        )
        assert workflow["jobs"][0]["artifacts"]["input_png"].startswith(
            f"/workspace-media/{workspace_id}/outputs/image_to_3d/"
        )
        assert workflow["jobs"][0]["artifacts"]["preview_png"].startswith(
            f"/workspace-media/{workspace_id}/outputs/image_to_3d/"
        )
        assert workflow["jobs"][0]["artifacts"]["metadata_json"].startswith(
            f"/workspace-media/{workspace_id}/outputs/image_to_3d/"
        )
        preview_url = workflow["images"][0]["url"]
        preview_response = urllib.request.urlopen(f"{base}{preview_url}")
        assert preview_response.status == 200
        assert preview_response.headers.get_content_type().startswith("image/")

        mp4_url = workflow["video_jobs"][0]["artifacts"]["mp4"]
        mp4_response = urllib.request.urlopen(f"{base}{mp4_url}")
        assert mp4_response.status == 200
        assert mp4_response.headers.get_content_type() == "video/mp4"

        glb_url = workflow["jobs"][0]["artifacts"]["glb"]
        glb_response = urllib.request.urlopen(f"{base}{glb_url}")
        assert glb_response.status == 200
        deleted = _delete_json(
            f"{base}/api/workspaces/{workspace_id}/image-workflow/assets/{generated_workflow['selected_image_id']}"
        )
        assert all(item["id"] != generated_workflow["selected_image_id"] for item in deleted["images"])
        assert all(item["source_image_id"] != generated_workflow["selected_image_id"] for item in deleted["jobs"])
        assert all(item["source_image_id"] != generated_workflow["selected_image_id"] for item in deleted["video_jobs"])
    finally:
        server.shutdown()
        server.server_close()


def test_image_workflow_describe_reference_and_size_profile_endpoint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_runner.service.describe_reference_image",
        lambda **kwargs: {
            "source_image_name": kwargs["image_path"].name,
            "vision_model": "qwen3.5:9b",
            "prompt_model": "qwen3.5:9b",
            "reference": {
                "subject": "teenage boy in military attire",
                "scene": "snowy encampment at dusk",
                "composition": "central figure with fires behind him",
                "palette": "blue-gray with warm orange firelight",
                "lighting": "dusky winter light",
                "style": "painterly realism",
                "mood": "somber",
                "important_details": ["tents", "snow", "campfires"],
                "recreation_prompt": "teenage boy in a blue-gray coat standing in a snowy encampment at dusk",
            },
            "reference_summary": "teenage boy in a snowy encampment at dusk, with a somber tone.",
            "suggested_prompt": "teenage boy in a blue-gray coat standing in a snowy encampment at dusk",
            "notes": "Loaded into the generator.",
            "raw_reference_response": "{}",
            "raw_prompt_response": "{}",
        },
    )
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    created = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Reference Lab",
        template_kind="image-gen",
    )
    workspace_id = str(created["workspace"]["id"])
    uploaded = service.upload_image_asset(
        workspace_id=workspace_id,
        file_name="reference.png",
        mime_type="image/png",
        data=b"mock-image-bytes",
    )
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"

        described = _post_json(
            f"{base}/api/workspaces/{workspace_id}/image-workflow/describe-reference",
            {"source_image_id": uploaded["selected_image_id"]},
        )
        assert described["reference"]["suggested_prompt"] == "teenage boy in a blue-gray coat standing in a snowy encampment at dusk"

        generated = _post_json(
            f"{base}/api/workspaces/{workspace_id}/image-workflow/generate",
            {
                "prompt": described["reference"]["suggested_prompt"],
                "count": 1,
                "size_profile_id": "landscape-1024x576",
            },
        )
        assert generated["accepted"] is True
        _wait_for(lambda: len(_get_json(f"{base}/api/workspaces/{workspace_id}/image-workflow")["images"]) >= 2)
        workflow = _get_json(f"{base}/api/workspaces/{workspace_id}/image-workflow")
        generated_image = next(item for item in workflow["images"] if item["source"] == "generated")
        assert generated_image["metadata"]["size_profile_id"] == "landscape-1024x576"
        assert generated_image["metadata"]["width"] == 1024
        assert generated_image["metadata"]["height"] == 576
        assert workflow["generation_profiles"][0]["id"] == "portrait-768x1024"
    finally:
        server.shutdown()
        server.server_close()


def test_image_workflow_generate_endpoint_reuses_seed_and_reference_image(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    created = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Seed Lab",
        template_kind="image-gen",
    )
    workspace_id = str(created["workspace"]["id"])
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"

        initial = _post_json(
            f"{base}/api/workspaces/{workspace_id}/image-workflow/generate",
            {"prompt": "Painted explorer figurine", "count": 1},
        )
        assert initial["accepted"] is True
        _wait_for(lambda: len(_get_json(f"{base}/api/workspaces/{workspace_id}/image-workflow")["images"]) == 1)
        first_workflow = _get_json(f"{base}/api/workspaces/{workspace_id}/image-workflow")
        source_image = first_workflow["images"][0]

        remixed = _post_json(
            f"{base}/api/workspaces/{workspace_id}/image-workflow/generate",
            {
                "prompt": "Painted explorer figurine with brighter rim light",
                "count": 1,
                "composition_source_image_id": source_image["id"],
                "remix_mode": "match",
            },
        )
        assert remixed["accepted"] is True
        _wait_for(lambda: len(_get_json(f"{base}/api/workspaces/{workspace_id}/image-workflow")["images"]) == 2)
        workflow = _get_json(f"{base}/api/workspaces/{workspace_id}/image-workflow")
        generated_image = workflow["images"][0]
        assert generated_image["metadata"]["composition_source_image_id"] == source_image["id"]
        assert generated_image["metadata"]["seed_reused"] is True
        assert generated_image["metadata"]["generation_mode"] == "match"
        assert generated_image["metadata"]["seed"] == source_image["metadata"]["seed"]
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


def test_workspace_can_be_renamed_and_deleted_via_api(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    service.create_conversation("workspace-1", title="Desktop thread")
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        renamed = _patch_json(
            f"{base}/api/workspaces/workspace-1",
            {
                "display_name": "Fresh Onboarding",
            },
        )
        assert renamed["id"] == "workspace-1"
        assert renamed["display_name"] == "Fresh Onboarding"

        deleted = _delete_json(f"{base}/api/workspaces/workspace-1")
        assert deleted["ok"] is True
        assert deleted["workspace_id"] == "workspace-1"

        remaining = _get_json(f"{base}/api/workspaces")
        assert "workspace-1" not in [workspace["id"] for workspace in remaining["workspaces"]]
    finally:
        server.shutdown()
        server.server_close()


def test_workspace_import_endpoint_accepts_repo_path_and_auto_detects_studio(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    repo = tmp_path / "northstar-site"
    dist = repo / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Northstar</title>", encoding="utf-8")
    service = _make_service(tmp_path)
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        workspace = _post_json(
            f"{base}/api/workspaces/import-folder",
            {
                "repo_path": str(repo),
            },
        )
        assert workspace["repo_path"] == str(repo)
        assert workspace["workspace_kind"] == "studio_web"
        assert workspace["preview_url"] == f"/studio/preview/{workspace['id']}/dist/index.html"
    finally:
        server.shutdown()
        server.server_close()


def test_workspace_import_endpoint_can_use_native_picker(monkeypatch, tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    repo = tmp_path / "picked-repo"
    _init_git_repo(repo)
    service = _make_service(tmp_path)
    monkeypatch.setattr(service, "pick_local_folder_path", lambda: str(repo))
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        workspace = _post_json(f"{base}/api/workspaces/import-folder", {})
        assert workspace["repo_path"] == str(repo)
        assert workspace["display_name"] == "picked-repo"
    finally:
        server.shutdown()
        server.server_close()


def test_workspace_import_endpoint_uses_studio_manifest_for_existing_project(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    repo = tmp_path / "landmines"
    repo.mkdir(parents=True)
    (repo / "index.html").write_text("<!doctype html><title>Landmines</title>", encoding="utf-8")
    (repo / "alcove-studio.json").write_text(
        json.dumps(
            {
                "workspace_id": "landmines",
                "workspace_kind": "studio_game",
                "artifact_title": "landmines",
                "template_kind": "platformer",
                "preview_mode": "managed-static",
                "entry_file": "game.js",
            }
        ),
        encoding="utf-8",
    )
    service = _make_service(tmp_path)
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        workspace = _post_json(
            f"{base}/api/workspaces/import-folder",
            {
                "repo_path": str(repo),
            },
        )
        assert workspace["repo_path"] == str(repo)
        assert workspace["workspace_kind"] == "studio_game"
        assert workspace["template_kind"] == "platformer"
        assert workspace["preview_url"] == f"/studio/preview/{workspace['id']}/index.html"
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


def test_generic_studio_endpoints_create_station_web_data_and_docs_workspaces(tmp_path: Path) -> None:
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

        station = _post_json(
            f"{base}/api/studio/workspaces",
            {
                "workspace_kind": "field_station",
                "artifact_title": "Garage Console",
                "template_kind": "magic-button",
            },
        )["workspace"]
        station_html = urllib.request.urlopen(f"{base}{station['preview_url']}").read().decode("utf-8")
        assert station["workspace_kind"] == "field_station"
        assert "Field Station" in station_html

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


def test_field_station_orchestration_api_queues_fake_job_and_approves_review(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"

        workspace = _post_json(
            f"{base}/api/studio/workspaces",
            {
                "workspace_kind": "field_station",
                "artifact_title": "Garage Console",
                "template_kind": "magic-button",
            },
            expected_status=201,
        )["workspace"]
        workspace_id = str(workspace["id"])
        assert _get_json(f"{base}/api/field-station/snapshot?workspace_id={workspace_id}")["jobs"] == []
        briefing_sources = _get_json(f"{base}/api/field-station/briefing-sources?workspace_id={workspace_id}")
        assert briefing_sources["owner_briefing"]["permission_lane"] == "read-only"
        assert any(source["id"] == "sample_ck_customer_threads" for source in briefing_sources["sources"])

        capture = _post_json(
            f"{base}/api/field-station/captures",
            {
                "workspace_id": workspace_id,
                "text": "Make a field station shopping checklist.",
                "source": "typed",
                "mode": "maker",
                "metadata": {"voice_state": "ready"},
            },
            expected_status=201,
        )["capture"]
        asset = _post_json(
            f"{base}/api/field-station/capture-assets",
            {
                "workspace_id": workspace_id,
                "data_url": "data:image/png;base64,aGVsbG8=",
                "file_name": "parts.png",
                "label": "parts photo",
                "source": "upload",
            },
            expected_status=201,
        )["attachment"]
        asset_bytes = urllib.request.urlopen(
            f"{base}/api/field-station/capture-assets?workspace_id={workspace_id}&path={urllib.parse.quote(asset['path'])}"
        ).read()
        assert asset_bytes == b"hello"
        mission = _post_json(
            f"{base}/api/field-station/missions",
            {
                "workspace_id": workspace_id,
                "goal": "Make a field station shopping checklist.",
                "mode": "maker",
                "permission_lane": "read-only",
                "expected_output": "project_plan",
                "capture_id": capture["id"],
            },
            expected_status=201,
        )["mission"]
        assert mission["capture_id"] == capture["id"]
        job = _post_json(
            f"{base}/api/field-station/jobs",
            {
                "workspace_id": workspace_id,
                "mission_id": mission["id"],
                "provider": "fake",
            },
            expected_status=201,
        )["job"]
        assert job["status"] == "queued"

        _wait_for(lambda: _get_json(f"{base}/api/workspaces/{workspace_id}/field-station")["reviews"])
        snapshot = _get_json(f"{base}/api/workspaces/{workspace_id}/field-station")
        review = snapshot["reviews"][0]
        assert snapshot["jobs"][0]["status"] == "needs_review"
        artifact = _get_json(
            f"{base}/api/field-station/artifact?workspace_id={workspace_id}&path={urllib.parse.quote(review['artifact_paths'][0])}"
        )
        assert "Make a field station shopping checklist" in artifact["content"]

        approved = _post_json(
            f"{base}/api/field-station/reviews/{review['id']}/approve",
            {"workspace_id": workspace_id},
        )
        assert approved["review"]["status"] == "approved"
        assert approved["snapshot"]["jobs"][0]["status"] == "succeeded"

        bridge = _post_json(
            f"{base}/api/field-station/station-events",
            {
                "workspace_id": workspace_id,
                "event_type": "button.capture",
                "payload": {
                    "mode": "maker",
                    "text": "Bridge button should queue a capture.",
                    "provider": "fake",
                    "simulated": True,
                },
            },
            expected_status=201,
        )
        assert bridge["capture"]["source"] == "physical_button"
        assert bridge["mission"]["capture_id"] == bridge["capture"]["id"]
        camera = _post_json(
            f"{base}/api/field-station/station-events",
            {
                "workspace_id": workspace_id,
                "event_type": "camera.snapshot",
                "payload": {
                    "mode": "maker",
                    "text": "Camera captured the desk parts.",
                    "data_url": "data:image/png;base64,aGVsbG8=",
                    "simulated": True,
                },
            },
            expected_status=201,
        )
        assert camera["capture"]["source"] == "camera"
        assert camera["capture"]["attachments"][0]["mime_type"] == "image/png"

        custom_source = _post_json(
            f"{base}/api/field-station/briefing-sources",
            {
                "workspace_id": workspace_id,
                "kind": "manual",
                "label": "Owner notes",
                "summary": "Read-only owner notes for today's customer follow-up.",
                "sample_items": [{"title": "Draft a reply", "detail": "Human approval required.", "urgency": "today"}],
            },
            expected_status=201,
        )["source"]
        owner_briefing = _post_json(
            f"{base}/api/field-station/owner-briefings",
            {
                "workspace_id": workspace_id,
                "source_ids": ["sample_ck_customer_threads", custom_source["id"]],
                "note": "Focus on owner decisions.",
                "provider": "fake",
            },
            expected_status=201,
        )
        assert owner_briefing["capture"]["source"] == "owner_briefing"
        assert owner_briefing["mission"]["expected_output"] == "owner_briefing"
        assert owner_briefing["mission"]["permission_lane"] == "read-only"
        assert len(owner_briefing["sources"]) == 2
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
        assert settings["codex_bin"] == "codex"
        assert settings["openai_model"] == "gpt-5.3-codex"
        assert "open_source_model" in settings
        assert settings["resolved_context_char_cap"] == 100000
        updated = _patch_json(
            f"{base}/api/settings",
            {
                "provider": "ollama",
                "openai_model": "gpt-5.4",
                "open_source_model": "llama3.1:8b",
                "context_char_cap": 150000,
            },
        )
        assert updated["provider"] == "ollama"
        assert updated["model"] == "llama3.1:8b"
        assert updated["openai_model"] == "gpt-5.4"
        assert updated["open_source_model"] == "llama3.1:8b"
        assert updated["context_char_cap"] == 150000
        assert updated["resolved_context_char_cap"] == 150000
        models = _get_json(f"{base}/api/providers/ollama/models")
        assert "available" in models and "models" in models and "message" in models
    finally:
        server.shutdown()
        server.server_close()


def test_setup_check_endpoint_reports_doctor_status(tmp_path: Path, monkeypatch) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    monkeypatch.setattr(
        "agent_runner.service.run_doctor",
        lambda **kwargs: type(
            "Report",
            (),
            {
                "to_dict": lambda self: {
                    "ok": False,
                    "checks": [
                        {
                            "key": "codex_login",
                            "label": "Codex authentication",
                            "ok": False,
                            "detail": "Not logged in.",
                            "fix": "Run `codex login`.",
                        }
                    ],
                    "summary": "Setup is incomplete.",
                }
            },
        )(),
    )
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        payload = _get_json(f"{base}/api/setup-check")
        assert payload["ok"] is False
        assert payload["checks"][0]["key"] == "codex_login"
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


def test_message_endpoint_queues_requests_while_busy(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    gate = Event()
    service = _make_service(tmp_path, phase_client=GatePhaseClient(gate))
    first = service.create_conversation("workspace-1", title="First thread")
    second = service.create_conversation("workspace-2", title="Second thread")
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        started = _post_json(
            f"{base}/api/conversations/{first['id']}/messages",
            {"content": "Keep running", "mode": "message", "workspace_id": "workspace-1"},
        )
        queued = _post_json(
            f"{base}/api/conversations/{second['id']}/messages",
            {"content": "Queue this next", "mode": "message", "workspace_id": "workspace-2"},
        )

        assert started["queued"] is False
        assert queued["queued"] is True
        assert queued["queue_position"] == 1
        status = _get_json(f"{base}/api/run-status")
        assert status["queue_count"] == 1
        assert status["queued_runs"][0]["conversation_id"] == str(second["id"])

        gate.set()
        _wait_for(
            lambda: len(
                _get_json(f"{base}/api/conversations/{second['id']}?workspace_id=workspace-2")["messages"]
            )
            == 2
        )
        assert _get_json(f"{base}/api/run-status")["queue_count"] == 0
    finally:
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
        assert cleared["title"] == "New conversation"
        assert cleared["messages"] == []
        conversation = _get_json(f"{base}/api/conversations/{created['id']}?workspace_id=workspace-1")
        assert conversation["title"] == "New conversation"
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


def test_workspace_define_rejects_unsafe_workspace_id(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    server = create_server(service, "127.0.0.1", 0)
    outside_workspace = tmp_path / "outside-workspace"
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        request = urllib.request.Request(
            f"{base}/api/workspaces",
            data=json.dumps(
                {
                    "id": "../../outside-workspace",
                    "display_name": "Oops",
                    "repo_path": str(tmp_path),
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
            assert "path separators" in payload["detail"].lower()
        else:
            raise AssertionError("Expected unsafe workspace id to be rejected")

        assert not outside_workspace.exists()
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


def test_connections_endpoint_reports_local_url_and_phone_unavailable_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
        assert payload["native_transcription_available"] is False
        assert payload["realtime_voice_available"] is False
        assert payload["realtime_voice_provider"] is None
        assert payload["realtime_voice_model"] == "gpt-realtime"
    finally:
        server.shutdown()
        server.server_close()


def test_realtime_client_secret_endpoint_requires_openai_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            _post_json(
                f"{base}/api/field-station/realtime-client-secret",
                {"workspace_id": "presence-qa-demo", "mode": "maker"},
            )
            raise AssertionError("Expected realtime client secret request to fail without OPENAI_API_KEY.")
        except urllib.error.HTTPError as exc:
            assert exc.code == 409
            payload = json.loads(exc.read().decode("utf-8"))
            assert "OPENAI_API_KEY" in payload["detail"]
    finally:
        server.shutdown()
        server.server_close()


def test_realtime_client_secret_endpoint_returns_ephemeral_payload(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    captured: dict[str, object] = {}

    def fake_client_secret(*, mode: str | None, current_text: str | None, repo_path: Path) -> dict[str, object]:
        captured["mode"] = mode
        captured["current_text"] = current_text
        captured["repo_path"] = repo_path
        return {
            "provider": "openai",
            "model": "gpt-realtime",
            "voice": "marin",
            "calls_url": "https://api.openai.com/v1/realtime/calls",
            "client_secret": {"value": "ek_test", "expires_at": 123456},
        }

    monkeypatch.setattr("agent_runner.http_api._create_openai_realtime_client_secret", fake_client_secret)
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        payload = _post_json(
            f"{base}/api/field-station/realtime-client-secret",
            {
                "workspace_id": "presence-qa-demo",
                "mode": "maker",
                "current_text": "Build a tiny rover.",
            },
        )
        assert payload["client_secret"]["value"] == "ek_test"
        assert payload["calls_url"].endswith("/realtime/calls")
        assert "sk-test" not in json.dumps(payload)
        assert captured["mode"] == "maker"
        assert captured["current_text"] == "Build a tiny rover."
        assert captured["repo_path"] == service.config.repo_path
    finally:
        server.shutdown()
        server.server_close()


def test_openai_realtime_client_secret_helper_posts_session_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ALCOVE_REALTIME_VOICE", "verse")
    calls: list[tuple[urllib.request.Request, int]] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps({"value": "ek_test", "expires_at": 123456}).encode("utf-8")

    def fake_urlopen(request: urllib.request.Request, timeout: int = 0):
        calls.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(http_api.urllib.request, "urlopen", fake_urlopen)

    payload = http_api._create_openai_realtime_client_secret(
        mode="family",
        current_text="Tell a story about this drawing.",
        repo_path=tmp_path,
    )

    assert payload["client_secret"]["value"] == "ek_test"
    assert payload["voice"] == "verse"
    assert len(calls) == 1
    request, timeout = calls[0]
    assert timeout == 12
    assert request.full_url == "https://api.openai.com/v1/realtime/client_secrets"
    assert request.get_header("Authorization") == "Bearer sk-test"
    request_payload = json.loads(request.data.decode("utf-8"))
    session = request_payload["session"]
    assert session["model"] == "gpt-realtime"
    assert session["audio"]["output"]["voice"] == "verse"
    assert session["audio"]["input"]["transcription"]["model"] == "gpt-4o-mini-transcribe"
    assert session["tool_choice"] == "auto"
    assert session["tools"][0]["name"] == "queue_alcove_job"
    assert session["tools"][0]["parameters"]["required"] == ["goal"]
    assert "Family mode" in session["instructions"]
    assert "Default to English" in session["instructions"]
    assert "Only switch languages" in session["instructions"]
    assert "ask one short clarifying question" in session["instructions"]
    assert "no random roleplay" in session["instructions"]
    assert "queue_alcove_job" in session["instructions"]
    assert "Tell a story about this drawing." in session["instructions"]


def test_native_transcription_endpoint_uses_wrapper_callable(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    requested_locales: list[str | None] = []

    def transcribe(locale: str | None) -> dict[str, object]:
        requested_locales.append(locale)
        return {
            "transcript": "ship the fix",
            "locale": locale or "en-US",
            "provider": "macos-native",
        }

    server = create_server(service, "127.0.0.1", 0, native_transcriber=transcribe)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"

        info = _get_json(f"{base}/api/server-info")
        assert info["native_transcription_available"] is True
        assert info["native_transcription_provider"] == "macos-wrapper"

        payload = _post_json(
            f"{base}/api/native/transcribe",
            {"locale": "en-US"},
        )
        assert payload["transcript"] == "ship the fix"
        assert payload["provider"] == "macos-native"
        assert requested_locales == ["en-US"]
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


def test_message_endpoint_rejects_oversized_json_body(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    created = service.create_conversation("workspace-1", title="Large request thread")
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"
        payload = {
            "workspace_id": "workspace-1",
            "mode": "message",
            "content": "x" * MAX_JSON_BODY_BYTES,
        }
        request = urllib.request.Request(
            f"{base}/api/conversations/{created['id']}/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request)
        except urllib.error.HTTPError as exc:
            assert exc.code == 413
            response = json.loads(exc.read().decode("utf-8"))
            assert "too large" in response["detail"].lower()
        except urllib.error.URLError as exc:
            # urllib may surface an early 413-style rejection as a broken pipe because
            # the server closes the connection before the full oversized body is sent.
            error_text = str(exc).lower()
            assert "broken pipe" in error_text or "connection reset by peer" in error_text
        else:
            raise AssertionError("Expected oversized body to be rejected")
        assert service.get_conversation(str(created["id"]), workspace_id="workspace-1")["messages"] == []
    finally:
        server.shutdown()
        server.server_close()


def test_conversation_archive_and_restore_endpoints_expose_archived_threads(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    service = _make_service(tmp_path)
    created = service.create_conversation("workspace-1", title="Archive me")
    controller = service._controller("workspace-1")
    controller.select_conversation(str(created["id"]))
    controller.append_message(role="user", content="Keep this transcript")
    server = create_server(service, "127.0.0.1", 0)
    try:
        _start(server)
        base = f"http://127.0.0.1:{server.server_port}"

        archived = _post_json(
            f"{base}/api/conversations/{created['id']}/archive",
            {"workspace_id": "workspace-1"},
        )
        assert archived["conversation"]["archived_at"] is not None
        assert archived["active_conversation_id"] != created["id"]

        visible = _get_json(f"{base}/api/workspaces/workspace-1/conversations")
        assert str(created["id"]) not in {item["id"] for item in visible["conversations"]}

        all_conversations = _get_json(f"{base}/api/workspaces/workspace-1/conversations?include_archived=1")
        archived_items = [item for item in all_conversations["conversations"] if item["id"] == str(created["id"])]
        assert archived_items
        assert archived_items[0]["is_archived"] is True

        restored = _post_json(
            f"{base}/api/conversations/{created['id']}/restore",
            {"workspace_id": "workspace-1"},
        )
        assert restored["id"] == created["id"]
        assert restored["active_conversation_id"] == created["id"]
        assert restored["archived_at"] is None
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
        image_workflow_provider=default_mock_provider(),
        image_to_3d_provider=MockImageTo3DProvider(),
        image_to_video_provider=MockImageToVideoProvider(),
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


def _post_json(url: str, payload: dict, *, expected_status: int | None = None) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        if expected_status is not None:
            assert response.status == expected_status
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


def _delete_json(url: str) -> dict:
    request = urllib.request.Request(url, method="DELETE")
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
