from __future__ import annotations

import time
import json
from pathlib import Path
from threading import Event
import subprocess
from types import SimpleNamespace

from agent_runner.codex_client import CodexExecResult
from agent_runner.image_workflow import (
    GeneratedImageCandidate,
    ImageTo3DJobUpdate,
    MockImageTo3DProvider,
    MockImageToVideoProvider,
    StoredFile,
    default_mock_provider,
)
from agent_runner.models import AssistantCapabilityMode, BuildResult, ProviderKind, ReviewResult, RunMode, RunOutcome, StepRun
from agent_runner.providers import ProviderRouter
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


class FieldStationPhaseClient:
    def __init__(self) -> None:
        self.requests = []

    def run(self, request) -> CodexExecResult:
        self.requests.append(request)
        return CodexExecResult(
            payload={
                "title": "Moon Rover Puppet Plan",
                "summary": "A practical maker plan for the cardboard rover idea.",
                "artifact_markdown": "# Moon Rover Puppet Plan\n\n## Parts\n\n- cardboard\n- tape\n\n## Next Step\n\nBuild the base.",
                "evidence": ["Mode prompt used maker constraints.", "Permission lane stayed read-only."],
                "risks": ["Use scissors with supervision."],
                "suggested_next_action": "Approve the plan, then queue a parts checklist.",
            },
            raw_jsonl="",
            stderr="",
            return_code=0,
        )


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


def test_service_update_context_persists_thread_context(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient())
    conversation = service.create_conversation("workspace-1")
    conversation_id = str(conversation["id"])

    updated = service.update_conversation_context(
        conversation_id,
        workspace_id="workspace-1",
        thread_context={
            "channel": "sms",
            "thread_key": "+14352137423",
            "participant_name": "Taylor",
            "summary": "Launching a side project together.",
            "open_loops": ["Send the preview link"],
        },
    )

    assert updated["thread_context"]["channel"] == "sms"
    assert updated["thread_context"]["thread_key"] == "+14352137423"
    assert updated["thread_context"]["participant_name"] == "Taylor"
    assert updated["thread_context"]["open_loops"] == ["Send the preview link"]


def test_service_includes_thread_context_in_message_prompt(tmp_path: Path) -> None:
    client = RecordingPhaseClient(message="On it")
    service = _make_service(tmp_path, phase_client=client)
    conversation = service.create_conversation(
        "workspace-1",
        thread_context={
            "channel": "sms",
            "thread_key": "+14352137423",
            "participant_name": "Taylor",
            "summary": "Launching a side project together.",
            "open_loops": ["Send the preview link"],
        },
    )
    conversation_id = str(conversation["id"])

    service.send_message(
        workspace_id="workspace-1",
        conversation_id=conversation_id,
        content="Draft a quick reply",
        mode=RunMode.MESSAGE,
    )

    _wait_for(lambda: service.get_run_status()["state"] == "succeeded")
    prompt = client.requests[0].prompt
    assert "THREAD CONTEXT:" in prompt
    assert "- channel: sms" in prompt
    assert "- participant_name: Taylor" in prompt
    assert "Send the preview link" in prompt


def test_service_delivers_external_messages_into_existing_thread(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Reply ready"))

    first = service.deliver_external_message(
        workspace_id="workspace-1",
        content="Hey, did you send the link?",
        mode=RunMode.MESSAGE,
        thread_context={
            "channel": "sms",
            "thread_key": "+14352137423",
            "participant_name": "Taylor",
            "open_loops": ["Send the preview link"],
        },
    )
    second = service.deliver_external_message(
        workspace_id="workspace-1",
        content="Following up on that preview.",
        mode=RunMode.MESSAGE,
        thread_context={
            "channel": "sms",
            "thread_key": "+14352137423",
            "participant_name": "Taylor",
        },
    )

    assert first["created_conversation"] is True
    assert second["created_conversation"] is False
    assert first["conversation_id"] == second["conversation_id"]


def test_service_prefers_discovered_multimodal_model_for_screenshot_messages_on_ollama(monkeypatch, tmp_path: Path) -> None:
    client = RecordingPhaseClient(message="Visual review ready")
    service = _make_service(tmp_path, phase_client=client)
    service.app_settings.provider = ProviderKind.OLLAMA
    service.app_settings.model = "gemma4:e4b"
    service.app_settings.open_source_model = "gemma4:e4b"
    service.app_settings.vision_model = "qwen3.5:9b"
    monkeypatch.setattr(
        "agent_runner.service.probe_ollama",
        lambda host: type("Probe", (), {"models": ["llava:latest"], "available": True, "message": "ok"})(),
    )
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
        model="gemma4:e4b",
    )

    _wait_for(lambda: service.get_run_status()["state"] == "succeeded")
    assert client.requests
    assert client.requests[-1].model == "llava:latest"


def test_service_uses_single_pass_runner_for_dev_message_actions(monkeypatch, tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="should not be used"))
    service.app_settings.provider = ProviderKind.OLLAMA
    service.app_settings.model = "qwen3.5:9b"
    service.app_settings.open_source_model = "qwen3.5:9b"
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
        model="qwen3.5:9b",
    )

    _wait_for(lambda: service.get_run_status()["state"] == "succeeded")
    assert captured
    assert captured[-1].max_step_retries == 0
    record = service.get_conversation(conversation_id, workspace_id="workspace-1")
    assert "Applied grounded NPC physics." in record["messages"][-1]["content"]


