from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path

from .app_paths import app_support_dir, resolve_runtime_paths
from .codex_client import CodexError
from .doctor import render_doctor_report, run_doctor
from .image_workflow import default_image_asset_export_root
from .macos_wrapper import load_wrapper_state, resolve_wrapper_password, wrapper_state_path
from .models import ProviderKind
from .packaged_entry import _launch_arcade
from .runner import AgentRunner, RunnerConfig
from .server_info import is_localhost_bind, server_info
from .service import AgentRunnerService, ServiceConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Alcove workspace runtime")
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
        default=7200,
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
        default=7200,
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
        default=7200,
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
        default=7200,
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

    arcade = sub.add_parser("arcade", help="Publish Arcade and open the fresh share link in Chrome")
    arcade.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Runtime repository path. Defaults to the installed Alcove wrapper repo when available.",
    )
    arcade.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path(".agent-runner"),
        help="Directory to store run artifacts when falling back to repo-local runtime state.",
    )
    arcade.add_argument(
        "--port",
        type=int,
        default=None,
        help="Local Alcove web port override. Defaults to the installed wrapper port or 8765.",
    )
    arcade.add_argument(
        "--password",
        default=None,
        help="Optional web access password override.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _load_env_defaults(repo=getattr(args, "repo", None))

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
            print(f"[alcove] error: {exc}", file=sys.stderr)
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
                image_export_root=default_image_asset_export_root(),
            )
        )
        password = (args.password or "").strip() or None
        try:
            _require_password_for_public_bind(host=args.host, password=password, command="alcove ui")
        except ValueError as exc:
            print(f"[alcove] error: {exc}", file=sys.stderr)
            return 1
        server = create_server(service, host=args.host, port=args.port, access_password=password)
        info = server_info(args.host, server.server_port)
        print(f"[alcove] Web runtime started on {info['bind_host']}:{info['bind_port']}")
        print(f"[alcove] Local URL: {info['localhost_url']}")
        if info.get("lan_url"):
            print(f"[alcove] LAN URL: {info['lan_url']}")
        else:
            print("[alcove] LAN URL: unavailable")
        if info.get("tailscale_url"):
            print(f"[alcove] Tailscale URL: {info['tailscale_url']}")
        if password:
            print("[alcove] Access password is enabled.")
            if not info.get("localhost_only"):
                print("[alcove] Public bind is protected with basic auth.")
        if info.get("localhost_only"):
            print("[alcove] Note: bound to localhost only (LAN devices cannot connect).")
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
                image_export_root=default_image_asset_export_root(),
            )
        )
        password = (args.password or "").strip() or None
        try:
            _require_password_for_public_bind(
                host=args.host,
                password=password,
                command=f"alcove {args.command}",
            )
        except ValueError as exc:
            print(f"[alcove] error: {exc}", file=sys.stderr)
            return 1
        server = create_server(service, host=args.host, port=args.port, access_password=password)
        info = server_info(args.host, server.server_port)
        print(f"[alcove] Web runtime started on {info['bind_host']}:{info['bind_port']}")
        print(f"[alcove] Local URL: {info['localhost_url']}")
        if info.get("lan_url"):
            print(f"[alcove] LAN URL: {info['lan_url']}")
        else:
            print("[alcove] LAN URL: unavailable")
        if info.get("tailscale_url"):
            print(f"[alcove] Tailscale URL: {info['tailscale_url']}")
        if password:
            print("[alcove] Access password is enabled.")
            if not info.get("localhost_only"):
                print("[alcove] Public bind is protected with basic auth.")
        if info.get("localhost_only"):
            print("[alcove] Note: bound to localhost only (LAN devices cannot connect).")
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

    if args.command == "arcade":
        runtime_repo, state_root, port, password = _resolve_arcade_launch_context(
            repo=args.repo,
            artifacts_dir=args.artifacts_dir,
            port=args.port,
            password=args.password,
        )
        result = _launch_arcade(
            runtime_repo=runtime_repo,
            state_root=state_root,
            port=port,
            password=password,
        )
        if result == 0:
            print("[alcove] Arcade published and opened in Chrome.")
        else:
            print("[alcove] Could not publish Arcade.", file=sys.stderr)
        return result

    parser.print_help()
    return 2


def _load_env_defaults(*, repo: Path | None) -> None:
    paths: list[Path] = []
    explicit = os.environ.get("ALCOVE_ENV_FILE", "").strip() or os.environ.get("AGENT_RUNNER_ENV_FILE", "").strip()
    if explicit:
        paths.append(Path(explicit).expanduser())
    for base in (repo.expanduser() if repo else None, Path.cwd()):
        if base is None:
            continue
        paths.extend([base / ".env.local", base / ".env"])

    seen: set[Path] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        _load_env_file_if_present(resolved)


def _load_env_file_if_present(path: Path) -> None:
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].strip()
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key or key in os.environ or not _valid_env_key(key):
            continue
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        os.environ[key] = value


def _valid_env_key(key: str) -> bool:
    if not (key[0].isalpha() or key[0] == "_"):
        return False
    return all(char.isalnum() or char == "_" for char in key)


def _require_password_for_public_bind(*, host: str, password: str | None, command: str) -> None:
    host_text = str(host or "").strip() or "0.0.0.0"
    if is_localhost_bind(host_text):
        return
    if str(password or "").strip():
        return
    raise ValueError(
        f"{command} requires --password whenever --host is not localhost. "
        "Use --host 127.0.0.1 for local-only access, or pass --password to protect remote access."
    )


def _resolve_arcade_launch_context(
    *,
    repo: Path | None,
    artifacts_dir: Path,
    port: int | None,
    password: str | None,
) -> tuple[Path, Path, int, str | None]:
    wrapper_root = app_support_dir()
    wrapper_payload = load_wrapper_state(wrapper_root) if wrapper_state_path(wrapper_root).exists() else {}

    runtime_paths = resolve_runtime_paths(repo_path=repo, artifacts_dir=artifacts_dir)
    runtime_repo = runtime_paths.repo_path
    state_root = runtime_paths.settings_path.parent

    wrapper_repo_text = str(wrapper_payload.get("repo_path") or "").strip()
    if repo is None and wrapper_repo_text:
        runtime_repo = Path(wrapper_repo_text).expanduser().resolve()
        state_root = wrapper_root

    server_info_payload = wrapper_payload.get("server_info") if isinstance(wrapper_payload.get("server_info"), dict) else {}
    resolved_port = port
    if resolved_port is None:
        try:
            resolved_port = int(server_info_payload.get("bind_port") or 8765)
        except (TypeError, ValueError):
            resolved_port = 8765

    resolved_password = resolve_wrapper_password(
        repo_path=runtime_repo,
        explicit_password=password,
    )
    return runtime_repo, state_root, resolved_port, resolved_password


if __name__ == "__main__":
    sys.exit(main())
