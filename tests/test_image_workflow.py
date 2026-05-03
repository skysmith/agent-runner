from __future__ import annotations

import sys
import textwrap
import threading
import time
from pathlib import Path

from agent_runner.image_workflow import (
    ImageWorkflowStore,
    LtxProcessImageToVideoProvider,
    LtxVideoRuntimeConfig,
    MockImageTo3DProvider,
    MockImageToVideoProvider,
    RemoteLtxVideoConfig,
    RemoteLtxVideoProvider,
    TrellisProcessImageTo3DProvider,
    TrellisRuntimeConfig,
    UnavailableImageToVideoProvider,
    UnavailableImageTo3DProvider,
    ZImageLocalRuntimeConfig,
    ZImageLocalWorkflowProvider,
    describe_reference_image,
    discover_zimage_local_runtime_config,
    _summarize_process_error,
    default_image_to_3d_provider,
    default_image_to_video_provider,
    pick_first_available_model,
)
from agent_runner.ltx_video_worker_server import WorkerServerConfig, create_server as create_ltx_worker_server


def test_default_image_to_3d_provider_stays_mock_without_trellis_config(monkeypatch) -> None:
    monkeypatch.delenv("ALCOVE_IMAGE_TO_3D_PROVIDER", raising=False)
    monkeypatch.delenv("ALCOVE_TRELLIS_PYTHON", raising=False)
    monkeypatch.delenv("ALCOVE_TRELLIS_REPO", raising=False)
    monkeypatch.delenv("ALCOVE_TRELLIS_WORKER_SCRIPT", raising=False)

    provider = default_image_to_3d_provider()

    assert isinstance(provider, MockImageTo3DProvider)


def test_default_image_to_3d_provider_reports_unavailable_when_trellis_requested(monkeypatch) -> None:
    monkeypatch.setenv("ALCOVE_IMAGE_TO_3D_PROVIDER", "trellis")
    monkeypatch.delenv("ALCOVE_TRELLIS_PYTHON", raising=False)
    monkeypatch.delenv("ALCOVE_TRELLIS_REPO", raising=False)
    monkeypatch.delenv("ALCOVE_TRELLIS_WORKER_SCRIPT", raising=False)

    provider = default_image_to_3d_provider()

    assert isinstance(provider, UnavailableImageTo3DProvider)
    try:
        provider.create_job(image_path=Path("/tmp/input.png"), output_dir=Path("/tmp/out"))
    except RuntimeError as exc:
        assert "Trellis 3D worker unavailable" in str(exc)
    else:
        raise AssertionError("Expected unavailable Trellis provider to raise")


def test_default_image_to_video_provider_stays_mock_without_ltx_config(monkeypatch) -> None:
    monkeypatch.delenv("ALCOVE_IMAGE_TO_VIDEO_PROVIDER", raising=False)
    monkeypatch.delenv("ALCOVE_LTX_PYTHON", raising=False)
    monkeypatch.delenv("ALCOVE_LTX_REPO", raising=False)
    monkeypatch.delenv("ALCOVE_LTX_PIPELINE_CONFIG", raising=False)
    monkeypatch.setattr("agent_runner.image_workflow._candidate_ltx_repo_paths", lambda: [])

    provider = default_image_to_video_provider()

    assert isinstance(provider, MockImageToVideoProvider)


def test_default_image_to_video_provider_reports_unavailable_when_ltx_requested(monkeypatch) -> None:
    monkeypatch.setenv("ALCOVE_IMAGE_TO_VIDEO_PROVIDER", "ltx")
    monkeypatch.delenv("ALCOVE_LTX_PYTHON", raising=False)
    monkeypatch.delenv("ALCOVE_LTX_REPO", raising=False)
    monkeypatch.delenv("ALCOVE_LTX_PIPELINE_CONFIG", raising=False)
    monkeypatch.setattr("agent_runner.image_workflow._candidate_ltx_repo_paths", lambda: [])

    provider = default_image_to_video_provider()

    assert isinstance(provider, UnavailableImageToVideoProvider)
    try:
        provider.create_job(image_path=Path("/tmp/input.png"), output_dir=Path("/tmp/out"))
    except RuntimeError as exc:
        assert "LTX video worker unavailable" in str(exc)
    else:
        raise AssertionError("Expected unavailable LTX provider to raise")