def test_service_open_source_dev_message_updates_file_via_ollama_builder(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "widget.txt"
    target.write_text("before\n", encoding="utf-8")
    responses = iter(
        [
            {
                "response": json.dumps(
                    {
                        "assumptions": [],
                        "steps": [
                            {
                                "id": "step-1",
                                "title": "Update widget copy",
                                "instructions": "Edit widget.txt to say after.",
                                "done_criteria": ["widget.txt says after"],
                                "dependencies": [],
                            }
                        ],
                    }
                )
            },
            {"response": '{"kind":"tool","tool_name":"write_file","tool_args":{"path":"widget.txt","content":"after\\n"}}'},
            {"response": '{"kind":"final","status":"ok","summary":"Updated widget.txt","files_touched":["widget.txt"],"commands_run":[],"notes":[]}'},
            {
                "response": json.dumps(
                    {
                        "verdict": "pass",
                        "task_complete": True,
                        "step_complete": True,
                        "issues": [],
                        "guidance": "",
                    }
                )
            },
        ]
    )
    monkeypatch.setattr(
        "agent_runner.service.probe_ollama",
        lambda host: type("Probe", (), {"models": [], "available": False, "message": "unavailable"})(),
    )
    monkeypatch.setattr("agent_runner.providers._http_json", lambda url, body=None, timeout_seconds=None: next(responses))
    service = _make_service(tmp_path, phase_client=ProviderRouter())
    service.app_settings.provider = ProviderKind.OLLAMA
    service.app_settings.open_source_model = "qwen3.5:9b"
    service.app_settings.model = "qwen3.5:9b"
    conversation = service.create_conversation("workspace-1")
    conversation_id = str(conversation["id"])

    service.send_message(
        workspace_id="workspace-1",
        conversation_id=conversation_id,
        content="Please update widget.txt so it says after.",
        mode=RunMode.MESSAGE,
        assistant_mode=AssistantCapabilityMode.DEV,
        provider=ProviderKind.OLLAMA,
        model="qwen3.5:9b",
    )

    _wait_for(lambda: service.get_run_status()["state"] == "succeeded")
    assert target.read_text(encoding="utf-8") == "after\n"
    record = service.get_conversation(conversation_id, workspace_id="workspace-1")
    assert "Updated widget.txt" in record["messages"][-1]["content"]
    assert "widget.txt" in record["messages"][-1]["content"]


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

    station = service.create_studio_workspace(
        workspace_kind="field_station",
        artifact_title="Garage Console",
        template_kind="magic-button",
        theme_prompt="A calm tabletop AI workbench with a friendly face.",
    )["workspace"]
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

    assert station["workspace_kind"] == "field_station"
    assert station["artifact_title"] == "Garage Console"
    assert station["preview_state"] == "ready"
    assert (Path(str(station["repo_path"])) / "field-station.js").exists()
    assert "Field Station" in (Path(str(station["repo_path"])) / "index.html").read_text(encoding="utf-8")
    station_js = (Path(str(station["repo_path"])) / "field-station.js").read_text(encoding="utf-8")
    assert "/api/field-station/missions" in station_js
    assert "/api/field-station/jobs" in station_js
    assert 'provider: "codex"' in station_js
    assert "codex_handoff" in station_js
    assert "Artifact review drawer" in station_js
    assert "RTCPeerConnection" in station_js
    assert "/api/field-station/realtime-client-secret" in station_js
    assert "WAKE ALCOVE" in station_js
    assert "ALCOVE AWAKE" in station_js
    assert "START ALCOVE" not in station_js
    assert "Tap to cancel" in station_js
    assert "Mic permission did not finish" in station_js
    assert "waitForDataChannelOpen" in station_js
    assert "queueRealtimeAlcoveJob" in station_js
    assert "function_call_output" in station_js
    assert 'id="capture-button"' not in station_js
    assert ">MIC<" not in station_js
    assert "SpeechRecognition" in station_js
    assert "capture-diagnostics" in station_js
    assert "/api/field-station/captures" in station_js
    assert "/api/field-station/station-events" in station_js
    assert "/api/events/since" in station_js
    assert "Project library" in station_js
    assert "Button test" in station_js
    assert "capture-image-input" in station_js
    assert "camera-button" in station_js
    assert "/api/field-station/capture-assets" in station_js
    assert "queueDerivedJob" in station_js
    assert "data-state=\"idle\"" in station_js
    assert "Background jobs" in station_js
    assert "Review tray" in station_js
    assert "Owner briefing" in station_js
    assert "Read-only adapters" in station_js
    assert "/api/field-station/owner-briefings" in station_js
    assert "pendingReviews.length && reviewDrawerOpen" in station_js
    assert 'setStationState("needs-review", "Needs review")' not in station_js
    station_js_path = Path(str(station["repo_path"])) / "field-station.js"
    station_js_path.write_text("old generated preview", encoding="utf-8")
    refreshed_station = service.refresh_studio_preview(str(station["id"]))
    assert refreshed_station["preview_state"] == "ready"
    assert "Project library" in station_js_path.read_text(encoding="utf-8")

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


def test_field_station_orchestration_queues_fake_job_and_review_bundle(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Station ready"))
    workspace = service.create_studio_workspace(
        workspace_kind="field_station",
        artifact_title="Garage Console",
        template_kind="magic-button",
    )["workspace"]
    workspace_id = str(workspace["id"])

    created = service.create_field_station_mission(
        workspace_id=workspace_id,
        goal="Turn the cardboard rover idea into a build plan.",
        mode="maker",
        permission_lane="read-only",
        expected_output="project_plan",
    )
    mission = created["mission"]
    queued = service.create_field_station_job(
        workspace_id=workspace_id,
        mission_id=str(mission["id"]),
        provider="fake",
    )

    assert queued["job"]["status"] == "queued"
    _wait_for(lambda: service.get_field_station_snapshot(workspace_id)["reviews"])
    snapshot = service.get_field_station_snapshot(workspace_id)
    job = snapshot["jobs"][0]
    review = snapshot["reviews"][0]
    assert job["status"] == "needs_review"
    assert review["status"] == "pending"
    assert review["artifact_paths"]
    assert (service.conversation_store.workspace_dir(workspace_id) / str(review["artifact_paths"][0])).exists()

    approved = service.approve_field_station_review(workspace_id=workspace_id, review_id=str(review["id"]))
    assert approved["review"]["status"] == "approved"
    assert service.get_field_station_snapshot(workspace_id)["jobs"][0]["status"] == "succeeded"


def test_field_station_capture_library_and_button_bridge_queue_jobs(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Station ready"))
    workspace = service.create_studio_workspace(
        workspace_kind="field_station",
        artifact_title="Garage Console",
        template_kind="magic-button",
    )["workspace"]
    workspace_id = str(workspace["id"])

    capture_response = service.create_field_station_capture(
        workspace_id=workspace_id,
        mode="family",
        source="voice",
        text="Penny drew a moon fox. Turn it into a mission card.",
        metadata={"voice_state": "heard"},
    )
    capture = capture_response["capture"]
    mission = service.create_field_station_mission(
        workspace_id=workspace_id,
        goal="Penny drew a moon fox. Turn it into a mission card.",
        mode="family",
        capture_id=str(capture["id"]),
    )["mission"]

    assert mission["capture_id"] == capture["id"]
    assert mission["capture_snapshot"]["source"] == "voice"
    snapshot = service.get_field_station_snapshot(workspace_id)
    assert snapshot["captures"][0]["text"].startswith("Penny drew")
    assert snapshot["library"]["captures"][0]["id"] == capture["id"]
    assert snapshot["station"]["services"][0]["id"] == "button"

    bridge = service.trigger_field_station_station_event(
        workspace_id=workspace_id,
        event_type="button.capture",
        payload={
            "mode": "maker",
            "text": "Build a cardboard rover from the drawer parts.",
            "provider": "fake",
            "simulated": True,
        },
    )
    assert bridge["capture"]["source"] == "physical_button"
    assert bridge["mission"]["capture_id"] == bridge["capture"]["id"]
    assert bridge["job"]["status"] == "queued"
    _wait_for(lambda: service.get_field_station_snapshot(workspace_id)["reviews"])
    after = service.get_field_station_snapshot(workspace_id)
    assert after["library"]["artifacts"]
    assert any(event["type"] == "station.button.capture" for event in after["events"])

    asset = service.create_field_station_capture_asset(
        workspace_id=workspace_id,
        data_url="data:image/png;base64,aGVsbG8=",
        file_name="moon-fox.png",
        label="moon fox drawing",
        source="upload",
    )["attachment"]
    image_capture = service.create_field_station_capture(
        workspace_id=workspace_id,
        mode="family",
        source="camera",
        text="Use this drawing as the story seed.",
        attachments=[asset],
    )["capture"]
    assert image_capture["attachments"][0]["mime_type"] == "image/png"
    assert (service.conversation_store.workspace_dir(workspace_id) / str(asset["path"])).read_bytes() == b"hello"
    image_snapshot = service.get_field_station_snapshot(workspace_id)
    assert image_snapshot["library"]["captures"][0]["attachments"][0]["url"].startswith("/api/field-station/capture-assets")


def test_field_station_codex_worker_creates_mode_artifact_and_review_bundle(tmp_path: Path) -> None:
    phase_client = FieldStationPhaseClient()
    service = _make_service(tmp_path, phase_client=phase_client)
    workspace = service.create_studio_workspace(
        workspace_kind="field_station",
        artifact_title="Garage Console",
        template_kind="magic-button",
    )["workspace"]
    workspace_id = str(workspace["id"])
    asset = service.create_field_station_capture_asset(
        workspace_id=workspace_id,
        data_url="data:image/png;base64,aGVsbG8=",
        file_name="rover-parts.png",
        label="rover parts photo",
        source="upload",
    )["attachment"]
    capture = service.create_field_station_capture(
        workspace_id=workspace_id,
        mode="maker",
        source="upload",
        text="Turn the cardboard rover idea into a build plan.",
        attachments=[asset],
    )["capture"]

    created = service.create_field_station_mission(
        workspace_id=workspace_id,
        goal="Turn the cardboard rover idea into a build plan.",
        mode="maker",
        permission_lane="read-only",
        capture_id=str(capture["id"]),
    )
    mission = created["mission"]
    assert mission["expected_output"] == "project_plan"

    queued = service.create_field_station_job(
        workspace_id=workspace_id,
        mission_id=str(mission["id"]),
        provider="codex",
    )
    assert queued["job"]["provider"] == "codex"

    _wait_for(lambda: service.get_field_station_snapshot(workspace_id)["reviews"])
    snapshot = service.get_field_station_snapshot(workspace_id)
    job = snapshot["jobs"][0]
    review = snapshot["reviews"][0]
    artifact_path = service.conversation_store.workspace_dir(workspace_id) / str(review["artifact_paths"][0])

    assert job["status"] == "needs_review"
    assert job["result_metadata"]["provider"] == "codex"
    assert review["title"] == "Moon Rover Puppet Plan"
    assert "cardboard rover idea" in phase_client.requests[0].prompt
    assert "rover parts photo" in phase_client.requests[0].prompt
    assert phase_client.requests[0].phase_name == "field-station-codex"
    assert artifact_path.exists()
    assert "Build the base" in artifact_path.read_text(encoding="utf-8")
    artifact_payload = service.get_field_station_artifact(
        workspace_id=workspace_id,
        artifact_path=str(review["artifact_paths"][0]),
    )
    assert artifact_payload["file_name"].endswith(".md")
    assert "Moon Rover Puppet Plan" in artifact_payload["content"]


def test_field_station_owner_briefing_uses_read_only_source_adapters(tmp_path: Path) -> None:
    phase_client = RecordingPhaseClient(message="fallback please")
    service = _make_service(tmp_path, phase_client=phase_client)
    workspace = service.create_studio_workspace(
        workspace_kind="field_station",
        artifact_title="Garage Console",
        template_kind="magic-button",
    )["workspace"]
    workspace_id = str(workspace["id"])

    initial = service.get_field_station_snapshot(workspace_id)
    assert initial["owner_briefing"]["permission_lane"] == "read-only"
    assert any(source["id"] == "sample_ck_customer_threads" for source in initial["briefing_sources"])

    custom_source = service.create_field_station_briefing_source(
        workspace_id=workspace_id,
        kind="manual",
        label="Wholesale notes",
        summary="Read-only notes about two wholesale follow-ups waiting for owner attention.",
        sample_items=[
            {
                "title": "Boutique reorder question",
                "detail": "Draft a reply, but do not send it.",
                "urgency": "soon",
            }
        ],
    )["source"]

    queued = service.create_field_station_owner_briefing(
        workspace_id=workspace_id,
        source_ids=["sample_ck_customer_threads", custom_source["id"]],
        note="Focus on replies that need Sky today.",
        provider="codex",
    )

    assert queued["capture"]["source"] == "owner_briefing"
    assert queued["mission"]["mode"] == "business"
    assert queued["mission"]["expected_output"] == "owner_briefing"
    assert queued["mission"]["permission_lane"] == "read-only"
    assert queued["job"]["provider"] == "codex"
    assert len(queued["capture"]["metadata"]["briefing_sources"]) == 2

    _wait_for(lambda: service.get_field_station_snapshot(workspace_id)["reviews"])
    snapshot = service.get_field_station_snapshot(workspace_id)
    review = snapshot["reviews"][0]
    artifact = service.get_field_station_artifact(
        workspace_id=workspace_id,
        artifact_path=str(review["artifact_paths"][0]),
    )

    assert "Customer threads" in phase_client.requests[0].prompt
    assert "Wholesale notes" in phase_client.requests[0].prompt
    assert "Approval boundary" in phase_client.requests[0].prompt
    assert "## Briefing Sources" in artifact["content"]
    assert "Customer threads" in artifact["content"]
    assert "Wholesale notes" in artifact["content"]


def test_image_studio_runs_native_image_3d_and_video_workflow(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))

    created = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Figurine Lab",
        template_kind="image-gen",
        theme_prompt="Stylized collectible characters with clean silhouettes.",
    )

    workspace = created["workspace"]
    conversation = created["conversation"]
    assert workspace["workspace_kind"] == "studio_image"
    assert workspace["preview_url"] is None
    assert workspace["preview_state"] == "native"

    generated = service.generate_image_candidates(
        workspace_id=str(workspace["id"]),
        prompt="A toy astronaut figurine with soft studio lighting",
        count=3,
    )
    assert len(generated["images"]) == 3
    selected_image_id = str(generated["selected_image_id"])

    uploaded = service.upload_image_asset(
        workspace_id=str(workspace["id"]),
        file_name="source.png",
        mime_type="image/png",
        data=b"mock-png-bytes",
    )
    assert any(item["source"] == "upload" for item in uploaded["images"])

    animated = service.animate_image(
        workspace_id=str(workspace["id"]),
        source_image_id=selected_image_id,
    )
    assert animated["job_id"].startswith("job_")

    started = service.make_image_3d(
        workspace_id=str(workspace["id"]),
        source_image_id=selected_image_id,
    )
    assert started["job_id"].startswith("job_")

    _wait_for(
        lambda: any(
            item["status"] == "succeeded"
            for item in service.get_image_workflow_snapshot(str(workspace["id"]))["jobs"]
        )
    )
    _wait_for(
        lambda: any(
            item["status"] == "succeeded"
            for item in service.get_image_workflow_snapshot(str(workspace["id"]))["video_jobs"]
        )
    )
    snapshot = service.get_image_workflow_snapshot(str(workspace["id"]))
    assert snapshot["images"][0]["url"].startswith(f"/workspace-media/{workspace['id']}/")
    assert snapshot["jobs"][0]["artifacts"]["glb"].startswith(f"/workspace-media/{workspace['id']}/")
    assert snapshot["video_jobs"][0]["artifacts"]["mp4"].startswith(
        f"/workspace-media/{workspace['id']}/outputs/image_to_video/"
    )
    assert snapshot["video_jobs"][0]["artifacts"]["poster_png"].startswith(
        f"/workspace-media/{workspace['id']}/outputs/image_to_video/"
    )
    assert snapshot["video_jobs"][0]["artifacts"]["metadata_json"].startswith(
        f"/workspace-media/{workspace['id']}/outputs/image_to_video/"
    )
    assert snapshot["jobs"][0]["artifacts"]["input_png"].startswith(
        f"/workspace-media/{workspace['id']}/outputs/image_to_3d/"
    )
    assert snapshot["jobs"][0]["artifacts"]["preview_png"].startswith(
        f"/workspace-media/{workspace['id']}/outputs/image_to_3d/"
    )
    assert snapshot["jobs"][0]["artifacts"]["metadata_json"].startswith(
        f"/workspace-media/{workspace['id']}/outputs/image_to_3d/"
    )
    source_image = next(item for item in snapshot["images"] if item["id"] == selected_image_id)
    assert source_image["video_ready"] is True
    review = service.get_review_snapshot(
        conversation_id=str(conversation["id"]),
        workspace_id=str(workspace["id"]),
    )
    assert "image_workflow" in review


def test_image_studio_queues_image_generation_requests(tmp_path: Path) -> None:
    class BlockingRasterProvider:
        name = "blocking-raster"

        def __init__(self) -> None:
            self.started = Event()
            self.release = Event()
            self.prompts: list[str] = []

        def generate_images(self, *, prompt: str, count: int) -> list[GeneratedImageCandidate]:
            self.prompts.append(prompt)
            self.started.set()
            self.release.wait(timeout=2)
            return default_mock_provider().generate_images(prompt=prompt, count=count)

        def image_to_3d(self, *, image_path: Path, prompt_context: str | None = None):
            return default_mock_provider().image_to_3d(image_path=image_path, prompt_context=prompt_context)

    provider = BlockingRasterProvider()
    service = AgentRunnerService(
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
        phase_client=FakePhaseClient(message="Studio ready"),
        image_workflow_provider=provider,
        image_to_3d_provider=MockImageTo3DProvider(),
    )
    workspace = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Queue Lab",
        template_kind="image-gen",
    )["workspace"]

    first = service.queue_image_generation(
        workspace_id=str(workspace["id"]),
        prompt="first queued figurine",
        count=1,
    )
    assert first["accepted"] is True
    assert first["queued"] is False
    _wait_for(lambda: provider.started.is_set())

    second = service.queue_image_generation(
        workspace_id=str(workspace["id"]),
        prompt="second queued figurine",
        count=1,
    )
    assert second["accepted"] is True
    assert second["queued"] is True
    assert second["queue_position"] == 1

    queued_snapshot = service.get_image_workflow_snapshot(str(workspace["id"]))
    assert queued_snapshot["generation_queue"]["active"]["prompt_preview"] == "first queued figurine"
    assert queued_snapshot["generation_queue"]["active"]["started_at"]
    assert queued_snapshot["generation_queue"]["active"]["passes"] == 2
    assert queued_snapshot["generation_queue"]["items"][0]["prompt_preview"] == "second queued figurine"
    assert queued_snapshot["generation_queue"]["items"][0]["started_at"] is None

    provider.release.set()
    _wait_for(lambda: len(service.get_image_workflow_snapshot(str(workspace["id"]))["images"]) == 2)

    final_snapshot = service.get_image_workflow_snapshot(str(workspace["id"]))
    assert final_snapshot["generation_queue"]["running"] is False
    assert final_snapshot["generation_queue"]["count"] == 0
    assert final_snapshot["generation_queue"]["last_error"] in {"", None}
    assert provider.prompts == ["first queued figurine", "second queued figurine"]


