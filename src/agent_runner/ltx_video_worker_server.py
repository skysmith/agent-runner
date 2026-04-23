from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4


@dataclass(slots=True)
class WorkerServerConfig:
    jobs_root: Path
    python_path: Path
    worker_script_path: Path
    ltx_repo: Path | None = None
    pipeline_config_path: Path | None = None
    device: str = "mps"
    width: int = 512
    height: int = 320
    num_frames: int = 17
    frame_rate: int = 12
    seed: int = 171198
    offload_to_cpu: bool = False
    timeout_seconds: int = 5400
    hf_home: Path | None = None
    api_key: str | None = None


@dataclass(slots=True)
class _ServerJobHandle:
    proc: subprocess.Popen[str]
    output_dir: Path
    status_path: Path
    stdout_path: Path
    stderr_path: Path
    started_at: float
    timeout_seconds: int
    stdout_handle: Any
    stderr_handle: Any
    closed: bool = False


def create_server(config: WorkerServerConfig, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    jobs: dict[str, _ServerJobHandle] = {}
    jobs_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "AlcoveLtxWorker/0.1"

        def do_GET(self) -> None:
            if not self._authorize():
                return
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/health":
                self._send_json(200, {"ok": True})
                return
            if path.startswith("/jobs/"):
                job_id = unquote(path[len("/jobs/"):])
                self._handle_job_status(job_id)
                return
            if path.startswith("/artifacts/"):
                remainder = path[len("/artifacts/"):]
                job_id, _, file_name = remainder.partition("/")
                self._handle_artifact(unquote(job_id), unquote(file_name))
                return
            self._send_json(404, {"detail": "Not found"})

        def do_POST(self) -> None:
            if not self._authorize():
                return
            parsed = urlparse(self.path)
            if parsed.path != "/jobs":
                self._send_json(404, {"detail": "Not found"})
                return
            self._handle_create_job()

        def log_message(self, fmt: str, *args: object) -> None:
            return

        def _handle_create_job(self) -> None:
            try:
                payload = self._read_json_body(limit=50_000_000)
                image_name = str(payload.get("image_name") or "source.png").strip() or "source.png"
                image_base64 = str(payload.get("image_base64") or "").strip()
                if not image_base64:
                    raise ValueError("Missing image_base64.")
                image_bytes = base64.b64decode(image_base64.encode("ascii"), validate=True)
                prompt_context = _optional_text(payload.get("prompt_context"))
                options = payload.get("options")
                option_map = options if isinstance(options, dict) else {}

                job_id = f"ltxremote_{uuid4().hex[:12]}"
                output_dir = config.jobs_root / job_id
                output_dir.mkdir(parents=True, exist_ok=True)
                input_path = output_dir / _safe_source_name(image_name)
                input_path.write_bytes(image_bytes)
                status_path = output_dir / "ltx-job.json"
                stdout_path = output_dir / "ltx.stdout.log"
                stderr_path = output_dir / "ltx.stderr.log"
                _write_atomic_json(status_path, {"status": "queued", "external_job_id": job_id})
                stdout_handle = stdout_path.open("w", encoding="utf-8")
                stderr_handle = stderr_path.open("w", encoding="utf-8")
                cmd = _build_worker_command(
                    config=config,
                    input_path=input_path,
                    output_dir=output_dir,
                    status_path=status_path,
                    prompt_context=prompt_context,
                    options=option_map,
                )
                proc = subprocess.Popen(
                    cmd,
                    cwd=output_dir,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    text=True,
                    env=_build_worker_env(config),
                )
                with jobs_lock:
                    jobs[job_id] = _ServerJobHandle(
                        proc=proc,
                        output_dir=output_dir,
                        status_path=status_path,
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                        started_at=time.perf_counter(),
                        timeout_seconds=max(int(config.timeout_seconds), 1),
                        stdout_handle=stdout_handle,
                        stderr_handle=stderr_handle,
                    )
                self._send_json(202, {"job_id": job_id, "status": "queued"})
            except ValueError as exc:
                self._send_json(400, {"detail": str(exc)})
            except Exception as exc:
                self._send_json(500, {"detail": str(exc)})

        def _handle_job_status(self, job_id: str) -> None:
            with jobs_lock:
                handle = jobs.get(job_id)
            if handle is None:
                self._send_json(404, {"detail": "Unknown job"})
                return
            if handle.proc.poll() is None and (time.perf_counter() - handle.started_at) > handle.timeout_seconds:
                handle.proc.terminate()
                _write_atomic_json(
                    handle.status_path,
                    {"status": "failed", "error": f"LTX worker timed out after {handle.timeout_seconds} seconds."},
                )
            payload = _read_json_file(handle.status_path, default={"status": "queued"})
            if handle.proc.poll() is not None:
                _close_handles(handle)
                if str(payload.get("status") or "").strip().lower() not in {"succeeded", "failed"} and handle.proc.returncode not in (0, None):
                    payload = {
                        "status": "failed",
                        "error": _tail_text(handle.stderr_path) or _tail_text(handle.stdout_path) or "LTX worker failed.",
                    }
            response = payload if isinstance(payload, dict) else {"status": "queued"}
            status = str(response.get("status") or "queued").strip().lower() or "queued"
            if status == "succeeded":
                response = dict(response)
                response["artifacts"] = _artifact_urls(job_id, response.get("artifacts"), handle.output_dir)
            self._send_json(200, response)

        def _handle_artifact(self, job_id: str, file_name: str) -> None:
            with jobs_lock:
                handle = jobs.get(job_id)
            if handle is None:
                self._send_json(404, {"detail": "Unknown job"})
                return
            if not file_name:
                self._send_json(404, {"detail": "Artifact not found"})
                return
            candidate = (handle.output_dir / Path(file_name).name).resolve()
            if candidate.parent != handle.output_dir.resolve() or not candidate.exists() or not candidate.is_file():
                self._send_json(404, {"detail": "Artifact not found"})
                return
            mime_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            payload = candidate.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _authorize(self) -> bool:
            if not config.api_key:
                return True
            auth = self.headers.get("Authorization", "").strip()
            if auth == f"Bearer {config.api_key}":
                return True
            self._send_json(401, {"detail": "Unauthorized"})
            return False

        def _read_json_body(self, *, limit: int) -> dict[str, object]:
            length_text = self.headers.get("Content-Length", "").strip()
            try:
                length = int(length_text)
            except ValueError as exc:
                raise ValueError("Missing or invalid Content-Length header.") from exc
            if length < 0 or length > limit:
                raise ValueError("Request body is too large.")
            raw = self.rfile.read(length)
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Request body must be valid JSON.") from exc
            if not isinstance(parsed, dict):
                raise ValueError("JSON body must be an object.")
            return parsed

        def _send_json(self, status: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    return server


def _build_worker_command(
    *,
    config: WorkerServerConfig,
    input_path: Path,
    output_dir: Path,
    status_path: Path,
    prompt_context: str | None,
    options: dict[object, object],
) -> list[str]:
    width = _bounded_int(options.get("width"), default=config.width, minimum=128)
    height = _bounded_int(options.get("height"), default=config.height, minimum=128)
    num_frames = _bounded_int(options.get("num_frames"), default=config.num_frames, minimum=9)
    frame_rate = _bounded_int(options.get("frame_rate"), default=config.frame_rate, minimum=1)
    seed = _bounded_int(options.get("seed"), default=config.seed, minimum=1)
    cmd = [
        str(config.python_path),
        str(config.worker_script_path),
        "--input",
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--status-path",
        str(status_path),
        "--device",
        config.device,
        "--pipeline-config",
        str(config.pipeline_config_path),
        "--height",
        str(height),
        "--width",
        str(width),
        "--num-frames",
        str(num_frames),
        "--frame-rate",
        str(frame_rate),
        "--seed",
        str(seed),
    ]
    if config.ltx_repo is not None:
        cmd.extend(["--ltx-repo", str(config.ltx_repo)])
    if config.hf_home is not None:
        cmd.extend(["--hf-home", str(config.hf_home)])
    if config.offload_to_cpu:
        cmd.append("--offload-to-cpu")
    if prompt_context:
        cmd.extend(["--prompt-context", prompt_context])
    return cmd


def _build_worker_env(config: WorkerServerConfig) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("HF_HUB_DISABLE_XET", "1")
    if config.hf_home is not None:
        env["HF_HOME"] = str(config.hf_home)
    if config.device.lower() == "mps":
        env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    return env


def _artifact_urls(job_id: str, raw_artifacts: object, output_dir: Path) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    source = raw_artifacts if isinstance(raw_artifacts, dict) else {}
    for key, value in source.items():
        text = str(value or "").strip()
        if not text:
            continue
        artifacts[str(key)] = f"/artifacts/{job_id}/{Path(text).name}"
    if artifacts:
        return artifacts
    inferred = _infer_known_video_artifacts(output_dir)
    return {key: f"/artifacts/{job_id}/{path.name}" for key, path in inferred.items()}


def _infer_known_video_artifacts(output_dir: Path) -> dict[str, Path]:
    mapping = {
        "input_png": output_dir / "input.png",
        "poster_png": output_dir / "poster.png",
        "mp4": output_dir / "clip.mp4",
        "metadata_json": output_dir / "metadata.json",
    }
    return {key: path for key, path in mapping.items() if path.exists() and path.is_file()}


def _read_json_file(path: Path, *, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, path)


def _tail_text(path: Path, limit: int = 4000) -> str:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return raw[-limit:].strip()


def _close_handles(handle: _ServerJobHandle) -> None:
    if handle.closed:
        return
    try:
        handle.stdout_handle.close()
    except Exception:
        pass
    try:
        handle.stderr_handle.close()
    except Exception:
        pass
    handle.closed = True


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _bounded_int(value: object, *, default: int, minimum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return max(int(default), minimum)
    return max(parsed, minimum)


def _safe_source_name(image_name: str) -> str:
    suffix = Path(image_name).suffix or ".png"
    safe_suffix = suffix if len(suffix) <= 10 else ".png"
    return f"source-upload{safe_suffix}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Alcove remote LTX video worker server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8421, help="Bind port")
    parser.add_argument("--jobs-root", required=True, help="Directory for remote worker jobs")
    parser.add_argument("--python", required=True, help="Python interpreter that can run the LTX worker")
    parser.add_argument("--worker-script", default="", help="Optional override path to ltx_video_worker.py")
    parser.add_argument("--ltx-repo", default="", help="Optional local LTX repo path")
    parser.add_argument("--pipeline-config", default="", help="Optional pipeline config YAML")
    parser.add_argument("--device", default="mps", help="Inference device")
    parser.add_argument("--width", type=int, default=512, help="Default frame width")
    parser.add_argument("--height", type=int, default=320, help="Default frame height")
    parser.add_argument("--num-frames", type=int, default=17, help="Default frame count")
    parser.add_argument("--frame-rate", type=int, default=12, help="Default frame rate")
    parser.add_argument("--seed", type=int, default=171198, help="Default generation seed")
    parser.add_argument("--timeout-seconds", type=int, default=5400, help="Per-job timeout")
    parser.add_argument("--hf-home", default="", help="Optional Hugging Face cache root")
    parser.add_argument("--api-key", default="", help="Optional bearer token required for requests")
    parser.add_argument("--offload-to-cpu", action="store_true", help="Allow the worker to offload to CPU")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    worker_script_path = Path(args.worker_script).expanduser().resolve() if str(args.worker_script).strip() else script_dir / "ltx_video_worker.py"
    pipeline_config_path = (
        Path(args.pipeline_config).expanduser().resolve()
        if str(args.pipeline_config).strip()
        else script_dir / "ltx_video_2b_distilled_macos.yaml"
    )
    config = WorkerServerConfig(
        jobs_root=Path(args.jobs_root).expanduser().resolve(),
        python_path=Path(args.python).expanduser().resolve(),
        worker_script_path=worker_script_path,
        ltx_repo=Path(args.ltx_repo).expanduser().resolve() if str(args.ltx_repo).strip() else None,
        pipeline_config_path=pipeline_config_path,
        device=args.device.strip() or "mps",
        width=max(int(args.width), 128),
        height=max(int(args.height), 128),
        num_frames=max(int(args.num_frames), 9),
        frame_rate=max(int(args.frame_rate), 1),
        seed=max(int(args.seed), 1),
        offload_to_cpu=bool(args.offload_to_cpu),
        timeout_seconds=max(int(args.timeout_seconds), 60),
        hf_home=Path(args.hf_home).expanduser().resolve() if str(args.hf_home).strip() else None,
        api_key=_optional_text(args.api_key),
    )
    config.jobs_root.mkdir(parents=True, exist_ok=True)
    server = create_server(config=config, host=args.host, port=args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
