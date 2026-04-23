from __future__ import annotations

import base64
from pathlib import Path

from agent_runner.codex_client import CodexExecResult
from agent_runner.models import ProviderKind
from agent_runner.providers import ExecutionRequest, ProviderRouter, _run_ollama_builder_loop, _run_ollama_json, probe_ollama


def _request(provider: ProviderKind) -> ExecutionRequest:
    return ExecutionRequest(
        provider=provider,
        model="gpt-5.3-codex",
        prompt="{}",
        schema={"type": "object"},
        repo_path=Path("."),
        phase_name="planner",
        timeout_seconds=10,
        codex_bin="codex",
        extra_access_dir=None,
        ollama_host="http://127.0.0.1:11434",
        dry_run=False,
    )


def test_provider_router_routes_to_codex(monkeypatch) -> None:
    def fake_run_codex_json(**kwargs):
        return CodexExecResult(payload={"ok": True}, raw_jsonl="", stderr="", return_code=0)

    monkeypatch.setattr("agent_runner.providers.run_codex_json", fake_run_codex_json)
    router = ProviderRouter()
    result = router.run(_request(ProviderKind.CODEX))
    assert result.payload == {"ok": True}


def test_provider_router_routes_to_ollama(monkeypatch) -> None:
    def fake_ollama(request):
        return CodexExecResult(payload={"kind": "ollama"}, raw_jsonl="", stderr="", return_code=0)

    monkeypatch.setattr("agent_runner.providers._run_ollama_json", fake_ollama)
    router = ProviderRouter()
    result = router.run(_request(ProviderKind.OLLAMA))
    assert result.payload == {"kind": "ollama"}


