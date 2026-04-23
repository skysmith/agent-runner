from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import traceback
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a single TRELLIS image-to-3D job.")
    parser.add_argument("--input", required=True, help="Source image path")
    parser.add_argument("--output-dir", required=True, help="Output directory for artifacts")
    parser.add_argument("--status-path", required=True, help="Status JSON path written during the job")
    parser.add_argument("--trellis-repo", default="", help="Optional local TRELLIS repo path to prepend to sys.path")
    parser.add_argument("--model", default="microsoft/TRELLIS-image-large", help="Trellis model repo or local model path")
    parser.add_argument("--device", default="cuda", help="Device to place the pipeline on")
    parser.add_argument("--attn-backend", default="", help="Optional attention backend")
    parser.add_argument("--spconv-algo", default="native", help="SPCONV_ALGO environment value")
    parser.add_argument("--texture-size", type=int, default=1024, help="Texture size for GLB export")
    parser.add_argument("--simplify", type=float, default=0.95, help="Simplification ratio for GLB export")
    parser.add_argument("--prompt-context", default="", help="Optional prompt context to store in metadata")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    status_path = Path(args.status_path).expanduser().resolve()
    trellis_repo = Path(args.trellis_repo).expanduser().resolve() if str(args.trellis_repo).strip() else None

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_status(
        status_path,
        {
            "status": "running",
            "metadata": {
                "generator": "trellis",
                "model": args.model,
                "device": args.device,
            },
        },
    )
    started = time.perf_counter()

    try:
        if trellis_repo is not None:
            sys.path.insert(0, str(trellis_repo))
        if args.attn_backend:
            import os

            os.environ["ATTN_BACKEND"] = args.attn_backend
        if args.spconv_algo:
            import os

            os.environ["SPCONV_ALGO"] = args.spconv_algo

        import imageio.v2 as imageio
        from PIL import Image
        from trellis.pipelines import TrellisImageTo3DPipeline
        from trellis.utils import postprocessing_utils, render_utils

        pipeline = TrellisImageTo3DPipeline.from_pretrained(args.model)
        if args.device.lower() == "cuda":
            pipeline.cuda()
        elif hasattr(pipeline, "to"):
            pipeline.to(args.device)

        image = Image.open(input_path).convert("RGBA")
        outputs = pipeline.run(image)

        input_png_path = output_dir / "input.png"
        preview_png_path = output_dir / "preview.png"
        model_glb_path = output_dir / "model.glb"
        metadata_path = output_dir / "metadata.json"

        image.save(input_png_path)

        preview_frames = render_utils.render_video(outputs["mesh"][0])["normal"]
        if not preview_frames:
            raise RuntimeError("TRELLIS rendered no preview frames.")
        imageio.imwrite(preview_png_path, preview_frames[0])

        glb = postprocessing_utils.to_glb(
            outputs["gaussian"][0],
            outputs["mesh"][0],
            simplify=float(args.simplify),
            texture_size=max(int(args.texture_size), 128),
        )
        glb.export(model_glb_path)

        metadata = {
            "job_type": "image_to_3d",
            "generator": "trellis",
            "model": args.model,
            "device": args.device,
            "source_image_name": input_path.name,
            "prompt_context": args.prompt_context.strip() or None,
            "artifacts": ["input.png", "preview.png", "model.glb", "metadata.json"],
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        _write_status(
            status_path,
            {
                "status": "succeeded",
                "artifacts": {
                    "input_png": str(input_png_path),
                    "preview_png": str(preview_png_path),
                    "glb": str(model_glb_path),
                    "metadata_json": str(metadata_path),
                },
                "metadata": metadata,
            },
        )
        return 0
    except Exception as exc:
        log_path = output_dir / "trellis-error.log"
        trace = traceback.format_exc()
        log_path.write_text(trace, encoding="utf-8")
        _write_status(
            status_path,
            {
                "status": "failed",
                "error": str(exc).strip() or "Trellis generation failed.",
                "metadata": {
                    "generator": "trellis",
                    "model": args.model,
                    "device": args.device,
                    "error_log": str(log_path),
                },
            },
        )
        return 1


def _write_status(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    shutil.move(str(tmp_path), str(path))


if __name__ == "__main__":
    raise SystemExit(main())
