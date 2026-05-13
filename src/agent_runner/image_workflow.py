from __future__ import annotations

import base64
import hashlib
import inspect
import importlib.util
import json
import os
import platform
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import textwrap
import time
import zlib
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.error import URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen
from uuid import uuid4


IMAGE_3D_JOB_STATES = (
    "queued",
    "running",
    "succeeded",
    "failed",
)

IMAGE_VIDEO_JOB_STATES = (
    "queued",
    "running",
    "succeeded",
    "failed",
)

IMAGE_GENERATION_SIZE_PROFILES: tuple[dict[str, object], ...] = (
    {
        "id": "portrait-768x1024",
        "label": "Portrait",
        "display_size": "768 x 1024",
        "width": 768,
        "height": 1024,
        "aspect_ratio": "3:4",
        "description": "Best for characters, portraits, and reference recreations. Smaller and steadier on this Mac.",
        "recommended": True,
    },
    {
        "id": "square-768x768",
        "label": "Square",
        "display_size": "768 x 768",
        "width": 768,
        "height": 768,
        "aspect_ratio": "1:1",
        "description": "A safe all-purpose canvas for props, icons, and centered concepts.",
        "recommended": False,
    },
    {
        "id": "landscape-1024x576",
        "label": "Landscape",
        "display_size": "1024 x 576",
        "width": 1024,
        "height": 576,
        "aspect_ratio": "16:9",
        "description": "Wider scene framing without the heavier old dashboard sizes.",
        "recommended": False,
    },
)

DEFAULT_IMAGE_GENERATION_SIZE_PROFILE_ID = "portrait-768x1024"
IMAGE_GENERATION_COUNT_OPTIONS = (1, 2, 3, 4)
MAX_IMAGE_GENERATION_COUNT = 6
DEFAULT_IMAGE_GENERATION_COUNT = 1
IMAGE_GENERATION_PASS_OPTIONS = (2, 4, 8, 10, 12, 16, 20)
DEFAULT_IMAGE_GENERATION_PASSES = 2
IMAGE_REUSE_MODES = ("match", "remix")
DEFAULT_IMAGE_REUSE_MODE = "match"
NEXTCLOUD_IMAGE_EXPORT_SUBPATH = ("Alcove", "Generations")


@dataclass(slots=True)
class StoredFile:
    file_name: str
    mime_type: str
    data: bytes


@dataclass(slots=True)
class GeneratedImageCandidate:
    label: str
    file: StoredFile
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ImageTo3DArtifacts:
    files: dict[str, StoredFile]
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ImageTo3DJobUpdate:
    status: str
    artifacts: dict[str, Path] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class ImageToVideoArtifacts:
    files: dict[str, StoredFile]
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ImageToVideoJobUpdate:
    status: str
    artifacts: dict[str, Path] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class TrellisRuntimeConfig:
    python_path: Path
    repo_path: Path | None = None
    model: str = "microsoft/TRELLIS-image-large"
    device: str = "cuda"
    attn_backend: str | None = None
    spconv_algo: str = "native"
    texture_size: int = 1024
    simplify: float = 0.95
    timeout_seconds: int = 5400
    worker_script_path: Path | None = None


@dataclass(slots=True)
class LtxVideoRuntimeConfig:
    python_path: Path
    repo_path: Path | None = None
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
    worker_script_path: Path | None = None


@dataclass(slots=True)
class RemoteLtxVideoConfig:
    base_url: str
    api_key: str | None = None
    width: int = 512
    height: int = 320
    num_frames: int = 17
    frame_rate: int = 12
    seed: int = 171198
    request_timeout_seconds: int = 30
    download_timeout_seconds: int = 900


@dataclass(slots=True)
class ZImageLocalRuntimeConfig:
    binary_path: Path
    diffusion_model: Path
    text_encoder: Path
    vae: Path
    width: int = 1024
    height: int = 1024
    steps: int = 2
    cfg_scale: float = 1.0
    sampling_method: str = "euler"
    offload_to_cpu: bool = True
    keep_clip_on_cpu: bool = True
    diffusion_flash_attn: bool = True
    timeout_seconds: int | None = None
    extra_args: tuple[str, ...] = ()
    source_config_path: Path | None = None


@dataclass(slots=True)
class AutoRefineConfig:
    enabled: bool = False
    threshold: float = 0.78
    max_retries: int = 1
    judge_model: str | None = None
    prompt_fixer_model: str | None = None


def image_generation_size_profiles() -> list[dict[str, object]]:
    return [dict(profile) for profile in IMAGE_GENERATION_SIZE_PROFILES]


def image_generation_pass_options() -> list[int]:
    return [int(value) for value in IMAGE_GENERATION_PASS_OPTIONS]


def image_generation_count_options() -> list[int]:
    return [int(value) for value in IMAGE_GENERATION_COUNT_OPTIONS]


def zimage_lora_options() -> list[dict[str, object]]:
    runtime_config = discover_zimage_local_runtime_config()
    if runtime_config is None:
        return []
    lora_dir = _lora_model_dir_from_args(runtime_config.extra_args)
    if lora_dir is None or not lora_dir.exists() or not lora_dir.is_dir():
        return []
    options: list[dict[str, object]] = []
    for path in sorted(lora_dir.glob("*.safetensors"), key=lambda item: item.stem.lower()):
        options.append(
            {
                "name": path.stem,
                "label": _lora_label(path.stem),
                "file_name": path.name,
                "path": str(path),
                "byte_size": path.stat().st_size,
            }
        )
    return options


def normalize_image_generation_count(value: object | None) -> int:
    try:
        parsed = int(value) if value is not None else None
    except (TypeError, ValueError):
        parsed = None
    if parsed is not None:
        return min(max(parsed, 1), MAX_IMAGE_GENERATION_COUNT)
    return DEFAULT_IMAGE_GENERATION_COUNT


def normalize_image_generation_passes(value: object | None) -> int:
    try:
        parsed = int(value) if value is not None else None
    except (TypeError, ValueError):
        parsed = None
    if parsed in IMAGE_GENERATION_PASS_OPTIONS:
        return parsed
    return DEFAULT_IMAGE_GENERATION_PASSES


def normalize_image_generation_size_profile_id(value: object) -> str:
    requested = str(value or "").strip()
    valid = {str(profile["id"]) for profile in IMAGE_GENERATION_SIZE_PROFILES}
    if requested in valid:
        return requested
    return DEFAULT_IMAGE_GENERATION_SIZE_PROFILE_ID


def image_generation_size_profile(profile_id: object | None = None) -> dict[str, object]:
    resolved_id = normalize_image_generation_size_profile_id(profile_id)
    for profile in IMAGE_GENERATION_SIZE_PROFILES:
        if str(profile["id"]) == resolved_id:
            return dict(profile)
    return dict(IMAGE_GENERATION_SIZE_PROFILES[0])


def normalize_image_reuse_mode(value: object | None) -> str:
    requested = str(value or "").strip().lower()
    if requested in IMAGE_REUSE_MODES:
        return requested
    return DEFAULT_IMAGE_REUSE_MODE


def image_reuse_strength(mode: object | None) -> float:
    resolved = normalize_image_reuse_mode(mode)
    return 0.35 if resolved == "match" else 0.68


def default_image_asset_export_root() -> Path | None:
    explicit = _optional_text(os.environ.get("ALCOVE_IMAGE_EXPORT_DIR"))
    if explicit:
        return Path(explicit).expanduser().resolve()
    cloud_storage = Path.home() / "Library" / "CloudStorage"
    if not cloud_storage.exists():
        return None
    for candidate in sorted(cloud_storage.glob("Nextcloud*")):
        if not candidate.is_dir():
            continue
        personal_dir = candidate / "Personal"
        base_dir = personal_dir if personal_dir.is_dir() else candidate
        return base_dir.joinpath(*NEXTCLOUD_IMAGE_EXPORT_SUBPATH)
    return None


class ImageWorkflowProvider(Protocol):
    name: str

    def generate_images(self, *, prompt: str, count: int) -> list[GeneratedImageCandidate]:
        ...

    def image_to_3d(self, *, image_path: Path, prompt_context: str | None = None) -> ImageTo3DArtifacts:
        ...


class ImageTo3DProvider(Protocol):
    name: str

    def create_job(self, *, image_path: Path, output_dir: Path, prompt_context: str | None = None) -> str:
        ...

    def get_job_status(self, external_job_id: str) -> ImageTo3DJobUpdate:
        ...


class ImageToVideoProvider(Protocol):
    name: str

    def create_job(self, *, image_path: Path, output_dir: Path, prompt_context: str | None = None) -> str:
        ...

    def get_job_status(self, external_job_id: str) -> ImageToVideoJobUpdate:
        ...


class MockImageWorkflowProvider:
    name = "mock-native"

    _PALETTES = (
        ("#f7efe2", "#d66f4d", "#22313f"),
        ("#e9f6f2", "#3c8c74", "#1f2d2a"),
        ("#f6f0fb", "#7d63d1", "#2b2247"),
        ("#fff4db", "#d6932b", "#3b2d1d"),
    )

    def generate_images(
        self,
        *,
        prompt: str,
        count: int,
        size_profile_id: str | None = None,
        seed: int | None = None,
        init_image_path: Path | None = None,
        remix_mode: str | None = None,
        strength: float | None = None,
        composition_source_image_id: str | None = None,
    ) -> list[GeneratedImageCandidate]:
        trimmed_prompt = " ".join(prompt.split()) or "Untitled prompt"
        size_profile = image_generation_size_profile(size_profile_id)
        width = int(size_profile["width"])
        height = int(size_profile["height"])
        candidates: list[GeneratedImageCandidate] = []
        base_seed = int(seed) if seed is not None else random.SystemRandom().randint(1, 2**31 - 1)
        for index in range(max(1, count)):
            background, accent, ink = self._PALETTES[index % len(self._PALETTES)]
            candidate_number = index + 1
            seed_value = base_seed + index
            svg = _svg_card(
                title=f"Candidate {candidate_number}",
                subtitle=trimmed_prompt,
                background=background,
                accent=accent,
                ink=ink,
                footer="Generated inside Alcove",
                width=width,
                height=height,
            )
            candidates.append(
                GeneratedImageCandidate(
                    label=f"Candidate {candidate_number}",
                    file=StoredFile(
                        file_name=f"candidate-{candidate_number}.svg",
                        mime_type="image/svg+xml",
                        data=svg.encode("utf-8"),
                    ),
                    metadata={
                        "prompt": trimmed_prompt,
                        "candidate_index": candidate_number,
                        "provider": self.name,
                        "width": width,
                        "height": height,
                        "size_profile_id": str(size_profile["id"]),
                        "aspect_ratio": str(size_profile["aspect_ratio"]),
                        "seed": seed_value,
                        "generation_mode": normalize_image_reuse_mode(remix_mode) if init_image_path else "fresh",
                        "init_image_used": bool(init_image_path),
                        "remix_strength": strength,
                        "composition_source_image_id": composition_source_image_id,
                        "init_image_name": init_image_path.name if init_image_path else None,
                    },
                )
            )
        return candidates

    def image_to_3d(self, *, image_path: Path, prompt_context: str | None = None) -> ImageTo3DArtifacts:
        input_png_bytes = _png_bytes_from_source_or_placeholder(image_path)
        preview_png_bytes = _solid_png_bytes(512, 512, (229, 237, 245))
        glb_bytes = _minimal_glb_bytes()
        metadata = {
            "job_type": "image_to_3d",
            "generator": self.name,
            "source_image_name": image_path.name,
            "prompt_context": (prompt_context or "").strip() or None,
            "mesh_vertices": 4,
            "mesh_faces": 4,
            "artifacts": ["input.png", "preview.png", "model.glb", "metadata.json"],
        }
        files = {
            "input_png": StoredFile(
                file_name="input.png",
                mime_type="image/png",
                data=input_png_bytes,
            ),
            "preview_png": StoredFile(
                file_name="preview.png",
                mime_type="image/png",
                data=preview_png_bytes,
            ),
            "glb": StoredFile(
                file_name="model.glb",
                mime_type="model/gltf-binary",
                data=glb_bytes,
            ),
            "metadata_json": StoredFile(
                file_name="metadata.json",
                mime_type="application/json",
                data=json.dumps(metadata, indent=2, sort_keys=True).encode("utf-8"),
            ),
        }
        return ImageTo3DArtifacts(files=files, metadata=metadata)


@dataclass(slots=True)
class _MockImageTo3DJob:
    image_path: Path
    output_dir: Path
    prompt_context: str | None
    created_at: float
    status: str = "queued"
    artifacts: dict[str, Path] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    error: str | None = None


class MockImageTo3DProvider:
    name = "mock-3d"

    def __init__(self) -> None:
        self._renderer = MockImageWorkflowProvider()
        self._jobs: dict[str, _MockImageTo3DJob] = {}
        self._lock = threading.Lock()

    def create_job(self, *, image_path: Path, output_dir: Path, prompt_context: str | None = None) -> str:
        external_job_id = f"mock3d_{uuid4().hex[:12]}"
        job = _MockImageTo3DJob(
            image_path=image_path,
            output_dir=output_dir,
            prompt_context=(prompt_context or "").strip() or None,
            created_at=time.perf_counter(),
        )
        with self._lock:
            self._jobs[external_job_id] = job
        return external_job_id

    def get_job_status(self, external_job_id: str) -> ImageTo3DJobUpdate:
        with self._lock:
            job = self._jobs.get(external_job_id)
            if job is None:
                raise KeyError(external_job_id)
            elapsed = time.perf_counter() - job.created_at
            if job.status == "queued" and elapsed >= 0.08:
                job.status = "running"
            if job.status == "running" and elapsed >= 0.22:
                rendered = self._renderer.image_to_3d(image_path=job.image_path, prompt_context=job.prompt_context)
                job.output_dir.mkdir(parents=True, exist_ok=True)
                job.artifacts = {}
                for key, stored_file in rendered.files.items():
                    destination = job.output_dir / stored_file.file_name
                    destination.write_bytes(stored_file.data)
                    job.artifacts[key] = destination
                job.metadata = dict(rendered.metadata)
                job.metadata["generator"] = self.name
                job.status = "succeeded"
            return ImageTo3DJobUpdate(
                status=job.status,
                artifacts=dict(job.artifacts),
                metadata=dict(job.metadata),
                error=job.error,
            )


@dataclass(slots=True)
class _MockImageToVideoJob:
    image_path: Path
    output_dir: Path
    prompt_context: str | None
    created_at: float
    status: str = "queued"
    artifacts: dict[str, Path] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    error: str | None = None


