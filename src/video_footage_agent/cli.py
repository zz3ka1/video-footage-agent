"""Command-line interface for Video Footage Agent."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from video_footage_agent import __version__
from video_footage_agent.consolidate import execute_consolidation
from video_footage_agent.inventory import (
    DEFAULT_EXTENSIONS,
    build_inventory,
    write_inventory_csv,
    write_inventory_json,
)
from video_footage_agent.overview import build_overview
from video_footage_agent.transcribe import transcribe_video
from video_footage_agent.triage import TriageConfig, triage_video


def _extensions(value: str) -> tuple[str, ...]:
    extensions = tuple(part.strip() for part in value.split(",") if part.strip())
    if not extensions:
        raise argparse.ArgumentTypeError("At least one extension is required")
    return extensions


def _ratios(value: str) -> tuple[float, ...]:
    try:
        ratios = tuple(float(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Ratios must be comma-separated numbers"
        ) from exc
    if not ratios or any(ratio < 0 or ratio > 1 for ratio in ratios):
        raise argparse.ArgumentTypeError("Ratios must be between 0 and 1")
    return ratios


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="footage-agent",
        description="Inventory, preflight, transcribe, and organize long-form raw video footage.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check local runtime dependencies")
    doctor.set_defaults(handler=_handle_doctor)

    inventory = subparsers.add_parser(
        "inventory", help="Discover videos and write a media inventory"
    )
    inventory.add_argument("source", type=Path)
    inventory.add_argument("--output", type=Path, required=True, help="CSV output path")
    inventory.add_argument("--json", type=Path, help="Optional JSON output path")
    inventory.add_argument("--extensions", type=_extensions, default=DEFAULT_EXTENSIONS)
    inventory.add_argument("--part-regex", default=r"part(\d+)")
    inventory.set_defaults(handler=_handle_inventory)

    overview = subparsers.add_parser(
        "overview", help="Build three-frame-per-file project contact sheets"
    )
    overview.add_argument("inventory", type=Path)
    overview.add_argument("--output", type=Path, required=True)
    overview.add_argument("--ratios", type=_ratios, default=(0.15, 0.5, 0.85))
    overview.add_argument("--items-per-sheet", type=int, default=5)
    overview.add_argument("--frame-width", type=int, default=320)
    overview.add_argument("--frame-height", type=int, default=180)
    overview.set_defaults(handler=_handle_overview)

    triage = subparsers.add_parser(
        "triage", help="Run conservative technical preflight on one video"
    )
    triage.add_argument("video", type=Path)
    triage.add_argument("--output", type=Path, required=True)
    triage.add_argument("--sample-fps", type=float, default=1.0)
    triage.add_argument("--proxy-width", type=int, default=640)
    triage.add_argument("--window-seconds", type=int, default=10)
    triage.add_argument("--contact-every", type=int, default=5)
    triage.add_argument(
        "--fresh", action="store_true", help="Replace an existing matching proxy cache"
    )
    triage.set_defaults(handler=_handle_triage)

    transcribe = subparsers.add_parser(
        "transcribe", help="Extract audio and run a local Whisper CLI"
    )
    transcribe.add_argument("video", type=Path)
    transcribe.add_argument("--output", type=Path, required=True)
    transcribe.add_argument("--model", default="small")
    transcribe.add_argument("--language", default="auto")
    transcribe.add_argument("--whisper-command", default="whisper")
    transcribe.add_argument("--overwrite", action="store_true")
    transcribe.add_argument("--discard-audio", action="store_true")
    transcribe.set_defaults(handler=_handle_transcribe)

    consolidate = subparsers.add_parser(
        "consolidate", help="Gather scattered media into a new folder safely"
    )
    consolidate.add_argument("inventory", type=Path)
    consolidate.add_argument("target", type=Path)
    consolidate.add_argument(
        "--mode", choices=("hardlink", "symlink", "copy"), default="hardlink"
    )
    consolidate.add_argument("--name-template", default="part{part:02d}{suffix}")
    consolidate.add_argument("--dry-run", action="store_true")
    consolidate.set_defaults(handler=_handle_consolidate)

    scan = subparsers.add_parser(
        "scan-project", help="Create an inventory and compact overview in one command"
    )
    scan.add_argument("source", type=Path)
    scan.add_argument("--output", type=Path, required=True)
    scan.add_argument("--extensions", type=_extensions, default=DEFAULT_EXTENSIONS)
    scan.add_argument("--part-regex", default=r"part(\d+)")
    scan.add_argument("--ratios", type=_ratios, default=(0.15, 0.5, 0.85))
    scan.add_argument("--items-per-sheet", type=int, default=5)
    scan.set_defaults(handler=_handle_scan_project)
    return parser


def _handle_doctor(_: argparse.Namespace) -> dict:
    tools = {name: shutil.which(name) for name in ("ffmpeg", "ffprobe", "whisper")}
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "executables": tools,
        "ready_for_visual_work": bool(tools["ffmpeg"] and tools["ffprobe"]),
        "ready_for_transcription": bool(tools["whisper"]),
    }


def _handle_inventory(args: argparse.Namespace) -> dict:
    items = build_inventory(
        args.source, extensions=args.extensions, part_regex=args.part_regex
    )
    csv_path = write_inventory_csv(args.output, items)
    json_path = write_inventory_json(args.json, items) if args.json else None
    return {
        "items": len(items),
        "duplicates": [
            item.part for item in items if item.part is not None and item.copies > 1
        ],
        "total_duration_seconds": round(
            sum(item.duration_seconds for item in items), 3
        ),
        "total_size_bytes": sum(item.size_bytes for item in items),
        "inventory_csv": str(csv_path),
        "inventory_json": str(json_path) if json_path else None,
    }


def _handle_overview(args: argparse.Namespace) -> dict:
    sheets = build_overview(
        args.inventory,
        args.output,
        sample_ratios=args.ratios,
        items_per_sheet=args.items_per_sheet,
        frame_width=args.frame_width,
        frame_height=args.frame_height,
    )
    return {"sheets": [str(sheet) for sheet in sheets], "count": len(sheets)}


def _handle_triage(args: argparse.Namespace) -> dict:
    config = TriageConfig(
        sample_fps=args.sample_fps,
        proxy_width=args.proxy_width,
        window_seconds=args.window_seconds,
        contact_every_seconds=args.contact_every,
    )
    return triage_video(args.video, args.output, config=config, fresh=args.fresh)


def _handle_transcribe(args: argparse.Namespace) -> dict:
    transcript = transcribe_video(
        args.video,
        args.output,
        model=args.model,
        language=args.language,
        whisper_command=args.whisper_command,
        overwrite=args.overwrite,
        keep_audio=not args.discard_audio,
    )
    return {"transcript": str(transcript)}


def _handle_consolidate(args: argparse.Namespace) -> dict:
    plan = execute_consolidation(
        args.inventory,
        args.target,
        mode=args.mode,
        name_template=args.name_template,
        dry_run=args.dry_run,
    )
    return {
        "dry_run": args.dry_run,
        "mode": args.mode,
        "files": len(plan),
        "target": str(args.target.expanduser().resolve()),
        "planned": [
            {"source": str(entry.source), "destination": str(entry.destination)}
            for entry in plan[:10]
        ],
        "planned_truncated": len(plan) > 10,
    }


def _handle_scan_project(args: argparse.Namespace) -> dict:
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    items = build_inventory(
        args.source, extensions=args.extensions, part_regex=args.part_regex
    )
    inventory_csv = write_inventory_csv(output / "inventory.csv", items)
    inventory_json = write_inventory_json(output / "inventory.json", items)
    sheets = build_overview(
        inventory_csv,
        output / "overview",
        sample_ratios=args.ratios,
        items_per_sheet=args.items_per_sheet,
    )
    return {
        "items": len(items),
        "inventory_csv": str(inventory_csv),
        "inventory_json": str(inventory_json),
        "overview_sheets": [str(sheet) for sheet in sheets],
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except (FileNotFoundError, FileExistsError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
