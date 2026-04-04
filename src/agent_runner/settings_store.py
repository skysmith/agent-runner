from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import AppSettings, ChecksPolicy, ProviderKind, RunMode


def load_app_settings(path: Path, defaults: AppSettings) -> AppSettings:
    if not path.exists():
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return defaults
    if not isinstance(raw, dict):
        return defaults
    provider_raw = str(raw.get("provider", defaults.provider))
    provider = ProviderKind.CODEX
    if provider_raw == ProviderKind.OLLAMA:
        provider = ProviderKind.OLLAMA
    run_mode_raw = str(raw.get("default_run_mode", defaults.default_run_mode))
    default_run_mode = RunMode.LOOP if run_mode_raw == RunMode.LOOP else RunMode.MESSAGE
    checks_policy_raw = str(raw.get("checks_policy", defaults.checks_policy))
    checks_policy = ChecksPolicy.CUSTOM if checks_policy_raw == ChecksPolicy.CUSTOM else ChecksPolicy.AUTO
    extra_raw = raw.get("extra_access_dir")
    extra_access_dir = defaults.extra_access_dir if extra_raw is None else Path(str(extra_raw))
    return AppSettings(
        provider=provider,
        model=str(raw.get("model", defaults.model)),
        codex_bin=str(raw.get("codex_bin", defaults.codex_bin)),
        ollama_host=str(raw.get("ollama_host", defaults.ollama_host)),
        extra_access_dir=extra_access_dir,
        default_run_mode=default_run_mode,
        preflight_clarifications=bool(raw.get("preflight_clarifications", defaults.preflight_clarifications)),
        checks_policy=checks_policy,
        animate_status_scenes=bool(raw.get("animate_status_scenes", defaults.animate_status_scenes)),
        max_step_retries=int(raw.get("max_step_retries", defaults.max_step_retries)),
        phase_timeout_seconds=int(raw.get("phase_timeout_seconds", defaults.phase_timeout_seconds)),
        default_checks=_as_string_list(raw.get("default_checks"), defaults.default_checks),
    )


def save_app_settings(path: Path, settings: AppSettings) -> None:
    payload: dict[str, Any] = asdict(settings)
    payload["provider"] = str(settings.provider)
    if settings.extra_access_dir is not None:
        payload["extra_access_dir"] = str(settings.extra_access_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _as_string_list(value: object, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)
    items: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                items.append(text)
    return items
