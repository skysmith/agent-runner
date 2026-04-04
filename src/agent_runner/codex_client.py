from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CodexExecResult:
    payload: dict
    raw_jsonl: str
    stderr: str
    return_code: int


class CodexError(RuntimeError):
    pass


def run_codex_json(
    *,
    codex_bin: str,
    model: str = "gpt-5.3-codex",
    prompt: str,
    schema: dict,
    repo_path: Path,
    extra_access_dir: Path | None = None,
    dry_run: bool = False,
    timeout_seconds: int | None = None,
    phase_name: str = "codex phase",
) -> CodexExecResult:
    if dry_run:
        return CodexExecResult(payload={}, raw_jsonl="", stderr="", return_code=0)

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as schema_file:
        schema_path = Path(schema_file.name)
        json.dump(schema, schema_file)

    try:
        cmd = [
            codex_bin,
            "exec",
            "--json",
            "--model",
            model,
            "--sandbox",
            "workspace-write",
            "--cd",
            str(repo_path),
            "--skip-git-repo-check",
            "--output-schema",
            str(schema_path),
        ]
        if extra_access_dir and extra_access_dir.exists():
            cmd.extend(["--add-dir", str(extra_access_dir)])
        cmd.append(prompt)
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise CodexError(
            f"{phase_name} timed out after {timeout_seconds} seconds. "
            "Try a larger timeout or a more specific task."
        ) from exc
    finally:
        schema_path.unlink(missing_ok=True)

    payload = _extract_final_json(proc.stdout)
    if proc.returncode != 0:
        raise CodexError(f"codex exec failed ({proc.returncode}): {proc.stderr.strip()}")
    if payload is None:
        raise CodexError("codex exec did not produce a parseable final JSON payload.")
    return CodexExecResult(
        payload=payload,
        raw_jsonl=proc.stdout,
        stderr=proc.stderr,
        return_code=proc.returncode,
    )


def _extract_final_json(stdout: str) -> dict | None:
    last_payload: dict | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            if isinstance(event.get("final_output"), dict):
                last_payload = event["final_output"]
            elif isinstance(event.get("output"), dict):
                last_payload = event["output"]
            else:
                item = event.get("item")
                if isinstance(item, dict) and item.get("type") == "agent_message":
                    message_text = item.get("text")
                    parsed = _parse_json_text(message_text)
                    if parsed is not None:
                        last_payload = parsed
    return last_payload


def _parse_json_text(value: object) -> dict | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None
