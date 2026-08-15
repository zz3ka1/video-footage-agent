"""Discover video files and build a reproducible media inventory."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from video_footage_agent.media import probe_media, video_stream


DEFAULT_EXTENSIONS = (".mp4", ".mov", ".mkv", ".avi", ".m4v")


@dataclass(frozen=True)
class InventoryItem:
    part: int | None
    filename: str
    duration_seconds: float
    size_bytes: int
    codec: str
    width: int | None
    height: int | None
    frame_rate: str
    copies: int
    path: str
    duplicate_paths: str = ""


def extract_part_number(filename: str, part_regex: str | None) -> int | None:
    if not part_regex:
        return None
    match = re.search(part_regex, filename, flags=re.IGNORECASE)
    if not match:
        return None
    raw = match.group(1) if match.groups() else match.group(0)
    return int(raw)


def discover_paths(
    source: Path, extensions: Iterable[str] = DEFAULT_EXTENSIONS
) -> list[Path]:
    source = source.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    normalized = {
        extension.lower() if extension.startswith(".") else f".{extension.lower()}"
        for extension in extensions
    }
    candidates = [source] if source.is_file() else source.rglob("*")
    return sorted(
        path
        for path in candidates
        if path.is_file() and path.suffix.lower() in normalized
    )


def choose_canonical(paths: list[Path]) -> Path:
    """Choose one deterministic path when duplicate part numbers are present."""

    if not paths:
        raise ValueError("Cannot choose from an empty path list")
    return sorted(paths, key=lambda path: (len(str(path)), str(path).casefold()))[0]


def build_inventory(
    source: Path,
    *,
    extensions: Iterable[str] = DEFAULT_EXTENSIONS,
    part_regex: str | None = r"part(\d+)",
    probe: Callable[[Path], dict] = probe_media,
) -> list[InventoryItem]:
    paths = discover_paths(source, extensions)
    grouped: dict[tuple[str, int | str], list[Path]] = {}
    for path in paths:
        part = extract_part_number(path.name, part_regex)
        key = ("part", part) if part is not None else ("path", str(path))
        grouped.setdefault(key, []).append(path)

    items: list[InventoryItem] = []
    for group in grouped.values():
        canonical = choose_canonical(group)
        metadata = probe(canonical)
        stream = video_stream(metadata)
        part = extract_part_number(canonical.name, part_regex)
        duplicates = [str(path) for path in sorted(group) if path != canonical]
        items.append(
            InventoryItem(
                part=part,
                filename=canonical.name,
                duration_seconds=float(metadata["format"]["duration"]),
                size_bytes=int(metadata["format"]["size"]),
                codec=str(stream.get("codec_name", "unknown")),
                width=int(stream["width"]) if stream.get("width") is not None else None,
                height=(
                    int(stream["height"]) if stream.get("height") is not None else None
                ),
                frame_rate=str(stream.get("r_frame_rate", "unknown")),
                copies=len(group),
                path=str(canonical.resolve()),
                duplicate_paths=" | ".join(duplicates),
            )
        )
    return sorted(
        items,
        key=lambda item: (item.part is None, item.part or 0, item.filename.casefold()),
    )


def write_inventory_csv(path: Path, items: list[InventoryItem]) -> Path:
    if not items:
        raise ValueError("No media files were discovered")
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(item) for item in items]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_inventory_json(path: Path, items: list[InventoryItem]) -> Path:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "items": [asdict(item) for item in items],
        "summary": {
            "unique_files": len(items),
            "total_duration_seconds": sum(item.duration_seconds for item in items),
            "total_size_bytes": sum(item.size_bytes for item in items),
            "duplicate_parts": [
                item.part for item in items if item.part is not None and item.copies > 1
            ],
        },
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def read_inventory_csv(path: Path) -> list[InventoryItem]:
    path = path.expanduser().resolve()
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [
        InventoryItem(
            part=(
                int(row["part"]) if row.get("part") not in (None, "", "None") else None
            ),
            filename=row["filename"],
            duration_seconds=float(row["duration_seconds"]),
            size_bytes=int(row["size_bytes"]),
            codec=row.get("codec", "unknown"),
            width=(
                int(row["width"])
                if row.get("width") not in (None, "", "None")
                else None
            ),
            height=(
                int(row["height"])
                if row.get("height") not in (None, "", "None")
                else None
            ),
            frame_rate=row.get("frame_rate", "unknown"),
            copies=int(row.get("copies", 1)),
            path=row["path"],
            duplicate_paths=row.get("duplicate_paths", ""),
        )
        for row in rows
    ]
