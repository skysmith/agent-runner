from __future__ import annotations

import json
from pathlib import Path

from agent_runner.artifacts import ArtifactStore


def test_artifact_store_assigns_incrementing_build_numbers(tmp_path: Path) -> None:
    base = tmp_path / ".agent-runner"
    first = ArtifactStore(base)
    second = ArtifactStore(base)
    assert first.build_number == 1
    assert second.build_number == 2
    assert first.run_dir.name.startswith("run-b0001-")
    assert second.run_dir.name.startswith("run-b0002-")


def test_artifact_store_writes_metadata_and_counter(tmp_path: Path) -> None:
    base = tmp_path / ".agent-runner"
    store = ArtifactStore(base)
    metadata_path = store.run_dir / "run_metadata.json"
    assert metadata_path.exists()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["build_number"] == 1
    counter = json.loads((base / "build-counter.json").read_text(encoding="utf-8"))
    assert counter["last_build_number"] == 1


def test_artifact_store_infers_counter_from_existing_runs(tmp_path: Path) -> None:
    base = tmp_path / ".agent-runner"
    (base / "run-b0012-20260101T000000Z").mkdir(parents=True)
    store = ArtifactStore(base)
    assert store.build_number == 13
