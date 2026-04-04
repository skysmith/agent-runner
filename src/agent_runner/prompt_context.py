from __future__ import annotations

from pathlib import Path


def load_mind_map(repo_path: Path) -> str:
    path = repo_path / "mind-map.md"
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return text


def render_mind_map_block(mind_map_text: str) -> str:
    text = mind_map_text.strip()
    if not text:
        return ""
    return f"\nOPERATING MIND MAP:\n{text}\n"
