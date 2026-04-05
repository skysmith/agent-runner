from __future__ import annotations

import time
from pathlib import Path
from threading import Event
import subprocess

from agent_runner.codex_client import CodexExecResult
from agent_runner.models import AssistantCapabilityMode, ProviderKind, RunMode
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


def test_service_blocks_second_active_run(tmp_path: Path) -> None:
    gate = Event()
    service = _make_service(tmp_path, phase_client=FakePhaseClient(gate=gate))
    first = service.create_conversation("workspace-1")
    second = service.create_conversation("workspace-2")

    service.send_message(
        workspace_id="workspace-1",
        conversation_id=str(first["id"]),
        content="First request",
        mode=RunMode.MESSAGE,
    )

    try:
        service.send_message(
            workspace_id="workspace-2",
            conversation_id=str(second["id"]),
            content="Second request",
            mode=RunMode.MESSAGE,
        )
    except RuntimeError as exc:
        assert "Another workspace is running" in str(exc)
    else:
        raise AssertionError("Expected second run to be blocked")

    gate.set()
    _wait_for(lambda: service.get_run_status()["state"] == "succeeded")


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
