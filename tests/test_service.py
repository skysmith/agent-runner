from __future__ import annotations

import time
import json
from pathlib import Path
from threading import Event
import subprocess
from types import SimpleNamespace

from agent_runner.codex_client import CodexExecResult
from agent_runner.models import AssistantCapabilityMode, BuildResult, ProviderKind, ReviewResult, RunMode, RunOutcome, StepRun
from agent_runner.service import AgentRunnerService, ServiceConfig


class FakePhaseClient:
    def __init__(self, *, message: str = "mobile reply", gate: Event | None = None):
        self.message = message
        self.gate = gate

    def run(self, request) -> CodexExecResult:
        if self.gate is not None:
            self.gate.wait(timeout=2)
        return CodexExecResult(
            payload={"message": self.message},
            raw_jsonl="",
            stderr="",
            return_code=0,
        )


class RecordingPhaseClient(FakePhaseClient):
    def __init__(self, *, message: str = "mobile reply"):
        super().__init__(message=message)
        self.requests = []

    def run(self, request) -> CodexExecResult:
        self.requests.append(request)
        return super().run(request)


class FailingPhaseClient:
    def run(self, request) -> CodexExecResult:
        raise RuntimeError("provider exploded")


def test_service_send_message_persists_reply(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Here is the summary"))
    conversation = service.create_conversation("workspace-1", title="Inbox")

    service.send_message(
        workspace_id="workspace-1",
        conversation_id=str(conversation["id"]),
        content="Summarize the repo changes",
        mode=RunMode.MESSAGE,
    )

    _wait_for(lambda: len(service.get_conversation(str(conversation["id"]))["messages"]) == 2)
    _wait_for(lambda: service.get_run_status()["state"] == "succeeded")
    record = service.get_conversation(str(conversation["id"]))
    messages = record["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert "Here is the summary" in messages[-1]["content"]
    assert not (tmp_path / ".agent-runner" / "active-run.lock").exists()


def test_service_queues_second_active_run(tmp_path: Path) -> None:
    gate = Event()
    service = _make_service(tmp_path, phase_client=FakePhaseClient(gate=gate))
    first = service.create_conversation("workspace-1")
    second = service.create_conversation("workspace-2")

    first_response = service.send_message(
        workspace_id="workspace-1",
        conversation_id=str(first["id"]),
        content="First request",
        mode=RunMode.MESSAGE,
    )
    queued_response = service.send_message(
        workspace_id="workspace-2",
        conversation_id=str(second["id"]),
        content="Second request",
        mode=RunMode.MESSAGE,
    )

    assert first_response["queued"] is False
    assert queued_response["queued"] is True
    assert queued_response["queue_position"] == 1
    status = service.get_run_status()
    assert status["queue_count"] == 1
    assert status["queued_runs"][0]["conversation_id"] == str(second["id"])
    assert service.get_conversation(str(second["id"]), workspace_id="workspace-2")["messages"] == []

    gate.set()
    _wait_for(lambda: service.get_run_status()["state"] == "succeeded")
    _wait_for(lambda: len(service.get_conversation(str(second["id"]), workspace_id="workspace-2")["messages"]) == 2)
    assert service.get_run_status()["queue_count"] == 0


def test_service_clear_conversation_resets_title_and_messages(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient())
    conversation = service.create_conversation("workspace-1", title="Investigate regression")
    controller = service._controller("workspace-1")
    controller.select_conversation(str(conversation["id"]))
    controller.append_message(role="user", content="Keep this out of the next run")
    controller.append_message(role="assistant", content="Will do")
    controller.update_summary(str(conversation["id"]), "Summary to clear")

    cleared = service.clear_conversation(str(conversation["id"]), workspace_id="workspace-1")

    assert cleared["id"] == conversation["id"]
    assert cleared["title"] == "New conversation"
    assert cleared["messages"] == []
    assert cleared["summary"] is None
    assert cleared["active_conversation_id"] == conversation["id"]


def test_service_archive_and_restore_conversation_uses_explicit_archive_state(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient())
    conversation = service.create_conversation("workspace-1", title="Quiet launch thread")
    controller = service._controller("workspace-1")
    controller.select_conversation(str(conversation["id"]))
    controller.append_message(role="user", content="Preserve this conversation")

    archived = service.archive_conversation(str(conversation["id"]), workspace_id="workspace-1")

    assert archived["conversation"]["id"] == conversation["id"]
    assert archived["conversation"]["archived_at"] is not None
    assert archived["active_conversation_id"] != conversation["id"]
    assert str(conversation["id"]) not in {item["id"] for item in service.list_conversations("workspace-1")}
    archived_records = service.list_conversations("workspace-1", include_archived=True)
    assert str(conversation["id"]) in {item["id"] for item in archived_records if item["is_archived"]}

    restored = service.restore_conversation(str(conversation["id"]), workspace_id="workspace-1")

    assert restored["id"] == conversation["id"]
    assert restored["archived_at"] is None
    assert restored["active_conversation_id"] == conversation["id"]
    assert str(conversation["id"]) in {item["id"] for item in service.list_conversations("workspace-1")}


def test_recover_run_rejects_when_active(tmp_path: Path) -> None:
    gate = Event()
    service = _make_service(tmp_path, phase_client=FakePhaseClient(gate=gate))
    conversation = service.create_conversation("workspace-1")

    service.send_message(
        workspace_id="workspace-1",
        conversation_id=str(conversation["id"]),
        content="Long request",
        mode=RunMode.MESSAGE,
    )

    _wait_for(lambda: service.get_run_status()["state"] in {"starting", "running", "stopping"})
    try:
        service.recover_run()
    except RuntimeError as exc:
        assert "Run is active" in str(exc)
    else:
        raise AssertionError("Expected recover_run to reject while active")

    gate.set()
    _wait_for(lambda: service.get_run_status()["state"] == "succeeded")


def test_service_recovers_from_background_failure(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FailingPhaseClient())
    conversation = service.create_conversation("workspace-1")

    service.send_message(
        workspace_id="workspace-1",
        conversation_id=str(conversation["id"]),
        content="Trigger failure",
        mode=RunMode.MESSAGE,
    )

    _wait_for(lambda: service.get_run_status()["state"] == "failed")
    _wait_for(lambda: service.coordinator.active_workspace_id() is None)
    assert not (tmp_path / ".agent-runner" / "active-run.lock").exists()


def test_service_retry_last_prompt_resubmits_latest_user_message(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Retry ok"))
    conversation = service.create_conversation("workspace-1")
    conversation_id = str(conversation["id"])

    service.send_message(
        workspace_id="workspace-1",
        conversation_id=conversation_id,
        content="Retry this message",
        mode=RunMode.MESSAGE,
    )
    _wait_for(lambda: service.get_run_status()["state"] == "succeeded")

    service.retry_last_prompt()
    _wait_for(lambda: len(service.get_conversation(conversation_id)["messages"]) == 4)

    record = service.get_conversation(conversation_id)
    user_messages = [message["content"] for message in record["messages"] if message["role"] == "user"]
    assert user_messages[-1] == "Retry this message"


def test_service_emits_events_since_cursor(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Event reply"))
    conversation = service.create_conversation("workspace-1", title="Events")
    conversation_id = str(conversation["id"])

    service.send_message(
        workspace_id="workspace-1",
        conversation_id=conversation_id,
        content="Emit events",
        mode=RunMode.MESSAGE,
    )
    _wait_for(lambda: service.get_run_status()["state"] == "succeeded")

    page1 = service.list_events_since(cursor=None, limit=3)
    assert page1["events"]
    assert int(page1["next_cursor"]) >= 1

    page2 = service.list_events_since(cursor=str(page1["next_cursor"]))
    assert isinstance(page2["events"], list)


def test_service_event_listener_receives_run_status_payloads(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Listener reply"))
    conversation = service.create_conversation("workspace-1", title="Listeners")
    conversation_id = str(conversation["id"])
    events: list[tuple[str, dict[str, object]]] = []
    service.add_event_listener(lambda event_type, payload: events.append((event_type, payload)))

    service.send_message(
        workspace_id="workspace-1",
        conversation_id=conversation_id,
        content="Emit listener events",
        mode=RunMode.MESSAGE,
    )
    _wait_for(lambda: service.get_run_status()["state"] == "succeeded")

    run_events = [payload for event_type, payload in events if event_type.startswith("run.")]
    assert run_events
    assert any((payload.get("status") or {}).get("state") == "succeeded" for payload in run_events)


def test_service_loop_requires_dev_assistant_mode(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Loop blocked"))
    conversation = service.create_conversation("workspace-1")
    conversation_id = str(conversation["id"])

    try:
        service.send_message(
            workspace_id="workspace-1",
            conversation_id=conversation_id,
            content="Run full loop",
            mode=RunMode.LOOP,
            assistant_mode=AssistantCapabilityMode.ASK,
        )
    except ValueError as exc:
        assert "requires dev assistant capability mode" in str(exc).lower()
    else:
        raise AssertionError("Expected loop send to be blocked outside dev mode")


def test_service_context_update_persists_mode_and_page_context(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient())
    conversation = service.create_conversation("workspace-1")
    conversation_id = str(conversation["id"])

    updated = service.update_conversation_context(
        conversation_id,
        workspace_id="workspace-1",
        assistant_mode=AssistantCapabilityMode.OPS,
        page_context={"route": "/finance/cash-flow", "filters": {"range": "30d"}},
    )

    assert updated["assistant_mode"] == "ops"
    assert updated["page_context"]["route"] == "/finance/cash-flow"
    assert updated["page_context"]["adapter"] == "cashflow"
    assert updated["page_context"]["filters"] == {"range": "30d"}


def test_send_message_normalizes_page_context_before_persisting(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="ok"))
    conversation = service.create_conversation("workspace-1")
    conversation_id = str(conversation["id"])

    service.send_message(
        workspace_id="workspace-1",
        conversation_id=conversation_id,
        content="Use inventory context",
        mode=RunMode.MESSAGE,
        page_context={
            "route": "/finance/inventory",
            "entities": {"sku": "SKU-42"},
            "filters": {"sell_through_window": "14d"},
        },
    )

    _wait_for(lambda: service.get_run_status()["state"] == "succeeded")
    record = service.get_conversation(conversation_id, workspace_id="workspace-1")
    context = record["page_context"]
    assert context["adapter"] == "inventory"
    assert context["sku"] == "SKU-42"
    assert context["sell_through_window"] == "14d"


def test_service_uses_vision_model_for_screenshot_messages_on_ollama(tmp_path: Path) -> None:
    client = RecordingPhaseClient(message="Visual review ready")
    service = _make_service(tmp_path, phase_client=client)
    service.app_settings.provider = ProviderKind.OLLAMA
    service.app_settings.model = "qwen3:8b"
    service.app_settings.vision_model = "qwen3-vl:4b"
    conversation = service.create_conversation("workspace-1")
    conversation_id = str(conversation["id"])
    screenshot = tmp_path / "frame.png"
    screenshot.write_bytes(b"fake-frame")

    service.send_message(
        workspace_id="workspace-1",
        conversation_id=conversation_id,
        content=(
            "Tell me what looks visually broken.\n\n"
            "Attached screenshot files (local paths):\n"
            f"- Screenshot: {screenshot} (image/png, 10 bytes)"
        ),
        mode=RunMode.MESSAGE,
        provider=ProviderKind.OLLAMA,
        model="qwen3:8b",
    )

    _wait_for(lambda: service.get_run_status()["state"] == "succeeded")
    assert client.requests
    assert client.requests[-1].model == "qwen3-vl:4b"


def test_service_uses_single_pass_runner_for_dev_message_actions(monkeypatch, tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="should not be used"))
    service.app_settings.provider = ProviderKind.OLLAMA
    service.app_settings.model = "qwen3:8b"
    service.app_settings.planner_model = "qwen3:8b"
    service.app_settings.builder_model = "gpt-5.3-codex"
    service.app_settings.reviewer_model = "qwen3:8b"
    conversation = service.create_conversation("workspace-1")
    conversation_id = str(conversation["id"])
    captured: list[object] = []

    class FakeRunner:
        def __init__(self, config):
            captured.append(config)
            self.store = SimpleNamespace(run_dir=tmp_path / ".agent-runner" / "runs" / "fake", build_number=7)

        def run(self):
            return RunOutcome(
                ok=True,
                reason="success",
                step_runs=[
                    StepRun(
                        step_id="step-1",
                        attempt=1,
                        build_result=BuildResult(
                            status="ok",
                            summary="Applied grounded NPC physics.",
                            files_touched=["src/game/npc.ts"],
                            commands_run=["npm test"],
                            notes=[],
                        ),
                        check_results=[],
                        review_result=ReviewResult(
                            verdict="pass",
                            task_complete=True,
                            step_complete=True,
                            issues=[],
                            guidance="",
                        ),
                    )
                ],
                final_message="Applied grounded NPC physics.",
            )

    monkeypatch.setattr("agent_runner.service.AgentRunner", FakeRunner)

    service.send_message(
        workspace_id="workspace-1",
        conversation_id=conversation_id,
        content="Please continue and make it so the NPCs don't bounce or float.",
        mode=RunMode.MESSAGE,
        assistant_mode=AssistantCapabilityMode.DEV,
        provider=ProviderKind.OLLAMA,
        model="qwen3:8b",
    )

    _wait_for(lambda: service.get_run_status()["state"] == "succeeded")
    assert captured
    assert captured[-1].max_step_retries == 0
    record = service.get_conversation(conversation_id, workspace_id="workspace-1")
    assert "Applied grounded NPC physics." in record["messages"][-1]["content"]


def test_define_workspace_persists_display_name_and_repo_path(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient())
    repo_path = tmp_path / "alt-repo"
    _init_git_repo(repo_path)

    workspace = service.define_workspace(
        "clementine-kids",
        display_name="Clementine Kids",
        repo_path=str(repo_path),
    )

    assert workspace["display_name"] == "Clementine Kids"
    assert workspace["repo_path"] == str(repo_path)


def test_import_workspace_reuses_existing_workspace_for_same_repo(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient())
    repo_path = tmp_path / "alt-repo"
    _init_git_repo(repo_path)

    first = service.import_workspace_from_path(str(repo_path))
    second = service.import_workspace_from_path(str(repo_path))

    assert first["id"] == second["id"]
    assert second["repo_path"] == str(repo_path)


def test_import_workspace_auto_detects_previewable_web_repo_as_studio(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient())
    repo_path = tmp_path / "northstar-site"
    dist = repo_path / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Northstar</title>", encoding="utf-8")

    workspace = service.import_workspace_from_path(str(repo_path))

    assert workspace["workspace_kind"] == "studio_web"
    assert workspace["preview_url"] == f"/studio/preview/{workspace['id']}/dist/index.html"
    assert workspace["preview_state"] == "ready"
    conversation = service.get_conversation(str(workspace["active_conversation_id"]), workspace_id=str(workspace["id"]))
    assert conversation["assistant_mode"] == "dev"


def test_import_workspace_auto_detects_phaser_repo_as_game_studio(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient())
    repo_path = tmp_path / "gnome-roundup"
    repo_path.mkdir(parents=True)
    (repo_path / "package.json").write_text(
        json.dumps(
            {
                "name": "gnome-roundup",
                "scripts": {"build": "vite build"},
                "dependencies": {"phaser": "^3.80.0"},
            }
        ),
        encoding="utf-8",
    )

    workspace = service.import_workspace_from_path(str(repo_path))

    assert workspace["workspace_kind"] == "studio_game"
    assert workspace["preview_url"] == f"/studio/preview/{workspace['id']}/dist/index.html"
    assert workspace["preview_state"] == "draft"


def test_import_workspace_uses_studio_manifest_kind_and_template(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient())
    repo_path = tmp_path / "landmines"
    repo_path.mkdir(parents=True)
    (repo_path / "index.html").write_text("<!doctype html><title>Landmines</title>", encoding="utf-8")
    (repo_path / "alcove-studio.json").write_text(
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

    workspace = service.import_workspace_from_path(str(repo_path))

    assert workspace["workspace_kind"] == "studio_game"
    assert workspace["template_kind"] == "platformer"
    assert workspace["preview_url"] == f"/studio/preview/{workspace['id']}/index.html"
    assert workspace["preview_state"] == "ready"


def test_list_active_repositories_scans_git_roots(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient())
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    _init_git_repo(repo_a)
    _init_git_repo(repo_b)
    (repo_b / "README.md").write_text("dirty\n", encoding="utf-8")

    results = service.list_active_repositories(root=tmp_path, limit=5)

    paths = [item["repo_path"] for item in results]
    assert str(repo_a) in paths
    assert str(repo_b) in paths


def test_create_studio_game_scaffolds_preview_and_publish(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))

    created = service.create_studio_game(
        game_title="Moon Mango Jump",
        template_kind="platformer",
        theme_prompt="A playful moonlit jungle.",
    )

    workspace = created["workspace"]
    assert workspace["workspace_kind"] == "studio_game"
    assert workspace["template_kind"] == "platformer"
    assert workspace["preview_state"] == "ready"
    assert workspace["preview_url"] == f"/studio/preview/{workspace['id']}/index.html"

    repo_path = Path(str(workspace["repo_path"]))
    assert (repo_path / "index.html").exists()
    assert (repo_path / "game.js").exists()
    assert (repo_path / "alcove-studio.json").exists()

    published = service.publish_studio_game(str(workspace["id"]))
    assert published["publish_state"] == "published"
    assert str(published["publish_url"]).startswith("/play/")


def test_create_studio_workspace_defaults_unknown_game_template_to_runner(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))

    created = service.create_studio_workspace(
        workspace_kind="studio_game",
        artifact_title="Night Shift Detective",
        template_kind="mystery",
    )

    workspace = created["workspace"]
    assert workspace["template_kind"] == "runner"
    game_js = (Path(str(workspace["repo_path"])) / "game.js").read_text(encoding="utf-8")
    assert "Case Interrupted" in game_js


def test_create_additional_studio_kinds_scaffold_previewable_projects(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))

    web = service.create_studio_workspace(
        workspace_kind="studio_web",
        artifact_title="Northstar Site",
        template_kind="landing-page",
        theme_prompt="A calm premium launch page.",
    )["workspace"]
    data = service.create_studio_workspace(
        workspace_kind="studio_data",
        artifact_title="Revenue Atlas",
        template_kind="dashboard",
        theme_prompt="Trustworthy revenue trends and simple charts.",
    )["workspace"]
    docs = service.create_studio_workspace(
        workspace_kind="studio_docs",
        artifact_title="Northstar Docs",
        template_kind="docs-site",
        theme_prompt="Friendly setup docs for new builders.",
    )["workspace"]

    assert web["workspace_kind"] == "studio_web"
    assert web["artifact_title"] == "Northstar Site"
    assert (Path(str(web["repo_path"])) / "app.js").exists()

    assert data["workspace_kind"] == "studio_data"
    assert (Path(str(data["repo_path"])) / "data.js").exists()
    assert (Path(str(data["repo_path"])) / "data.json").exists()

    assert docs["workspace_kind"] == "studio_docs"
    assert (Path(str(docs["repo_path"])) / "docs.js").exists()
    assert (Path(str(docs["repo_path"])) / "guide.md").exists()

    published = service.publish_studio_workspace(str(web["id"]))
    assert published["publish_state"] == "published"
    assert str(published["publish_url"]).startswith("/play/")


def test_imported_studio_workspace_preserves_custom_preview_entry_path(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))
    repo = tmp_path / "gnome-roundup"
    dist = repo / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Gnome Roundup</title>", encoding="utf-8")

    workspace = service.define_workspace(
        "gnome-roundup",
        display_name="Gnome Roundup",
        repo_path=str(repo),
        workspace_kind="studio_game",
        artifact_title="Gnome Roundup",
        template_kind="phaser-vite",
        preview_url="/studio/preview/gnome-roundup/dist/index.html",
        preview_state="ready",
        publish_state="draft",
    )

    refreshed = service.refresh_studio_preview("gnome-roundup")
    assert refreshed["preview_url"] == "/studio/preview/gnome-roundup/dist/index.html"

    published = service.publish_studio_workspace("gnome-roundup")
    assert published["publish_url"] == "/play/gnome-roundup/dist/index.html"


def test_refresh_studio_preview_builds_imported_node_project(monkeypatch, tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))
    repo = tmp_path / "gnome-roundup"
    dist = repo / "dist"
    dist.mkdir(parents=True)
    package_json = {
        "name": "gnome-roundup",
        "scripts": {
            "build": "vite build",
        },
    }
    (repo / "package.json").write_text(json.dumps(package_json), encoding="utf-8")
    (dist / "index.html").write_text("<!doctype html><title>old</title>", encoding="utf-8")

    service.define_workspace(
        "gnome-roundup",
        display_name="Gnome Roundup",
        repo_path=str(repo),
        workspace_kind="studio_game",
        artifact_title="Gnome Roundup",
        template_kind="phaser-vite",
        preview_url="/studio/preview/gnome-roundup/dist/index.html",
        preview_state="ready",
        publish_state="draft",
    )

    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False):
        calls.append(list(cmd))
        (dist / "index.html").write_text("<!doctype html><title>fresh</title>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="built", stderr="")

    monkeypatch.setattr("agent_runner.service.subprocess.run", fake_run)

    refreshed = service.refresh_studio_preview("gnome-roundup")

    assert calls == [["npm", "run", "build"]]
    assert refreshed["preview_state"] == "ready"
    assert (dist / "index.html").read_text(encoding="utf-8") == "<!doctype html><title>fresh</title>"


def test_refresh_studio_preview_surfaces_build_failure(monkeypatch, tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))
    repo = tmp_path / "broken-game"
    repo.mkdir(parents=True)
    (repo / "package.json").write_text(json.dumps({"scripts": {"build": "vite build"}}), encoding="utf-8")

    service.define_workspace(
        "broken-game",
        display_name="Broken Game",
        repo_path=str(repo),
        workspace_kind="studio_game",
        artifact_title="Broken Game",
        template_kind="phaser-vite",
        preview_url="/studio/preview/broken-game/dist/index.html",
        preview_state="draft",
        publish_state="draft",
    )

    def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="vite exploded")

    monkeypatch.setattr("agent_runner.service.subprocess.run", fake_run)

    try:
        service.refresh_studio_preview("broken-game")
    except ValueError as exc:
        assert "Could not build Studio preview" in str(exc)
        assert "vite exploded" in str(exc)
    else:
        raise AssertionError("Expected build failure to surface")


def _make_service(tmp_path: Path, *, phase_client) -> AgentRunnerService:
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
        phase_client=phase_client,
    )


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Codex"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "codex@example.com"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("test repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for condition")
