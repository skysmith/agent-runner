from __future__ import annotations

import base64
import difflib
import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

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
    allowed_check_commands: tuple[str, ...] = field(default_factory=tuple)


class PhaseExecutionClient(Protocol):
    def run(self, request: ExecutionRequest) -> CodexExecResult:
        ...


class ProviderRouter:
    def run(self, request: ExecutionRequest) -> CodexExecResult:
        if request.provider == ProviderKind.OLLAMA:
            if request.phase_name.lower().startswith("builder"):
                return _run_ollama_builder_loop(request)
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


VISION_MODEL_HINTS = ("vl", "vision", "llava", "bakllava", "minicpm", "moondream")
CODEX_MODEL_HINTS = ("gpt-", "codex")
OLLAMA_MODEL_HINTS = (
    ":",
    "qwen",
    "llama",
    "llava",
    "gemma",
    "mistral",
    "phi",
    "deepseek",
    "minicpm",
    "moondream",
    "bakllava",
)
OFFICIAL_MULTIMODAL_MODEL_PREFIXES = ("qwen3.5",)
MAX_OLLAMA_TOOL_ROUNDS = 12
MAX_OLLAMA_JSON_ATTEMPTS = 2
MAX_REPO_SEARCH_RESULTS = 20
MAX_FILE_READ_CHARS = 24000
MAX_TOOL_RESULT_CHARS = 6000


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
    prompt = request.prompt
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, MAX_OLLAMA_JSON_ATTEMPTS + 1):
        payload = _ollama_generate_json(
            ollama_host=request.ollama_host,
            model=request.model,
            prompt=prompt,
            schema=request.schema,
            timeout_seconds=request.timeout_seconds,
        )
        response_text = str(payload.get("response") or "")
        parsed = _parse_json_text(response_text)
        attempts.append(
            {
                "attempt": attempt,
                "response": response_text,
                "parsed": parsed,
            }
        )
        if parsed is not None:
            return CodexExecResult(
                payload=parsed,
                raw_jsonl=json.dumps({"attempts": attempts}, ensure_ascii=False),
                stderr="",
                return_code=0,
            )
        if attempt < MAX_OLLAMA_JSON_ATTEMPTS:
            prompt = _ollama_json_retry_prompt(request, response_text)
    raise CodexError(f"{request.phase_name} via Ollama did not return parseable JSON.")


def _run_ollama_builder_loop(request: ExecutionRequest) -> CodexExecResult:
    if request.dry_run:
        return CodexExecResult(payload={}, raw_jsonl="", stderr="", return_code=0)
    executor = _OllamaBuilderExecutor(request)
    final_payload, transcript = executor.run()
    return CodexExecResult(
        payload=final_payload,
        raw_jsonl=json.dumps({"events": transcript}, ensure_ascii=False),
        stderr="",
        return_code=0,
    )


