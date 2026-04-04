from __future__ import annotations

import subprocess
from pathlib import Path

from .models import CheckResult


def run_checks(commands: list[str], repo_path: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    for cmd in commands:
        proc = subprocess.run(
            cmd,
            shell=True,
            text=True,
            capture_output=True,
            cwd=repo_path,
            check=False,
        )
        results.append(
            CheckResult(
                command=cmd,
                return_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        )
    return results

