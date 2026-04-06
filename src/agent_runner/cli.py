from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from .app_paths import resolve_runtime_paths
from .codex_client import CodexError
from .doctor import render_doctor_report, run_doctor
from .models import ProviderKind
from .runner import AgentRunner, RunnerConfig
from .server_info import server_info
from .service import AgentRunnerService, ServiceConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex agent loop v1.01")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the codex agent loop")
    task_group = run.add_mutually_exclusive_group(required=True)
    task_group.add_argument("task_file", nargs="?", type=Path, help="Path to task markdown file")
    task_group.add_argument("--task", help="Inline plain-text task")
    run.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Target repository path (defaults to current directory)",
    )
    run.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path(".agent-runner"),
        help="Directory to store run artifacts",
    )
    run.add_argument("--check", action="append", default=[], help="Verification command (repeatable)")
    run.add_argument("--max-step-retries", type=int, default=2, help="Retries per step")
    run.add_argument(
        "--phase-timeout-seconds",
        type=int,
        default=240,
        help="Timeout for each planner/builder/reviewer Codex phase",
    )
    run.add_argument("--codex-bin", default="codex", help="Codex CLI binary")
    run.add_argument(
        "--provider",
        choices=[str(ProviderKind.CODEX), str(ProviderKind.OLLAMA)],
        default=str(ProviderKind.CODEX),
        help="Execution provider",
    )
    run.add_argument("--model", default="gpt-5.3-codex", help="Codex model to use")
    run.add_argument("--ollama-host", default="http://127.0.0.1:11434", help="Ollama API base URL")
    run.add_argument(
        "--extra-access-dir",
        type=Path,
        default=None,
        help="Additional directory passed to Codex via --add-dir",
    )
    run.add_argument("--dry-run", action="store_true", help="Run loop without calling codex")

    ui = sub.add_parser("ui", help="Launch minimal desktop UI")
    ui.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Target repository path (defaults to current directory)",
    )
    ui.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path(".agent-runner"),
        help="Directory to store run artifacts",
    )
    ui.add_argument("--check", action="append", default=[], help="Verification command (repeatable)")
    ui.add_argument("--max-step-retries", type=int, default=2, help="Retries per step")
    ui.add_argument(
        "--phase-timeout-seconds",
        type=int,
        default=240,
        help="Timeout for each planner/builder/reviewer Codex phase",
    )
    ui.add_argument("--codex-bin", default="codex", help="Codex CLI binary")
    ui.add_argument(
        "--provider",
        choices=[str(ProviderKind.CODEX), str(ProviderKind.OLLAMA)],
        default=str(ProviderKind.CODEX),
        help="Default execution provider",
    )
    ui.add_argument("--model", default="gpt-5.3-codex", help="Codex model to use")
    ui.add_argument("--ollama-host", default="http://127.0.0.1:11434", help="Ollama API base URL")
    ui.add_argument(
        "--extra-access-dir",
        type=Path,
        default=None,
        help="Additional directory passed to Codex via --add-dir",
    )
    ui.add_argument("--dry-run", action="store_true", help="Run loop without calling codex")
    ui.add_argument("--host", default="127.0.0.1", help="Host interface to bind for web runtime")
    ui.add_argument("--port", type=int, default=8765, help="Port to bind for web runtime")
    ui.add_argument(
        "--password",
        default=None,
        help="Optional web access password (basic auth).",
    )

    serve = sub.add_parser("serve", help="Launch local HTTP API and web UI")
    serve.add_argument("--host", default="0.0.0.0", help="Host interface to bind")
    serve.add_argument("--port", type=int, default=8765, help="Port to bind")
    serve.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Target repository path (defaults to current directory)",
    )
    serve.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path(".agent-runner"),
        help="Directory to store run artifacts",
    )
    serve.add_argument("--check", action="append", default=[], help="Verification command (repeatable)")
    serve.add_argument("--max-step-retries", type=int, default=2, help="Retries per step")
    serve.add_argument(
        "--phase-timeout-seconds",
        type=int,
        default=240,
        help="Timeout for each planner/builder/reviewer Codex phase",
    )
    serve.add_argument("--codex-bin", default="codex", help="Codex CLI binary")
    serve.add_argument(
        "--provider",
        choices=[str(ProviderKind.CODEX), str(ProviderKind.OLLAMA)],
        default=str(ProviderKind.CODEX),
        help="Default execution provider",
    )
    serve.add_argument("--model", default="gpt-5.3-codex", help="Codex model to use")
    serve.add_argument("--ollama-host", default="http://127.0.0.1:11434", help="Ollama API base URL")
    serve.add_argument(
        "--extra-access-dir",
        type=Path,
        default=None,
        help="Additional directory passed to Codex via --add-dir",
    )
    serve.add_argument("--dry-run", action="store_true", help="Run loop without calling codex")
    serve.add_argument(
        "--password",
        default=None,
        help="Optional web access password (basic auth).",
    )

    web = sub.add_parser("web", help="Launch browser-first local web runtime")
    web.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    web.add_argument("--port", type=int, default=8765, help="Port to bind")
    web.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Target repository path (defaults to current directory)",
    )
    web.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path(".agent-runner"),
        help="Directory to store run artifacts",
    )
    web.add_argument("--check", action="append", default=[], help="Verification command (repeatable)")
    web.add_argument("--max-step-retries", type=int, default=2, help="Retries per step")
    web.add_argument(
        "--phase-timeout-seconds",
        type=int,
        default=240,
        help="Timeout for each planner/builder/reviewer Codex phase",
    )
    web.add_argument("--codex-bin", default="codex", help="Codex CLI binary")
    web.add_argument(
        "--provider",
        choices=[str(ProviderKind.CODEX), str(ProviderKind.OLLAMA)],
        default=str(ProviderKind.CODEX),
        help="Default execution provider",
    )
    web.add_argument("--model", default="gpt-5.3-codex", help="Codex model to use")
    web.add_argument("--ollama-host", default="http://127.0.0.1:11434", help="Ollama API base URL")
    web.add_argument(
        "--extra-access-dir",
        type=Path,
        default=None,
        help="Additional directory passed to Codex via --add-dir",
    )
    web.add_argument("--dry-run", action="store_true", help="Run loop without calling codex")
    web.add_argument(
        "--password",
        default=None,
        help="Optional web access password (basic auth).",
    )

    doctor = sub.add_parser("doctor", help="Check local setup and explain what to fix")
    doctor.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Workspace path to validate (defaults to current directory)",
    )
    doctor.add_argument("--codex-bin", default="codex", help="Codex CLI binary")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        config = RunnerConfig(
            task_file=args.task_file.resolve() if args.task_file else None,
            repo_path=args.repo.resolve(),
            artifacts_dir=args.artifacts_dir.resolve(),
            task_text=args.task,
            codex_bin=args.codex_bin,
            provider=ProviderKind(args.provider),
            model=args.model,
            ollama_host=args.ollama_host,
            extra_access_dir=args.extra_access_dir.resolve() if args.extra_access_dir else None,
            max_step_retries=args.max_step_retries,
            check_commands=args.check,
            dry_run=args.dry_run,
            phase_timeout_seconds=args.phase_timeout_seconds,
        )
        try:
            runner = AgentRunner(config)
            outcome = runner.run()
        except (CodexError, ValueError) as exc:
            print(f"[agent-runner] error: {exc}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "ok": outcome.ok,
                    "reason": outcome.reason,
                    "final_message": outcome.final_message,
                    "steps_attempted": len(outcome.step_runs),
                    "build_number": runner.store.build_number,
                    "run_id": runner.store.run_id,
                    "artifacts_dir": str(runner.store.run_dir),
                },
                indent=2,
            )
        )
        return 0 if outcome.ok else 1

    if args.command == "ui":
        args.command = "web"
        runtime_paths = resolve_runtime_paths(repo_path=args.repo, artifacts_dir=args.artifacts_dir)
        from .http_api import create_server

        service = AgentRunnerService(
            ServiceConfig(
                repo_path=runtime_paths.repo_path,
                artifacts_dir=runtime_paths.artifacts_dir,
                settings_path=runtime_paths.settings_path,
                codex_bin=args.codex_bin,
                provider=ProviderKind(args.provider),
                model=args.model,
                ollama_host=args.ollama_host,
                extra_access_dir=args.extra_access_dir.resolve() if args.extra_access_dir else None,
                max_step_retries=args.max_step_retries,
                phase_timeout_seconds=args.phase_timeout_seconds,
                check_commands=list(args.check),
                dry_run=args.dry_run,
            )
        )
        password = (args.password or "").strip() or None
        server = create_server(service, host=args.host, port=args.port, access_password=password)
        info = server_info(args.host, server.server_port)
        print(f"[agent-runner] Web runtime started on {info['bind_host']}:{info['bind_port']}")
        print(f"[agent-runner] Local URL: {info['localhost_url']}")
        if info.get("lan_url"):
            print(f"[agent-runner] LAN URL: {info['lan_url']}")
        else:
            print("[agent-runner] LAN URL: unavailable")
        if info.get("tailscale_url"):
            print(f"[agent-runner] Tailscale URL: {info['tailscale_url']}")
        if password:
            print("[agent-runner] Access password is enabled.")
        if info.get("localhost_only"):
            print("[agent-runner] Note: bound to localhost only (LAN devices cannot connect).")
        try:
            webbrowser.open(info["localhost_url"])
        except Exception:
            pass
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0

    if args.command in {"serve", "web"}:
        from .http_api import create_server

        runtime_paths = resolve_runtime_paths(repo_path=args.repo, artifacts_dir=args.artifacts_dir)
        service = AgentRunnerService(
            ServiceConfig(
                repo_path=runtime_paths.repo_path,
                artifacts_dir=runtime_paths.artifacts_dir,
                settings_path=runtime_paths.settings_path,
                codex_bin=args.codex_bin,
                provider=ProviderKind(args.provider),
                model=args.model,
                ollama_host=args.ollama_host,
                extra_access_dir=args.extra_access_dir.resolve() if args.extra_access_dir else None,
                max_step_retries=args.max_step_retries,
                phase_timeout_seconds=args.phase_timeout_seconds,
                check_commands=list(args.check),
                dry_run=args.dry_run,
            )
        )
        password = (args.password or "").strip() or None
        server = create_server(service, host=args.host, port=args.port, access_password=password)
        info = server_info(args.host, server.server_port)
        print(f"[agent-runner] Web runtime started on {info['bind_host']}:{info['bind_port']}")
        print(f"[agent-runner] Local URL: {info['localhost_url']}")
        if info.get("lan_url"):
            print(f"[agent-runner] LAN URL: {info['lan_url']}")
        else:
            print("[agent-runner] LAN URL: unavailable")
        if info.get("tailscale_url"):
            print(f"[agent-runner] Tailscale URL: {info['tailscale_url']}")
        if password:
            print("[agent-runner] Access password is enabled.")
        if info.get("localhost_only"):
            print("[agent-runner] Note: bound to localhost only (LAN devices cannot connect).")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0

    if args.command == "doctor":
        report = run_doctor(codex_bin=args.codex_bin, repo_path=args.repo)
        print(render_doctor_report(report))
        return 0 if report.ok else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
