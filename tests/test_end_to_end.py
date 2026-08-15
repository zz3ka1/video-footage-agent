import shutil
import subprocess
from pathlib import Path

import pytest

from video_footage_agent.triage import TriageConfig, triage_video


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg unavailable",
)
def test_triage_generated_video(tmp_path: Path) -> None:
    video = tmp_path / "sample.mp4"
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=10",
            "-t",
            "2",
            "-c:v",
            "mpeg4",
            "-y",
            str(video),
        ],
        check=True,
    )
    output = tmp_path / "triage"
    result = triage_video(
        video,
        output,
        config=TriageConfig(
            sample_fps=1, proxy_width=320, window_seconds=1, contact_every_seconds=1
        ),
    )
    assert result["frames"] == 2
    assert (output / "technical_preflight.md").is_file()
    assert list((output / "contact_sheets").glob("*.png"))
