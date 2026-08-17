import csv
import json
from pathlib import Path

import pytest

from video_footage_agent.film_project import (
    EDITING_INDEX_HEADER,
    FACT_SOURCES_HEADER,
    SCENE_MAP_HEADER,
    initialize_film_project,
)


def test_initialize_film_project_without_source_is_blocked(tmp_path: Path) -> None:
    output = tmp_path / "film-project"
    result = initialize_film_project(
        output,
        project_id="movie_demo",
        title="示例电影",
        original_title="Example Film",
        release_year=2000,
    )

    assert result["run_status"] == "BLOCKED_INPUT"
    assert result["source_status"] == "MISSING"
    assert len(result["files"]) == 8

    project = json.loads(
        (output / "movie_demo_FULL_project.json").read_text(encoding="utf-8")
    )
    assert project["project"]["task_mode"] == "FILM_FIRST"
    assert project["film"]["source"]["sha256"] == ""
    assert project["legacy_reference_policy"]["timecodes_reusable"] is False
    assert project["legacy_reference_policy"]["asset_rights_reusable"] is False

    manifest = json.loads(
        (output / "movie_demo_FULL_run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["quality_gates"]["clean_script_allowed"] is False
    assert manifest["film"]["analysis_coverage"] == "NOT_STARTED"
    assert manifest["film"]["clip_policy_checked"] is False
    assert manifest["counts"]["local_assets"] == 0

    clean = (output / "movie_demo_FULL_script_clean.md").read_text(encoding="utf-8")
    assert clean.startswith("NOT_READY_TO_RECORD\n")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("movie_demo_FULL_scene_map.csv", SCENE_MAP_HEADER),
        ("movie_demo_FULL_editing_index.csv", EDITING_INDEX_HEADER),
        ("movie_demo_FULL_fact_sources.csv", FACT_SOURCES_HEADER),
    ],
)
def test_initialize_film_project_writes_header_only_csv_files(
    tmp_path: Path, name: str, expected: list[str]
) -> None:
    output = tmp_path / name.replace(".csv", "")
    initialize_film_project(
        output,
        project_id="movie_demo",
        title="示例电影",
        original_title="Example Film",
        release_year=2000,
    )
    with (output / name).open(newline="", encoding="utf-8") as handle:
        assert list(csv.reader(handle)) == [expected]


def test_initialize_film_project_refuses_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(FileExistsError):
        initialize_film_project(
            output,
            project_id="movie_demo",
            title="示例电影",
            original_title="Example Film",
            release_year=2000,
        )


def test_initialize_film_project_rejects_path_like_identifier(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        initialize_film_project(
            tmp_path / "unsafe",
            project_id="../movie",
            title="示例电影",
            original_title="Example Film",
            release_year=2000,
        )


def test_film_first_examples_are_valid_and_disallow_legacy_timecodes() -> None:
    root = Path(__file__).resolve().parents[1]
    template = json.loads(
        (root / "examples/film_first/project_template.json").read_text(encoding="utf-8")
    )
    profile = json.loads(
        (root / "examples/film_first/legacy_longform_style.json").read_text(
            encoding="utf-8"
        )
    )

    assert template["project"]["task_mode"] == "FILM_FIRST"
    assert template["legacy_reference_policy"]["timecodes_reusable"] is False
    assert profile["provenance"]["timecodes_verified"] is False
    assert profile["quality_gates"]["legacy_timecodes_must_not_be_used"] is True
