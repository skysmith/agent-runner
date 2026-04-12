from __future__ import annotations

from pathlib import Path

from agent_runner.models import AppSettings, ChecksPolicy, ProviderKind, RunMode
from agent_runner.settings_store import load_app_settings, save_app_settings


def test_save_and_load_settings_round_trip(tmp_path: Path) -> None:
    path = tmp_path / ".agent-runner" / "app-settings.json"
    settings = AppSettings(
        provider=ProviderKind.OLLAMA,
        model="llama3.2",
        vision_model="qwen3-vl:4b",
        codex_bin="codex",
        ollama_host="http://localhost:11434",
        extra_access_dir=tmp_path / "repo-access",
        default_run_mode=RunMode.MESSAGE,
        preflight_clarifications=False,
        checks_policy=ChecksPolicy.CUSTOM,
        animate_status_scenes=False,
        max_step_retries=3,
        phase_timeout_seconds=500,
        context_char_cap=150000,
        default_checks=["pytest -q", "npm test"],
    )
    save_app_settings(path, settings)
    loaded = load_app_settings(path, AppSettings())
    assert loaded.provider == ProviderKind.OLLAMA
    assert loaded.model == "llama3.2"
    assert loaded.vision_model == "qwen3-vl:4b"
    assert loaded.default_run_mode == RunMode.MESSAGE
    assert loaded.preflight_clarifications is False
    assert loaded.checks_policy == ChecksPolicy.CUSTOM
    assert loaded.animate_status_scenes is False
    assert loaded.default_checks == ["pytest -q", "npm test"]
    assert loaded.extra_access_dir == tmp_path / "repo-access"
    assert loaded.context_char_cap == 150000


def test_load_settings_falls_back_when_missing(tmp_path: Path) -> None:
    defaults = AppSettings(model="gpt-5.4")
    loaded = load_app_settings(tmp_path / "missing.json", defaults)
    assert loaded.model == "gpt-5.4"
    assert loaded.provider == defaults.provider


def test_load_settings_ignores_invalid_types_and_preserves_defaults(tmp_path: Path) -> None:
    path = tmp_path / ".agent-runner" / "app-settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
        {
          "provider": "not-a-provider",
          "model": "",
          "codex_bin": 42,
          "ollama_host": false,
          "default_run_mode": "sideways",
          "preflight_clarifications": "false",
          "checks_policy": "mystery",
          "animate_status_scenes": "0",
          "max_step_retries": "not-a-number",
          "phase_timeout_seconds": "12"
        }
        """.strip(),
        encoding="utf-8",
    )

    defaults = AppSettings(
        provider=ProviderKind.OLLAMA,
        model="qwen3:8b",
        codex_bin="codex-dev",
        ollama_host="http://localhost:11434",
        default_run_mode=RunMode.LOOP,
        preflight_clarifications=True,
        checks_policy=ChecksPolicy.CUSTOM,
        animate_status_scenes=True,
        max_step_retries=3,
        phase_timeout_seconds=240,
    )

    loaded = load_app_settings(path, defaults)

    assert loaded.provider == ProviderKind.OLLAMA
    assert loaded.model == "qwen3:8b"
    assert loaded.codex_bin == "codex-dev"
    assert loaded.ollama_host == "http://localhost:11434"
    assert loaded.default_run_mode == RunMode.LOOP
    assert loaded.preflight_clarifications is False
    assert loaded.checks_policy == ChecksPolicy.CUSTOM
    assert loaded.animate_status_scenes is False
    assert loaded.max_step_retries == 3
    assert loaded.phase_timeout_seconds == 30