def test_video_studio_creates_previewable_workspace(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))

    created = service.create_studio_workspace(
        workspace_kind="studio_video",
        artifact_title="Motion Lab",
        template_kind="video-gen",
        theme_prompt="Short motion studies and image-to-video experiments.",
    )

    workspace = created["workspace"]
    repo_path = Path(str(workspace["repo_path"]))

    assert workspace["workspace_kind"] == "studio_video"
    assert workspace["preview_state"] == "ready"
    assert workspace["preview_url"] == f"/studio/preview/{workspace['id']}/index.html"
    assert (repo_path / "video.js").exists()
    assert (repo_path / "index.html").exists()
    assert "Motion Lab Studio" == created["conversation"]["title"]


def test_image_studio_does_not_publish_static_preview(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))
    workspace = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Prop Forge",
        template_kind="image-gen",
    )["workspace"]

    refreshed = service.refresh_studio_preview(str(workspace["id"]))
    assert refreshed["preview_state"] == "native"
    assert refreshed["preview_url"] is None

    try:
        service.publish_studio_workspace(str(workspace["id"]))
    except ValueError as exc:
        assert "publish is not available" in str(exc)
    else:
        raise AssertionError("Expected Image Studio publish to be unavailable")


def test_image_studio_polls_image_to_3d_provider_jobs(tmp_path: Path) -> None:
    class Polling3DProvider:
        name = "polling-3d"

        def __init__(self) -> None:
            self.created_jobs: list[dict[str, object]] = []
            self.poll_count = 0
            self._output_dir: Path | None = None
            self._image_path: Path | None = None
            self._external_job_id = "polling-job-123"

        def create_job(self, *, image_path: Path, output_dir: Path, prompt_context: str | None = None) -> str:
            self.created_jobs.append(
                {
                    "image_path": image_path,
                    "output_dir": output_dir,
                    "prompt_context": prompt_context,
                }
            )
            self._output_dir = output_dir
            self._image_path = image_path
            return self._external_job_id

        def get_job_status(self, external_job_id: str) -> ImageTo3DJobUpdate:
            assert external_job_id == self._external_job_id
            self.poll_count += 1
            if self.poll_count == 1:
                return ImageTo3DJobUpdate(status="queued")
            if self.poll_count == 2:
                return ImageTo3DJobUpdate(status="running")
            assert self._output_dir is not None
            assert self._image_path is not None
            input_path = self._output_dir / "input.png"
            preview_path = self._output_dir / "preview.png"
            model_path = self._output_dir / "model.glb"
            metadata_path = self._output_dir / "metadata.json"
            self._output_dir.mkdir(parents=True, exist_ok=True)
            if not input_path.exists():
                input_path.write_bytes(self._image_path.read_bytes())
            if not preview_path.exists():
                preview_path.write_bytes(_tiny_png_bytes())
            if not model_path.exists():
                model_path.write_bytes(b"glTF")
            metadata_payload = {"generator": self.name, "mesh_faces": 12}
            metadata_path.write_text(json.dumps(metadata_payload), encoding="utf-8")
            return ImageTo3DJobUpdate(
                status="succeeded",
                artifacts={
                    "input_png": input_path,
                    "preview_png": preview_path,
                    "glb": model_path,
                    "metadata_json": metadata_path,
                },
                metadata=metadata_payload,
            )

    provider = Polling3DProvider()
    service = AgentRunnerService(
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
        phase_client=FakePhaseClient(message="Studio ready"),
        image_workflow_provider=default_mock_provider(),
        image_to_3d_provider=provider,
    )
    workspace = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Mesh Lab",
        template_kind="image-gen",
    )["workspace"]
    uploaded = service.upload_image_asset(
        workspace_id=str(workspace["id"]),
        file_name="source.png",
        mime_type="image/png",
        data=_tiny_png_bytes(),
    )

    started = service.make_image_3d(
        workspace_id=str(workspace["id"]),
        source_image_id=str(uploaded["selected_image_id"]),
    )
    assert started["job_id"].startswith("job_")

    _wait_for(
        lambda: any(
            item["status"] == "succeeded"
            for item in service.get_image_workflow_snapshot(str(workspace["id"]))["jobs"]
        )
    )
    snapshot = service.get_image_workflow_snapshot(str(workspace["id"]))
    assert snapshot["jobs"][0]["provider"] == "polling-3d"
    assert snapshot["jobs"][0]["provider_job_id"] == "polling-job-123"
    assert snapshot["jobs"][0]["artifacts"]["glb"].startswith(f"/workspace-media/{workspace['id']}/outputs/image_to_3d/")
    assert provider.poll_count >= 3
    assert provider.created_jobs[0]["prompt_context"] is None


