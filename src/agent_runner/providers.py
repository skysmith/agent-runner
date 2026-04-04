from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .codex_client import CodexError, CodexExecResult, _parse_json_text, run_codex_json
from .models import ProviderKind


@dataclass(slots=True)
class ExecutionRequest:
    provider: ProviderKind
    model: str
    prompt: str
    schema: dict
    repo_path: Path
    phase_name: str
    timeout_seconds: int | None
    codex_bin: str
    extra_access_dir: Path | None
    ollama_host: str
    dry_run: bool


class PhaseExecutionClient(Protocol):
    def run(self, request: ExecutionRequest) -> CodexExecResult:
        ...


class ProviderRouter:
    def run(self, request: ExecutionRequest) -> CodexExecResult:
        if request.provider == ProviderKind.OLLAMA:
            return _run_ollama_json(request)
        return run_codex_json(
            codex_bin=request.codex_bin,
            model=request.model,
            prompt=request.prompt,
            schema=request.schema,
            repo_path=request.repo_path,
            extra_access_dir=request.extra_access_dir,
            dry_run=request.dry_run,
            timeout_seconds=request.timeout_seconds,
            phase_name=request.phase_name,
        )


@dataclass(slots=True)
class OllamaProbeResult:
    available: bool
    models: list[str]
    message: str


def probe_ollama(ollama_host: str, timeout_seconds: float = 1.5) -> OllamaProbeResult:
    version_url = _join_url(ollama_host, "/api/version")
    tags_url = _join_url(ollama_host, "/api/tags")
    try:
        _http_json(version_url, timeout_seconds=timeout_seconds)
    except Exception as exc:  # pragma: no cover - defensive network fallback
        return OllamaProbeResult(available=False, models=[], message=f"Ollama unavailable: {exc}")
    try:
        payload = _http_json(tags_url, timeout_seconds=timeout_seconds)
    except Exception as exc:  # pragma: no cover - defensive network fallback
        return OllamaProbeResult(available=True, models=[], message=f"Ollama reachable, model listing failed: {exc}")
    models = []
    raw_models = payload.get("models")
    if isinstance(raw_models, list):
        for model in raw_models:
            if isinstance(model, dict):
                name = model.get("name")
                if isinstance(name, str) and name:
                    models.append(name)
    return OllamaProbeResult(available=True, models=models, message="Ollama reachable.")


def _run_ollama_json(request: ExecutionRequest) -> CodexExecResult:
    if request.dry_run:
        return CodexExecResult(payload={}, raw_jsonl="", stderr="", return_code=0)
    url = _join_url(request.ollama_host, "/api/generate")
    body = {
        "model": request.model,
        "prompt": request.prompt,
        "stream": False,
        "format": request.schema,
    }
    try:
        payload = _http_json(url, body=body, timeout_seconds=request.timeout_seconds)
    except Exception as exc:
        raise CodexError(f"{request.phase_name} failed via Ollama: {exc}") from exc
    response_text = payload.get("response")
    parsed = _parse_json_text(response_text)
    if parsed is None:
        raise CodexError(f"{request.phase_name} via Ollama did not return parseable JSON.")
    return CodexExecResult(payload=parsed, raw_jsonl=json.dumps(payload), stderr="", return_code=0)


def _http_json(url: str, body: dict | None = None, timeout_seconds: float | None = None) -> dict:
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url=url, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("invalid JSON response") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("unexpected response format")
    return payload


def _join_url(base: str, path: str) -> str:
    return base.rstrip("/") + path
