import json
from pathlib import Path

from agent_runner.check_detection import detect_repo_checks


def test_detect_node_checks(tmp_path: Path) -> None:
    package_json = {
        "name": "demo",
        "scripts": {
            "test": "vitest",
            "build": "vite build",
        },
    }
    (tmp_path / "package.json").write_text(json.dumps(package_json), encoding="utf-8")
    checks = detect_repo_checks(tmp_path)
    assert checks == ["npm test", "npm run build"]


def test_detect_python_check_from_tests_dir(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    checks = detect_repo_checks(tmp_path)
    assert checks == ["pytest -q"]


def test_detect_prefers_package_manager(tmp_path: Path) -> None:
    package_json = {"name": "demo", "scripts": {"test": "vitest"}}
    (tmp_path / "package.json").write_text(json.dumps(package_json), encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lock", encoding="utf-8")
    checks = detect_repo_checks(tmp_path)
    assert checks == ["pnpm test"]