def test_image_studio_auto_refine_retries_and_records_review_metadata(tmp_path: Path, monkeypatch) -> None:
    class RasterProvider:
        name = "test-raster"

        def __init__(self) -> None:
            self.prompts: list[str] = []

        def generate_images(self, *, prompt: str, count: int) -> list[GeneratedImageCandidate]:
            self.prompts.append(prompt)
            return [
                GeneratedImageCandidate(
                    label="Candidate 1",
                    file=StoredFile(
                        file_name="candidate.png",
                        mime_type="image/png",
                        data=_tiny_png_bytes(),
                    ),
                    metadata={"provider": self.name},
                )
            ]

        def image_to_3d(self, *, image_path: Path, prompt_context: str | None = None):
            return default_mock_provider().image_to_3d(image_path=image_path, prompt_context=prompt_context)

    review_results = iter(
        [
            {
                "review_status": "fail",
                "overall_score": 0.48,
                "notes": "Subject feels muddy.",
                "judge_model": "qwen3.5:9b",
            },
            {
                "review_status": "pass",
                "overall_score": 0.89,
                "notes": "Much clearer.",
                "judge_model": "qwen3.5:9b",
            },
        ]
    )
    monkeypatch.setattr("agent_runner.image_workflow.list_local_ollama_models", lambda: {"qwen3.5:9b"})
    monkeypatch.setattr("agent_runner.image_workflow.review_generated_candidate", lambda **kwargs: next(review_results))
    monkeypatch.setattr(
        "agent_runner.image_workflow.rewrite_prompt_from_review",
        lambda **kwargs: f"{kwargs['current_prompt']}, clearer focal point",
    )

    service = AgentRunnerService(
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
        phase_client=FakePhaseClient(message="Studio ready"),
        image_workflow_provider=RasterProvider(),
        image_to_3d_provider=MockImageTo3DProvider(),
    )
    created = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Refine Lab",
        template_kind="image-gen",
    )

    generated = service.generate_image_candidates(
        workspace_id=str(created["workspace"]["id"]),
        prompt="Toy astronaut figurine",
        auto_refine={"enabled": True, "threshold": 0.72, "max_retries": 1},
    )

    image = generated["images"][0]
    assert image["review_status"] == "pass"
    assert image["review_attempts"] == 2
    assert "Much clearer." in str(image["review_notes"])
    assert service._image_workflow_provider.prompts == [
        "Toy astronaut figurine",
        "Toy astronaut figurine, clearer focal point",
    ]


