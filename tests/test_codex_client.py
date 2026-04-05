import subprocess
from pathlib import Path

import pytest

from agent_runner.codex_client import CodexError, _extract_final_json, run_codex_json


def test_extract_final_json_prefers_final_output() -> None:
    stdout = "\n".join(
        [
            '{"event":"progress"}',
            '{"output":{"status":"old"}}',
            '{"final_output":{"status":"new"}}',
        ]
    )
    payload = _extract_final_json(stdout)
    assert payload == {"status": "new"}


def test_extract_final_json_from_item_completed_agent_message() -> None:
    stdout = "\n".join(
        [
            '{"type":"turn.started"}',
            '{"type":"item.completed","item":{"id":"1","type":"agent_message","text":"{\\"ok\\":true,\\"kind\\":\\"planner\\"}"}}',
            '{"type":"turn.completed"}',
        ]
    )
    payload = _extract_final_json(stdout)
    assert payload == {"ok": True, "kind": "planner"}


def test_run_codex_json_raises_on_timeout(monkeypatch, tmp_path: Path) -> None:
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="codex exec", timeout=1)

    monkeypatch.setattr("agent_runner.codex_client.subprocess.run", fake_run)

    with pytest.raises(CodexError, match="timed out"):
        run_codex_json(
            codex_bin="codex",
            prompt="{}",
            schema={"type": "object"},
            repo_path=tmp_path,
            timeout_seconds=1,
            phase_name="planner",
        )


def test_run_codex_json_includes_sandbox_and_add_dir(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    extra_dir = tmp_path / "extra"
    extra_dir.mkdir()

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout='{"final_output":{"ok":true}}',
            stderr="",
        )

    monkeypatch.setattr("agent_runner.codex_client.subprocess.run", fake_run)

    result = run_codex_json(
        codex_bin="codex",
        prompt="{}",
        schema={"type": "object"},
        repo_path=tmp_path,
        extra_access_dir=extra_dir,
        timeout_seconds=1,
        phase_name="planner",
    )

    assert result.payload == {"ok": True}
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert "--sandbox" in cmd and "workspace-write" in cmd
    assert "--add-dir" in cmd and str(extra_dir) in cmd


def test_run_codex_json_invokes_js_entrypoint_via_node(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    codex_js = tmp_path / "codex.js"
    codex_js.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    codex_shim = tmp_path / "codex"
    codex_shim.symlink_to(codex_js)

    monkeypatch.setattr("agent_runner.codex_client.shutil.which", lambda name: "/usr/local/bin/node" if name == "node" else str(codex_shim))

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout='{"final_output":{"ok":true}}',
            stderr="",
        )

    monkeypatch.setattr("agent_runner.codex_client.subprocess.run", fake_run)

    result = run_codex_json(
        codex_bin="codex",
        prompt="{}",
        schema={"type": "object"},
        repo_path=tmp_path,
        timeout_seconds=1,
        phase_name="planner",
    )

    assert result.payload == {"ok": True}
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd[:2] == ["/usr/local/bin/node", str(codex_js)]
