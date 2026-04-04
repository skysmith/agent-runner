from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class VoiceError(RuntimeError):
    pass


@dataclass(slots=True)
class VoiceRecordingSession:
    process: subprocess.Popen[str]
    audio_path: Path


def start_recording(*, audio_device_index: str | None = None) -> VoiceRecordingSession:
    wav_file = tempfile.NamedTemporaryFile(prefix="agent-runner-voice-", suffix=".wav", delete=False)
    wav_file.close()
    audio_path = Path(wav_file.name)
    device_index = audio_device_index or "1"
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "avfoundation",
        "-i",
        f":{device_index}",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(audio_path),
    ]
    try:
        process = subprocess.Popen(
            cmd,
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise VoiceError("ffmpeg is not installed.") from exc
    return VoiceRecordingSession(process=process, audio_path=audio_path)


def stop_recording(session: VoiceRecordingSession) -> None:
    session.process.terminate()
    try:
        session.process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        session.process.kill()
        session.process.wait(timeout=5)


def transcribe_audio(audio_path: Path, *, model: str = "tiny") -> str:
    out_dir = audio_path.parent
    cmd = [
        "whisper",
        str(audio_path),
        "--model",
        model,
        "--language",
        "en",
        "--task",
        "transcribe",
        "--output_format",
        "txt",
        "--output_dir",
        str(out_dir),
    ]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise VoiceError("whisper CLI is not installed.") from exc
    if proc.returncode != 0:
        raise VoiceError(proc.stderr.strip() or "Transcription failed.")
    transcript_path = out_dir / f"{audio_path.stem}.txt"
    if not transcript_path.exists():
        raise VoiceError("Transcription did not create a text file.")
    return transcript_path.read_text(encoding="utf-8").strip()
