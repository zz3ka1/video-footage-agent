"""Small, testable wrappers around FFmpeg and FFprobe."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class DependencyError(RuntimeError):
    """Raised when a required external executable is unavailable."""


class MediaProbeError(RuntimeError):
    """Raised when FFprobe cannot inspect a media file."""


def require_executable(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise DependencyError(f"Required executable not found on PATH: {name}")
    return executable


def run_checked(
    command: list[str], *, capture_output: bool = False
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=capture_output,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else str(exc)
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{detail}") from exc


def probe_media(path: Path) -> dict[str, Any]:
    """Return FFprobe JSON for one local media file."""

    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    ffprobe = require_executable("ffprobe")
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        (
            "format=duration,size,bit_rate,format_name:"
            "stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels"
        ),
        "-of",
        "json",
        str(path),
    ]
    try:
        result = run_checked(command, capture_output=True)
        data = json.loads(result.stdout)
    except (RuntimeError, json.JSONDecodeError) as exc:
        raise MediaProbeError(f"Could not probe media file: {path}") from exc
    if "format" not in data or "duration" not in data["format"]:
        raise MediaProbeError(f"FFprobe returned no duration for: {path}")
    return data


def format_time(seconds: float, *, include_hours: bool | None = None) -> str:
    """Format seconds as MM:SS or HH:MM:SS."""

    value = max(0, int(round(seconds)))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    show_hours = hours > 0 if include_hours is None else include_hours
    if show_hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours * 60 + minutes:02d}:{secs:02d}"


def video_stream(metadata: dict[str, Any]) -> dict[str, Any]:
    try:
        return next(
            stream
            for stream in metadata.get("streams", [])
            if stream.get("codec_type") == "video"
        )
    except StopIteration as exc:
        raise MediaProbeError("Media contains no video stream") from exc


def extract_audio_proxy(
    video: Path,
    output: Path,
    *,
    sample_rate: int = 16_000,
    channels: int = 1,
    overwrite: bool = False,
) -> Path:
    """Extract a PCM WAV suitable for speech recognition."""

    ffmpeg = require_executable("ffmpeg")
    video = video.expanduser().resolve()
    output = output.expanduser().resolve()
    if output.exists() and not overwrite:
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg, "-hide_banner", "-loglevel", "warning"]
    command.append("-y" if overwrite else "-n")
    command.extend(
        [
            "-i",
            str(video),
            "-map",
            "0:a:0",
            "-ac",
            str(channels),
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(output),
        ]
    )
    run_checked(command)
    return output