def test_pick_first_available_model_prefers_requested_size_with_quantized_suffix() -> None:
    selected = pick_first_available_model(("qwen3.5:9b",), {"qwen3.5:9b-q4_K_M", "qwen3.5:4b"})

    assert selected == "qwen3.5:9b-q4_K_M"


def test_pick_first_available_model_does_not_fall_back_to_wrong_qwen35_size() -> None:
    selected = pick_first_available_model(("qwen3.5:9b",), {"qwen3.5:4b"})

    assert selected is None


def test_describe_reference_image_prefers_configured_ollama_models(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "reference.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    seen_models: list[str] = []
    monkeypatch.setattr(
        "agent_runner.image_workflow.list_local_ollama_models",
        lambda: {"qwen3.5:9b", "llava:latest", "llama3.2:3b"},
    )

    def fake_generate(*, model, image_paths, **kwargs):
        seen_models.append(model)
        if image_paths:
            return '{"subject":"woman","scene":"studio","composition":"portrait","palette":"warm","lighting":"soft","style":"realistic","mood":"calm","important_details":["robe"],"recreation_prompt":"warm studio portrait"}'
        return '{"generation_prompt":"warm studio portrait, clean background","notes":"ok"}'

    monkeypatch.setattr("agent_runner.image_workflow.ollama_generate", fake_generate)

    result = describe_reference_image(
        image_path=image_path,
        ollama_host="http://127.0.0.1:11434",
        preferred_vision_model="llava:latest",
        preferred_prompt_model="llama3.2:3b",
    )

    assert result["vision_model"] == "llava:latest"
    assert result["prompt_model"] == "llama3.2:3b"
    assert seen_models == ["llava:latest", "llama3.2:3b"]


def test_zimage_build_command_keeps_conditioner_on_cpu_when_configured(tmp_path: Path) -> None:
    provider = ZImageLocalWorkflowProvider(
        ZImageLocalRuntimeConfig(
            binary_path=tmp_path / "sd-cli",
            diffusion_model=tmp_path / "model.gguf",
            text_encoder=tmp_path / "encoder.gguf",
            vae=tmp_path / "vae.safetensors",
            keep_clip_on_cpu=True,
        )
    )

    cmd = provider._build_command(
        prompt="astronaut figurine",
        seed=42,
        output_path=tmp_path / "output.png",
        runtime_config=provider.runtime_config,
    )

    assert "--clip-on-cpu" in cmd


def test_zimage_build_command_can_leave_conditioner_on_accelerator(tmp_path: Path) -> None:
    provider = ZImageLocalWorkflowProvider(
        ZImageLocalRuntimeConfig(
            binary_path=tmp_path / "sd-cli",
            diffusion_model=tmp_path / "model.gguf",
            text_encoder=tmp_path / "encoder.gguf",
            vae=tmp_path / "vae.safetensors",
            keep_clip_on_cpu=False,
        )
    )

    cmd = provider._build_command(
        prompt="astronaut figurine",
        seed=42,
        output_path=tmp_path / "output.png",
        runtime_config=provider.runtime_config,
    )

    assert "--clip-on-cpu" not in cmd


def test_zimage_generate_uses_configured_timeout(monkeypatch, tmp_path: Path) -> None:
    provider = ZImageLocalWorkflowProvider(
        ZImageLocalRuntimeConfig(
            binary_path=tmp_path / "sd-cli",
            diffusion_model=tmp_path / "model.gguf",
            text_encoder=tmp_path / "encoder.gguf",
            vae=tmp_path / "vae.safetensors",
            timeout_seconds=1234,
        )
    )
    seen: dict[str, object] = {}

    def fake_run(cmd, *, cwd, capture_output, text, check, timeout):
        seen["timeout"] = timeout
        Path(cwd, "candidate-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr("agent_runner.image_workflow.subprocess.run", fake_run)

    candidates = provider.generate_images(prompt="astronaut figurine", count=1, passes=2)

    assert seen["timeout"] == 1234
    assert candidates[0].metadata["steps"] == 2
    assert isinstance(candidates[0].metadata["generation_duration_ms"], int)


def test_zimage_generate_has_no_timeout_by_default(monkeypatch, tmp_path: Path) -> None:
    provider = ZImageLocalWorkflowProvider(
        ZImageLocalRuntimeConfig(
            binary_path=tmp_path / "sd-cli",
            diffusion_model=tmp_path / "model.gguf",
            text_encoder=tmp_path / "encoder.gguf",
            vae=tmp_path / "vae.safetensors",
        )
    )
    seen: dict[str, object] = {}

    def fake_run(cmd, *, cwd, capture_output, text, check, timeout):
        seen["timeout"] = timeout
        Path(cwd, "candidate-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr("agent_runner.image_workflow.subprocess.run", fake_run)

    provider.generate_images(prompt="astronaut figurine", count=1, passes=12)

    assert seen["timeout"] is None


def test_zimage_runtime_config_reads_timeout_from_env(monkeypatch, tmp_path: Path) -> None:
    binary = tmp_path / "sd-cli"
    diffusion = tmp_path / "model.gguf"
    encoder = tmp_path / "encoder.gguf"
    vae = tmp_path / "vae.safetensors"
    for path in (binary, diffusion, encoder, vae):
        path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("ALCOVE_ZIMAGE_BINARY", str(binary))
    monkeypatch.setenv("ALCOVE_ZIMAGE_DIFFUSION_MODEL", str(diffusion))
    monkeypatch.setenv("ALCOVE_ZIMAGE_TEXT_ENCODER", str(encoder))
    monkeypatch.setenv("ALCOVE_ZIMAGE_VAE", str(vae))
    monkeypatch.setenv("ALCOVE_ZIMAGE_TIMEOUT_SECONDS", "2400")

    config = discover_zimage_local_runtime_config()

    assert config is not None
    assert config.timeout_seconds == 2400


def test_summarize_process_error_calls_out_metal_oom() -> None:
    summary = _summarize_process_error(
        "[INFO ] ggml_extend.hpp:1921 - qwen3 offload params (3555.38 MB, 398 tensors) to runtime backend (Metal), taking 39.65s\n"
        "[ERROR] ggml-metal.m:1234 - ggml_metal_synchronize: error: command buffer 0 failed with status 5\n"
        "[ERROR] ggml-metal.m:1235 - error: Insufficient Memory (00000008:kIOGPUCommandBufferCallbackErrorOutOfMemory)\n",
        "",
    )

    assert "Metal GPU ran out of memory" in summary
    assert "CPU-only sd-cli build" in summary


def test_summarize_process_error_preserves_recent_lines_for_generic_failures() -> None:
    summary = _summarize_process_error(
        "line1\nline2\nline3\nline4\nline5\n",
        "line6\n",
    )

    assert summary == "line3 | line4 | line5 | line6"


def test_summarize_process_error_accepts_timeout_bytes() -> None:
    summary = _summarize_process_error(
        b"line1\nline2\nline3\nline4\nline5\n",
        b"line6\n",
    )

    assert summary == "line3 | line4 | line5 | line6"


def test_default_image_to_video_provider_prefers_remote_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("ALCOVE_LTX_REMOTE_URL", "http://ck-server:8421")
    monkeypatch.delenv("ALCOVE_IMAGE_TO_VIDEO_PROVIDER", raising=False)
    monkeypatch.delenv("ALCOVE_LTX_PYTHON", raising=False)
    monkeypatch.delenv("ALCOVE_LTX_REPO", raising=False)
    monkeypatch.delenv("ALCOVE_LTX_PIPELINE_CONFIG", raising=False)

    provider = default_image_to_video_provider()

    assert isinstance(provider, RemoteLtxVideoProvider)


def test_default_image_to_video_provider_stays_mock_when_repo_exists_without_weights(monkeypatch, tmp_path: Path) -> None:
    repo_path = tmp_path / "LTX-Video"
    python_path = repo_path / "env" / "bin" / "python"
    hf_home = tmp_path / "models" / "huggingface"
    repo_path.mkdir(parents=True)
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    python_path.chmod(0o755)
    hf_home.mkdir(parents=True)
    monkeypatch.delenv("ALCOVE_IMAGE_TO_VIDEO_PROVIDER", raising=False)
    monkeypatch.delenv("ALCOVE_LTX_PYTHON", raising=False)
    monkeypatch.delenv("ALCOVE_LTX_REPO", raising=False)
    monkeypatch.delenv("ALCOVE_LTX_PIPELINE_CONFIG", raising=False)
    monkeypatch.setattr("agent_runner.image_workflow._candidate_ltx_repo_paths", lambda: [repo_path])

    provider = default_image_to_video_provider()

    assert isinstance(provider, MockImageToVideoProvider)


def test_image_workflow_store_symlinks_assets_into_export_root(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    export_root = tmp_path / "nextcloud" / "Alcove" / "Image Studio"
    store = ImageWorkflowStore(workspace_dir, asset_export_root=export_root)

    asset = store.add_uploaded_asset(
        file_name="reference.png",
        mime_type="image/png",
        data=b"\x89PNG\r\n\x1a\n",
        prompt_context="snowy camp",
    )

    assets_link = workspace_dir / "image-workflow" / "assets"
    assert assets_link.is_symlink()
    assert asset.relative_path.startswith("image-workflow/assets/")
    assert store.asset_path(asset).exists()
    assert store.asset_path(asset).parent.resolve() == export_root.resolve()
    assert store.asset_path(asset).resolve().is_relative_to(export_root.resolve())
    assert store.asset_path(asset).name == f"{asset.id}__source.png"


def test_image_workflow_store_migrates_existing_assets_into_export_root(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    local_store = ImageWorkflowStore(workspace_dir)
    asset = local_store.add_uploaded_asset(
        file_name="reference.png",
        mime_type="image/png",
        data=b"\x89PNG\r\n\x1a\n",
    )

    export_root = tmp_path / "nextcloud" / "Alcove" / "Image Studio"
    migrated_store = ImageWorkflowStore(workspace_dir, asset_export_root=export_root)

    assets_link = workspace_dir / "image-workflow" / "assets"
    assert assets_link.is_symlink()
    assert migrated_store.asset_path(asset).exists()
    assert migrated_store.asset_path(asset).parent.resolve() == export_root.resolve()
    assert migrated_store.asset_path(asset).resolve().is_relative_to(export_root.resolve())


def test_image_workflow_store_serves_symlinked_asset_files_from_export_root(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    export_root = tmp_path / "nextcloud" / "Alcove" / "Image Studio"
    store = ImageWorkflowStore(workspace_dir, asset_export_root=export_root)

    asset = store.add_uploaded_asset(
        file_name="reference.png",
        mime_type="image/png",
        data=b"\x89PNG\r\n\x1a\n",
    )

    served = store.workflow_file(asset.relative_path)

    assert served.exists()
    assert served.is_file()
    assert str(served).startswith(str(workspace_dir))
    assert served.resolve().is_relative_to(export_root.resolve())


def test_image_workflow_store_migrates_symlink_target_to_new_export_root(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    old_export_root = tmp_path / "nextcloud-old" / "Alcove" / "Image Studio"
    old_target = old_export_root / workspace_dir.name / "assets"
    old_target.mkdir(parents=True, exist_ok=True)
    (old_target / "img_existing").mkdir(parents=True, exist_ok=True)
    (old_target / "img_existing" / "candidate-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    local_assets_dir = workspace_dir / "image-workflow" / "assets"
    local_assets_dir.parent.mkdir(parents=True, exist_ok=True)
    local_assets_dir.symlink_to(old_target, target_is_directory=True)

    new_export_root = tmp_path / "nextcloud-new" / "Alcove" / "Generations"
    store = ImageWorkflowStore(workspace_dir, asset_export_root=new_export_root)

    assert store.assets_dir.is_symlink()
    assert store.assets_dir.resolve() == new_export_root.resolve()
    migrated = new_export_root / "img_existing__candidate-1.png"
    assert migrated.exists()
    assert not (new_export_root / "img_existing").exists()


def test_image_workflow_store_updates_manifest_to_flat_asset_files(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    assets_dir = workspace_dir / "image-workflow" / "assets"
    nested_dir = assets_dir / "img_existing"
    nested_dir.mkdir(parents=True, exist_ok=True)
    source_file = nested_dir / "candidate-1.png"
    source_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    manifest_path = workspace_dir / "image-workflow" / "manifest.json"
    manifest_path.write_text(
        textwrap.dedent(
            """\
            {
              "selected_image_id": "img_existing",
              "assets": [
                {
                  "id": "img_existing",
                  "created_at": "2026-04-17T00:00:00+00:00",
                  "updated_at": "2026-04-17T00:00:00+00:00",
                  "label": "Candidate 1",
                  "source": "generated",
                  "mime_type": "image/png",
                  "file_name": "candidate-1.png",
                  "relative_path": "image-workflow/assets/img_existing/candidate-1.png",
                  "prompt": "Painted explorer",
                  "prompt_context": null,
                  "metadata": {}
                }
              ],
              "jobs": []
            }
            """
        ),
        encoding="utf-8",
    )

    store = ImageWorkflowStore(workspace_dir)
    asset = store.get_asset("img_existing")

    assert asset.file_name == "img_existing__candidate-1.png"
    assert asset.relative_path == "image-workflow/assets/img_existing__candidate-1.png"
    assert store.asset_path(asset).exists()
    assert store.asset_path(asset).parent == assets_dir
    assert not nested_dir.exists()


def test_image_workflow_store_delete_asset_removes_related_jobs_and_files(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    store = ImageWorkflowStore(workspace_dir)
    asset = store.add_uploaded_asset(
        file_name="reference.png",
        mime_type="image/png",
        data=b"\x89PNG\r\n\x1a\n",
    )
    job = store.create_image_to_3d_job(source_image_id=asset.id, provider="mock")
    job_output_dir = workspace_dir / job.output_dir
    job_output_dir.mkdir(parents=True, exist_ok=True)
    (job_output_dir / "preview.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    deleted = store.delete_asset(asset.id)

    assert deleted["deleted_image_id"] == asset.id
    assert deleted["deleted_job_count"] == 1
    assert deleted["deleted_job_ids"] == [job.id]
    assert not store.asset_path(asset).exists()
    assert not job_output_dir.exists()
    snapshot = store.snapshot()
    assert snapshot["selected_image_id"] is None
    assert snapshot["assets"] == []
    assert snapshot["jobs"] == []


def test_image_workflow_store_prunes_assets_deleted_from_export_folder(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    store = ImageWorkflowStore(workspace_dir)
    asset = store.add_uploaded_asset(
        file_name="reference.png",
        mime_type="image/png",
        data=b"\x89PNG\r\n\x1a\n",
    )
    job = store.create_image_to_3d_job(source_image_id=asset.id, provider="mock")
    job_output_dir = workspace_dir / job.output_dir
    job_output_dir.mkdir(parents=True, exist_ok=True)
    (job_output_dir / "preview.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    store.asset_path(asset).unlink()

    assets = store.list_assets()
    jobs = store.list_jobs()

    assert assets == []
    assert jobs == []
    assert store.selected_image_id() is None
    assert not job_output_dir.exists()


def test_trellis_process_provider_polls_worker_status(tmp_path: Path) -> None:
    worker_script = tmp_path / "fake_trellis_worker.py"
    worker_script.write_text(
        textwrap.dedent(
            """\
            import argparse
            import json
            import time
            from pathlib import Path

            parser = argparse.ArgumentParser()
            parser.add_argument("--input", required=True)
            parser.add_argument("--output-dir", required=True)
            parser.add_argument("--status-path", required=True)
            parser.add_argument("--model", required=True)
            parser.add_argument("--device", required=True)
            parser.add_argument("--texture-size", required=True)
            parser.add_argument("--simplify", required=True)
            parser.add_argument("--spconv-algo", required=True)
            parser.add_argument("--trellis-repo", default="")
            parser.add_argument("--attn-backend", default="")
            parser.add_argument("--prompt-context", default="")
            args = parser.parse_args()

            output_dir = Path(args.output_dir)
            status_path = Path(args.status_path)
            output_dir.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps({"status": "running"}), encoding="utf-8")
            time.sleep(0.12)
            input_png = output_dir / "input.png"
            preview_png = output_dir / "preview.png"
            model_glb = output_dir / "model.glb"
            metadata_json = output_dir / "metadata.json"
            input_png.write_bytes(Path(args.input).read_bytes())
            preview_png.write_bytes(b"PNG")
            model_glb.write_bytes(b"glTF")
            metadata_json.write_text(json.dumps({"generator": "trellis", "model": args.model}), encoding="utf-8")
            status_path.write_text(
                json.dumps(
                    {
                        "status": "succeeded",
                        "artifacts": {
                            "input_png": str(input_png),
                            "preview_png": str(preview_png),
                            "glb": str(model_glb),
                            "metadata_json": str(metadata_json),
                        },
                        "metadata": {"generator": "trellis", "model": args.model},
                    }
                ),
                encoding="utf-8",
            )
            """
        ),
        encoding="utf-8",
    )
    input_path = tmp_path / "source.png"
    input_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    provider = TrellisProcessImageTo3DProvider(
        TrellisRuntimeConfig(
            python_path=Path(sys.executable),
            repo_path=None,
            model="microsoft/TRELLIS-image-large",
            device="cpu",
            worker_script_path=worker_script,
            timeout_seconds=120,
        )
    )

    output_dir = tmp_path / "job-output"
    job_id = provider.create_job(image_path=input_path, output_dir=output_dir, prompt_context="figurine")

    statuses: list[str] = []
    deadline = time.time() + 5
    final = None
    while time.time() < deadline:
        update = provider.get_job_status(job_id)
        statuses.append(update.status)
        if update.status == "succeeded":
            final = update
            break
        time.sleep(0.05)

    assert final is not None
    assert "running" in statuses or "queued" in statuses
    assert final.artifacts["glb"].name == "model.glb"
    assert final.metadata["model"] == "microsoft/TRELLIS-image-large"


def test_ltx_process_provider_polls_worker_status(tmp_path: Path) -> None:
    worker_script = tmp_path / "fake_ltx_worker.py"
    worker_script.write_text(
        textwrap.dedent(
            """\
            import argparse
            import json
            import time
            from pathlib import Path

            parser = argparse.ArgumentParser()
            parser.add_argument("--input", required=True)
            parser.add_argument("--output-dir", required=True)
            parser.add_argument("--status-path", required=True)
            parser.add_argument("--ltx-repo", default="")
            parser.add_argument("--pipeline-config", required=True)
            parser.add_argument("--device", required=True)
            parser.add_argument("--height", required=True)
            parser.add_argument("--width", required=True)
            parser.add_argument("--num-frames", required=True)
            parser.add_argument("--frame-rate", required=True)
            parser.add_argument("--seed", required=True)
            parser.add_argument("--hf-home", default="")
            parser.add_argument("--prompt-context", default="")
            parser.add_argument("--offload-to-cpu", action="store_true")
            args = parser.parse_args()

            output_dir = Path(args.output_dir)
            status_path = Path(args.status_path)
            output_dir.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps({"status": "running"}), encoding="utf-8")
            time.sleep(0.12)
            input_png = output_dir / "input.png"
            poster_png = output_dir / "poster.png"
            clip_mp4 = output_dir / "clip.mp4"
            metadata_json = output_dir / "metadata.json"
            input_png.write_bytes(Path(args.input).read_bytes())
            poster_png.write_bytes(b"PNG")
            clip_mp4.write_bytes(b"MP4")
            metadata_json.write_text(json.dumps({"generator": "ltx-video", "device": args.device}), encoding="utf-8")
            status_path.write_text(
                json.dumps(
                    {
                        "status": "succeeded",
                        "artifacts": {
                            "input_png": str(input_png),
                            "poster_png": str(poster_png),
                            "mp4": str(clip_mp4),
                            "metadata_json": str(metadata_json),
                        },
                        "metadata": {"generator": "ltx-video", "device": args.device},
                    }
                ),
                encoding="utf-8",
            )
            """
        ),
        encoding="utf-8",
    )
    pipeline_config = tmp_path / "ltx-config.yaml"
    pipeline_config.write_text("pipeline_type: base\ncheckpoint_path: foo.safetensors\n", encoding="utf-8")
    input_path = tmp_path / "source.png"
    input_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    provider = LtxProcessImageToVideoProvider(
        LtxVideoRuntimeConfig(
            python_path=Path(sys.executable),
            repo_path=None,
            pipeline_config_path=pipeline_config,
            device="cpu",
            worker_script_path=worker_script,
            timeout_seconds=120,
        )
    )

    output_dir = tmp_path / "job-output"
    job_id = provider.create_job(image_path=input_path, output_dir=output_dir, prompt_context="gentle motion")

    statuses: list[str] = []
    deadline = time.time() + 5
    final = None
    while time.time() < deadline:
        update = provider.get_job_status(job_id)
        statuses.append(update.status)
        if update.status == "succeeded":
            final = update
            break
        time.sleep(0.05)

    assert final is not None
    assert "running" in statuses or "queued" in statuses
    assert final.artifacts["mp4"].name == "clip.mp4"
    assert final.metadata["device"] == "cpu"


def test_remote_ltx_provider_downloads_artifacts_from_worker_server(tmp_path: Path) -> None:
    worker_script = tmp_path / "fake_ltx_worker.py"
    worker_script.write_text(
        textwrap.dedent(
            """\
            import argparse
            import json
            import time
            from pathlib import Path

            parser = argparse.ArgumentParser()
            parser.add_argument("--input", required=True)
            parser.add_argument("--output-dir", required=True)
            parser.add_argument("--status-path", required=True)
            parser.add_argument("--ltx-repo", default="")
            parser.add_argument("--pipeline-config", required=True)
            parser.add_argument("--device", required=True)
            parser.add_argument("--height", required=True)
            parser.add_argument("--width", required=True)
            parser.add_argument("--num-frames", required=True)
            parser.add_argument("--frame-rate", required=True)
            parser.add_argument("--seed", required=True)
            parser.add_argument("--hf-home", default="")
            parser.add_argument("--prompt-context", default="")
            parser.add_argument("--offload-to-cpu", action="store_true")
            args = parser.parse_args()

            output_dir = Path(args.output_dir)
            status_path = Path(args.status_path)
            output_dir.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps({"status": "running"}), encoding="utf-8")
            time.sleep(0.12)
            input_png = output_dir / "input.png"
            poster_png = output_dir / "poster.png"
            clip_mp4 = output_dir / "clip.mp4"
            metadata_json = output_dir / "metadata.json"
            input_png.write_bytes(Path(args.input).read_bytes())
            poster_png.write_bytes(b"PNG")
            clip_mp4.write_bytes(b"MP4")
            metadata_json.write_text(
                json.dumps(
                    {
                        "generator": "ltx-video",
                        "device": args.device,
                        "prompt_context": args.prompt_context,
                    }
                ),
                encoding="utf-8",
            )
            status_path.write_text(
                json.dumps(
                    {
                        "status": "succeeded",
                        "artifacts": {
                            "input_png": str(input_png),
                            "poster_png": str(poster_png),
                            "mp4": str(clip_mp4),
                            "metadata_json": str(metadata_json),
                        },
                        "metadata": {
                            "generator": "ltx-video",
                            "device": args.device,
                            "prompt_context": args.prompt_context,
                        },
                    }
                ),
                encoding="utf-8",
            )
            """
        ),
        encoding="utf-8",
    )
    pipeline_config = tmp_path / "ltx-config.yaml"
    pipeline_config.write_text("pipeline_type: base\ncheckpoint_path: foo.safetensors\n", encoding="utf-8")
    jobs_root = tmp_path / "worker-jobs"
    server = create_ltx_worker_server(
        WorkerServerConfig(
            jobs_root=jobs_root,
            python_path=Path(sys.executable),
            worker_script_path=worker_script,
            pipeline_config_path=pipeline_config,
            device="cpu",
            timeout_seconds=120,
        ),
        host="127.0.0.1",
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = RemoteLtxVideoProvider(
            RemoteLtxVideoConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                request_timeout_seconds=5,
                download_timeout_seconds=5,
            )
        )
        input_path = tmp_path / "source.png"
        input_path.write_bytes(b"\x89PNG\r\n\x1a\n")
        output_dir = tmp_path / "downloaded-job"

        job_id = provider.create_job(image_path=input_path, output_dir=output_dir, prompt_context="soft motion")

        statuses: list[str] = []
        deadline = time.time() + 5
        final = None
        while time.time() < deadline:
            update = provider.get_job_status(job_id)
            statuses.append(update.status)
            if update.status == "succeeded":
                final = update
                break
            time.sleep(0.05)

        assert final is not None
        assert "running" in statuses or "queued" in statuses
        assert final.artifacts["mp4"].name == "clip.mp4"
        assert final.artifacts["mp4"].read_bytes() == b"MP4"
        assert (output_dir / "poster.png").exists()
        assert final.metadata["prompt_context"] == "soft motion"
    finally:
        server.shutdown()
        server.server_close()
