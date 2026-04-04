from __future__ import annotations

from pathlib import Path

from agent_runner.prompt_context import load_mind_map, render_mind_map_block


def test_load_mind_map_reads_repo_file(tmp_path: Path) -> None:
    path = tmp_path / "mind-map.md"
    path.write_text("# Mind Map\nhello", encoding="utf-8")
    assert load_mind_map(tmp_path) == "# Mind Map\nhello"


def test_render_mind_map_block_empty_when_missing() -> None:
    assert render_mind_map_block("") == ""


def test_render_mind_map_block_wraps_text() -> None:
    block = render_mind_map_block("hello")
    assert "OPERATING MIND MAP:" in block
    assert "hello" in block
