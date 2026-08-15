import os
from pathlib import Path

import pytest

from video_footage_agent.consolidate import execute_consolidation
from video_footage_agent.inventory import InventoryItem, write_inventory_csv


def item(part: int, path: Path) -> InventoryItem:
    return InventoryItem(
        part=part,
        filename=path.name,
        duration_seconds=1.0,
        size_bytes=path.stat().st_size,
        codec="h264",
        width=320,
        height=180,
        frame_rate="10/1",
        copies=1,
        path=str(path),
    )


def test_hardlink_consolidation_and_dry_run(tmp_path: Path) -> None:
    source_a = tmp_path / "source_a.MP4"
    source_b = tmp_path / "source_b.MP4"
    source_a.write_bytes(b"a")
    source_b.write_bytes(b"bb")
    inventory = write_inventory_csv(
        tmp_path / "media.csv", [item(1, source_a), item(2, source_b)]
    )

    dry_target = tmp_path / "dry"
    plan = execute_consolidation(inventory, dry_target, dry_run=True)
    assert len(plan) == 2
    assert not dry_target.exists()

    target = tmp_path / "all_parts"
    execute_consolidation(inventory, target, mode="hardlink")
    assert sorted(path.name for path in target.iterdir()) == [
        "part01.MP4",
        "part02.MP4",
    ]
    assert os.stat(source_a).st_ino == os.stat(target / "part01.MP4").st_ino


def test_consolidation_refuses_existing_target(tmp_path: Path) -> None:
    source = tmp_path / "source.MP4"
    source.write_bytes(b"a")
    inventory = write_inventory_csv(tmp_path / "media.csv", [item(1, source)])
    target = tmp_path / "existing"
    target.mkdir()
    with pytest.raises(FileExistsError):
        execute_consolidation(inventory, target)
