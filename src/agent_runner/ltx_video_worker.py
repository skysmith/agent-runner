from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a single LTX image-to-video job.")
    parser.add_argument("--input", required=True, help="Source image path")
    parser.add_argument("--output-dir", required=True, help="Output directory for artifacts")
    parser.add_argument("--status-path", required=True, help="Status JSON path written during the job")
    parser.add_argument("--ltx-repo", default="", help="Optional local LTX repo path to prepend to sys.path")
    parser.add_argument("--pipeline-config", required=True, help="Pipeline config YAML path")
    parser.add_argument("--device", default="mps", help="Device to place the pipeline on")
    parser.add_argument("--height", type=int, default=320, help="Output frame height")
    parser.add_argument("--width", type=int, default=512, help="Output frame width")
    parser.add_argument("--num-frames", type=int, default=17, help="Number of output frames")
    parser.add_argument("--frame-rate", type=int, default=12, help="Output frame rate")
    parser.add_argument("--seed", type=int, default=171198, help="Seed for generation")
    parser.add_argument("--hf-home", default="", help="Optional Hugging Face cache root")
    parser.add_argument("--prompt-context", default="", help="Optional prompt context to adapt into motion prompt")
    parser.add_argument("--offload-to-cpu", action="store_true", help="Allow the runtime to offload work to CPU")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    status_path = Path(args.status_path).expanduser().resolve()
    ltx_repo = Path(args.ltx_repo).expanduser().resolve() if str(args.ltx_repo).strip() else None
    pipeline_config_path = Path(args.pipeline_config).expanduser().resolve()

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_status(
        status_path,
        {
            "status": "running",
            "metadata": {
                "generator": "ltx-video",
                "device": args.device,
                "pipeline_config": pipeline_config_path.name,
            },
        },
    )
    started = time.perf_counter()

    try:
        if ltx_repo is not None:
            sys.path.insert(0, str(ltx_repo))
        if args.hf_home.strip():
            os.environ["HF_HOME"] = args.hf_home.strip()
        if args.device.lower() == "mps":
            os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

        import imageio.v2 as imageio
        from PIL import Image
        from ltx_video.inference import InferenceConfig, infer

        input_png_path = output_dir / "input.png"
        poster_png_path = output_dir / "poster.png"
        clip_path = output_dir / "clip.mp4"
        metadata_path = output_dir / "metadata.json"

        Image.open(input_path).convert("RGB").save(input_png_path)

        before_outputs = {path.resolve() for path in output_dir.glob("*.mp4")}
        prompt = _motion_prompt(args.prompt_context)
        infer(
            InferenceConfig(
                prompt=prompt,
                output_path=str(output_dir),
                pipeline_config=str(pipeline_config_path),
                seed=max(int(args.seed), 1),
                height=max(int(args.height), 128),
                width=max(int(args.width), 128),
                num_frames=max(int(args.num_frames), 9),
                frame_rate=max(int(args.frame_rate), 1),
                offload_to_cpu=bool(args.offload_to_cpu),
                conditioning_media_paths=[str(input_path)],
                conditioning_start_frames=[0],
            )
        )

        generated_mp4 = _find_generated_mp4(output_dir, before_outputs)
        if generated_mp4 is None:
            raise RuntimeError("LTX generation finished without producing an MP4 clip.")
        if generated_mp4.resolve() != clip_path.resolve():
            shutil.move(str(generated_mp4), str(clip_path))

        frame_count = 0
        reader = imageio.get_reader(clip_path)
        try:
            poster_frame = reader.get_data(0)
            try:
                frame_count = int(reader.count_frames())
            except Exception:
                frame_count = max(int(args.num_frames), 1)
        finally:
            reader.close()
        imageio.imwrite(poster_png_path, poster_frame)

        metadata = {
            "job_type": "image_to_video",
            "generator": "ltx-video",
            "device": args.device,
            "pipeline_config": pipeline_config_path.name,
            "source_image_name": input_path.name,
            "prompt_context": args.prompt_context.strip() or None,
            "final_prompt": prompt,
            "width": max(int(args.width), 128),
            "height": max(int(args.height), 128),
            "frame_count": frame_count,
            "fps": max(int(args.frame_rate), 1),
            "duration_seconds": round(frame_count / max(int(args.frame_rate), 1), 3),
            "artifacts": ["input.png", "poster.png", "clip.mp4", "metadata.json"],
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        _write_status(
            status_path,
            {
                "status": "succeeded",
                "artifacts": {
                    "input_png": str(input_png_path),
                    "poster_png": str(poster_png_path),
                    "mp4": str(clip_path),
                    "metadata_json": str(metadata_path),
                },
                "metadata": metadata,
            },
        )
        return 0
    except Exception as exc:
        log_path = output_dir / "ltx-video-error.log"
        trace = traceback.format_exc()
        log_path.write_text(trace, encoding="utf-8")
        _write_status(
            status_path,
            {
                "status": "failed",
                "error": str(exc).strip() or "LTX video generation failed.",
                "metadata": {
                    "generator": "ltx-video",
                    "device": args.device,
                    "pipeline_config": pipeline_config_path.name,
                    "error_log": str(log_path),
                },
            },
        )
        return 1


def _motion_prompt(prompt_context: str) -> str:
    base = (prompt_context or "").strip()
    if base:
        return (
            f"{base} Preserve the original composition and subject. "
            "Add subtle natural motion only, with stable framing, gentle environmental movement, coherent details, and no abrupt scene changes."
        )
    return (
        "Preserve the source image composition and subject while adding subtle natural motion, stable framing, "
        "gentle environmental movement, and no abrupt scene changes."
    )


def _find_generated_mp4(output_dir: Path, before_outputs: set[Path]) -> Path | None:
    candidates = [path.resolve() for path in output_dir.glob("*.mp4")]
    fresh = [path for path in candidates if path not in before_outputs]
    pool = fresh or candidates
    if not pool:
        return None
    return max(pool, key=lambda path: path.stat().st_mtime)


def _write_status(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    shutil.move(str(tmp_path), str(path))


if __name__ == "__main__":
    raise SystemExit(main())
