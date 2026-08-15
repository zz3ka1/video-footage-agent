"""Technical preflight for long handheld footage.

The output is deliberately conservative: it surfaces windows for review but
does not claim to understand their editorial value.
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from video_footage_agent.media import (
    format_time,
    probe_media,
    require_executable,
    run_checked,
    video_stream,
)


@dataclass(frozen=True)
class TriageConfig:
    sample_fps: float = 1.0
    proxy_width: int = 640
    window_seconds: int = 10
    contact_every_seconds: int = 5
    contact_columns: int = 5
    contact_rows: int = 5

    def validate(self) -> None:
        if self.sample_fps <= 0:
            raise ValueError("sample_fps must be positive")
        if self.proxy_width < 160:
            raise ValueError("proxy_width must be at least 160")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if self.contact_every_seconds <= 0:
            raise ValueError("contact_every_seconds must be positive")
        if self.contact_columns <= 0 or self.contact_rows <= 0:
            raise ValueError("contact sheet dimensions must be positive")


def _font(size: int) -> ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _frame_manifest(video: Path, config: TriageConfig) -> dict:
    stat = video.stat()
    return {
        "source": str(video.resolve()),
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "sample_fps": config.sample_fps,
        "proxy_width": config.proxy_width,
    }


def extract_proxy_frames(
    video: Path, frames_dir: Path, config: TriageConfig, *, fresh: bool = False
) -> list[Path]:
    """Extract low-resolution frames without touching the source video."""

    ffmpeg = require_executable("ffmpeg")
    video = video.expanduser().resolve()
    frames_dir = frames_dir.expanduser().resolve()
    manifest_path = frames_dir / "manifest.json"
    expected = _frame_manifest(video, config)

    if fresh and frames_dir.exists():
        shutil.rmtree(frames_dir)
    if frames_dir.exists() and manifest_path.exists():
        actual = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing = sorted(frames_dir.glob("frame_*.jpg"))
        if actual == expected and existing:
            return existing
        raise RuntimeError(
            f"Existing proxy cache does not match this source/configuration: {frames_dir}. Use --fresh."
        )
    if frames_dir.exists() and any(frames_dir.iterdir()):
        raise RuntimeError(
            f"Proxy directory is not empty and has no valid manifest: {frames_dir}. Use --fresh."
        )

    frames_dir.mkdir(parents=True, exist_ok=True)
    vf = f"fps={config.sample_fps:g},scale={config.proxy_width}:-2:flags=lanczos"
    try:
        run_checked(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "warning",
                "-i",
                str(video),
                "-map",
                "0:v:0",
                "-vf",
                vf,
                "-q:v",
                "4",
                str(frames_dir / "frame_%06d.jpg"),
            ]
        )
        paths = sorted(frames_dir.glob("frame_*.jpg"))
        if not paths:
            raise RuntimeError(f"FFmpeg extracted no frames from {video}")
        manifest_path.write_text(
            json.dumps(expected, indent=2) + "\n", encoding="utf-8"
        )
        return paths
    except Exception:
        shutil.rmtree(frames_dir, ignore_errors=True)
        raise


def measure_frames(paths: list[Path], *, sample_fps: float = 1.0) -> list[dict]:
    rows: list[dict] = []
    previous_gray: np.ndarray | None = None
    for index, path in enumerate(paths):
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        timestamp = index / sample_fps
        rows.append(
            {
                "frame_index": index,
                "second": round(timestamp, 3),
                "timecode": format_time(timestamp),
                "brightness": float(np.mean(gray)),
                "contrast": float(np.std(gray)),
                "sharpness": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
                "dark_ratio": float(np.mean(gray < 16)),
                "bright_ratio": float(np.mean(gray > 239)),
                "frame_change": (
                    0.0
                    if previous_gray is None
                    else float(cv2.absdiff(gray, previous_gray).mean())
                ),
                "frame": path.name,
            }
        )
        previous_gray = gray
    if not rows:
        raise RuntimeError("No proxy frames could be decoded")
    return rows


def group_windows(
    rows: list[dict], duration: float, *, window_seconds: int = 10
) -> list[dict]:
    """Aggregate frame metrics into conservative technical review windows."""

    if not rows:
        return []
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    sharp_p10 = float(np.percentile([row["sharpness"] for row in rows], 10))
    buckets: dict[int, list[dict]] = {}
    for row in rows:
        buckets.setdefault(int(float(row["second"]) // window_seconds), []).append(row)

    windows: list[dict] = []
    count = int(math.ceil(duration / window_seconds))
    for index in range(count):
        sample = buckets.get(index, [])
        if not sample:
            continue
        start = index * window_seconds
        end = min(duration, start + window_seconds)

        def median(key: str) -> float:
            return float(np.median([row[key] for row in sample]))

        low_sharp_ratio = float(
            np.mean([row["sharpness"] <= sharp_p10 for row in sample])
        )
        dark_problem_ratio = float(
            np.mean(
                [row["brightness"] < 35 or row["dark_ratio"] > 0.55 for row in sample]
            )
        )
        bright_problem_ratio = float(
            np.mean(
                [
                    row["brightness"] > 220 or row["bright_ratio"] > 0.55
                    for row in sample
                ]
            )
        )
        flags: list[str] = []
        if dark_problem_ratio >= 0.5:
            flags.append("very_dark")
        if bright_problem_ratio >= 0.5:
            flags.append("overexposed")
        if low_sharp_ratio >= 0.5:
            flags.append("soft_or_blurred")
        if median("frame_change") < 2.0:
            flags.append("nearly_static")
        if median("frame_change") > 42.0:
            flags.append("large_visual_change")

        if dark_problem_ratio >= 0.8 or bright_problem_ratio >= 0.8:
            status = "TECHNICAL_FAIL_CANDIDATE"
        elif flags:
            status = "REVIEW"
        else:
            status = "TECHNICALLY_USABLE"
        windows.append(
            {
                "window": index + 1,
                "start_second": start,
                "end_second": round(end, 3),
                "start": format_time(start),
                "end": format_time(end),
                "brightness_median": median("brightness"),
                "sharpness_median": median("sharpness"),
                "frame_change_median": median("frame_change"),
                "low_sharp_ratio": low_sharp_ratio,
                "technical_status": status,
                "flags": ",".join(flags),
            }
        )
    return windows


def build_contact_sheets(
    paths: list[Path], output_dir: Path, config: TriageConfig
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    step = max(1, int(round(config.contact_every_seconds * config.sample_fps)))
    samples = [(index, path) for index, path in enumerate(paths) if index % step == 0]
    thumb_w, thumb_h, label_h = 320, 180, 28
    per_sheet = config.contact_columns * config.contact_rows
    label_font = _font(20)
    outputs: list[Path] = []
    for sheet_index in range(math.ceil(len(samples) / per_sheet)):
        chunk = samples[sheet_index * per_sheet : (sheet_index + 1) * per_sheet]
        canvas = Image.new(
            "RGB",
            (
                config.contact_columns * thumb_w,
                config.contact_rows * (thumb_h + label_h),
            ),
            "white",
        )
        draw = ImageDraw.Draw(canvas)
        for cell, (frame_index, path) in enumerate(chunk):
            bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if bgr is None:
                image = Image.new("RGB", (thumb_w, thumb_h), "#4c0000")
            else:
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(rgb).resize(
                    (thumb_w, thumb_h), Image.Resampling.LANCZOS
                )
            x = (cell % config.contact_columns) * thumb_w
            y = (cell // config.contact_columns) * (thumb_h + label_h)
            canvas.paste(image, (x, y))
            draw.rectangle(
                (x, y + thumb_h, x + thumb_w, y + thumb_h + label_h), fill="black"
            )
            timestamp = frame_index / config.sample_fps
            draw.text(
                (x + 8, y + thumb_h + 3),
                format_time(timestamp),
                fill="white",
                font=label_font,
            )
        output = output_dir / f"contact_sheet_{sheet_index + 1:02d}.png"
        canvas.save(output)
        outputs.append(output)
    return outputs


def write_report(
    path: Path,
    *,
    video: Path,
    metadata: dict,
    windows: list[dict],
    sheets: list[Path],
    config: TriageConfig,
) -> None:
    duration = float(metadata["format"]["duration"])
    size = int(metadata["format"]["size"])
    stream = video_stream(metadata)
    counts = Counter(window["technical_status"] for window in windows)
    lines = [
        "# Handheld footage technical preflight",
        "",
        f"- Source: `{video}`",
        f"- Duration: {format_time(duration, include_hours=duration >= 3600)} ({duration:.3f} seconds)",
        f"- Size: {size / 1024**3:.2f} GiB",
        (
            f"- Video: {stream.get('codec_name')}, "
            f"{stream.get('width')}×{stream.get('height')}, {stream.get('r_frame_rate')} fps"
        ),
        f"- Sampling: {config.sample_fps:g} fps proxies, {config.window_seconds}-second windows",
        "",
        "## Summary",
        "",
    ]
    for status in ("TECHNICALLY_USABLE", "REVIEW", "TECHNICAL_FAIL_CANDIDATE"):
        lines.append(f"- {status}: {counts.get(status, 0)} windows")
    lines.extend(
        [
            "",
            "> These labels cover technical risk only. They do not decide KEEP / SALVAGE / LOW_VALUE editorial status.",
            "",
            "## Contact sheets",
            "",
            *[f"- `{sheet.name}`" for sheet in sheets],
            "",
            "## Windows",
            "",
            "| Time | Status | Flags | Brightness | Sharpness | Visual change |",
            "|---|---|---|---:|---:|---:|",
        ]
    )
    for window in windows:
        lines.append(
            f"| {window['start']}–{window['end']} | {window['technical_status']} | {window['flags'] or '—'} | "
            f"{window['brightness_median']:.1f} | {window['sharpness_median']:.1f} | "
            f"{window['frame_change_median']:.1f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def triage_video(
    video: Path,
    output: Path,
    *,
    config: TriageConfig | None = None,
    fresh: bool = False,
) -> dict:
    config = config or TriageConfig()
    config.validate()
    video = video.expanduser().resolve()
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata = probe_media(video)
    (output / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    (output / "triage_config.json").write_text(
        json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8"
    )
    paths = extract_proxy_frames(video, output / "proxy_frames", config, fresh=fresh)
    rows = measure_frames(paths, sample_fps=config.sample_fps)
    windows = group_windows(
        rows,
        float(metadata["format"]["duration"]),
        window_seconds=config.window_seconds,
    )
    sheets = build_contact_sheets(paths, output / "contact_sheets", config)
    _write_csv(output / "frame_metrics.csv", rows)
    _write_csv(output / "window_metrics.csv", windows)
    write_report(
        output / "technical_preflight.md",
        video=video,
        metadata=metadata,
        windows=windows,
        sheets=sheets,
        config=config,
    )
    return {
        "source": str(video),
        "frames": len(paths),
        "windows": len(windows),
        "contact_sheets": [str(path) for path in sheets],
        "output": str(output),
    }