def test_image_studio_describes_reference_and_uses_small_generation_profiles(tmp_path: Path, monkeypatch) -> None:
    seen_describe_kwargs: dict[str, object] = {}

    def fake_describe_reference(**kwargs):
        seen_describe_kwargs.update(kwargs)
        return {
            "source_image_name": kwargs["image_path"].name,
            "vision_model": "qwen3.5:9b",
            "prompt_model": "qwen3.5:9b",
            "reference": {
                "subject": "teenage boy in military attire",
                "scene": "snowy military encampment at dusk",
                "composition": "full-body central portrait with campfires behind him",
                "palette": "cool blue-gray with warm firelight",
                "lighting": "dusky ambient light with orange campfire glow",
                "style": "painterly realism",
                "mood": "somber and weary",
                "important_details": ["tents", "snow", "campfires"],
                "recreation_prompt": "teenage boy in a blue-gray coat standing in a snowy encampment at dusk",
            },
            "reference_summary": "teenage boy in a snowy military encampment at dusk, with a somber and weary tone.",
            "suggested_prompt": "teenage boy in a blue-gray coat standing in a snowy encampment at dusk",
            "notes": "Loaded into the generator.",
            "raw_reference_response": "{}",
            "raw_prompt_response": "{}",
        }

    monkeypatch.setattr(
        "agent_runner.service.describe_reference_image",
        fake_describe_reference,
    )
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))
    workspace = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Reference Lab",
        template_kind="image-gen",
    )["workspace"]
    uploaded = service.upload_image_asset(
        workspace_id=str(workspace["id"]),
        file_name="reference.png",
        mime_type="image/png",
        data=_tiny_png_bytes(),
    )

    described = service.describe_image_reference(
        workspace_id=str(workspace["id"]),
        source_image_id=str(uploaded["selected_image_id"]),
    )
    assert described["reference"]["suggested_prompt"] == "teenage boy in a blue-gray coat standing in a snowy encampment at dusk"
    assert "preferred_vision_model" in seen_describe_kwargs
    assert "preferred_prompt_model" in seen_describe_kwargs

    generated = service.generate_image_candidates(
        workspace_id=str(workspace["id"]),
        prompt=described["reference"]["suggested_prompt"],
        count=1,
        size_profile_id="square-768x768",
    )

    image = generated["images"][0]
    assert image["metadata"]["size_profile_id"] == "square-768x768"
    assert image["metadata"]["width"] == 768
    assert image["metadata"]["height"] == 768

    snapshot = service.get_image_workflow_snapshot(str(workspace["id"]))
    assert snapshot["default_generation_count"] == 1
    assert snapshot["generation_count_options"] == [1, 2, 3, 4]
    assert snapshot["default_generation_profile_id"] == "portrait-768x1024"
    assert snapshot["generation_profiles"][0]["id"] == "portrait-768x1024"
    assert snapshot["default_generation_passes"] == 2
    assert snapshot["generation_pass_options"] == [2, 4, 8, 10, 12, 16, 20]


