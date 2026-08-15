"""Optional local Whisper integration."""

from __future__ import annotations

import shutil
from pathlib import Path

from video_footage_agent.media import (
    extract_audio_proxy,
    require_executable,
    run_checked,
)


def transcribe_video(
    video: Path,
    output: Path,
    *,
    model: str = "small",
    language: str = "auto",
    whisper_command: str = "whisper",
    overwrite: bool = False,
    keep_audio: bool = True,
) -> Path:
    video = video.expanduser().resolve()
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = (
        shutil.which(whisper_command)
        if Path(whisper_command).name == whisper_command
        else whisper_command
    )
    if not executable or not Path(executable).exists():
        require_executable(whisper_command)  # Raises a consistent message.
    audio = output / f"{video.stem}_16khz_mono.wav"
    transcript = output / f"{audio.stem}.json"
    if transcript.exists() and not overwrite:
        raise FileExistsError(transcript)
    extract_audio_proxy(video, audio, overwrite=overwrite)
    command = [
        str(executable),
        str(audio),
        "--model",
        model,
        "--task",
        "transcribe",
        "--output_dir",
        str(output),
        "--output_format",
        "json",
        "--verbose",
        "False",
        "--fp16",
        "False",
    ]
    if language.lower() != "auto":
        command.extend(["--language", language])
    run_checked(command)
    if not transcript.is_file():
        raise RuntimeError(
            f"Whisper completed but did not create the expected transcript: {transcript}"
        )
    if not keep_audio:
        audio.unlink(missing_ok=True)
    return transcript
