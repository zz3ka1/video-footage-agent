from pathlib import Path

from video_footage_agent.inventory import build_inventory, extract_part_number


def fake_probe(_: Path) -> dict:
    return {
        "format": {"duration": "12.5", "size": "12345"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30000/1001",
            }
        ],
    }


def test_extract_part_number() -> None:
    assert extract_part_number("trip_part07.MP4", r"part(\d+)") == 7
    assert extract_part_number("clip.MP4", r"part(\d+)") is None
    assert extract_part_number("clip.MP4", None) is None


def test_build_inventory_deduplicates_part_numbers(tmp_path: Path) -> None:
    first = tmp_path / "part01.MP4"
    nested = tmp_path / "nested"
    nested.mkdir()
    duplicate = nested / "part01.MP4"
    second = tmp_path / "part02.mov"
    for path in (first, duplicate, second):
        path.write_bytes(b"not real video")

    items = build_inventory(tmp_path, probe=fake_probe)

    assert [item.part for item in items] == [1, 2]
    assert items[0].copies == 2
    assert items[0].path == str(first.resolve())
    assert str(duplicate.resolve()) in items[0].duplicate_paths
    assert items[1].duration_seconds == 12.5
