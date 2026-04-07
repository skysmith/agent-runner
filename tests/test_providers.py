from __future__ import annotations

import base64
from pathlib import Path

from agent_runner.codex_client import CodexExecResult
from agent_runner.models import ProviderKind
from agent_runner.providers import ExecutionRequest, ProviderRouter, _run_ollama_json, probe_ollama


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
    request.model = "qwen3-vl:4b"
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
    request.model = "qwen3:8b"
    request.prompt = (
        "Inspect this frame.\n\n"
        "Attached screenshot files (local paths):\n"
        f"- Screenshot: {screenshot} (image/png, 9 bytes)"
    )

    _run_ollama_json(request)

    assert "images" not in seen["body"]