class MockImageToVideoProvider:
    name = "mock-video"

    def __init__(self) -> None:
        self._jobs: dict[str, _MockImageToVideoJob] = {}
        self._lock = threading.Lock()

    def create_job(self, *, image_path: Path, output_dir: Path, prompt_context: str | None = None) -> str:
        external_job_id = f"mockvideo_{uuid4().hex[:12]}"
        job = _MockImageToVideoJob(
            image_path=image_path,
            output_dir=output_dir,
            prompt_context=(prompt_context or "").strip() or None,
            created_at=time.perf_counter(),
        )
        with self._lock:
            self._jobs[external_job_id] = job
        return external_job_id

    def get_job_status(self, external_job_id: str) -> ImageToVideoJobUpdate:
        with self._lock:
            job = self._jobs.get(external_job_id)
            if job is None:
                raise KeyError(external_job_id)
            elapsed = time.perf_counter() - job.created_at
            if job.status == "queued" and elapsed >= 0.08:
                job.status = "running"
            if job.status == "running" and elapsed >= 0.22:
                input_png_bytes = _png_bytes_from_source_or_placeholder(job.image_path)
                poster_png_bytes = _solid_png_bytes(768, 432, (122, 166, 194))
                clip_mp4_bytes = _minimal_mp4_bytes()
                metadata = {
                    "job_type": "image_to_video",
                    "generator": self.name,
                    "source_image_name": job.image_path.name,
                    "prompt_context": job.prompt_context,
                    "duration_seconds": 1.0,
                    "fps": 25,
                    "frame_count": 25,
                    "artifacts": ["input.png", "poster.png", "clip.mp4", "metadata.json"],
                }
                output_dir = job.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                artifact_payloads = {
                    "input_png": ("input.png", input_png_bytes),
                    "poster_png": ("poster.png", poster_png_bytes),
                    "mp4": ("clip.mp4", clip_mp4_bytes),
                    "metadata_json": ("metadata.json", json.dumps(metadata, indent=2, sort_keys=True).encode("utf-8")),
                }
                job.artifacts = {}
                for key, (file_name, payload) in artifact_payloads.items():
                    destination = output_dir / file_name
                    destination.write_bytes(payload)
                    job.artifacts[key] = destination
                job.metadata = metadata
                job.status = "succeeded"
            return ImageToVideoJobUpdate(
                status=job.status,
                artifacts=dict(job.artifacts),
                metadata=dict(job.metadata),
                error=job.error,
            )


@dataclass(slots=True)
class _LtxProcessJob:
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


class UnavailableImageToVideoProvider:
    name = "ltx-unavailable"

    def __init__(self, reason: str):
        self.reason = reason

    def create_job(self, *, image_path: Path, output_dir: Path, prompt_context: str | None = None) -> str:
        raise RuntimeError(self.reason)

    def get_job_status(self, external_job_id: str) -> ImageToVideoJobUpdate:
        return ImageToVideoJobUpdate(status="failed", error=self.reason)


@dataclass(slots=True)
class _RemoteLtxJob:
    output_dir: Path
    artifacts: dict[str, Path] = field(default_factory=dict)


class RemoteLtxVideoProvider:
    name = "ltx-remote"

    def __init__(self, runtime_config: RemoteLtxVideoConfig):
        self.runtime_config = runtime_config
        self._jobs: dict[str, _RemoteLtxJob] = {}
        self._lock = threading.Lock()

    def create_job(self, *, image_path: Path, output_dir: Path, prompt_context: str | None = None) -> str:
        payload = {
            "image_name": image_path.name,
            "image_base64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
            "prompt_context": (prompt_context or "").strip() or None,
            "options": {
                "width": self.runtime_config.width,
                "height": self.runtime_config.height,
                "num_frames": self.runtime_config.num_frames,
                "frame_rate": self.runtime_config.frame_rate,
                "seed": self.runtime_config.seed,
            },
        }
        response = _request_json(
            self._url("/jobs"),
            method="POST",
            payload=payload,
            headers=self._headers(),
            timeout_seconds=self.runtime_config.request_timeout_seconds,
        )
        external_job_id = str(response.get("job_id") or "").strip()
        if not external_job_id:
            raise RuntimeError("Remote LTX worker did not return a job id.")
        output_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._jobs[external_job_id] = _RemoteLtxJob(output_dir=output_dir)
        return external_job_id

    def get_job_status(self, external_job_id: str) -> ImageToVideoJobUpdate:
        with self._lock:
            handle = self._jobs.get(external_job_id)
            if handle is None:
                raise KeyError(external_job_id)
        payload = _request_json(
            self._url(f"/jobs/{quote(external_job_id, safe='')}"),
            headers=self._headers(),
            timeout_seconds=self.runtime_config.request_timeout_seconds,
        )
        status = str(payload.get("status") or "queued").strip().lower() or "queued"
        metadata = _dict_copy(payload.get("metadata"))
        error = _optional_text(payload.get("error"))
        if status != "succeeded":
            return ImageToVideoJobUpdate(status=status, metadata=metadata, error=error)

        if handle.artifacts and all(path.exists() for path in handle.artifacts.values()):
            return ImageToVideoJobUpdate(status="succeeded", artifacts=dict(handle.artifacts), metadata=metadata)

        artifacts_payload = payload.get("artifacts")
        if not isinstance(artifacts_payload, dict) or not artifacts_payload:
            raise RuntimeError("Remote LTX worker marked the job succeeded without artifact URLs.")
        artifacts = self._download_artifacts(handle.output_dir, artifacts_payload)
        with self._lock:
            handle.artifacts = dict(artifacts)
        return ImageToVideoJobUpdate(status="succeeded", artifacts=artifacts, metadata=metadata)

    def _download_artifacts(self, output_dir: Path, artifacts_payload: dict[object, object]) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded: dict[str, Path] = {}
        for raw_key, raw_value in artifacts_payload.items():
            key = str(raw_key or "").strip()
            artifact_url = str(raw_value or "").strip()
            if not key or not artifact_url:
                continue
            resolved_url = self._url(artifact_url)
            destination = output_dir / _video_artifact_file_name(key, resolved_url)
            body = _request_bytes(
                resolved_url,
                headers=self._headers(),
                timeout_seconds=self.runtime_config.download_timeout_seconds,
            )
            destination.write_bytes(body)
            downloaded[key] = destination
        return downloaded

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.runtime_config.api_key:
            headers["Authorization"] = f"Bearer {self.runtime_config.api_key}"
        return headers

    def _url(self, path_or_url: str) -> str:
        target = str(path_or_url or "").strip()
        if target.startswith("http://") or target.startswith("https://"):
            return target
        return urljoin(self.runtime_config.base_url.rstrip("/") + "/", target.lstrip("/"))


class LtxProcessImageToVideoProvider:
    name = "ltx-video"

    def __init__(self, runtime_config: LtxVideoRuntimeConfig):
        self.runtime_config = runtime_config
        self._jobs: dict[str, _LtxProcessJob] = {}
        self._lock = threading.Lock()

    def create_job(self, *, image_path: Path, output_dir: Path, prompt_context: str | None = None) -> str:
        output_dir.mkdir(parents=True, exist_ok=True)
        external_job_id = f"ltxvideo_{uuid4().hex[:12]}"
        status_path = output_dir / "ltx-job.json"
        stdout_path = output_dir / "ltx.stdout.log"
        stderr_path = output_dir / "ltx.stderr.log"
        _write_atomic_json(
            status_path,
            {
                "status": "queued",
                "external_job_id": external_job_id,
            },
        )
        stdout_handle = stdout_path.open("w", encoding="utf-8")
        stderr_handle = stderr_path.open("w", encoding="utf-8")
        cmd = self._build_command(
            image_path=image_path,
            output_dir=output_dir,
            status_path=status_path,
            prompt_context=prompt_context,
        )
        proc = subprocess.Popen(
            cmd,
            cwd=output_dir,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            env=self._build_env(),
        )
        with self._lock:
            self._jobs[external_job_id] = _LtxProcessJob(
                proc=proc,
                output_dir=output_dir,
                status_path=status_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                started_at=time.perf_counter(),
                timeout_seconds=max(int(self.runtime_config.timeout_seconds), 1),
                stdout_handle=stdout_handle,
                stderr_handle=stderr_handle,
            )
        return external_job_id

    def get_job_status(self, external_job_id: str) -> ImageToVideoJobUpdate:
        with self._lock:
            handle = self._jobs.get(external_job_id)
            if handle is None:
                raise KeyError(external_job_id)
        if handle.proc.poll() is None and (time.perf_counter() - handle.started_at) > handle.timeout_seconds:
            handle.proc.terminate()
            _write_atomic_json(
                handle.status_path,
                {
                    "status": "failed",
                    "error": f"LTX video worker timed out after {handle.timeout_seconds} seconds.",
                },
            )
        payload = _read_json_file(handle.status_path, default={})
        if handle.proc.poll() is None:
            return _ltx_job_update_from_payload(payload, handle.output_dir)
        self._close_process_handles(handle)
        parsed = _ltx_job_update_from_payload(payload, handle.output_dir)
        if parsed.status == "failed":
            return parsed
        if handle.proc.returncode not in (0, None):
            error_text = _tail_text(handle.stderr_path) or _tail_text(handle.stdout_path) or "LTX worker failed."
            return ImageToVideoJobUpdate(status="failed", error=error_text)
        if parsed.status == "succeeded":
            return parsed
        inferred_artifacts = _infer_known_video_artifacts(handle.output_dir)
        if inferred_artifacts:
            metadata = _read_json_file(handle.output_dir / "metadata.json", default={})
            return ImageToVideoJobUpdate(
                status="succeeded",
                artifacts=inferred_artifacts,
                metadata=metadata if isinstance(metadata, dict) else {},
            )
        return ImageToVideoJobUpdate(status="failed", error="LTX worker exited without producing artifacts.")

    def _build_command(
        self,
        *,
        image_path: Path,
        output_dir: Path,
        status_path: Path,
        prompt_context: str | None,
    ) -> list[str]:
        worker_script = self.runtime_config.worker_script_path or Path(__file__).with_name("ltx_video_worker.py")
        pipeline_config_path = self.runtime_config.pipeline_config_path or Path(__file__).with_name("ltx_video_2b_distilled_macos.yaml")
        cmd = [
            str(self.runtime_config.python_path),
            str(worker_script),
            "--input",
            str(image_path),
            "--output-dir",
            str(output_dir),
            "--status-path",
            str(status_path),
            "--device",
            self.runtime_config.device,
            "--pipeline-config",
            str(pipeline_config_path),
            "--height",
            str(self.runtime_config.height),
            "--width",
            str(self.runtime_config.width),
            "--num-frames",
            str(self.runtime_config.num_frames),
            "--frame-rate",
            str(self.runtime_config.frame_rate),
            "--seed",
            str(self.runtime_config.seed),
        ]
        if self.runtime_config.repo_path is not None:
            cmd.extend(["--ltx-repo", str(self.runtime_config.repo_path)])
        if self.runtime_config.hf_home is not None:
            cmd.extend(["--hf-home", str(self.runtime_config.hf_home)])
        if self.runtime_config.offload_to_cpu:
            cmd.append("--offload-to-cpu")
        if prompt_context:
            cmd.extend(["--prompt-context", prompt_context])
        return cmd

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.runtime_config.hf_home is not None:
            env["HF_HOME"] = str(self.runtime_config.hf_home)
        env.setdefault("HF_HUB_DISABLE_XET", "1")
        if self.runtime_config.device.lower() == "mps":
            env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        return env

    def _close_process_handles(self, handle: _LtxProcessJob) -> None:
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


@dataclass(slots=True)
class _ThreadedImageTo3DJob:
    status: str = "queued"
    artifacts: dict[str, Path] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    error: str | None = None


class ThreadedImageTo3DProviderAdapter:
    def __init__(self, provider: ImageWorkflowProvider):
        self._provider = provider
        self.name = str(getattr(provider, "name", "image-to-3d")).strip() or "image-to-3d"
        self._jobs: dict[str, _ThreadedImageTo3DJob] = {}
        self._lock = threading.Lock()

    def create_job(self, *, image_path: Path, output_dir: Path, prompt_context: str | None = None) -> str:
        external_job_id = f"{self.name.replace(' ', '-')}_{uuid4().hex[:12]}"
        with self._lock:
            self._jobs[external_job_id] = _ThreadedImageTo3DJob()
        threading.Thread(
            target=self._run_job,
            args=(external_job_id, image_path, output_dir, prompt_context),
            daemon=True,
        ).start()
        return external_job_id

    def get_job_status(self, external_job_id: str) -> ImageTo3DJobUpdate:
        with self._lock:
            job = self._jobs.get(external_job_id)
            if job is None:
                raise KeyError(external_job_id)
            return ImageTo3DJobUpdate(
                status=job.status,
                artifacts=dict(job.artifacts),
                metadata=dict(job.metadata),
                error=job.error,
            )

    def _run_job(self, external_job_id: str, image_path: Path, output_dir: Path, prompt_context: str | None) -> None:
        try:
            time.sleep(0.05)
            with self._lock:
                job = self._jobs[external_job_id]
                job.status = "running"
            rendered = self._provider.image_to_3d(image_path=image_path, prompt_context=prompt_context)
            output_dir.mkdir(parents=True, exist_ok=True)
            artifacts: dict[str, Path] = {}
            for key, stored_file in rendered.files.items():
                destination = output_dir / stored_file.file_name
                destination.write_bytes(stored_file.data)
                artifacts[key] = destination
            with self._lock:
                job = self._jobs[external_job_id]
                job.status = "succeeded"
                job.artifacts = artifacts
                job.metadata = dict(rendered.metadata)
        except Exception as exc:
            with self._lock:
                job = self._jobs.get(external_job_id)
                if job is not None:
                    job.status = "failed"
                    job.error = str(exc)


@dataclass(slots=True)
class _TrellisProcessJob:
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


class UnavailableImageTo3DProvider:
    name = "trellis-unavailable"

    def __init__(self, reason: str):
        self.reason = reason

    def create_job(self, *, image_path: Path, output_dir: Path, prompt_context: str | None = None) -> str:
        raise RuntimeError(self.reason)

    def get_job_status(self, external_job_id: str) -> ImageTo3DJobUpdate:
        return ImageTo3DJobUpdate(status="failed", error=self.reason)


