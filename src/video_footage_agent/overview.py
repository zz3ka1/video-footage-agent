"""Build compact project-level contact sheets from an inventory."""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from video_footage_agent.inventory import InventoryItem, read_inventory_csv
from video_footage_agent.media import format_time, require_executable, run_checked


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _extract_still(
    source: Path, second: float, output: Path, *, width: int, height: int
) -> None:
    ffmpeg = require_executable("ffmpeg")
    vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    run_checked(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{second:.3f}",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-vf",
            vf,
            "-y",
            str(output),
        ]
    )


def _item_label(item: InventoryItem) -> str:
    return (
        f"part{item.part:02d}"
        if item.part is not None
        else Path(item.filename).stem[:28]
    )


def build_overview(
    inventory: Path,
    output: Path,
    *,
    sample_ratios: tuple[float, ...] = (0.15, 0.5, 0.85),
    items_per_sheet: int = 5,
    frame_width: int = 320,
    frame_height: int = 180,
) -> list[Path]:
    if not sample_ratios or any(ratio < 0 or ratio > 1 for ratio in sample_ratios):
        raise ValueError("sample_ratios must contain values between 0 and 1")
    if items_per_sheet <= 0 or frame_width <= 0 or frame_height <= 0:
        raise ValueError("sheet and frame dimensions must be positive")
    items = read_inventory_csv(inventory)
    if not items:
        raise ValueError("Inventory is empty")
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    label_height = 28
    label_font = _font(18)
    outputs: list[Path] = []

    with tempfile.TemporaryDirectory(prefix="footage-overview-") as temporary:
        temp = Path(temporary)
        for sheet_index in range(math.ceil(len(items) / items_per_sheet)):
            chunk = items[
                sheet_index * items_per_sheet : (sheet_index + 1) * items_per_sheet
            ]
            canvas = Image.new(
                "RGB",
                (
                    frame_width * len(sample_ratios),
                    (frame_height + label_height) * items_per_sheet,
                ),
                "white",
            )
            draw = ImageDraw.Draw(canvas)
            for row_index, item in enumerate(chunk):
                source = Path(item.path)
                for column, ratio in enumerate(sample_ratios):
                    second = min(
                        max(0.0, item.duration_seconds * ratio),
                        max(0.0, item.duration_seconds - 0.05),
                    )
                    still = (
                        temp
                        / f"sheet{sheet_index:02d}_row{row_index:02d}_col{column:02d}.png"
                    )
                    _extract_still(
                        source, second, still, width=frame_width, height=frame_height
                    )
                    with Image.open(still) as frame:
                        image = frame.convert("RGB")
                    x = column * frame_width
                    y = row_index * (frame_height + label_height)
                    canvas.paste(image, (x, y))
                    draw.rectangle(
                        (
                            x,
                            y + frame_height,
                            x + frame_width,
                            y + frame_height + label_height,
                        ),
                        fill="black",
                    )
                    draw.text(
                        (x + 8, y + frame_height + 3),
                        f"{_item_label(item)}  {format_time(second)}",
                        fill="white",
                        font=label_font,
                    )
            destination = output / f"overview_{sheet_index + 1:02d}.png"
            canvas.save(destination)
            outputs.append(destination)

    summary = {
        "inventory": str(inventory.expanduser().resolve()),
        "items": len(items),
        "sample_ratios": sample_ratios,
        "sheets": [path.name for path in outputs],
    }
    (output / "overview_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return outputs