def test_image_studio_passes_requested_step_count_to_provider(tmp_path: Path) -> None:
    class PassRecordingProvider:
        name = "pass-recorder"

        def __init__(self) -> None:
            self.requests: list[dict[str, object]] = []

        def generate_images(self, *, prompt: str, count: int, size_profile_id: str | None = None, passes: int | None = None):
            self.requests.append(
                {
                    "prompt": prompt,
                    "count": count,
                    "size_profile_id": size_profile_id,
                    "passes": passes,
                }
            )
            return [
                GeneratedImageCandidate(
                    label="Candidate 1",
                    file=StoredFile(
                        file_name="candidate.png",
                        mime_type="image/png",
                        data=_tiny_png_bytes(),
                    ),
                    metadata={"provider": self.name, "steps": passes},
                )
            ]

    provider = PassRecordingProvider()
    service = AgentRunnerService(
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
        phase_client=FakePhaseClient(message="Studio ready"),
        image_workflow_provider=provider,
        image_to_3d_provider=MockImageTo3DProvider(),
        image_to_video_provider=MockImageToVideoProvider(),
    )
    workspace = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Pass Lab",
        template_kind="image-gen",
    )["workspace"]

    generated = service.generate_image_candidates(
        workspace_id=str(workspace["id"]),
        prompt="Painted explorer figurine",
        count=1,
        passes=20,
    )

    assert provider.requests[0]["passes"] == 20
    assert generated["images"][0]["metadata"]["steps"] == 20
    assert isinstance(generated["images"][0]["metadata"]["generation_duration_ms"], int)