class TrellisProcessImageTo3DProvider:
    name = "trellis"

    def __init__(self, runtime_config: TrellisRuntimeConfig):
        self.runtime_config = runtime_config
        self._jobs: dict[str, _TrellisProcessJob] = {}
        self._lock = threading.Lock()

    def create_job(self, *, image_path: Path, output_dir: Path, prompt_context: str | None = None) -> str:
        output_dir.mkdir(parents=True, exist_ok=True)
        external_job_id = f"trellis_{uuid4().hex[:12]}"
        status_path = output_dir / "trellis-job.json"
        stdout_path = output_dir / "trellis.stdout.log"
        stderr_path = output_dir / "trellis.stderr.log"
        _write_atomic_json(
            status_path,
            {
                "status": "queued",
                "external_job_id": external_job_id,
            },
        )
        stdout_handle = stdout_path.open("w", encoding="utf-8")
        stderr_handle = stderr_path.open("w", encoding="utf-8")
        cmd = self._build_command(
            image_path=image_path,
            output_dir=output_dir,
            status_path=status_path,
            prompt_context=prompt_context,
        )
        proc = subprocess.Popen(
            cmd,
            cwd=output_dir,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            env=self._build_env(),
        )
        with self._lock:
            self._jobs[external_job_id] = _TrellisProcessJob(
                proc=proc,
                output_dir=output_dir,
                status_path=status_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                started_at=time.perf_counter(),
                timeout_seconds=max(int(self.runtime_config.timeout_seconds), 1),
                stdout_handle=stdout_handle,
                stderr_handle=stderr_handle,
            )
        return external_job_id

    def get_job_status(self, external_job_id: str) -> ImageTo3DJobUpdate:
        with self._lock:
            handle = self._jobs.get(external_job_id)
            if handle is None:
                raise KeyError(external_job_id)
        if handle.proc.poll() is None and (time.perf_counter() - handle.started_at) > handle.timeout_seconds:
            handle.proc.terminate()
            payload = {
                "status": "failed",
                "error": f"Trellis worker timed out after {handle.timeout_seconds} seconds.",
            }
            _write_atomic_json(handle.status_path, payload)
        payload = _read_json_file(handle.status_path, default={})
        if handle.proc.poll() is None:
            return _trellis_job_update_from_payload(payload, handle.output_dir)
        self._close_process_handles(handle)
        parsed = _trellis_job_update_from_payload(payload, handle.output_dir)
        if parsed.status == "failed":
            return parsed
        if handle.proc.returncode not in (0, None):
            error_text = _tail_text(handle.stderr_path) or _tail_text(handle.stdout_path) or "Trellis worker failed."
            return ImageTo3DJobUpdate(status="failed", error=error_text)
        if parsed.status == "succeeded":
            return parsed
        inferred_artifacts = _infer_known_3d_artifacts(handle.output_dir)
        if inferred_artifacts:
            metadata = _read_json_file(handle.output_dir / "metadata.json", default={})
            return ImageTo3DJobUpdate(status="succeeded", artifacts=inferred_artifacts, metadata=metadata if isinstance(metadata, dict) else {})
        return ImageTo3DJobUpdate(status="failed", error="Trellis worker exited without producing artifacts.")

    def _build_command(
        self,
        *,
        image_path: Path,
        output_dir: Path,
        status_path: Path,
        prompt_context: str | None,
    ) -> list[str]:
        worker_script = self.runtime_config.worker_script_path or Path(__file__).with_name("trellis_worker.py")
        cmd = [
            str(self.runtime_config.python_path),
            str(worker_script),
            "--input",
            str(image_path),
            "--output-dir",
            str(output_dir),
            "--status-path",
            str(status_path),
            "--model",
            self.runtime_config.model,
            "--device",
            self.runtime_config.device,
            "--texture-size",
            str(self.runtime_config.texture_size),
            "--simplify",
            str(self.runtime_config.simplify),
            "--spconv-algo",
            self.runtime_config.spconv_algo,
        ]
        if self.runtime_config.repo_path is not None:
            cmd.extend(["--trellis-repo", str(self.runtime_config.repo_path)])
        if self.runtime_config.attn_backend:
            cmd.extend(["--attn-backend", self.runtime_config.attn_backend])
        if prompt_context:
            cmd.extend(["--prompt-context", prompt_context])
        return cmd

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.runtime_config.attn_backend:
            env["ATTN_BACKEND"] = self.runtime_config.attn_backend
        env["SPCONV_ALGO"] = self.runtime_config.spconv_algo
        return env

    def _close_process_handles(self, handle: _TrellisProcessJob) -> None:
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


class ZImageLocalWorkflowProvider:
    def __init__(self, runtime_config: ZImageLocalRuntimeConfig):
        self.runtime_config = runtime_config
        self.name = "zimage-local"
        self._three_d_provider = MockImageWorkflowProvider()

    def generate_images(
        self,
        *,
        prompt: str,
        count: int,
        size_profile_id: str | None = None,
        passes: int | None = None,
        seed: int | None = None,
        init_image_path: Path | None = None,
        remix_mode: str | None = None,
        strength: float | None = None,
        composition_source_image_id: str | None = None,
    ) -> list[GeneratedImageCandidate]:
        trimmed_prompt = " ".join(prompt.split()) or "Untitled prompt"
        runtime_config = self.runtime_config_for_profile(size_profile_id, passes=passes)
        size_profile = image_generation_size_profile(size_profile_id)
        candidates: list[GeneratedImageCandidate] = []
        base_seed = int(seed) if seed is not None else random.SystemRandom().randint(1, 2**31 - 1)
        resolved_reuse_mode = normalize_image_reuse_mode(remix_mode) if init_image_path is not None else "fresh"
        resolved_strength = float(strength) if strength is not None else (image_reuse_strength(remix_mode) if init_image_path is not None else None)
        for index in range(max(1, count)):
            candidate_number = index + 1
            seed_value = base_seed + index
            with tempfile.TemporaryDirectory(prefix="alcove-zimage-") as tmp_dir_text:
                tmp_dir = Path(tmp_dir_text)
                output_path = tmp_dir / f"candidate-{candidate_number}.png"
                cmd = self._build_command(
                    prompt=trimmed_prompt,
                    seed=seed_value,
                    output_path=output_path,
                    runtime_config=runtime_config,
                    init_image_path=init_image_path,
                    strength=resolved_strength,
                )
                started_at = time.perf_counter()
                try:
                    completed = subprocess.run(
                        cmd,
                        cwd=tmp_dir,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=runtime_config.timeout_seconds,
                    )
                except subprocess.TimeoutExpired as exc:
                    timeout_seconds = runtime_config.timeout_seconds
                    raise RuntimeError(
                        f"Z-Image local generation timed out for candidate {candidate_number} after {timeout_seconds}s: "
                        f"{_summarize_process_error(exc.stderr or '', exc.stdout or '')}"
                    ) from exc
                if completed.returncode != 0:
                    raise RuntimeError(
                        f"Z-Image local generation failed for candidate {candidate_number} (exit {completed.returncode}): "
                        f"{_summarize_process_error(completed.stderr, completed.stdout)}"
                    )
                if not output_path.exists():
                    raise RuntimeError(f"Z-Image local generation did not produce {output_path.name}.")
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                candidates.append(
                    GeneratedImageCandidate(
                        label=f"Candidate {candidate_number}",
                        file=StoredFile(
                            file_name=output_path.name,
                            mime_type="image/png",
                            data=output_path.read_bytes(),
                        ),
                        metadata={
                            "prompt": trimmed_prompt,
                            "candidate_index": candidate_number,
                            "provider": self.name,
                            "seed": seed_value,
                            "width": runtime_config.width,
                            "height": runtime_config.height,
                            "steps": runtime_config.steps,
                            "generation_duration_ms": duration_ms,
                            "cfg_scale": runtime_config.cfg_scale,
                            "sampling_method": runtime_config.sampling_method,
                            "binary_path": str(runtime_config.binary_path),
                            "offload_to_cpu": runtime_config.offload_to_cpu,
                            "keep_clip_on_cpu": runtime_config.keep_clip_on_cpu,
                            "diffusion_flash_attn": runtime_config.diffusion_flash_attn,
                            "extra_args": list(runtime_config.extra_args),
                            "size_profile_id": str(size_profile["id"]),
                            "aspect_ratio": str(size_profile["aspect_ratio"]),
                            "generation_mode": resolved_reuse_mode,
                            "init_image_used": bool(init_image_path),
                            "remix_strength": resolved_strength,
                            "composition_source_image_id": composition_source_image_id,
                            "init_image_name": init_image_path.name if init_image_path else None,
                            "diffusion_model": runtime_config.diffusion_model.name,
                            "text_encoder": runtime_config.text_encoder.name,
                            "source_config_path": (
                                str(runtime_config.source_config_path)
                                if runtime_config.source_config_path
                                else None
                            ),
                        },
                    )
                )
        return candidates

    def image_to_3d(self, *, image_path: Path, prompt_context: str | None = None) -> ImageTo3DArtifacts:
        return self._three_d_provider.image_to_3d(image_path=image_path, prompt_context=prompt_context)

    def runtime_config_for_profile(self, size_profile_id: str | None = None, *, passes: int | None = None) -> ZImageLocalRuntimeConfig:
        size_profile = image_generation_size_profile(size_profile_id)
        return replace(
            self.runtime_config,
            width=int(size_profile["width"]),
            height=int(size_profile["height"]),
            steps=normalize_image_generation_passes(passes),
        )

    def _build_command(
        self,
        *,
        prompt: str,
        seed: int,
        output_path: Path,
        runtime_config: ZImageLocalRuntimeConfig,
        init_image_path: Path | None = None,
        strength: float | None = None,
    ) -> list[str]:
        cmd = [
            str(runtime_config.binary_path),
            "--diffusion-model",
            str(runtime_config.diffusion_model),
            "--llm",
            str(runtime_config.text_encoder),
            "--vae",
            str(runtime_config.vae),
            "-p",
            prompt,
            "-W",
            str(runtime_config.width),
            "-H",
            str(runtime_config.height),
            "--steps",
            str(runtime_config.steps),
            "--cfg-scale",
            str(runtime_config.cfg_scale),
            "--sampling-method",
            runtime_config.sampling_method,
            "--seed",
            str(seed),
            "--output",
            output_path.name,
        ]
        if init_image_path is not None:
            cmd.extend(["--init-img", str(init_image_path)])
            cmd.extend(["--strength", str(float(strength) if strength is not None else image_reuse_strength(None))])
        if runtime_config.offload_to_cpu:
            cmd.append("--offload-to-cpu")
        if runtime_config.keep_clip_on_cpu:
            cmd.append("--clip-on-cpu")
        if runtime_config.diffusion_flash_attn:
            cmd.append("--diffusion-fa")
        cmd.extend(runtime_config.extra_args)
        return cmd


@dataclass(slots=True)
class ImageAssetRecord:
    id: str
    created_at: str
    updated_at: str
    label: str
    source: str
    mime_type: str
    file_name: str
    relative_path: str
    prompt: str | None = None
    prompt_context: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ImageWorkflowJobRecord:
    id: str
    created_at: str
    updated_at: str
    job_type: str
    source_image_id: str
    status: str
    provider: str
    output_dir: str
    external_job_id: str | None = None
    prompt_context: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    error: str | None = None


