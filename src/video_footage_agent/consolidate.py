"""Safely consolidate scattered media without silently overwriting files."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from video_footage_agent.inventory import InventoryItem, read_inventory_csv


@dataclass(frozen=True)
class ConsolidationEntry:
    source: Path
    destination: Path
    mode: str


def render_destination_name(item: InventoryItem, index: int, template: str) -> str:
    values = {
        "part": item.part if item.part is not None else index,
        "index": index,
        "filename": item.filename,
        "stem": Path(item.filename).stem,
        "suffix": Path(item.filename).suffix,
    }
    try:
        name = template.format(**values)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid name template: {template}") from exc
    if not name or Path(name).name != name:
        raise ValueError(f"Template must produce a plain filename, got: {name!r}")
    return name


def plan_consolidation(
    items: list[InventoryItem],
    target: Path,
    *,
    mode: str = "hardlink",
    name_template: str = "part{part:02d}{suffix}",
) -> list[ConsolidationEntry]:
    if mode not in {"hardlink", "symlink", "copy"}:
        raise ValueError(f"Unsupported mode: {mode}")
    target = target.expanduser().resolve()
    plan: list[ConsolidationEntry] = []
    names: set[str] = set()
    for index, item in enumerate(items, start=1):
        source = Path(item.path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        name = render_destination_name(item, index, name_template)
        folded = name.casefold()
        if folded in names:
            raise ValueError(f"Name template produced a duplicate filename: {name}")
        names.add(folded)
        plan.append(
            ConsolidationEntry(source=source, destination=target / name, mode=mode)
        )
    if not plan:
        raise ValueError("Inventory is empty")
    return plan


def execute_consolidation(
    inventory: Path,
    target: Path,
    *,
    mode: str = "hardlink",
    name_template: str = "part{part:02d}{suffix}",
    dry_run: bool = False,
) -> list[ConsolidationEntry]:
    items = read_inventory_csv(inventory)
    target = target.expanduser().resolve()
    plan = plan_consolidation(items, target, mode=mode, name_template=name_template)
    if target.exists():
        raise FileExistsError(
            f"Target already exists; refusing to merge or overwrite: {target}"
        )
    if dry_run:
        return plan

    if mode == "hardlink":
        target_device = target.parent.stat().st_dev
        for entry in plan:
            if entry.source.stat().st_dev != target_device:
                raise RuntimeError(
                    f"Hard links require the same filesystem: {entry.source}"
                )

    created: list[Path] = []
    target.mkdir(parents=False)
    try:
        for entry in plan:
            if mode == "hardlink":
                os.link(entry.source, entry.destination)
            elif mode == "symlink":
                entry.destination.symlink_to(entry.source)
            else:
                shutil.copy2(entry.source, entry.destination)
            created.append(entry.destination)
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        target.rmdir()
        raise

    for entry in plan:
        if not entry.destination.is_file():
            raise RuntimeError(
                f"Consolidation verification failed: {entry.destination}"
            )
        if mode == "hardlink":
            source_stat = entry.source.stat()
            target_stat = entry.destination.stat()
            if (source_stat.st_dev, source_stat.st_ino) != (
                target_stat.st_dev,
                target_stat.st_ino,
            ):
                raise RuntimeError(
                    f"Hard-link verification failed: {entry.destination}"
                )
        elif (
            mode == "copy"
            and entry.source.stat().st_size != entry.destination.stat().st_size
        ):
            raise RuntimeError(f"Copy size verification failed: {entry.destination}")
    return plan
