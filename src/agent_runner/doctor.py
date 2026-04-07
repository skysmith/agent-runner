from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .executable_utils import resolve_executable_path


@dataclass(slots=True)
class DoctorCheck:
    key: str
    label: str
    ok: bool
    detail: str
    fix: str | None = None


@dataclass(slots=True)
class DoctorReport:
    checks: list[DoctorCheck]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checks": [
                {
                    "key": check.key,
                    "label": check.label,
                    "ok": check.ok,
                    "detail": check.detail,
                    "fix": check.fix,
                }
                for check in self.checks
            ],
            "summary": render_doctor_report(self),
        }


def run_doctor(*, codex_bin: str = "codex", repo_path: Path | None = None) -> DoctorReport:
    checks = [
        _check_python(),
        _check_repo_path(repo_path),
        _check_codex_installed(codex_bin),
    ]
    codex_check = checks[-1]
    if codex_check.ok:
        checks.append(_check_codex_login(codex_bin))
    else:
        checks.append(
            DoctorCheck(
                key="codex_login",
                label="Codex authentication",
                ok=False,
                detail="Skipped because Codex CLI was not found.",
                fix=f"Install Codex first, then run `{codex_bin} login`.",
            )
        )
    return DoctorReport(checks=checks)


def render_doctor_report(report: DoctorReport) -> str:
    lines = ["Alcove setup check", ""]
    for check in report.checks:
        status = "PASS" if check.ok else "FAIL"
        lines.append(f"[{status}] {check.label}: {check.detail}")
        if check.fix:
            lines.append(f"  Fix: {check.fix}")
    lines.append("")
    if report.ok:
        lines.append("Ready to go.")
        lines.append("Next: `alcove web`")
    else:
        lines.append("Setup is incomplete.")
        lines.append("Fix the failed checks above, then re-run `alcove doctor`.")
    return "\n".join(lines)


def _check_python() -> DoctorCheck:
    version = sys.version_info
    ok = version >= (3, 11)
    detail = f"Using Python {version.major}.{version.minor}.{version.micro}."
    fix = None if ok else "Install Python 3.11 or newer and re-create your virtual environment."
    return DoctorCheck(
        key="python",
        label="Python",
        ok=ok,
        detail=detail,
        fix=fix,
    )


def _check_repo_path(repo_path: Path | None) -> DoctorCheck:
    path = (repo_path or Path.cwd()).resolve()
    ok = path.exists() and path.is_dir()
    detail = f"Workspace path is `{path}`."
    fix = None if ok else "Run Alcove from an existing project directory or pass `--repo /path/to/repo`."
    return DoctorCheck(
        key="repo_path",
        label="Workspace path",
        ok=ok,
        detail=detail,
        fix=fix,
    )


def _check_codex_installed(codex_bin: str) -> DoctorCheck:
    resolved = resolve_executable_path(codex_bin)
    ok = bool(resolved)
    detail = f"Found `{codex_bin}` at `{resolved}`." if resolved else f"`{codex_bin}` was not found on PATH."
    fix = None if ok else "Install Codex CLI and make sure the `codex` command works in your shell."
    return DoctorCheck(
        key="codex_installed",
        label="Codex CLI",
        ok=ok,
        detail=detail,
        fix=fix,
    )


def _check_codex_login(codex_bin: str) -> DoctorCheck:
    resolved = resolve_executable_path(codex_bin) or codex_bin
    try:
        proc = subprocess.run(
            [resolved, "login", "status"],
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except OSError as exc:
        return DoctorCheck(
            key="codex_login",
            label="Codex authentication",
            ok=False,
            detail=f"Failed to run `{codex_bin} login status`: {exc}",
            fix=f"Verify `{codex_bin}` is runnable, then run `{codex_bin} login`.",
        )
    except subprocess.TimeoutExpired:
        return DoctorCheck(
            key="codex_login",
            label="Codex authentication",
            ok=False,
            detail=f"`{codex_bin} login status` timed out.",
            fix=f"Try `{codex_bin} login status` manually, then run `{codex_bin} login` if needed.",
        )

    output = "\n".join(part.strip() for part in [proc.stdout, proc.stderr] if part.strip()).strip()
    if proc.returncode == 0:
        detail = output.splitlines()[0] if output else "Codex CLI is authenticated."
        return DoctorCheck(
            key="codex_login",
            label="Codex authentication",
            ok=True,
            detail=detail,
        )
    return DoctorCheck(
        key="codex_login",
        label="Codex authentication",
        ok=False,
        detail=output.splitlines()[0] if output else f"`{codex_bin} login status` returned {proc.returncode}.",
        fix=f"Run `{codex_bin} login` and confirm `{codex_bin} login status` succeeds.",
    )