class ImageWorkflowStore:
    def __init__(self, workspace_dir: Path, *, asset_export_root: Path | None = None):
        self.workspace_dir = workspace_dir
        self.root = workspace_dir / "image-workflow"
        self.library_config_path = self.root / "library.json"
        self._library_folder = self._configured_library_folder()
        self.asset_export_root = asset_export_root.resolve() if asset_export_root is not None else None
        self.manifest_path = self.root / "manifest.json"
        self.assets_dir = self._prepare_assets_dir()
        self._migrate_assets_to_flat_layout()
        self.image_to_3d_jobs_dir = workspace_dir / "outputs" / "image_to_3d"
        self.image_to_video_jobs_dir = workspace_dir / "outputs" / "image_to_video"

    def list_assets(self) -> list[ImageAssetRecord]:
        manifest = self._load_manifest()
        manifest = self._reconcile_missing_assets(manifest)
        manifest = self._index_library_folder_assets(manifest)
        return [self._asset_from_raw(item) for item in manifest.get("assets", [])]

    def list_jobs(self, *, job_type: str | None = None) -> list[ImageWorkflowJobRecord]:
        manifest = self._load_manifest()
        manifest = self._reconcile_missing_assets(manifest)
        jobs = [self._job_from_raw(item) for item in manifest.get("jobs", [])]
        if job_type:
            return [item for item in jobs if item.job_type == job_type]
        return jobs

    def selected_image_id(self) -> str | None:
        manifest = self._load_manifest()
        manifest = self._reconcile_missing_assets(manifest)
        value = str(manifest.get("selected_image_id") or "").strip()
        return value or None

    def set_selected_image(self, image_id: str | None) -> None:
        manifest = self._load_manifest()
        manifest["selected_image_id"] = image_id
        self._save_manifest(manifest)

    def get_asset(self, image_id: str) -> ImageAssetRecord:
        for asset in self.list_assets():
            if asset.id == image_id:
                return asset
        raise KeyError(image_id)

    def get_job(self, job_id: str) -> ImageWorkflowJobRecord:
        for job in self.list_jobs():
            if job.id == job_id:
                return job
        raise KeyError(job_id)

    def delete_asset(self, image_id: str) -> dict[str, object]:
        manifest = self._load_manifest()
        assets_raw = list(manifest.get("assets", []))
        jobs_raw = list(manifest.get("jobs", []))
        target_asset: ImageAssetRecord | None = None
        remaining_assets: list[object] = []
        removed_jobs: list[ImageWorkflowJobRecord] = []

        for raw in assets_raw:
            asset = self._asset_from_raw(raw)
            if asset.id == image_id:
                target_asset = asset
            else:
                remaining_assets.append(raw)
        if target_asset is None:
            raise KeyError(image_id)

        remaining_jobs: list[object] = []
        for raw in jobs_raw:
            job = self._job_from_raw(raw)
            if job.source_image_id == image_id:
                removed_jobs.append(job)
            else:
                remaining_jobs.append(raw)

        selected_image_id = str(manifest.get("selected_image_id") or "").strip() or None
        if selected_image_id == image_id:
            next_selected = None
            if remaining_assets:
                next_selected = self._asset_from_raw(remaining_assets[0]).id
            manifest["selected_image_id"] = next_selected

        manifest["assets"] = remaining_assets
        manifest["jobs"] = remaining_jobs
        self._save_manifest(manifest)

        self._delete_asset_file(target_asset)
        for job in removed_jobs:
            self._delete_job_output_dir(job)

        return {
            "deleted_image_id": image_id,
            "deleted_job_ids": [job.id for job in removed_jobs],
            "deleted_job_count": len(removed_jobs),
        }

    def add_uploaded_asset(
        self,
        *,
        file_name: str,
        mime_type: str,
        data: bytes,
        prompt_context: str | None = None,
    ) -> ImageAssetRecord:
        asset_id = f"img_{uuid4().hex[:12]}"
        now = _timestamp_now()
        suffix = Path(file_name).suffix or _suffix_for_mime(mime_type)
        stored_name = _flat_asset_file_name(asset_id, f"source{suffix}")
        destination = self.assets_dir / stored_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        asset = ImageAssetRecord(
            id=asset_id,
            created_at=now,
            updated_at=now,
            label=Path(file_name).stem or asset_id,
            source="upload",
            mime_type=mime_type,
            file_name=stored_name,
            relative_path=_relative_to_workspace(destination, self.workspace_dir),
            prompt_context=(prompt_context or "").strip() or None,
            metadata={
                "original_file_name": file_name,
                "byte_size": len(data),
            },
        )
        manifest = self._load_manifest()
        assets = [item for item in manifest.get("assets", []) if str(item.get("id")) != asset.id]
        assets.insert(0, self._asset_to_raw(asset))
        manifest["assets"] = assets
        manifest["selected_image_id"] = asset.id
        self._save_manifest(manifest)
        return asset

    def add_generated_assets(
        self,
        *,
        prompt: str,
        prompt_context: str | None,
        candidates: list[GeneratedImageCandidate],
    ) -> list[ImageAssetRecord]:
        manifest = self._load_manifest()
        assets = list(manifest.get("assets", []))
        created: list[ImageAssetRecord] = []
        for index, candidate in enumerate(candidates, start=1):
            asset_id = f"img_{uuid4().hex[:12]}"
            now = _timestamp_now()
            base_name = candidate.file.file_name or f"candidate-{index}{_suffix_for_mime(candidate.file.mime_type)}"
            stored_name = _flat_asset_file_name(asset_id, base_name)
            destination = self.assets_dir / stored_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(candidate.file.data)
            asset = ImageAssetRecord(
                id=asset_id,
                created_at=now,
                updated_at=now,
                label=candidate.label,
                source="generated",
                mime_type=candidate.file.mime_type,
                file_name=stored_name,
                relative_path=_relative_to_workspace(destination, self.workspace_dir),
                prompt=prompt.strip() or None,
                prompt_context=(prompt_context or "").strip() or None,
                metadata=dict(candidate.metadata),
            )
            created.append(asset)
            assets.insert(0, self._asset_to_raw(asset))
        manifest["assets"] = assets
        if created:
            manifest["selected_image_id"] = created[0].id
        self._save_manifest(manifest)
        return created

    def create_image_to_3d_job(
        self,
        *,
        source_image_id: str,
        provider: str,
        prompt_context: str | None = None,
    ) -> ImageWorkflowJobRecord:
        return self._create_job(
            job_type="image_to_3d",
            output_root=self.image_to_3d_jobs_dir,
            source_image_id=source_image_id,
            provider=provider,
            prompt_context=prompt_context,
        )

    def create_image_to_video_job(
        self,
        *,
        source_image_id: str,
        provider: str,
        prompt_context: str | None = None,
    ) -> ImageWorkflowJobRecord:
        return self._create_job(
            job_type="image_to_video",
            output_root=self.image_to_video_jobs_dir,
            source_image_id=source_image_id,
            provider=provider,
            prompt_context=prompt_context,
        )

    def _create_job(
        self,
        *,
        job_type: str,
        output_root: Path,
        source_image_id: str,
        provider: str,
        prompt_context: str | None = None,
    ) -> ImageWorkflowJobRecord:
        self.get_asset(source_image_id)
        manifest = self._load_manifest()
        job_id = f"job_{uuid4().hex[:12]}"
        now = _timestamp_now()
        output_dir = output_root / _job_output_dir_name(job_id, now)
        output_dir.mkdir(parents=True, exist_ok=True)
        job = ImageWorkflowJobRecord(
            id=job_id,
            created_at=now,
            updated_at=now,
            job_type=job_type,
            source_image_id=source_image_id,
            status="queued",
            provider=provider,
            output_dir=_relative_to_workspace(output_dir, self.workspace_dir),
            prompt_context=(prompt_context or "").strip() or None,
        )
        jobs = [item for item in manifest.get("jobs", []) if str(item.get("id")) != job.id]
        jobs.insert(0, self._job_to_raw(job))
        manifest["jobs"] = jobs
        self._save_manifest(manifest)
        return job

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        external_job_id: str | None = None,
        artifacts: dict[str, str] | None = None,
        metadata: dict[str, object] | None = None,
        error: str | None = None,
    ) -> ImageWorkflowJobRecord:
        manifest = self._load_manifest()
        jobs = list(manifest.get("jobs", []))
        updated: ImageWorkflowJobRecord | None = None
        for index, raw in enumerate(jobs):
            if str(raw.get("id")) != job_id:
                continue
            job = self._job_from_raw(raw)
            if status:
                job.status = status
            if external_job_id is not None:
                job.external_job_id = external_job_id
            if artifacts is not None:
                job.artifacts = dict(artifacts)
            if metadata is not None:
                job.metadata = dict(metadata)
            if error is not None:
                job.error = error
            job.updated_at = _timestamp_now()
            jobs[index] = self._job_to_raw(job)
            updated = job
            break
        if updated is None:
            raise KeyError(job_id)
        manifest["jobs"] = jobs
        self._save_manifest(manifest)
        return updated

    def save_job_artifacts(self, job_id: str, result: ImageTo3DArtifacts | ImageToVideoArtifacts) -> ImageWorkflowJobRecord:
        job = self.get_job(job_id)
        output_dir = self.workspace_dir / job.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts: dict[str, str] = {}
        for key, stored_file in result.files.items():
            destination = output_dir / stored_file.file_name
            destination.write_bytes(stored_file.data)
            artifacts[key] = _relative_to_workspace(destination, self.workspace_dir)
        return self.update_job(
            job_id,
            artifacts=artifacts,
            metadata=result.metadata,
        )

    def save_job_artifact_paths(
        self,
        job_id: str,
        artifacts: dict[str, Path],
        *,
        metadata: dict[str, object] | None = None,
    ) -> ImageWorkflowJobRecord:
        job = self.get_job(job_id)
        output_dir = self.workspace_dir / job.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        stored_artifacts: dict[str, str] = {}
        for key, artifact_path in artifacts.items():
            source = Path(artifact_path)
            if not source.exists() or not source.is_file():
                raise FileNotFoundError(str(source))
            destination = output_dir / source.name
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)
            stored_artifacts[key] = _relative_to_workspace(destination, self.workspace_dir)
        return self.update_job(
            job_id,
            artifacts=stored_artifacts,
            metadata=metadata if metadata is not None else self.get_job(job_id).metadata,
        )

    def asset_path(self, asset: ImageAssetRecord) -> Path:
        candidate = (self.workspace_dir / asset.relative_path).resolve()
        return candidate

    def workflow_file(self, relative_path: str) -> Path:
        candidate = Path(os.path.abspath(self.workspace_dir / relative_path))
        workspace_root = Path(os.path.abspath(self.workspace_dir))
        if candidate != workspace_root and workspace_root not in candidate.parents:
            raise ValueError("Invalid image workflow file path.")
        if not candidate.exists() or not candidate.is_file():
            raise FileNotFoundError(relative_path)
        return candidate

    def snapshot(self) -> dict[str, object]:
        assets = [self._asset_to_raw(item) for item in self.list_assets()]
        jobs = [self._job_to_raw(item) for item in self.list_jobs()]
        return {
            "selected_image_id": self.selected_image_id(),
            "library_folder_path": str(self.current_library_folder()),
            "assets": assets,
            "jobs": jobs,
        }

    def current_library_folder(self) -> Path:
        if self.assets_dir.is_symlink():
            return self.assets_dir.resolve()
        return self.assets_dir

    def set_library_folder(self, folder_path: Path) -> Path:
        target = Path(folder_path).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.library_config_path.write_text(
            json.dumps({"folder_path": str(target)}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self._library_folder = target
        self.assets_dir = self._prepare_assets_dir()
        manifest = self._load_manifest()
        manifest["assets"] = []
        manifest["jobs"] = []
        manifest["selected_image_id"] = None
        self._save_manifest(manifest)
        self._index_library_folder_assets(self._load_manifest())
        return self.current_library_folder()

    def _migrate_assets_to_flat_layout(self) -> None:
        try:
            self._flatten_legacy_asset_directories()
        except OSError:
            return
        manifest = self._load_manifest()
        raw_assets = list(manifest.get("assets", []))
        changed = False
        for raw in raw_assets:
            if not isinstance(raw, dict):
                continue
            asset_id = str(raw.get("id") or "").strip()
            relative_path = str(raw.get("relative_path") or "").strip()
            current_file_name = str(raw.get("file_name") or "").strip()
            if not asset_id or not relative_path:
                continue
            flat_name = _flat_asset_file_name(asset_id, current_file_name or Path(relative_path).name)
            destination = self.assets_dir / flat_name
            current_path = Path(os.path.abspath(self.workspace_dir / relative_path))
            if current_path.exists() and current_path.is_file():
                try:
                    if current_path.resolve() != destination.resolve():
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        if destination.exists():
                            current_path.unlink()
                        else:
                            shutil.move(str(current_path), str(destination))
                except OSError:
                    continue
            if not destination.exists():
                continue
            new_relative_path = _relative_to_workspace(destination, self.workspace_dir)
            if current_file_name != flat_name or relative_path != new_relative_path:
                raw["file_name"] = flat_name
                raw["relative_path"] = new_relative_path
                changed = True
        if changed:
            manifest["assets"] = raw_assets
            self._save_manifest(manifest)
        self._remove_empty_legacy_asset_directories()

    def _flatten_legacy_asset_directories(self) -> None:
        if not self.assets_dir.exists():
            return
        for child in list(self.assets_dir.iterdir()):
            if not child.is_dir() or not child.name.startswith("img_"):
                continue
            for nested in sorted(child.rglob("*")):
                if not nested.is_file():
                    continue
                destination = self.assets_dir / _flat_asset_file_name(child.name, nested.name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    nested.unlink()
                else:
                    shutil.move(str(nested), str(destination))
            shutil.rmtree(child, ignore_errors=True)

    def _remove_empty_legacy_asset_directories(self) -> None:
        if not self.assets_dir.exists():
            return
        for child in list(self.assets_dir.iterdir()):
            if child.is_dir() and child.name.startswith("img_"):
                try:
                    next(child.iterdir())
                except StopIteration:
                    child.rmdir()
                except OSError:
                    continue

    def _delete_asset_file(self, asset: ImageAssetRecord) -> None:
        try:
            asset_path = self.asset_path(asset)
        except OSError:
            return
        try:
            asset_path.unlink(missing_ok=True)
        except OSError:
            return

    def _delete_job_output_dir(self, job: ImageWorkflowJobRecord) -> None:
        candidate = Path(os.path.abspath(self.workspace_dir / job.output_dir))
        workspace_root = Path(os.path.abspath(self.workspace_dir))
        if candidate != workspace_root and workspace_root not in candidate.parents:
            return
        try:
            shutil.rmtree(candidate, ignore_errors=True)
        except OSError:
            return

    def _reconcile_missing_assets(self, manifest: dict[str, object]) -> dict[str, object]:
        raw_assets = list(manifest.get("assets", []))
        raw_jobs = list(manifest.get("jobs", []))
        kept_assets: list[object] = []
        kept_asset_ids: set[str] = set()
        removed_asset_ids: set[str] = set()
        changed = False

        for raw in raw_assets:
            try:
                asset = self._asset_from_raw(raw)
            except ValueError:
                changed = True
                continue
            if self._asset_file_exists(asset):
                kept_assets.append(raw)
                kept_asset_ids.add(asset.id)
            else:
                removed_asset_ids.add(asset.id)
                changed = True

        kept_jobs: list[object] = []
        removed_jobs: list[ImageWorkflowJobRecord] = []
        for raw in raw_jobs:
            try:
                job = self._job_from_raw(raw)
            except ValueError:
                changed = True
                continue
            if job.source_image_id in removed_asset_ids or (job.source_image_id and job.source_image_id not in kept_asset_ids):
                removed_jobs.append(job)
                changed = True
            else:
                kept_jobs.append(raw)

        selected_image_id = str(manifest.get("selected_image_id") or "").strip() or None
        next_selected = selected_image_id
        if next_selected and next_selected not in kept_asset_ids:
            next_selected = self._asset_from_raw(kept_assets[0]).id if kept_assets else None
            changed = True

        if not changed:
            return manifest

        manifest["assets"] = kept_assets
        manifest["jobs"] = kept_jobs
        manifest["selected_image_id"] = next_selected
        self._save_manifest(manifest)
        for job in removed_jobs:
            self._delete_job_output_dir(job)
        return manifest

    def _index_library_folder_assets(self, manifest: dict[str, object]) -> dict[str, object]:
        try:
            assets_root = self.current_library_folder()
        except OSError:
            return manifest
        if not assets_root.exists() or not assets_root.is_dir():
            return manifest
        raw_assets = list(manifest.get("assets", []))
        known_paths = {
            str(raw.get("relative_path") or "")
            for raw in raw_assets
            if isinstance(raw, dict)
        }
        added: list[dict[str, object]] = []
        for child in sorted(assets_root.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_file() or not _is_supported_image_file(child):
                continue
            if _is_managed_flat_asset_file_name(child.name):
                continue
            relative_path = f"image-workflow/assets/{child.name}"
            if relative_path in known_paths:
                continue
            stat = child.stat()
            timestamp = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")
            asset_id = f"img_lib_{hashlib.sha1(str(child.resolve()).encode('utf-8')).hexdigest()[:12]}"
            added.append(
                self._asset_to_raw(
                    ImageAssetRecord(
                        id=asset_id,
                        created_at=timestamp,
                        updated_at=timestamp,
                        label=child.stem,
                        source="upload",
                        mime_type=_mime_type_for_image_file(child),
                        file_name=child.name,
                        relative_path=relative_path,
                        metadata={
                            "original_file_name": child.name,
                            "byte_size": stat.st_size,
                            "library_folder_path": str(assets_root),
                            "library_indexed": True,
                        },
                    )
                )
            )
        if not added:
            return manifest
        manifest["assets"] = [*added, *raw_assets]
        if not str(manifest.get("selected_image_id") or "").strip():
            manifest["selected_image_id"] = self._asset_from_raw(added[0]).id
        self._save_manifest(manifest)
        return manifest

    def _asset_file_exists(self, asset: ImageAssetRecord) -> bool:
        try:
            asset_path = self.asset_path(asset)
        except OSError:
            return False
        return asset_path.exists() and asset_path.is_file()

    def _prepare_assets_dir(self) -> Path:
        local_assets_dir = self.root / "assets"
        export_root = self._library_folder or self.asset_export_root
        if export_root is None:
            return local_assets_dir
        export_assets_dir = export_root
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            export_assets_dir.mkdir(parents=True, exist_ok=True)
            if local_assets_dir.is_symlink():
                current_target = local_assets_dir.resolve()
                if current_target != export_assets_dir.resolve():
                    if self._library_folder is None and current_target.exists() and current_target.is_dir() and any(current_target.iterdir()):
                        shutil.copytree(current_target, export_assets_dir, dirs_exist_ok=True)
                    local_assets_dir.unlink()
                    local_assets_dir.symlink_to(export_assets_dir, target_is_directory=True)
                return local_assets_dir
            if local_assets_dir.exists():
                if not local_assets_dir.is_dir():
                    return local_assets_dir
                if any(local_assets_dir.iterdir()):
                    shutil.copytree(local_assets_dir, export_assets_dir, dirs_exist_ok=True)
                shutil.rmtree(local_assets_dir)
            local_assets_dir.symlink_to(export_assets_dir, target_is_directory=True)
            return local_assets_dir
        except OSError:
            return local_assets_dir

    def _configured_library_folder(self) -> Path | None:
        try:
            raw = json.loads(self.library_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        folder_text = str(raw.get("folder_path") or "").strip()
        if not folder_text:
            return None
        return Path(folder_text).expanduser().resolve()

    def _load_manifest(self) -> dict[str, object]:
        if not self.manifest_path.exists():
            return {
                "selected_image_id": None,
                "assets": [],
                "jobs": [],
            }
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "selected_image_id": None,
                "assets": [],
                "jobs": [],
            }
        if not isinstance(raw, dict):
            return {
                "selected_image_id": None,
                "assets": [],
                "jobs": [],
            }
        raw.setdefault("selected_image_id", None)
        raw.setdefault("assets", [])
        raw.setdefault("jobs", [])
        return raw

    def _save_manifest(self, payload: dict[str, object]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp_path = self.manifest_path.with_suffix(f".{uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, self.manifest_path)

    def _asset_from_raw(self, raw: object) -> ImageAssetRecord:
        if not isinstance(raw, dict):
            raise ValueError("Invalid image asset record.")
        return ImageAssetRecord(
            id=str(raw.get("id") or ""),
            created_at=str(raw.get("created_at") or _timestamp_now()),
            updated_at=str(raw.get("updated_at") or _timestamp_now()),
            label=str(raw.get("label") or "Image"),
            source=str(raw.get("source") or "generated"),
            mime_type=str(raw.get("mime_type") or "application/octet-stream"),
            file_name=str(raw.get("file_name") or "asset.bin"),
            relative_path=str(raw.get("relative_path") or ""),
            prompt=_optional_text(raw.get("prompt")),
            prompt_context=_optional_text(raw.get("prompt_context")),
            metadata=_dict_copy(raw.get("metadata")),
        )

    def _asset_to_raw(self, asset: ImageAssetRecord) -> dict[str, object]:
        return asdict(asset)

    def _job_from_raw(self, raw: object) -> ImageWorkflowJobRecord:
        if not isinstance(raw, dict):
            raise ValueError("Invalid image workflow job record.")
        return ImageWorkflowJobRecord(
            id=str(raw.get("id") or ""),
            created_at=str(raw.get("created_at") or _timestamp_now()),
            updated_at=str(raw.get("updated_at") or _timestamp_now()),
            job_type=str(raw.get("job_type") or "image_to_3d"),
            source_image_id=str(raw.get("source_image_id") or ""),
            status=str(raw.get("status") or "queued"),
            provider=str(raw.get("provider") or "mock-native"),
            output_dir=str(raw.get("output_dir") or ""),
            external_job_id=_optional_text(raw.get("external_job_id")),
            prompt_context=_optional_text(raw.get("prompt_context")),
            artifacts={str(key): str(value) for key, value in _dict_copy(raw.get("artifacts")).items()},
            metadata=_dict_copy(raw.get("metadata")),
            error=_optional_text(raw.get("error")),
        )

    def _job_to_raw(self, job: ImageWorkflowJobRecord) -> dict[str, object]:
        return asdict(job)


def default_mock_provider() -> ImageWorkflowProvider:
    return MockImageWorkflowProvider()


def default_image_to_3d_provider() -> ImageTo3DProvider:
    mode = os.environ.get("ALCOVE_IMAGE_TO_3D_PROVIDER", "auto").strip().lower()
    if mode == "mock":
        return MockImageTo3DProvider()
    runtime_config = discover_trellis_runtime_config()
    if runtime_config is not None:
        return TrellisProcessImageTo3DProvider(runtime_config)
    if mode == "trellis":
        return UnavailableImageTo3DProvider(
            "Trellis 3D worker unavailable. Set ALCOVE_TRELLIS_PYTHON and optionally ALCOVE_TRELLIS_REPO before enabling Trellis."
        )
    return MockImageTo3DProvider()


def default_image_to_video_provider() -> ImageToVideoProvider:
    mode = os.environ.get("ALCOVE_IMAGE_TO_VIDEO_PROVIDER", "auto").strip().lower()
    if mode == "mock":
        return MockImageToVideoProvider()
    remote_runtime_config = discover_remote_ltx_video_config()
    if mode in {"ltx-remote", "remote"}:
        if remote_runtime_config is not None:
            return RemoteLtxVideoProvider(remote_runtime_config)
        return UnavailableImageToVideoProvider(
            "Remote LTX worker unavailable. Set ALCOVE_LTX_REMOTE_URL and optionally ALCOVE_LTX_REMOTE_API_KEY before enabling the remote video worker."
        )
    runtime_config = discover_ltx_video_runtime_config()
    if runtime_config is not None:
        return LtxProcessImageToVideoProvider(runtime_config)
    if remote_runtime_config is not None:
        return RemoteLtxVideoProvider(remote_runtime_config)
    if mode == "ltx":
        return UnavailableImageToVideoProvider(
            "LTX video worker unavailable. Install the local LTX runtime or set ALCOVE_LTX_PYTHON and optionally ALCOVE_LTX_REPO before enabling LTX."
        )
    return MockImageToVideoProvider()


def default_image_workflow_provider() -> ImageWorkflowProvider:
    mode = os.environ.get("ALCOVE_IMAGE_PROVIDER", "auto").strip().lower()
    if mode == "mock":
        return default_mock_provider()
    runtime_config = discover_zimage_local_runtime_config()
    if runtime_config is not None:
        return ZImageLocalWorkflowProvider(runtime_config)
    return default_mock_provider()


def discover_ltx_video_runtime_config() -> LtxVideoRuntimeConfig | None:
    explicit = _ltx_runtime_config_from_env()
    if explicit is not None:
        return explicit
    for candidate in _candidate_ltx_repo_paths():
        runtime_config = _ltx_runtime_config_from_repo(candidate)
        if runtime_config is not None:
            return runtime_config
    return None


def discover_remote_ltx_video_config() -> RemoteLtxVideoConfig | None:
    remote_url = os.environ.get("ALCOVE_LTX_REMOTE_URL", "").strip()
    if not remote_url:
        return None
    width, height = _parse_size_value(os.environ.get("ALCOVE_LTX_SIZE", "512x320"))
    return RemoteLtxVideoConfig(
        base_url=remote_url.rstrip("/"),
        api_key=_optional_text(os.environ.get("ALCOVE_LTX_REMOTE_API_KEY")),
        width=max(width, 128),
        height=max(height, 128),
        num_frames=_bounded_int(os.environ.get("ALCOVE_LTX_NUM_FRAMES"), default=17, minimum=9),
        frame_rate=_bounded_int(os.environ.get("ALCOVE_LTX_FRAME_RATE"), default=12, minimum=1),
        seed=_bounded_int(os.environ.get("ALCOVE_LTX_SEED"), default=171198, minimum=1),
        request_timeout_seconds=_bounded_int(os.environ.get("ALCOVE_LTX_REMOTE_TIMEOUT_SECONDS"), default=30, minimum=1),
        download_timeout_seconds=_bounded_int(
            os.environ.get("ALCOVE_LTX_REMOTE_DOWNLOAD_TIMEOUT_SECONDS"),
            default=900,
            minimum=1,
        ),
    )


def _ltx_runtime_config_from_env() -> LtxVideoRuntimeConfig | None:
    repo_text = os.environ.get("ALCOVE_LTX_REPO", "").strip()
    python_text = os.environ.get("ALCOVE_LTX_PYTHON", "").strip()
    pipeline_config_text = os.environ.get("ALCOVE_LTX_PIPELINE_CONFIG", "").strip()
    hf_home_text = os.environ.get("ALCOVE_LTX_HF_HOME", "").strip()
    worker_text = os.environ.get("ALCOVE_LTX_WORKER_SCRIPT", "").strip()
    repo_path = Path(repo_text).expanduser() if repo_text else None
    python_path = Path(python_text).expanduser() if python_text else (
        repo_path / "env" / "bin" / "python" if repo_path is not None else None
    )
    pipeline_config_path = Path(pipeline_config_text).expanduser() if pipeline_config_text else _default_ltx_pipeline_config_path()
    hf_home = Path(hf_home_text).expanduser() if hf_home_text else (
        repo_path.parent / "models" / "huggingface" if repo_path is not None else None
    )
    worker_script_path = Path(worker_text).expanduser() if worker_text else None
    if python_path is None:
        return None
    width, height = _parse_size_value(os.environ.get("ALCOVE_LTX_SIZE", "512x320"))
    return _validated_ltx_runtime_config(
        python_path=python_path,
        repo_path=repo_path,
        pipeline_config_path=pipeline_config_path,
        device=(os.environ.get("ALCOVE_LTX_DEVICE", _default_ltx_device()).strip() or _default_ltx_device()),
        width=width,
        height=height,
        num_frames=_bounded_int(os.environ.get("ALCOVE_LTX_NUM_FRAMES"), default=17, minimum=9),
        frame_rate=_bounded_int(os.environ.get("ALCOVE_LTX_FRAME_RATE"), default=12, minimum=1),
        seed=_bounded_int(os.environ.get("ALCOVE_LTX_SEED"), default=171198, minimum=1),
        offload_to_cpu=_env_flag("ALCOVE_LTX_OFFLOAD_TO_CPU", default=False),
        timeout_seconds=_bounded_int(os.environ.get("ALCOVE_LTX_TIMEOUT_SECONDS"), default=5400, minimum=60),
        hf_home=hf_home,
        worker_script_path=worker_script_path,
    )


def _candidate_ltx_repo_paths() -> list[Path]:
    home = Path.home()
    paths = [
        home / "Documents/codex/lab/ai-video/local/LTX-Video",
        home / "Documents/codex/lab/video/local/LTX-Video",
        home / "Documents/codex/lab/LTX-Video",
    ]
    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(path)
    return unique_paths


def _ltx_runtime_config_from_repo(repo_path: Path) -> LtxVideoRuntimeConfig | None:
    repo_path = repo_path.expanduser()
    python_path = repo_path / "env" / "bin" / "python"
    hf_home = repo_path.parent / "models" / "huggingface"
    return _validated_ltx_runtime_config(
        python_path=python_path,
        repo_path=repo_path,
        pipeline_config_path=_default_ltx_pipeline_config_path(),
        device=_default_ltx_device(),
        width=512,
        height=320,
        num_frames=17,
        frame_rate=12,
        seed=171198,
        offload_to_cpu=False,
        timeout_seconds=5400,
        hf_home=hf_home,
        worker_script_path=None,
    )


def _validated_ltx_runtime_config(
    *,
    python_path: Path,
    repo_path: Path | None,
    pipeline_config_path: Path | None,
    device: str,
    width: int,
    height: int,
    num_frames: int,
    frame_rate: int,
    seed: int,
    offload_to_cpu: bool,
    timeout_seconds: int,
    hf_home: Path | None,
    worker_script_path: Path | None,
) -> LtxVideoRuntimeConfig | None:
    if not str(python_path).strip() or not python_path.exists():
        return None
    if repo_path is not None and (not repo_path.exists() or not repo_path.is_dir()):
        return None
    if pipeline_config_path is not None and not pipeline_config_path.exists():
        return None
    if worker_script_path is not None and not worker_script_path.exists():
        return None
    if not _ltx_runtime_payload_ready(hf_home):
        return None
    return LtxVideoRuntimeConfig(
        python_path=python_path,
        repo_path=repo_path,
        pipeline_config_path=pipeline_config_path,
        device=device.strip() or _default_ltx_device(),
        width=max(int(width), 128),
        height=max(int(height), 128),
        num_frames=max(int(num_frames), 9),
        frame_rate=max(int(frame_rate), 1),
        seed=max(int(seed), 1),
        offload_to_cpu=bool(offload_to_cpu),
        timeout_seconds=max(int(timeout_seconds), 60),
        hf_home=hf_home,
        worker_script_path=worker_script_path,
    )


def _default_ltx_pipeline_config_path() -> Path:
    return Path(__file__).with_name("ltx_video_2b_distilled_macos.yaml")


def _default_ltx_device() -> str:
    return "mps" if platform.system() == "Darwin" else "cuda"


def _ltx_runtime_payload_ready(hf_home: Path | None) -> bool:
    if hf_home is None:
        return False
    hub_root = hf_home / "hub"
    required_patterns = (
        "models--Lightricks--LTX-Video/snapshots/*/ltxv-2b-0.9.6-distilled-04-25.safetensors",
        "models--PixArt-alpha--PixArt-XL-2-1024-MS/snapshots/*/text_encoder/model-00001-of-00002.safetensors",
        "models--PixArt-alpha--PixArt-XL-2-1024-MS/snapshots/*/text_encoder/model-00002-of-00002.safetensors",
    )
    for pattern in required_patterns:
        if not any(hub_root.glob(pattern)):
            return False
    return True


def discover_trellis_runtime_config() -> TrellisRuntimeConfig | None:
    python_text = os.environ.get("ALCOVE_TRELLIS_PYTHON", "").strip()
    repo_text = os.environ.get("ALCOVE_TRELLIS_REPO", "").strip()
    worker_text = os.environ.get("ALCOVE_TRELLIS_WORKER_SCRIPT", "").strip()
    model = os.environ.get("ALCOVE_TRELLIS_MODEL", "microsoft/TRELLIS-image-large").strip() or "microsoft/TRELLIS-image-large"
    device = os.environ.get("ALCOVE_TRELLIS_DEVICE", "cuda").strip() or "cuda"
    attn_backend = _optional_text(os.environ.get("ALCOVE_TRELLIS_ATTN_BACKEND"))
    spconv_algo = os.environ.get("ALCOVE_TRELLIS_SPCONV_ALGO", "native").strip() or "native"
    texture_size = _bounded_int(os.environ.get("ALCOVE_TRELLIS_TEXTURE_SIZE"), default=1024, minimum=128)
    simplify = _bounded_float(os.environ.get("ALCOVE_TRELLIS_SIMPLIFY"), default=0.95, minimum=0.0)
    timeout_seconds = _bounded_int(os.environ.get("ALCOVE_TRELLIS_TIMEOUT_SECONDS"), default=5400, minimum=60)

    repo_path = Path(repo_text).expanduser() if repo_text else None
    if repo_path is not None and not repo_path.exists():
        return None
    worker_script_path = Path(worker_text).expanduser() if worker_text else None
    if worker_script_path is not None and not worker_script_path.exists():
        return None

    if python_text:
        python_path = Path(python_text).expanduser()
        if not python_path.exists():
            return None
        return TrellisRuntimeConfig(
            python_path=python_path,
            repo_path=repo_path,
            model=model,
            device=device,
            attn_backend=attn_backend,
            spconv_algo=spconv_algo,
            texture_size=texture_size,
            simplify=min(simplify, 1.0),
            timeout_seconds=timeout_seconds,
            worker_script_path=worker_script_path,
        )

    if repo_path is None and not _current_python_has_trellis():
        return None
    return TrellisRuntimeConfig(
        python_path=Path(sys.executable),
        repo_path=repo_path,
        model=model,
        device=device,
        attn_backend=attn_backend,
        spconv_algo=spconv_algo,
        texture_size=texture_size,
        simplify=min(simplify, 1.0),
        timeout_seconds=timeout_seconds,
        worker_script_path=worker_script_path,
    )


def normalize_auto_refine_config(raw: dict[str, object] | None) -> AutoRefineConfig:
    payload = raw if isinstance(raw, dict) else {}
    return AutoRefineConfig(
        enabled=bool(payload.get("enabled", False)),
        threshold=_bounded_float(payload.get("threshold"), default=0.78, minimum=0.1),
        max_retries=min(_bounded_int(payload.get("max_retries"), default=1, minimum=0), 3),
        judge_model=_optional_text(payload.get("judge_model")),
        prompt_fixer_model=_optional_text(payload.get("prompt_fixer_model")),
    )


def generate_images_for_provider(
    provider: ImageWorkflowProvider,
    *,
    prompt: str,
    count: int,
    size_profile_id: str | None = None,
    passes: int | None = None,
    seed: int | None = None,
    init_image_path: Path | None = None,
    remix_mode: str | None = None,
    strength: float | None = None,
    composition_source_image_id: str | None = None,
) -> list[GeneratedImageCandidate]:
    resolved_size_profile_id = normalize_image_generation_size_profile_id(size_profile_id)
    kwargs: dict[str, object] = {
        "prompt": prompt,
        "count": count,
    }
    try:
        signature = inspect.signature(provider.generate_images)
    except (TypeError, ValueError):
        signature = None
    parameters = signature.parameters if signature is not None else {}
    if "size_profile_id" in parameters:
        kwargs["size_profile_id"] = resolved_size_profile_id
    if "passes" in parameters and passes is not None:
        kwargs["passes"] = normalize_image_generation_passes(passes)
    if "seed" in parameters and seed is not None:
        kwargs["seed"] = seed
    if "init_image_path" in parameters and init_image_path is not None:
        kwargs["init_image_path"] = init_image_path
    if "remix_mode" in parameters and remix_mode is not None:
        kwargs["remix_mode"] = normalize_image_reuse_mode(remix_mode)
    if "strength" in parameters and strength is not None:
        kwargs["strength"] = strength
    if "composition_source_image_id" in parameters and composition_source_image_id is not None:
        kwargs["composition_source_image_id"] = composition_source_image_id
    return provider.generate_images(**kwargs)


def generate_candidates_with_auto_refine(
    provider: ImageWorkflowProvider,
    *,
    prompt: str,
    prompt_context: str | None,
    ollama_host: str,
    auto_refine: AutoRefineConfig,
    size_profile_id: str | None = None,
    passes: int | None = None,
    seed: int | None = None,
    init_image_path: Path | None = None,
    remix_mode: str | None = None,
    strength: float | None = None,
    composition_source_image_id: str | None = None,
) -> list[GeneratedImageCandidate]:
    initial = generate_images_for_provider(
        provider,
        prompt=prompt,
        count=1,
        size_profile_id=size_profile_id,
        passes=passes,
        seed=seed,
        init_image_path=init_image_path,
        remix_mode=remix_mode,
        strength=strength,
        composition_source_image_id=composition_source_image_id,
    )
    if not initial:
        raise RuntimeError("The image provider did not return any candidates.")
    if not auto_refine.enabled:
        return initial
    candidate = initial[0]
    if candidate.file.mime_type == "image/svg+xml":
        raise RuntimeError("Auto-refine needs a raster image backend, not the mock SVG provider.")
    installed = list_local_ollama_models()
    judge_model = auto_refine.judge_model or pick_first_available_model(
        ("qwen3.5:9b", "qwen3.5:9b-q4_K_M", "llava:latest", "llava"),
        installed,
    )
    if not judge_model:
        raise RuntimeError("Auto-refine needs a local Ollama vision model such as qwen3.5:9b or llava:latest.")
    prompt_fixer_model = auto_refine.prompt_fixer_model or pick_first_available_model(
        ("qwen3.5:9b", "qwen3.5:9b-q4_K_M", "llama3.2:3b", "gemma4:e4b"),
        installed,
    )
    attempt_records: list[dict[str, object]] = []
    current_prompt = prompt
    current_candidate = candidate
    for attempt_index in range(auto_refine.max_retries + 1):
        review = review_generated_candidate(
            candidate=current_candidate,
            original_prompt=prompt,
            current_prompt=current_prompt,
            judge_model=judge_model,
            ollama_host=ollama_host,
        )
        accepted = review["review_status"] == "pass" and float(review["overall_score"]) >= auto_refine.threshold
        attempt_records.append(
            {
                "attempt": attempt_index + 1,
                "prompt": current_prompt,
                "review_status": "pass" if accepted else "fail",
                "overall_score": review["overall_score"],
                "notes": review["notes"],
                "judge_model": judge_model,
            }
        )
        if accepted or attempt_index >= auto_refine.max_retries:
            current_candidate.metadata = dict(current_candidate.metadata)
            current_candidate.metadata["review_loop"] = {
                "enabled": True,
                "status": "pass" if accepted else "fail",
                "overall_score": review["overall_score"],
                "notes": review["notes"],
                "attempt_count": attempt_index + 1,
                "max_retries": auto_refine.max_retries,
                "threshold": auto_refine.threshold,
                "judge_model": judge_model,
                "prompt_fixer_model": prompt_fixer_model,
                "final_prompt": current_prompt,
                "attempts": attempt_records,
            }
            current_candidate.metadata["provider"] = current_candidate.metadata.get("provider") or provider.name
            current_candidate.label = "Refined Candidate" if attempt_index > 0 else current_candidate.label
            return [current_candidate]
        if not prompt_fixer_model:
            current_candidate.metadata = dict(current_candidate.metadata)
            current_candidate.metadata["review_loop"] = {
                "enabled": True,
                "status": "fail",
                "overall_score": review["overall_score"],
                "notes": "Prompt fixer model unavailable for retries.",
                "attempt_count": attempt_index + 1,
                "max_retries": auto_refine.max_retries,
                "threshold": auto_refine.threshold,
                "judge_model": judge_model,
                "prompt_fixer_model": None,
                "final_prompt": current_prompt,
                "attempts": attempt_records,
            }
            return [current_candidate]
        current_prompt = rewrite_prompt_from_review(
            fixer_model=prompt_fixer_model,
            original_prompt=prompt,
            current_prompt=current_prompt,
            review=review,
            ollama_host=ollama_host,
        )
        next_candidates = generate_images_for_provider(
            provider,
            prompt=current_prompt,
            count=1,
            size_profile_id=size_profile_id,
            passes=passes,
            seed=seed,
            init_image_path=init_image_path,
            remix_mode=remix_mode,
            strength=strength,
            composition_source_image_id=composition_source_image_id,
        )
        if not next_candidates:
            raise RuntimeError("The image provider did not return a retry candidate.")
        current_candidate = next_candidates[0]
    return [current_candidate]


def review_generated_candidate(
    *,
    candidate: GeneratedImageCandidate,
    original_prompt: str,
    current_prompt: str,
    judge_model: str,
    ollama_host: str,
) -> dict[str, object]:
    image_path = write_candidate_temp_image(candidate)
    try:
        review_prompt = textwrap.dedent(
            f"""\
            You are evaluating whether an AI-generated image is worth keeping as a strong candidate.

            Return strict JSON only with this schema:
            {{
              "prompt_alignment": "pass" | "fail",
              "composition": "pass" | "fail",
              "cleanliness": "pass" | "fail",
              "overall_score": 0.0,
              "notes": "short practical explanation"
            }}

            Rubric:
            - prompt_alignment: the main subject, scene beat, and important traits from the prompt are clearly present.
            - composition: the image is readable, has a clear focal point, and does not feel muddy, confused, or accidentally cropped.
            - cleanliness: fail for visible text, watermark, logos, signatures, or obvious generation artifacts that make the image a weak keeper.
            - overall_score should be between 0.0 and 1.0.
            - Be pragmatic. "pass" means this image is worth keeping as a serious candidate.

            Original prompt:
            {original_prompt}

            Current prompt:
            {current_prompt}
            """
        ).strip()
        raw_response = ollama_generate(
            ollama_host=ollama_host,
            model=judge_model,
            prompt=review_prompt,
            image_paths=[image_path],
        )
        parsed = parse_json_object(raw_response)
    finally:
        image_path.unlink(missing_ok=True)
    prompt_alignment = normalize_review_rating(parsed.get("prompt_alignment"))
    composition = normalize_review_rating(parsed.get("composition"))
    cleanliness = normalize_review_rating(parsed.get("cleanliness"))
    overall_score = _bounded_float(parsed.get("overall_score"), default=0.0, minimum=0.0)
    if overall_score > 1.0:
        overall_score = 1.0
    notes = _optional_text(parsed.get("notes")) or "No judge notes returned."
    review_status = "pass" if all(item == "pass" for item in (prompt_alignment, composition, cleanliness)) else "fail"
    return {
        "review_status": review_status,
        "prompt_alignment": prompt_alignment,
        "composition": composition,
        "cleanliness": cleanliness,
        "overall_score": overall_score,
        "notes": notes,
        "judge_model": judge_model,
        "raw_response": raw_response,
    }


def rewrite_prompt_from_review(
    *,
    fixer_model: str,
    original_prompt: str,
    current_prompt: str,
    review: dict[str, object],
    ollama_host: str,
) -> str:
    fixer_prompt = textwrap.dedent(
        f"""\
        Rewrite this image prompt to improve the next generation attempt.

        Rules:
        - Make the smallest useful set of edits.
        - Preserve the original scene beat, subject, setting, and overall style direction.
        - Keep the prompt visual and concrete.
        - Explicitly discourage visible text, watermark, logos, signatures, and letters.
        - Improve subject clarity and image readability if the review says the composition is muddy or unclear.
        - Return only the revised prompt text.

        Original prompt:
        {original_prompt}

        Current prompt:
        {current_prompt}

        Review:
        {json.dumps(review, indent=2)}
        """
    ).strip()
    revised = ollama_generate(
        ollama_host=ollama_host,
        model=fixer_model,
        prompt=fixer_prompt,
        image_paths=None,
    ).strip()
    if not revised:
        return deterministic_prompt_correction(current_prompt, review)
    if prompt_rewrite_is_too_lossy(current_prompt, revised):
        return deterministic_prompt_correction(current_prompt, review)
    return revised


def describe_reference_image(
    *,
    image_path: Path,
    ollama_host: str,
    prompt_context: str | None = None,
    preferred_vision_model: str | None = None,
    preferred_prompt_model: str | None = None,
) -> dict[str, object]:
    installed = list_local_ollama_models()
    vision_preferences = _model_preferences(
        preferred_vision_model,
        ("qwen3.5:9b", "qwen3.5:9b-q4_K_M", "llava:latest", "llava"),
    )
    vision_model = pick_first_available_model(
        vision_preferences,
        installed,
    )
    if not vision_model:
        raise RuntimeError("Describe Reference needs a local Ollama vision model such as qwen3.5:9b.")
    prompt_preferences = _model_preferences(
        preferred_prompt_model,
        ("qwen3.5:9b", "qwen3.5:9b-q4_K_M", "llama3.2:3b", "gemma4:e4b"),
    )
    prompt_model = pick_first_available_model(
        prompt_preferences,
        installed,
    )
    reference_prompt = textwrap.dedent(
        f"""\
        You are helping recreate a reference image inside a local image-generation workflow.

        Return strict JSON only with this schema:
        {{
          "subject": "short phrase",
          "scene": "short phrase",
          "composition": "short phrase",
          "palette": "short phrase",
          "lighting": "short phrase",
          "style": "short phrase",
          "mood": "short phrase",
          "important_details": ["detail 1", "detail 2"],
          "recreation_prompt": "one concise visual prompt"
        }}

        Rules:
        - Focus on what is visibly present in the image.
        - Preserve the pose, framing, and scene beat.
        - Mention standout wardrobe, props, environment, and lighting.
        - Keep the recreation prompt concrete and visual.
        - Do not mention the existence of a photo reference.
        - Do not include camera jargon unless it is clearly visible in the composition.
        - Avoid text, watermark, logo, or signature language except to exclude them.

        Optional prompt context:
        {(prompt_context or "None").strip() or "None"}
        """
    ).strip()
    raw_reference = ollama_generate(
        ollama_host=ollama_host,
        model=vision_model,
        prompt=reference_prompt,
        image_paths=[image_path],
    )
    reference = parse_json_object(raw_reference)
    important_details_raw = reference.get("important_details")
    if isinstance(important_details_raw, list):
        important_details = [
            str(item).strip()
            for item in important_details_raw
            if str(item).strip()
        ][:8]
    else:
        important_details = []
    normalized_reference = {
        "subject": _optional_text(reference.get("subject")) or "reference subject",
        "scene": _optional_text(reference.get("scene")) or "reference scene",
        "composition": _optional_text(reference.get("composition")) or "clear focal subject",
        "palette": _optional_text(reference.get("palette")) or "balanced natural color",
        "lighting": _optional_text(reference.get("lighting")) or "soft readable lighting",
        "style": _optional_text(reference.get("style")) or "painterly realism",
        "mood": _optional_text(reference.get("mood")) or "grounded and focused",
        "important_details": important_details,
        "recreation_prompt": _optional_text(reference.get("recreation_prompt")) or "",
    }
    suggested_prompt = normalized_reference["recreation_prompt"] or _fallback_reference_prompt(normalized_reference)
    prompt_notes = "Reference prompt came directly from the vision description."
    raw_prompt_response = ""
    if prompt_model:
        prompt_builder = textwrap.dedent(
            f"""\
            Turn this structured reference description into one strong local image-generation prompt.

            Return strict JSON only with this schema:
            {{
              "generation_prompt": "single prompt string",
              "notes": "short note"
            }}

            Rules:
            - Keep the prompt visual and concrete.
            - Preserve the subject, scene beat, mood, palette, and composition.
            - Keep it compact enough for a local turbo image model.
            - Add a brief cleanliness clause that discourages text, watermark, logos, signatures, and letters.
            - Do not mention "reference image" or "uploaded image".

            Reference description:
            {json.dumps(normalized_reference, indent=2)}
            """
        ).strip()
        raw_prompt_response = ollama_generate(
            ollama_host=ollama_host,
            model=prompt_model,
            prompt=prompt_builder,
            image_paths=None,
        )
        prompt_payload = parse_json_object(raw_prompt_response)
        suggested_prompt = (
            _optional_text(prompt_payload.get("generation_prompt"))
            or _optional_text(prompt_payload.get("prompt"))
            or suggested_prompt
        )
        prompt_notes = _optional_text(prompt_payload.get("notes")) or prompt_notes
    suggested_prompt = suggested_prompt.strip() or _fallback_reference_prompt(normalized_reference)
    return {
        "source_image_name": image_path.name,
        "vision_model": vision_model,
        "prompt_model": prompt_model,
        "reference": normalized_reference,
        "reference_summary": _reference_summary(normalized_reference),
        "suggested_prompt": suggested_prompt,
        "notes": prompt_notes,
        "raw_reference_response": raw_reference,
        "raw_prompt_response": raw_prompt_response,
    }


def discover_zimage_local_runtime_config() -> ZImageLocalRuntimeConfig | None:
    explicit = _runtime_config_from_env()
    if explicit is not None:
        return explicit
    for candidate in _candidate_generation_config_paths():
        runtime_config = _runtime_config_from_generation_file(candidate)
        if runtime_config is not None:
            return runtime_config
    return None


def _runtime_config_from_env() -> ZImageLocalRuntimeConfig | None:
    binary_text = os.environ.get("ALCOVE_ZIMAGE_BINARY", "").strip()
    diffusion_text = os.environ.get("ALCOVE_ZIMAGE_DIFFUSION_MODEL", "").strip()
    encoder_text = os.environ.get("ALCOVE_ZIMAGE_TEXT_ENCODER", "").strip()
    vae_text = os.environ.get("ALCOVE_ZIMAGE_VAE", "").strip()
    if not all((binary_text, diffusion_text, encoder_text, vae_text)):
        return None
    width, height = _parse_size_value(os.environ.get("ALCOVE_ZIMAGE_SIZE", "1024x1024"))
    return _validated_runtime_config(
        binary_path=Path(binary_text).expanduser(),
        diffusion_model=Path(diffusion_text).expanduser(),
        text_encoder=Path(encoder_text).expanduser(),
        vae=Path(vae_text).expanduser(),
        width=width,
        height=height,
        steps=_bounded_int(os.environ.get("ALCOVE_ZIMAGE_STEPS"), default=2, minimum=1),
        cfg_scale=_bounded_float(os.environ.get("ALCOVE_ZIMAGE_CFG_SCALE"), default=1.0, minimum=0.1),
        sampling_method=(os.environ.get("ALCOVE_ZIMAGE_SAMPLING_METHOD", "euler").strip() or "euler"),
        offload_to_cpu=_env_flag("ALCOVE_ZIMAGE_OFFLOAD_TO_CPU", default=True),
        keep_clip_on_cpu=_env_flag("ALCOVE_ZIMAGE_KEEP_CLIP_ON_CPU", default=True),
        diffusion_flash_attn=_env_flag("ALCOVE_ZIMAGE_DIFFUSION_FA", default=True),
        timeout_seconds=_optional_bounded_int(os.environ.get("ALCOVE_ZIMAGE_TIMEOUT_SECONDS"), minimum=60),
        extra_args=tuple(_split_args(os.environ.get("ALCOVE_ZIMAGE_EXTRA_ARGS", ""))),
        source_config_path=None,
    )


def _candidate_generation_config_paths() -> list[Path]:
    explicit = os.environ.get("ALCOVE_ZIMAGE_CONFIG", "").strip()
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit).expanduser())
    home = Path.home()
    paths.extend(
        [
            home / "Documents/codex/personal/projects/ancestor-books/config/generation.json",
            home / "Documents/codex/lab/ai-art/config/generation.json",
        ]
    )
    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(path)
    return unique_paths


def _runtime_config_from_generation_file(path: Path) -> ZImageLocalRuntimeConfig | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    if str(raw.get("generator_backend", "")).strip().lower() != "zimage_local":
        return None
    zimage_local = raw.get("zimage_local")
    if not isinstance(zimage_local, dict):
        return None
    width, height = _parse_size_value(raw.get("generator_size", "1024x1024"))
    return _validated_runtime_config(
        binary_path=Path(str(zimage_local.get("binary_path", "")).strip()).expanduser(),
        diffusion_model=Path(str(zimage_local.get("diffusion_model", "")).strip()).expanduser(),
        text_encoder=Path(str(zimage_local.get("text_encoder", "")).strip()).expanduser(),
        vae=Path(str(zimage_local.get("vae", "")).strip()).expanduser(),
        width=width,
        height=height,
        steps=_bounded_int(raw.get("generator_steps"), default=2, minimum=1),
        cfg_scale=_bounded_float(zimage_local.get("default_cfg_scale"), default=1.0, minimum=0.1),
        sampling_method=str(zimage_local.get("default_sampling_method", "euler")).strip() or "euler",
        offload_to_cpu=bool(zimage_local.get("offload_to_cpu", True)),
        keep_clip_on_cpu=bool(zimage_local.get("keep_clip_on_cpu", zimage_local.get("offload_to_cpu", True))),
        diffusion_flash_attn=bool(zimage_local.get("diffusion_flash_attn", True)),
        timeout_seconds=_optional_bounded_int(zimage_local.get("timeout_seconds"), minimum=60),
        extra_args=tuple(_split_args(zimage_local.get("extra_args", []))),
        source_config_path=path,
    )


def _validated_runtime_config(
    *,
    binary_path: Path,
    diffusion_model: Path,
    text_encoder: Path,
    vae: Path,
    width: int,
    height: int,
    steps: int,
    cfg_scale: float,
    sampling_method: str,
    offload_to_cpu: bool,
    keep_clip_on_cpu: bool,
    diffusion_flash_attn: bool,
    timeout_seconds: int | None,
    extra_args: tuple[str, ...],
    source_config_path: Path | None,
) -> ZImageLocalRuntimeConfig | None:
    if not all(
        (
            str(binary_path).strip(),
            str(diffusion_model).strip(),
            str(text_encoder).strip(),
            str(vae).strip(),
        )
    ):
        return None
    if not (binary_path.exists() and diffusion_model.exists() and text_encoder.exists() and vae.exists()):
        return None
    return ZImageLocalRuntimeConfig(
        binary_path=binary_path,
        diffusion_model=diffusion_model,
        text_encoder=text_encoder,
        vae=vae,
        width=width,
        height=height,
        steps=steps,
        cfg_scale=cfg_scale,
        sampling_method=sampling_method,
        offload_to_cpu=offload_to_cpu,
        keep_clip_on_cpu=keep_clip_on_cpu,
        diffusion_flash_attn=diffusion_flash_attn,
        timeout_seconds=timeout_seconds,
        extra_args=extra_args,
        source_config_path=source_config_path,
    )


def _svg_card(
    *,
    title: str,
    subtitle: str,
    background: str,
    accent: str,
    ink: str,
    footer: str,
    width: int,
    height: int,
) -> str:
    safe_width = max(256, int(width))
    safe_height = max(256, int(height))
    padding = max(48, int(min(safe_width, safe_height) * 0.075))
    headline_size = max(42, int(min(safe_width, safe_height) * 0.06))
    body_size = max(22, int(min(safe_width, safe_height) * 0.03))
    footer_size = max(20, int(min(safe_width, safe_height) * 0.025))
    wrapped = "<tspan x='{x}' dy='0'>".format(x=padding) + "</tspan><tspan x='{x}' dy='{dy}'>".format(
        x=padding,
        dy=max(28, int(body_size * 1.15)),
    ).join(
        _escape_xml(line) for line in textwrap.wrap(subtitle, width=max(18, int(safe_width / 34)))[:4]
    ) + "</tspan>"
    inner_width = safe_width - (padding * 2)
    inner_height = safe_height - (padding * 2)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{safe_width}" height="{safe_height}" viewBox="0 0 {safe_width} {safe_height}" role="img" aria-label="{_escape_xml(title)}">
  <rect width="{safe_width}" height="{safe_height}" rx="{max(32, int(min(safe_width, safe_height) * 0.06))}" fill="{background}" />
  <rect x="{padding}" y="{padding}" width="{inner_width}" height="{inner_height}" rx="{max(28, int(min(safe_width, safe_height) * 0.05))}" fill="white" fill-opacity="0.68" />
  <circle cx="{safe_width - padding - max(64, int(safe_width * 0.08))}" cy="{padding + max(88, int(safe_height * 0.09))}" r="{max(54, int(min(safe_width, safe_height) * 0.09))}" fill="{accent}" fill-opacity="0.18" />
  <path d="M{padding + max(48, int(safe_width * 0.03))} {safe_height - max(180, int(safe_height * 0.28))}c{max(84, int(safe_width * 0.12))}-{max(90, int(safe_height * 0.12))} {max(176, int(safe_width * 0.24))}-{max(148, int(safe_height * 0.22))} {max(274, int(safe_width * 0.37))}-{max(148, int(safe_height * 0.22))} {max(100, int(safe_width * 0.12))} 0 {max(194, int(safe_width * 0.24))} {max(54, int(safe_height * 0.08))} {max(292, int(safe_width * 0.37))} {max(154, int(safe_height * 0.22))}v{max(96, int(safe_height * 0.12))}H{padding + max(48, int(safe_width * 0.03))}z" fill="{accent}" fill-opacity="0.2" />
  <rect x="{padding + 12}" y="{padding + 22}" width="{max(160, int(safe_width * 0.19))}" height="{max(10, int(safe_height * 0.012))}" rx="{max(5, int(safe_height * 0.006))}" fill="{accent}" />
  <text x="{padding + 12}" y="{padding + max(104, int(safe_height * 0.1))}" font-family="Avenir Next, Helvetica Neue, Arial, sans-serif" font-size="{headline_size}" font-weight="700" fill="{ink}">{_escape_xml(title)}</text>
  <text x="{padding + 12}" y="{padding + max(190, int(safe_height * 0.2))}" font-family="Avenir Next, Helvetica Neue, Arial, sans-serif" font-size="{body_size}" font-weight="500" fill="{ink}" opacity="0.84">{wrapped}</text>
  <text x="{padding + 12}" y="{safe_height - padding - max(24, int(safe_height * 0.03))}" font-family="Avenir Next, Helvetica Neue, Arial, sans-serif" font-size="{footer_size}" font-weight="600" fill="{accent}">{_escape_xml(footer)}</text>
</svg>
"""


def _minimal_glb_bytes() -> bytes:
    json_payload = json.dumps(
        {
            "asset": {"version": "2.0", "generator": "alcove-mock"},
            "scene": 0,
            "scenes": [{"nodes": []}],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    json_padding = (4 - (len(json_payload) % 4)) % 4
    json_chunk = json_payload + (b" " * json_padding)
    chunk_length = len(json_chunk)
    total_length = 12 + 8 + chunk_length
    return (
        b"glTF"
        + (2).to_bytes(4, "little")
        + total_length.to_bytes(4, "little")
        + chunk_length.to_bytes(4, "little")
        + b"JSON"
        + json_chunk
    )


def _minimal_mp4_bytes() -> bytes:
    encoded = (
            "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAAIZnJlZQAABEZtZGF0AAACrgYF//+q3EXpvebZSLeW"
            "LNgg2SPu73gyNjQgLSBjb3JlIDE2NSByMzIyMiBiMzU2MDVhIC0gSC4yNjQvTVBFRy00IEFWQyBjb2RlYyAtIENvcHls"
            "ZWZ0IDIwMDMtMjAyNSAtIGh0dHA6Ly93d3cudmlkZW9sYW4ub3JnL3gyNjQuaHRtbCAtIG9wdGlvbnM6IGNhYmFjPTEg"
            "cmVmPTMgZGVibG9jaz0xOjA6MCBhbmFseXNlPTB4MzoweDExMyBtZT1oZXggc3VibWU9NyBwc3k9MSBwc3lfcmQ9MS4w"
            "MDowLjAwIG1peGVkX3JlZj0xIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0xIHRyZWxsaXM9MSA4eDhkY3Q9MSBjcW09MCBk"
            "ZWFkem9uZT0yMSwxMSBmYXN0X3Bza2lwPTEgY2hyb21hX3FwX29mZnNldD0tMiB0aHJlYWRzPTMgbG9va2FoZWFkX3Ro"
            "cmVhZHM9MSBzbGljZWRfdGhyZWFkcz0wIG5yPTAgZGVjaW1hdGU9MSBpbnRlcmxhY2VkPTAgYmx1cmF5X2NvbXBhdD0w"
            "IGNvbnN0cmFpbmVkX2ludHJhPTAgYmZyYW1lcz0zIGJfcHlyYW1pZD0yIGJfYWRhcHQ9MSBiX2JpYXM9MCBkaXJlY3Q9"
            "MSB3ZWlnaHRiPTEgb3Blbl9nb3A9MCB3ZWlnaHRwPTIga2V5aW50PTI1MCBrZXlpbnRfbWluPTI1IHNjZW5lY3V0PTQw"
            "IGludHJhX3JlZnJlc2g9MCByY19sb29rYWhlYWQ9NDAgcmM9Y3JmIG1idHJlZT0xIGNyZj0yMy4wIHFjb21wPTAuNjAg"
            "cXBtaW49MCBxcG1heD02OSBxcHN0ZXA9NCBpcF9yYXRpbz0xLjQwIGFxPTE6MS4wMACAAAAALmWIhAA7//7jq/gUv/Dn"
            "MctkMwrRjT88Ul2zx1C13MiiuTuJHBDJ95CVYAHMNqEAAAALQZokbEO//qmWByQAAAAIQZ5CeIX/AgcAAAAIAZ5hdEK/"
            "ArYAAAAIAZ5jakK/ArcAAAARQZpoSahBaJlMCHf//qmWByUAAAAKQZ6GRREsL/8CBwAAAAgBnqV0Qr8CtwAAAAgBnqdq"
            "Qr8CtgAAABFBmqxJqEFsmUwId//+qZYHJAAAAApBnspFFSwv/wIHAAAACAGe6XRCvwK2AAAACAGe62pCvwK2AAAAEUGa"
            "8EmoQWyZTAhv//6nhA15AAAACkGfDkUVLC//AgcAAAAIAZ8tdEK/ArcAAAAIAZ8vakK/ArYAAAARQZs0SahBbJlMCGf/"
            "/p4QLuAAAAAKQZ9SRRUsL/8CBwAAAAgBn3F0Qr8CtgAAAAgBn3NqQr8CtgAAABFBm3hJqEFsmUwIV//+OEClgQAAAApB"
            "n5ZFFSwv/wIGAAAACAGftXRCvwK3AAAACAGft2pCvwK3AAAEZW1vb3YAAABsbXZoZAAAAAAAAAAAAAAAAAAAA+gAAAPo"
            "AAEAAAEAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAA"
            "AAAAAAAAAAAAAAIAAAOQdHJhawAAAFx0a2hkAAAAAwAAAAAAAAAAAAAAAQAAAAAAAAPoAAAAAAAAAAAAAAAAAAAAAAAB"
            "AAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAQAAAAABgAAAAYAAAAAAAJGVkdHMAAAAcZWxzdAAAAAAAAAABAAAD"
            "6AAABAAAAQAAAAADCG1kaWEAAAAgbWRoZAAAAAAAAAAAAAAAAAAAMgAAADIAVcQAAAAAAC1oZGxyAAAAAAAAAAB2aWRl"
            "AAAAAAAAAAAAAAAAVmlkZW9IYW5kbGVyAAAAArNtaW5mAAAAFHZtaGQAAAABAAAAAAAAAAAAAAAkZGluZgAAABxkcmVm"
            "AAAAAAAAAAEAAAAMdXJsIAAAAAEAAAJzc3RibAAAAL9zdHNkAAAAAAAAAAEAAACvYXZjMQAAAAAAAAABAAAAAAAAAAAA"
            "AAAAAAAAAABgAGAASAAAAEgAAAAAAAAAARVMYXZjNjIuMTEuMTAwIGxpYngyNjQAAAAAAAAAAAAAABj//wAAADVhdmND"
            "AWQACv/hABhnZAAKrNlGNsBEAAADAAQAAAMAyDxIllgBAAZo6+PLIsD9+PgAAAAAEHBhc3AAAAABAAAAAQAAABRidHJ0"
            "AAAAAAAAIfAAAAAAAAAAGHN0dHMAAAAAAAAAAQAAABkAAAIAAAAAFHN0c3MAAAAAAAAAAQAAAAEAAADYY3R0cwAAAAAA"
            "AAAZAAAAAQAABAAAAAABAAAKAAAAAAEAAAQAAAAAAQAAAAAAAAABAAACAAAAAAEAAAoAAAAAAQAABAAAAAABAAAAAAAA"
            "AAEAAAIAAAAAAQAACgAAAAABAAAEAAAAAAEAAAAAAAAAAQAAAgAAAAABAAAKAAAAAAEABAAAAAABAAAAAAAAAAEAAAIA"
            "AAAAAQAACgAAAAABAAAEAAAAAAEAAAAAAAAAAQAAAgAAAAABAAAKAAAAAAEAAAQAAAAAAQAAAAAAAAABAAACAAAAAAEA"
            "AAoAAAAAAQAABAAAAAABAAAAAAAAAAEAAAIAAAAAAcc3RzYwAAAAAAAAABAAAAAQAAABkAAAABAAAAeHN0c3oAAAAAAA"
            "AAAAAAABkAAALkAAAADwAAAAwAAAAMAAAADAAAABUAAAAOAAAADAAAAAwAAAAVAAAADgAAAAwAAAAMAAAAFQAAAA4AAA"
            "AMAAAADAAAABUAAAAOAAAADAAAAAwAAAAVAAAADgAAAAwAAAAMAAAAFHN0Y28AAAAAAAAAAQAAADAAAABhdWR0YQAAAF"
            "ltZXRhAAAAAAAAACFoZGxyAAAAAAAAAABtZGlyYXBwbAAAAAAAAAAAAAAAACxpbHN0AAAAJKl0b28AAAAcZGF0YQAAAA"
            "EAAAAATGF2ZjYyLjMuMTAw"
    )
    return base64.b64decode(encoded + ("=" * (-len(encoded) % 4)))


def _solid_png_bytes(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    row = b"\x00" + bytes(rgb) * width
    raw = row * height
    header = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", header),
            _png_chunk(b"IDAT", zlib.compress(raw, level=9)),
            _png_chunk(b"IEND", b""),
        )
    )


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    body = chunk_type + payload
    return len(payload).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")


def _png_bytes_from_source_or_placeholder(image_path: Path) -> bytes:
    data = image_path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data
    return _solid_png_bytes(512, 512, (243, 238, 230))


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _job_output_dir_name(job_id: str, timestamp: str) -> str:
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.now(timezone.utc)
    return f"{parsed.astimezone(timezone.utc).strftime('%Y-%m-%dT%H-%M-%SZ')}_{job_id}"


def _relative_to_workspace(path: Path, workspace_dir: Path) -> str:
    absolute_path = Path(os.path.abspath(path))
    absolute_workspace = Path(os.path.abspath(workspace_dir))
    try:
        return absolute_path.relative_to(absolute_workspace).as_posix()
    except ValueError:
        return path.resolve().relative_to(workspace_dir.resolve()).as_posix()


def _flat_asset_file_name(asset_id: str, original_name: str) -> str:
    clean_name = Path(str(original_name or "asset.bin")).name or "asset.bin"
    prefix = f"{asset_id}__"
    if clean_name.startswith(prefix):
        return clean_name
    return f"{prefix}{clean_name}"


def _is_managed_flat_asset_file_name(file_name: str) -> bool:
    return re.match(r"^img_[0-9a-f]{12}__", Path(str(file_name)).name or "") is not None


def _suffix_for_mime(mime_type: str) -> str:
    normalized = str(mime_type or "").strip().lower()
    if normalized == "image/png":
        return ".png"
    if normalized in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if normalized == "image/webp":
        return ".webp"
    if normalized == "image/svg+xml":
        return ".svg"
    return ".bin"


def _is_supported_image_file(path: Path) -> bool:
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}


def _mime_type_for_image_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".bmp":
        return "image/bmp"
    if suffix == ".svg":
        return "image/svg+xml"
    return "application/octet-stream"


def _lora_model_dir_from_args(extra_args: tuple[str, ...]) -> Path | None:
    for index, value in enumerate(extra_args):
        if value == "--lora-model-dir" and index + 1 < len(extra_args):
            return Path(extra_args[index + 1]).expanduser()
    return None


def _lora_label(name: str) -> str:
    label = re.sub(r"^zimage_", "", name)
    label = re.sub(r"_v\d+(_onetrainer)?$", "", label)
    label = label.replace("_", " ").replace("-", " ")
    return " ".join(part.capitalize() for part in label.split()) or name


def _fallback_reference_prompt(reference: dict[str, object]) -> str:
    important_details = reference.get("important_details")
    detail_text = ""
    if isinstance(important_details, list):
        detail_items = [str(item).strip() for item in important_details if str(item).strip()][:4]
        if detail_items:
            detail_text = ", " + ", ".join(detail_items)
    parts = [
        _optional_text(reference.get("style")) or "painterly realism",
        _optional_text(reference.get("subject")) or "clear subject",
        _optional_text(reference.get("scene")) or "grounded setting",
        _optional_text(reference.get("composition")) or "clear focal composition",
        _optional_text(reference.get("lighting")) or "soft readable lighting",
        _optional_text(reference.get("palette")) or "balanced color palette",
        _optional_text(reference.get("mood")) or "focused mood",
    ]
    core = ", ".join(part for part in parts if part)
    return f"{core}{detail_text}, no text, no watermark, no logos, no signatures".strip(", ")


def _reference_summary(reference: dict[str, object]) -> str:
    subject = _optional_text(reference.get("subject")) or "subject"
    scene = _optional_text(reference.get("scene")) or "scene"
    mood = _optional_text(reference.get("mood")) or "mood"
    return f"{subject} in {scene}, with a {mood} tone."


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dict_copy(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _current_python_has_trellis() -> bool:
    return importlib.util.find_spec("trellis") is not None


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


def _infer_known_3d_artifacts(output_dir: Path) -> dict[str, Path]:
    mapping = {
        "input_png": output_dir / "input.png",
        "preview_png": output_dir / "preview.png",
        "glb": output_dir / "model.glb",
        "metadata_json": output_dir / "metadata.json",
    }
    return {key: path for key, path in mapping.items() if path.exists() and path.is_file()}


def _infer_known_video_artifacts(output_dir: Path) -> dict[str, Path]:
    mapping = {
        "input_png": output_dir / "input.png",
        "poster_png": output_dir / "poster.png",
        "mp4": output_dir / "clip.mp4",
        "metadata_json": output_dir / "metadata.json",
    }
    return {key: path for key, path in mapping.items() if path.exists() and path.is_file()}


def _video_artifact_file_name(key: str, artifact_url: str) -> str:
    expected = {
        "input_png": "input.png",
        "poster_png": "poster.png",
        "mp4": "clip.mp4",
        "metadata_json": "metadata.json",
    }
    if key in expected:
        return expected[key]
    candidate = Path(artifact_url.split("?", 1)[0]).name
    return candidate or f"{key}.bin"


def _trellis_job_update_from_payload(payload: object, output_dir: Path) -> ImageTo3DJobUpdate:
    data = payload if isinstance(payload, dict) else {}
    status = str(data.get("status") or "queued").strip().lower() or "queued"
    artifacts_payload = data.get("artifacts")
    artifacts: dict[str, Path] = {}
    if isinstance(artifacts_payload, dict):
        for key, value in artifacts_payload.items():
            text = str(value or "").strip()
            if not text:
                continue
            candidate = Path(text)
            if not candidate.is_absolute():
                candidate = (output_dir / candidate).resolve()
            artifacts[str(key)] = candidate
    if not artifacts and status == "succeeded":
        artifacts = _infer_known_3d_artifacts(output_dir)
    return ImageTo3DJobUpdate(
        status=status,
        artifacts=artifacts,
        metadata=_dict_copy(data.get("metadata")),
        error=_optional_text(data.get("error")),
    )


def _ltx_job_update_from_payload(payload: object, output_dir: Path) -> ImageToVideoJobUpdate:
    data = payload if isinstance(payload, dict) else {}
    status = str(data.get("status") or "queued").strip().lower() or "queued"
    artifacts_payload = data.get("artifacts")
    artifacts: dict[str, Path] = {}
    if isinstance(artifacts_payload, dict):
        for key, value in artifacts_payload.items():
            text = str(value or "").strip()
            if not text:
                continue
            candidate = Path(text)
            if not candidate.is_absolute():
                candidate = (output_dir / candidate).resolve()
            artifacts[str(key)] = candidate
    if not artifacts and status == "succeeded":
        artifacts = _infer_known_video_artifacts(output_dir)
    return ImageToVideoJobUpdate(
        status=status,
        artifacts=artifacts,
        metadata=_dict_copy(data.get("metadata")),
        error=_optional_text(data.get("error")),
    )


def _tail_text(path: Path, limit: int = 4000) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return text[-limit:].strip()


def _escape_xml(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def list_local_ollama_models() -> set[str]:
    ollama_bin = find_ollama_binary()
    if ollama_bin is None:
        return set()
    completed = subprocess.run(
        [str(ollama_bin), "list"],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if completed.returncode != 0:
        return set()
    names: set[str] = set()
    for line in completed.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            names.add(parts[0].strip())
    return names


def find_ollama_binary() -> Path | None:
    discovered = shutil.which("ollama")
    candidates = [Path(discovered)] if discovered else []
    candidates.append(Path("/Applications/Ollama.app/Contents/Resources/ollama"))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def pick_first_available_model(preferred: tuple[str, ...], installed: set[str]) -> str | None:
    for requested in preferred:
        if requested in installed:
            return requested
        base_name, has_tag, requested_tag = requested.partition(":")
        for candidate in installed:
            candidate_base, _, candidate_tag = candidate.partition(":")
            if candidate_base != base_name:
                continue
            if not has_tag:
                return candidate
            if requested_tag == "latest":
                return candidate
            requested_head = requested_tag.split("-", 1)[0]
            candidate_head = candidate_tag.split("-", 1)[0]
            if candidate_tag == requested_tag or (requested_head and requested_head == candidate_head):
                return candidate
    return None


def _model_preferences(preferred: str | None, fallback: tuple[str, ...]) -> tuple[str, ...]:
    preferred_text = str(preferred or "").strip()
    if not preferred_text:
        return fallback
    return (preferred_text, *(item for item in fallback if item != preferred_text))


def write_candidate_temp_image(candidate: GeneratedImageCandidate) -> Path:
    suffix = Path(candidate.file.file_name).suffix or _suffix_for_mime(candidate.file.mime_type)
    if suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise RuntimeError("Auto-refine only supports PNG, JPG, or WEBP candidate images.")
    handle = tempfile.NamedTemporaryFile(prefix="alcove-review-", suffix=suffix, delete=False)
    try:
        handle.write(candidate.file.data)
        handle.flush()
    finally:
        handle.close()
    return Path(handle.name)


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: int,
) -> dict[str, object]:
    response_bytes = _request_bytes(
        url,
        method=method,
        payload=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        timeout_seconds=timeout_seconds,
    )
    try:
        parsed = json.loads(response_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Remote worker returned invalid JSON from {url}.") from exc
    return parsed if isinstance(parsed, dict) else {}


def _request_bytes(
    url: str,
    *,
    method: str = "GET",
    payload: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: int,
) -> bytes:
    request = Request(
        url,
        data=payload,
        headers=headers or {},
        method=method,
    )
    try:
        with urlopen(request, timeout=max(int(timeout_seconds), 1)) as response:
            return response.read()
    except URLError as exc:
        raise RuntimeError(f"Could not reach remote worker at {url}: {exc}") from exc


def ollama_generate(
    *,
    ollama_host: str,
    model: str,
    prompt: str,
    image_paths: list[Path] | None,
) -> str:
    base = ollama_host.rstrip("/")
    url = base if base.endswith("/api/generate") else f"{base}/api/generate"
    payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
    if image_paths:
        payload["images"] = [base64.b64encode(path.read_bytes()).decode("ascii") for path in image_paths]
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=300) as response:
            raw = response.read().decode("utf-8")
    except URLError as exc:
        raise RuntimeError(f"Could not reach Ollama at {url}: {exc}") from exc
    body = json.loads(raw)
    return str(body.get("response", "")).strip()


def parse_json_object(text: str) -> dict[str, object]:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


def normalize_review_rating(value: object) -> str:
    text = str(value or "").strip().lower()
    return "pass" if text in {"pass", "ok", "true", "yes"} else "fail"


def prompt_rewrite_is_too_lossy(original: str, revised: str) -> bool:
    if len(revised.strip()) < max(80, int(len(original.strip()) * 0.6)):
        return True
    original_words = {word.lower() for word in re.findall(r"[A-Za-z]{4,}", original)}
    revised_words = {word.lower() for word in re.findall(r"[A-Za-z]{4,}", revised)}
    anchors = {word for word in original_words if word in {"figurine", "portrait", "astronaut", "creature", "robot", "character", "scene"}}
    return bool(anchors and not anchors.intersection(revised_words))


def deterministic_prompt_correction(current_prompt: str, review: dict[str, object]) -> str:
    corrections = ["clean silhouette", "clear focal point", "readable composition", "no text, watermark, or logo"]
    notes = str(review.get("notes", "")).lower()
    if "crop" in notes:
        corrections.append("fully visible subject")
    if "muddy" in notes or "unclear" in notes:
        corrections.append("strong subject separation")
    return f"{current_prompt}. " + ", ".join(corrections)


def _parse_size_value(value: object) -> tuple[int, int]:
    text = str(value or "").strip().lower()
    if "x" not in text:
        return (1024, 1024)
    width_text, height_text = text.split("x", 1)
    try:
        width = max(int(width_text), 64)
        height = max(int(height_text), 64)
    except ValueError:
        return (1024, 1024)
    return (width, height)


def _bounded_int(value: object, *, default: int, minimum: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return default
    return max(parsed, minimum)


def _optional_bounded_int(value: object, *, minimum: int) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = int(text)
    except ValueError:
        return None
    return max(parsed, minimum)


def _bounded_float(value: object, *, default: float, minimum: float) -> float:
    try:
        parsed = float(str(value or "").strip())
    except ValueError:
        return default
    return max(parsed, minimum)


def _split_args(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return text.split() if text else []


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    text = raw.strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _process_output_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _summarize_process_error(stderr: object, stdout: object) -> str:
    combined = "\n".join(
        part.strip()
        for part in (_process_output_text(stderr), _process_output_text(stdout))
        if part.strip()
    ).strip()
    if not combined:
        return "No process output was captured."
    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    summary = " | ".join(lines[-4:])
    if _looks_like_metal_out_of_memory(combined):
        return (
            "Metal GPU ran out of memory while running local Z-Image. "
            "Switch to the CPU-only sd-cli build or use a smaller image size. "
            f"Details: {summary}"
        )
    return summary


def _looks_like_metal_out_of_memory(output: str) -> bool:
    lowered = output.lower()
    if "kiogpucommandbuffercallbackerroroutofmemory" in lowered:
        return True
    if "insufficient memory" in lowered and "metal" in lowered:
        return True
    return "ggml_metal_synchronize" in lowered and "command buffer" in lowered and "status 5" in lowered
