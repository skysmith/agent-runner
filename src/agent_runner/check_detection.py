from __future__ import annotations

import json
from pathlib import Path


def detect_repo_checks(repo_path: Path) -> list[str]:
    checks: list[str] = []

    checks.extend(_detect_node_checks(repo_path))
    checks.extend(_detect_python_checks(repo_path))
    checks.extend(_detect_rust_checks(repo_path))
    checks.extend(_detect_go_checks(repo_path))

    # Preserve order while removing duplicates.
    deduped: list[str] = []
    for check in checks:
        if check not in deduped:
            deduped.append(check)
    return deduped


def _detect_node_checks(repo_path: Path) -> list[str]:
    package_json = repo_path / "package.json"
    if not package_json.exists():
        return []
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    scripts = payload.get("scripts", {})
    if not isinstance(scripts, dict):
        return []

    runner = _node_runner(repo_path)
    checks: list[str] = []
    if "test" in scripts:
        checks.append(f"{runner} test")
    if "build" in scripts:
        checks.append(f"{runner} run build")
    return checks


def _node_runner(repo_path: Path) -> str:
    if (repo_path / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (repo_path / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _detect_python_checks(repo_path: Path) -> list[str]:
    has_pyproject = (repo_path / "pyproject.toml").exists()
    has_tests_dir = (repo_path / "tests").is_dir()
    has_pytest_ini = (repo_path / "pytest.ini").exists()
    has_conftest = (repo_path / "conftest.py").exists()
    if has_pyproject or has_tests_dir or has_pytest_ini or has_conftest:
        return ["pytest -q"]
    return []


def _detect_rust_checks(repo_path: Path) -> list[str]:
    if (repo_path / "Cargo.toml").exists():
        return ["cargo test"]
    return []


def _detect_go_checks(repo_path: Path) -> list[str]:
    if (repo_path / "go.mod").exists():
        return ["go test ./..."]
    return []