class _OllamaBuilderExecutor:
    def __init__(self, request: ExecutionRequest) -> None:
        self.request = request
        self.repo_path = request.repo_path.resolve()
        self.changed_files: list[str] = []
        self.commands_run: list[str] = []
        self.diff_notes: dict[str, str] = {}
        self.history: list[dict[str, Any]] = []
        self.transcript: list[dict[str, Any]] = []
        self.refusal_retried = False

    def run(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        system_prompt = _ollama_builder_system_prompt(self.request)
        repo_context = _builder_repo_context(self.repo_path, self.request.prompt)
        for round_index in range(1, MAX_OLLAMA_TOOL_ROUNDS + 1):
            prompt = _render_builder_loop_prompt(system_prompt, repo_context, self.history)
            payload = _ollama_generate_json(
                ollama_host=self.request.ollama_host,
                model=self.request.model,
                prompt=prompt,
                schema=_ollama_builder_action_schema(),
                timeout_seconds=self.request.timeout_seconds,
            )
            response_text = str(payload.get("response") or "").strip()
            parsed = _parse_json_text(response_text)
            self.transcript.append(
                {
                    "round": round_index,
                    "response": response_text,
                    "parsed": parsed,
                }
            )
            if parsed is None:
                self._append_tool_feedback(
                    tool_name="invalid_json",
                    args={},
                    result={
                        "ok": False,
                        "error": "Return JSON matching the required schema. Plain text is not valid here.",
                    },
                )
                continue
            kind = str(parsed.get("kind") or "").strip().lower()
            if kind == "tool":
                tool_name = str(parsed.get("tool_name") or "").strip()
                tool_args = parsed.get("tool_args")
                if not isinstance(tool_args, dict):
                    tool_args = {}
                result = self._execute_tool(tool_name, tool_args)
                self._append_tool_feedback(tool_name=tool_name, args=tool_args, result=result)
                continue
            if kind == "final":
                if self._looks_like_refusal(parsed, response_text):
                    if not self.refusal_retried:
                        self.refusal_retried = True
                        self.history.append(
                            {
                                "type": "tool_result",
                                "tool_name": "access_correction",
                                "result": {
                                    "ok": False,
                                    "error": (
                                        "Do not refuse for lack of repo access. You can use search_repo, list_dir, "
                                        "read_file, write_file, and run_selected_check inside this workspace."
                                    ),
                                },
                            }
                        )
                        continue
                    raise CodexError(
                        f"{self.request.phase_name} via Ollama refused the coding task after a corrective retry."
                    )
                return self._normalize_final_payload(parsed), self.transcript
            self._append_tool_feedback(
                tool_name="invalid_kind",
                args={"kind": kind},
                result={"ok": False, "error": "Use kind='tool' while gathering info, or kind='final' when done."},
            )
        raise CodexError(f"{self.request.phase_name} via Ollama exhausted the local tool loop without finishing.")

    def _append_tool_feedback(self, *, tool_name: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        self.history.append({"type": "assistant_action", "tool_name": tool_name, "args": args})
        self.history.append({"type": "tool_result", "tool_name": tool_name, "result": result})

    def _execute_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "search_repo":
            return self._tool_search_repo(args)
        if tool_name == "list_dir":
            return self._tool_list_dir(args)
        if tool_name == "read_file":
            return self._tool_read_file(args)
        if tool_name == "write_file":
            return self._tool_write_file(args)
        if tool_name == "run_selected_check":
            return self._tool_run_selected_check(args)
        return {"ok": False, "error": f"Unknown tool '{tool_name}'."}

    def _tool_search_repo(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "search_repo requires a non-empty 'query'."}
        max_results = args.get("max_results")
        try:
            limit = max(1, min(int(max_results), MAX_REPO_SEARCH_RESULTS))
        except (TypeError, ValueError):
            limit = MAX_REPO_SEARCH_RESULTS
        try:
            proc = subprocess.run(
                [
                    "rg",
                    "-n",
                    "--hidden",
                    "--glob",
                    "!.git",
                    "--glob",
                    "!.agent-runner",
                    "-m",
                    str(limit),
                    query,
                    ".",
                ],
                cwd=self.repo_path,
                text=True,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError:
            return {"ok": False, "error": "ripgrep (rg) is not available in this environment."}
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        if proc.returncode not in {0, 1}:
            return {"ok": False, "error": (proc.stderr or "repo search failed").strip()}
        return {
            "ok": True,
            "query": query,
            "matches": lines[:limit],
            "match_count": len(lines[:limit]),
        }

    def _tool_list_dir(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            path = self._resolve_relative_path(str(args.get("path") or "."))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if not path.exists():
            return {"ok": False, "error": f"Path does not exist: {path.relative_to(self.repo_path)}"}
        if not path.is_dir():
            return {"ok": False, "error": f"Path is not a directory: {path.relative_to(self.repo_path)}"}
        entries = []
        for child in sorted(path.iterdir(), key=lambda item: item.name.lower())[:80]:
            entries.append(
                {
                    "name": str(child.relative_to(self.repo_path)),
                    "kind": "dir" if child.is_dir() else "file",
                }
            )
        return {
            "ok": True,
            "path": str(path.relative_to(self.repo_path)),
            "entries": entries,
        }

    def _tool_read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        file_path_raw = str(args.get("path") or "").strip()
        if not file_path_raw:
            return {"ok": False, "error": "read_file requires 'path'."}
        try:
            path = self._resolve_relative_path(file_path_raw)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if not path.exists() or not path.is_file():
            return {"ok": False, "error": f"File not found: {file_path_raw}"}
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {"ok": False, "error": f"File is not UTF-8 text: {file_path_raw}"}
        truncated = False
        if len(text) > MAX_FILE_READ_CHARS:
            text = text[:MAX_FILE_READ_CHARS]
            truncated = True
        return {
            "ok": True,
            "path": str(path.relative_to(self.repo_path)),
            "content": text,
            "truncated": truncated,
        }

    def _tool_write_file(self, args: dict[str, Any]) -> dict[str, Any]:
        file_path_raw = str(args.get("path") or "").strip()
        if not file_path_raw:
            return {"ok": False, "error": "write_file requires 'path'."}
        if "content" not in args:
            return {"ok": False, "error": "write_file requires full-file 'content'."}
        content = args.get("content")
        if not isinstance(content, str):
            return {"ok": False, "error": "write_file content must be a string."}
        try:
            path = self._resolve_relative_path(file_path_raw, allow_missing=True)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        before = ""
        existed = path.exists()
        if existed:
            try:
                before = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return {"ok": False, "error": f"File is not UTF-8 text: {file_path_raw}"}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        relative_path = str(path.relative_to(self.repo_path))
        if relative_path not in self.changed_files:
            self.changed_files.append(relative_path)
        self.diff_notes[relative_path] = _compact_diff_summary(relative_path, before, content)
        return {
            "ok": True,
            "path": relative_path,
            "created": not existed,
            "changed": before != content,
            "bytes": len(content.encode("utf-8")),
        }

    def _tool_run_selected_check(self, args: dict[str, Any]) -> dict[str, Any]:
        command = str(args.get("command") or "").strip()
        if not command:
            return {"ok": False, "error": "run_selected_check requires 'command'."}
        if command not in self.request.allowed_check_commands:
            allowed = list(self.request.allowed_check_commands)
            return {
                "ok": False,
                "error": f"Command not allowed. Allowed commands: {allowed if allowed else 'none'}",
            }
        timeout_seconds = self.request.timeout_seconds
        try:
            proc = subprocess.run(
                command,
                shell=True,
                text=True,
                capture_output=True,
                cwd=self.repo_path,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Check timed out: {command}"}
        if command not in self.commands_run:
            self.commands_run.append(command)
        return {
            "ok": True,
            "command": command,
            "return_code": proc.returncode,
            "stdout": _truncate_text(proc.stdout, MAX_TOOL_RESULT_CHARS),
            "stderr": _truncate_text(proc.stderr, MAX_TOOL_RESULT_CHARS),
        }

    def _resolve_relative_path(self, raw_path: str, *, allow_missing: bool = False) -> Path:
        candidate = Path(raw_path.strip())
        if not raw_path.strip():
            raise ValueError("Path cannot be empty.")
        if candidate.is_absolute():
            raise ValueError("Use repo-relative paths only.")
        path = (self.repo_path / candidate).resolve()
        try:
            path.relative_to(self.repo_path)
        except ValueError as exc:
            raise ValueError("Path must stay inside the repo root.") from exc
        if not allow_missing and not path.exists():
            raise ValueError(f"Path does not exist: {candidate}")
        return path

    def _normalize_final_payload(self, parsed: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "status": _string_or_default(parsed.get("status"), "ok"),
            "summary": _string_or_default(
                parsed.get("summary"),
                "Updated the repository with the open-source coding executor.",
            ),
            "files_touched": _normalize_string_list(parsed.get("files_touched")),
            "commands_run": _normalize_string_list(parsed.get("commands_run")),
            "notes": _normalize_string_list(parsed.get("notes")),
        }
        for path in self.changed_files:
            if path not in payload["files_touched"]:
                payload["files_touched"].append(path)
        for command in self.commands_run:
            if command not in payload["commands_run"]:
                payload["commands_run"].append(command)
        for path in self.changed_files:
            note = self.diff_notes.get(path)
            if note and note not in payload["notes"]:
                payload["notes"].append(note)
        missing_keys = [key for key in ("status", "summary", "files_touched", "commands_run", "notes") if key not in payload]
        if missing_keys:
            raise CodexError(f"{self.request.phase_name} via Ollama returned an incomplete final payload.")
        return payload

    def _looks_like_refusal(self, parsed: dict[str, Any], response_text: str) -> bool:
        candidates = [response_text, str(parsed.get("summary") or ""), str(parsed.get("status") or "")]
        refusal_markers = (
            "can't edit",
            "cannot edit",
            "can't modify",
            "cannot modify",
            "no access",
            "don't have access",
            "unable to access",
            "unable to edit",
        )
        return any(marker in text.lower() for text in candidates for marker in refusal_markers)


def _ollama_generate_json(
    *,
    ollama_host: str,
    model: str,
    prompt: str,
    schema: dict,
    timeout_seconds: int | None,
) -> dict:
    url = _join_url(ollama_host, "/api/generate")
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": schema,
    }
    if model_supports_images(model):
        images = _ollama_images_from_prompt(prompt)
        if images:
            body["images"] = images
    try:
        return _http_json(url, body=body, timeout_seconds=timeout_seconds)
    except Exception as exc:
        raise CodexError(f"Ollama request failed: {exc}") from exc


def _ollama_builder_action_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind"],
        "properties": {
            "kind": {"type": "string", "enum": ["tool", "final"]},
            "tool_name": {"type": "string"},
            "tool_args": {"type": "object"},
            "status": {"type": "string"},
            "summary": {"type": "string"},
            "files_touched": {"type": "array", "items": {"type": "string"}},
            "commands_run": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "array", "items": {"type": "string"}},
        },
    }


def _ollama_json_retry_prompt(request: ExecutionRequest, invalid_response: str) -> str:
    invalid_excerpt = _truncate_text(invalid_response.strip(), 2000) or "(empty response)"
    schema_text = json.dumps(request.schema, indent=2, sort_keys=True)
    return (
        f"{request.prompt.rstrip()}\n\n"
        "IMPORTANT: Your previous response was not parseable JSON.\n"
        "Reply again with ONLY one JSON object that matches the schema exactly.\n"
        "Do not include markdown fences, explanations, or any text before or after the JSON.\n\n"
        "REQUIRED OUTPUT SCHEMA:\n"
        f"{schema_text}\n\n"
        "PREVIOUS INVALID RESPONSE:\n"
        f"{invalid_excerpt}\n"
    )


def _ollama_builder_system_prompt(request: ExecutionRequest) -> str:
    checks = "\n".join(f"- {command}" for command in request.allowed_check_commands) or "- none"
    return (
        "You are the BUILDER for a local coding workspace running through Ollama.\n"
        "You can inspect and edit the repository by requesting tools.\n"
        "Never refuse for lack of access; use the available tools instead.\n\n"
        "Available tools:\n"
        "- search_repo: {\"query\": \"text or regex\", \"max_results\": 20}\n"
        "- list_dir: {\"path\": \".\"}\n"
        "- read_file: {\"path\": \"relative/path\"}\n"
        "- write_file: {\"path\": \"relative/path\", \"content\": \"full file contents\"}\n"
        "- run_selected_check: {\"command\": \"exact check command from the list below\"}\n\n"
        "Rules:\n"
        "- Use repo-relative paths only.\n"
        "- write_file must send the complete final file contents, not a patch.\n"
        "- Keep actions bounded and relevant to the task.\n"
        "- When you are done, return kind=\"final\" with status, summary, files_touched, commands_run, and notes.\n"
        "- Return only JSON.\n\n"
        "Allowed check commands:\n"
        f"{checks}\n\n"
        "Task instructions:\n"
        f"{request.prompt.strip()}\n"
    )


def _render_builder_loop_prompt(
    system_prompt: str,
    repo_context: str,
    history: list[dict[str, Any]],
) -> str:
    lines = [system_prompt.strip()]
    if repo_context:
        lines.extend(["", "Repo context:", repo_context.strip()])
    if history:
        lines.extend(["", "Earlier tool activity:"])
        for item in history:
            if item.get("type") == "assistant_action":
                lines.append(
                    f"ASSISTANT ACTION: {json.dumps({'tool_name': item.get('tool_name'), 'tool_args': item.get('args')}, ensure_ascii=False)}"
                )
            elif item.get("type") == "tool_result":
                lines.append(
                    "TOOL RESULT: "
                    + json.dumps(item.get("result"), ensure_ascii=False)[: MAX_TOOL_RESULT_CHARS + 120]
                )
    lines.extend(
        [
            "",
            "Choose the next tool or finish the task.",
            "Return only JSON matching the schema.",
        ]
    )
    return "\n".join(lines).strip()


def _builder_repo_context(repo_path: Path, prompt: str) -> str:
    sections: list[str] = []
    root_entries = []
    for child in sorted(repo_path.iterdir(), key=lambda item: item.name.lower())[:16]:
        prefix = "/" if child.is_dir() else ""
        root_entries.append(child.name + prefix)
    if root_entries:
        sections.append("Repo root entries: " + ", ".join(root_entries))
    try:
        proc = subprocess.run(
            ["git", "status", "--short"],
            cwd=repo_path,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        proc = None
    if proc and proc.returncode == 0:
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        sections.append("Git status: " + (", ".join(lines[:10]) if lines else "clean"))
    search_hits: list[str] = []
    for term in _prompt_search_terms(prompt):
        try:
            proc = subprocess.run(
                [
                    "rg",
                    "-n",
                    "--hidden",
                    "--glob",
                    "!.git",
                    "--glob",
                    "!.agent-runner",
                    "-m",
                    "2",
                    term,
                    ".",
                ],
                cwd=repo_path,
                text=True,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError:
            break
        if proc.returncode not in {0, 1}:
            continue
        for line in proc.stdout.splitlines():
            cleaned = line.strip()
            if cleaned and cleaned not in search_hits:
                search_hits.append(cleaned)
            if len(search_hits) >= 8:
                break
        if len(search_hits) >= 8:
            break
    if search_hits:
        sections.append("Prompt-related search hits:\n" + "\n".join(f"- {line}" for line in search_hits))
    return "\n\n".join(section for section in sections if section).strip()


def _prompt_search_terms(prompt: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for token in prompt.replace("\n", " ").split():
        cleaned = token.strip("`'\".,:;()[]{}<>")
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if "/" in cleaned or "." in cleaned or "_" in cleaned:
            candidate = cleaned
        elif len(lowered) >= 5 and lowered.isalpha():
            candidate = lowered
        else:
            continue
        if candidate.lower() in {
            "assistant",
            "builder",
            "reviewer",
            "success",
            "criteria",
            "constraints",
            "instructions",
            "conversation",
            "context",
        }:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        terms.append(candidate)
        if len(terms) >= 5:
            break
    return terms


def _compact_diff_summary(path: str, before: str, after: str) -> str:
    if before == after:
        return f"Diff summary: {path} unchanged after write_file."
    diff_lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=path,
            tofile=path,
            lineterm="",
        )
    )
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    snippet = " | ".join(line for line in diff_lines[2:8] if line)
    if len(snippet) > 220:
        snippet = snippet[:217] + "..."
    return f"Diff summary: {path} (+{added}/-{removed}){': ' + snippet if snippet else ''}"


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text and text not in items:
            items.append(text)
    return items


def _string_or_default(value: object, default: str) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return default


def _truncate_text(text: str, max_chars: int) -> str:
    content = str(text or "")
    if len(content) <= max_chars:
        return content
    return content[: max_chars - 3] + "..."


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


def model_supports_images(model: str) -> bool:
    normalized = model.strip().lower()
    return any(hint in normalized for hint in VISION_MODEL_HINTS) or any(
        normalized == prefix or normalized.startswith(f"{prefix}:")
        for prefix in OFFICIAL_MULTIMODAL_MODEL_PREFIXES
    )


def infer_provider_for_model(model: str, default_provider: ProviderKind) -> ProviderKind:
    normalized = model.strip().lower()
    if not normalized:
        return default_provider
    if any(hint in normalized for hint in CODEX_MODEL_HINTS):
        return ProviderKind.CODEX
    if any(hint in normalized for hint in OLLAMA_MODEL_HINTS):
        return ProviderKind.OLLAMA
    return default_provider


def extract_prompt_screenshot_paths(prompt: str) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for raw_line in prompt.splitlines():
        line = raw_line.strip()
        if not line.startswith("- Screenshot: "):
            continue
        candidate = line.removeprefix("- Screenshot: ").split(" (", 1)[0].strip()
        if not candidate:
            continue
        key = str(Path(candidate).expanduser())
        if key in seen:
            continue
        seen.add(key)
        paths.append(Path(key))
    return paths


def _ollama_images_from_prompt(prompt: str) -> list[str]:
    images: list[str] = []
    for path in extract_prompt_screenshot_paths(prompt):
        try:
            if not path.is_file():
                continue
            images.append(base64.b64encode(path.read_bytes()).decode("ascii"))
        except OSError:
            continue
    return images