def test_image_studio_defaults_generation_count_to_one(tmp_path: Path) -> None:
    class CountRecordingProvider:
        name = "count-recorder"

        def __init__(self) -> None:
            self.requests: list[dict[str, object]] = []

        def generate_images(self, *, prompt: str, count: int, size_profile_id: str | None = None, passes: int | None = None):
            self.requests.append(
                {
                    "prompt": prompt,
                    "count": count,
                    "size_profile_id": size_profile_id,
                    "passes": passes,
                }
            )
            return [
                GeneratedImageCandidate(
                    label="Candidate 1",
                    file=StoredFile(
                        file_name="candidate.png",
                        mime_type="image/png",
                        data=_tiny_png_bytes(),
                    ),
                    metadata={"provider": self.name},
                )
            ]

    provider = CountRecordingProvider()
    service = AgentRunnerService(
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
        phase_client=FakePhaseClient(message="Studio ready"),
        image_workflow_provider=provider,
        image_to_3d_provider=MockImageTo3DProvider(),
        image_to_video_provider=MockImageToVideoProvider(),
    )
    workspace = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Count Lab",
        template_kind="image-gen",
    )["workspace"]

    generated = service.generate_image_candidates(
        workspace_id=str(workspace["id"]),
        prompt="Painted explorer figurine",
    )

    assert provider.requests[0]["count"] == 1
    assert len(generated["images"]) == 1


