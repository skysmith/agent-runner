from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ArtifactStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.build_number = _next_build_number(self.base_dir)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = f"b{self.build_number:04d}-{stamp}"
        self.run_dir = self.base_dir / f"run-{self.run_id}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "build_number": self.build_number,
            "run_id": self.run_id,
            "created_at_utc": stamp,
            "run_dir": str(self.run_dir),
        }
        (self.run_dir / "run_metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
        )

    def write_json(self, relative_path: str, payload: Any) -> Path:
        path = self.run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized = _normalize(payload)
        path.write_text(json.dumps(normalized, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def write_text(self, relative_path: str, text: str) -> Path:
        path = self.run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


def _normalize(value: Any) -> Any:
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def _next_build_number(base_dir: Path) -> int:
    counter_file = base_dir / "build-counter.json"
    existing = 0
    if counter_file.exists():
        try:
            payload = json.loads(counter_file.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                existing = int(payload.get("last_build_number", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            existing = 0
    if existing <= 0:
        existing = _infer_max_build_number(base_dir)
    next_value = existing + 1
    counter_file.write_text(
        json.dumps({"last_build_number": next_value}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return next_value


def _infer_max_build_number(base_dir: Path) -> int:
    pattern = re.compile(r"^run-b(\d{4,})-")
    max_value = 0
    for child in base_dir.iterdir():
        if not child.is_dir():
            continue
        match = pattern.match(child.name)
        if not match:
            continue
        try:
            value = int(match.group(1))
        except ValueError:
            continue
        max_value = max(max_value, value)
    return max_value