def test_probe_ollama_unavailable(monkeypatch) -> None:
    def fake_http_json(url, body=None, timeout_seconds=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("agent_runner.providers._http_json", fake_http_json)
    probe = probe_ollama("http://127.0.0.1:11434")
    assert probe.available is False
    assert probe.models == []


def test_run_ollama_json_attaches_images_for_vision_models(monkeypatch, tmp_path: Path) -> None:
    screenshot = tmp_path / "frame.png"
    screenshot.write_bytes(b"png-bytes")
    seen: dict[str, object] = {}

    def fake_http_json(url, body=None, timeout_seconds=None):
        seen["url"] = url
        seen["body"] = body
        return {"response": '{"message":"looks off"}'}

    monkeypatch.setattr("agent_runner.providers._http_json", fake_http_json)
    request = _request(ProviderKind.OLLAMA)
    request.model = "qwen3.5:9b"
    request.prompt = (
        "Inspect this frame.\n\n"
        "Attached screenshot files (local paths):\n"
        f"- Screenshot: {screenshot} (image/png, 9 bytes)"
    )

    result = _run_ollama_json(request)

    assert result.payload == {"message": "looks off"}
    assert seen["url"] == "http://127.0.0.1:11434/api/generate"
    assert seen["body"]["images"] == [base64.b64encode(b"png-bytes").decode("ascii")]


def test_run_ollama_json_skips_images_for_text_models(monkeypatch, tmp_path: Path) -> None:
    screenshot = tmp_path / "frame.png"
    screenshot.write_bytes(b"png-bytes")
    seen: dict[str, object] = {}

    def fake_http_json(url, body=None, timeout_seconds=None):
        seen["body"] = body
        return {"response": '{"message":"text only"}'}

    monkeypatch.setattr("agent_runner.providers._http_json", fake_http_json)
    request = _request(ProviderKind.OLLAMA)
    request.model = "gemma4:e4b"
    request.prompt = (
        "Inspect this frame.\n\n"
        "Attached screenshot files (local paths):\n"
        f"- Screenshot: {screenshot} (image/png, 9 bytes)"
    )

    _run_ollama_json(request)

    assert "images" not in seen["body"]


def test_run_ollama_json_extracts_embedded_json_object(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_runner.providers._http_json",
        lambda url, body=None, timeout_seconds=None: {
            "response": 'Here is the result:\n{"message":"embedded"}\nThanks!'
        },
    )
    request = _request(ProviderKind.OLLAMA)
    request.model = "qwen3.5:9b"

    result = _run_ollama_json(request)

    assert result.payload == {"message": "embedded"}


def test_run_ollama_json_retries_after_invalid_first_response(monkeypatch) -> None:
    requests: list[dict[str, object] | None] = []
    responses = iter(
        [
            {"response": "I can help with that. The plan is to inspect the repo first."},
            {"response": '{"message":"recovered"}'},
        ]
    )

    def fake_http_json(url, body=None, timeout_seconds=None):
        requests.append(body)
        return next(responses)

    monkeypatch.setattr("agent_runner.providers._http_json", fake_http_json)
    request = _request(ProviderKind.OLLAMA)
    request.model = "qwen3.5:9b"

    result = _run_ollama_json(request)

    assert result.payload == {"message": "recovered"}
    assert len(requests) == 2
    assert "IMPORTANT: Your previous response was not parseable JSON." in str(requests[1]["prompt"])


def test_run_ollama_builder_loop_can_read_write_and_finalize(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("hello\n", encoding="utf-8")
    responses = iter(
        [
            {"response": '{"kind":"tool","tool_name":"read_file","tool_args":{"path":"hello.txt"}}'},
            {"response": '{"kind":"tool","tool_name":"write_file","tool_args":{"path":"hello.txt","content":"hello\\nworld\\n"}}'},
            {"response": '{"kind":"final","status":"ok","summary":"Updated hello.txt","files_touched":["hello.txt"],"commands_run":[],"notes":[]}'},
        ]
    )

    monkeypatch.setattr("agent_runner.providers._http_json", lambda url, body=None, timeout_seconds=None: next(responses))
    request = _request(ProviderKind.OLLAMA)
    request.model = "qwen3.5:9b"
    request.repo_path = tmp_path
    request.phase_name = "builder (step-1 attempt 1)"

    result = _run_ollama_builder_loop(request)

    assert target.read_text(encoding="utf-8") == "hello\nworld\n"
    assert result.payload["files_touched"] == ["hello.txt"]
    assert result.payload["summary"] == "Updated hello.txt"
    assert any("Diff summary: hello.txt" in note for note in result.payload["notes"])


def test_run_ollama_builder_loop_recovers_from_initial_refusal(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "app.txt"
    target.write_text("before\n", encoding="utf-8")
    responses = iter(
        [
            {"response": '{"kind":"final","status":"blocked","summary":"I cannot edit files from here.","files_touched":[],"commands_run":[],"notes":[]}'},
            {"response": '{"kind":"tool","tool_name":"write_file","tool_args":{"path":"app.txt","content":"after\\n"}}'},
            {"response": '{"kind":"final","status":"ok","summary":"Updated app.txt","files_touched":["app.txt"],"commands_run":[],"notes":[]}'},
        ]
    )

    monkeypatch.setattr("agent_runner.providers._http_json", lambda url, body=None, timeout_seconds=None: next(responses))
    request = _request(ProviderKind.OLLAMA)
    request.model = "qwen3.5:9b"
    request.repo_path = tmp_path
    request.phase_name = "builder (step-1 attempt 1)"

    result = _run_ollama_builder_loop(request)

    assert target.read_text(encoding="utf-8") == "after\n"
    assert result.payload["status"] == "ok"


def test_run_ollama_builder_loop_handles_invalid_tool_then_finishes(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("draft\n", encoding="utf-8")
    responses = iter(
        [
            {"response": '{"kind":"tool","tool_name":"explode_repo","tool_args":{}}'},
            {"response": '{"kind":"tool","tool_name":"write_file","tool_args":{"path":"notes.txt","content":"final\\n"}}'},
            {"response": '{"kind":"final","status":"ok","summary":"Updated notes","files_touched":["notes.txt"],"commands_run":[],"notes":[]}'},
        ]
    )

    monkeypatch.setattr("agent_runner.providers._http_json", lambda url, body=None, timeout_seconds=None: next(responses))
    request = _request(ProviderKind.OLLAMA)
    request.model = "qwen3.5:9b"
    request.repo_path = tmp_path
    request.phase_name = "builder (step-1 attempt 1)"

    result = _run_ollama_builder_loop(request)

    assert target.read_text(encoding="utf-8") == "final\n"
    assert result.payload["summary"] == "Updated notes"


def test_run_ollama_builder_loop_runs_only_selected_checks(monkeypatch, tmp_path: Path) -> None:
    responses = iter(
        [
            {
                "response": '{"kind":"tool","tool_name":"run_selected_check","tool_args":{"command":"python -c \\"print(123)\\""}}'
            },
            {"response": '{"kind":"final","status":"ok","summary":"Ran the selected check","files_touched":[],"commands_run":[],"notes":[]}'},
        ]
    )

    monkeypatch.setattr("agent_runner.providers._http_json", lambda url, body=None, timeout_seconds=None: next(responses))
    request = _request(ProviderKind.OLLAMA)
    request.model = "qwen3.5:9b"
    request.repo_path = tmp_path
    request.phase_name = "builder (step-1 attempt 1)"
    request.allowed_check_commands = ('python -c "print(123)"',)

    result = _run_ollama_builder_loop(request)

    assert result.payload["commands_run"] == ['python -c "print(123)"']