def test_image_studio_opens_asset_folder(tmp_path: Path, monkeypatch) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))
    workspace = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Folder Lab",
        template_kind="image-gen",
    )["workspace"]
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("agent_runner.service.subprocess.run", fake_run)

    opened = service.open_image_asset_folder(workspace_id=str(workspace["id"]))

    assert opened["workspace_id"] == str(workspace["id"])
    assert opened["opened"] is True
    assert Path(str(opened["folder_path"])).exists()
    assert captured["cmd"][0] in {"open", "xdg-open", "explorer"}


def test_image_studio_imports_asset_from_local_path(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))
    workspace = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Drop Lab",
        template_kind="image-gen",
    )["workspace"]
    source = tmp_path / "finder-drop.png"
    source.write_bytes(_tiny_png_bytes())

    imported = service.import_image_asset_from_path(
        workspace_id=str(workspace["id"]),
        image_path=str(source),
    )

    assert imported["selected_image_id"]
    selected = next(item for item in imported["images"] if item["id"] == imported["selected_image_id"])
    assert selected["source"] == "upload"
    assert selected["label"] == "finder-drop"


def test_image_studio_deletes_image_asset_and_related_outputs(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))
    workspace = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Delete Lab",
        template_kind="image-gen",
    )["workspace"]
    workspace_id = str(workspace["id"])

    generated = service.generate_image_candidates(
        workspace_id=workspace_id,
        prompt="Painted explorer figurine",
        count=1,
    )
    source_image_id = str(generated["selected_image_id"])
    service.make_image_3d(workspace_id=workspace_id, source_image_id=source_image_id)
    _wait_for(
        lambda: any(
            item["status"] == "succeeded"
            for item in service.get_image_workflow_snapshot(workspace_id)["jobs"]
        )
    )

    store = service._image_store(workspace_id)
    asset = store.get_asset(source_image_id)
    asset_path = store.asset_path(asset)
    job_output_dirs = [service.conversation_store.workspace_dir(workspace_id) / job.output_dir for job in store.list_jobs()]

    deleted = service.delete_image_asset(workspace_id=workspace_id, image_id=source_image_id)

    assert deleted["selected_image_id"] is None
    assert all(item["id"] != source_image_id for item in deleted["images"])
    assert all(item["source_image_id"] != source_image_id for item in deleted["jobs"])
    assert not asset_path.exists()
    assert all(not output_dir.exists() for output_dir in job_output_dirs)


def test_image_studio_snapshot_prunes_missing_source_files(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))
    workspace = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Prune Lab",
        template_kind="image-gen",
    )["workspace"]
    workspace_id = str(workspace["id"])

    generated = service.generate_image_candidates(
        workspace_id=workspace_id,
        prompt="Painted explorer figurine",
        count=1,
    )
    source_image_id = str(generated["selected_image_id"])
    service.make_image_3d(workspace_id=workspace_id, source_image_id=source_image_id)
    _wait_for(
        lambda: any(
            item["status"] == "succeeded"
            for item in service.get_image_workflow_snapshot(workspace_id)["jobs"]
        )
    )

    store = service._image_store(workspace_id)
    asset = store.get_asset(source_image_id)
    asset_path = store.asset_path(asset)
    job_output_dirs = [service.conversation_store.workspace_dir(workspace_id) / job.output_dir for job in store.list_jobs()]

    asset_path.unlink()
    snapshot = service.get_image_workflow_snapshot(workspace_id)

    assert snapshot["selected_image_id"] is None
    assert all(item["id"] != source_image_id for item in snapshot["images"])
    assert all(item["source_image_id"] != source_image_id for item in snapshot["jobs"])
    assert all(not output_dir.exists() for output_dir in job_output_dirs)


def test_image_studio_keeps_composition_with_backend_managed_seed(tmp_path: Path) -> None:
    service = _make_service(tmp_path, phase_client=FakePhaseClient(message="Studio ready"))
    workspace = service.create_studio_workspace(
        workspace_kind="studio_image",
        artifact_title="Seed Lab",
        template_kind="image-gen",
    )["workspace"]

    first = service.generate_image_candidates(
        workspace_id=str(workspace["id"]),
        prompt="Painted explorer figurine",
        count=1,
        size_profile_id="portrait-768x1024",
    )
    source_image = first["images"][0]

    second = service.generate_image_candidates(
        workspace_id=str(workspace["id"]),
        prompt="Painted explorer figurine with brighter rim light",
        count=1,
        size_profile_id="portrait-768x1024",
        composition_source_image_id=str(source_image["id"]),
        remix_mode="remix",
    )

    remixed = second["images"][0]
    assert remixed["metadata"]["composition_source_image_id"] == source_image["id"]
    assert remixed["metadata"]["composition_source_label"] == source_image["label"]
    assert remixed["metadata"]["seed_reused"] is True
    assert remixed["metadata"]["generation_mode"] == "remix"
    assert remixed["metadata"]["init_image_used"] is True
    assert remixed["metadata"]["seed"] == source_image["metadata"]["seed"]


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
        image_workflow_provider=default_mock_provider(),
        image_to_3d_provider=MockImageTo3DProvider(),
        image_to_video_provider=MockImageToVideoProvider(),
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


def _tiny_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x04\x00\x01"
        b"\x0b\xe7\x02\x9d"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
