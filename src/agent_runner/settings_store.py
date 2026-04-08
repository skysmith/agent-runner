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
    provider_raw = _coerce_text(raw.get("provider"), str(defaults.provider)) or str(defaults.provider)
    provider = defaults.provider
    if provider_raw == str(ProviderKind.OLLAMA):
        provider = ProviderKind.OLLAMA
    elif provider_raw == str(ProviderKind.CODEX):
        provider = ProviderKind.CODEX
    run_mode_raw = _coerce_text(raw.get("default_run_mode"), str(defaults.default_run_mode)) or str(defaults.default_run_mode)
    default_run_mode = defaults.default_run_mode
    if run_mode_raw == str(RunMode.LOOP):
        default_run_mode = RunMode.LOOP
    elif run_mode_raw == str(RunMode.MESSAGE):
        default_run_mode = RunMode.MESSAGE
    checks_policy_raw = _coerce_text(raw.get("checks_policy"), str(defaults.checks_policy)) or str(defaults.checks_policy)
    checks_policy = defaults.checks_policy
    if checks_policy_raw == str(ChecksPolicy.CUSTOM):
        checks_policy = ChecksPolicy.CUSTOM
    elif checks_policy_raw == str(ChecksPolicy.AUTO):
        checks_policy = ChecksPolicy.AUTO
    extra_raw = raw.get("extra_access_dir")
    extra_access_dir = defaults.extra_access_dir
    if isinstance(extra_raw, str) and extra_raw.strip():
        extra_access_dir = Path(extra_raw.strip())
    return AppSettings(
        provider=provider,
        model=_coerce_text(raw.get("model"), defaults.model) or defaults.model,
        planner_model=_optional_text(raw.get("planner_model"), defaults.planner_model),
        builder_model=_optional_text(raw.get("builder_model"), defaults.builder_model),
        reviewer_model=_optional_text(raw.get("reviewer_model"), defaults.reviewer_model),
        vision_model=_optional_text(raw.get("vision_model"), defaults.vision_model),
        codex_bin=_coerce_text(raw.get("codex_bin"), defaults.codex_bin) or defaults.codex_bin,
        ollama_host=_coerce_text(raw.get("ollama_host"), defaults.ollama_host) or defaults.ollama_host,
        extra_access_dir=extra_access_dir,
        default_run_mode=default_run_mode,
        preflight_clarifications=_coerce_bool(
            raw.get("preflight_clarifications"),
            defaults.preflight_clarifications,
        ),
        checks_policy=checks_policy,
        animate_status_scenes=_coerce_bool(
            raw.get("animate_status_scenes"),
            defaults.animate_status_scenes,
        ),
        max_step_retries=_coerce_int(
            raw.get("max_step_retries"),
            defaults.max_step_retries,
            minimum=0,
        ),
        phase_timeout_seconds=_coerce_int(
            raw.get("phase_timeout_seconds"),
            defaults.phase_timeout_seconds,
            minimum=30,
        ),
        context_char_cap=_optional_int(
            raw.get("context_char_cap"),
            defaults.context_char_cap,
            minimum=100,
        ),
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


def _optional_text(value: object, fallback: str | None = None) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return fallback


def _coerce_text(value: object, fallback: str) -> str:
    if isinstance(value, str):
        text = value.strip()
        return text or fallback
    return fallback


def _coerce_bool(value: object, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return fallback


def _coerce_int(value: object, fallback: int, *, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _optional_int(value: object, fallback: int | None = None, *, minimum: int | None = None) -> int | None:
    if value is None:
        return fallback
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed
