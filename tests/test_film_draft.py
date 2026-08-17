import json
from pathlib import Path

from video_footage_agent.film_draft import prepare_film_draft
from video_footage_agent.film_project import (
    FACT_SOURCES_HEADER,
    initialize_film_project,
)

ROOT = Path(__file__).resolve().parents[1]


def _ready_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source = project_dir / "source.mp4"
    source.write_bytes(b"synthetic-test-source")
    project = {
        "schema_version": "1.0",
        "project": {
            "project_id": "movie_demo",
            "task_mode": "FILM_FIRST",
            "topic": "示例电影",
            "content_domain": "电影",
            "part_id": "FULL",
            "target_duration": "00:03:00",
            "speech_rate_profile": "teacher_v1",
            "style_profile_id": "legacy_longform_movie_explainer_zh_cn_v1",
            "human_insights_file": "movie_demo_FULL_human_insights.md",
        },
        "film": {
            "film_title": "示例电影",
            "film_original_title": "Example Film",
            "film_release_year": 2000,
            "source": {
                "status": "AVAILABLE",
                "path": str(source),
                "file_name": source.name,
                "sha256": "0" * 64,
                "size_bytes": source.stat().st_size,
                "duration": "00:10:00",
                "duration_seconds": 600.0,
            },
            "film_analysis_coverage": "00:00:00-00:10:00",
            "spoiler_policy": "PARTIAL_SPOILERS",
            "film_clip_policy": "测试项目确认的片段、原声和字幕规则",
            "max_web_assets": 4,
            "cast_focus": [],
            "other_works_scope": [],
        },
        "run_status": "RESEARCH_REQUIRED",
        "blocking_inputs": [],
    }
    project_path = project_dir / "movie_demo_FULL_project.json"
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (project_dir / "movie_demo_FULL_scene_map.csv").write_text(
        (ROOT / "examples/film_first/scene_map_example.csv").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (project_dir / "movie_demo_FULL_human_insights.md").write_text(
        (ROOT / "examples/film_first/human_insights_example.md").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (project_dir / "movie_demo_FULL_fact_sources.csv").write_text(
        ",".join(FACT_SOURCES_HEADER) + "\n", encoding="utf-8"
    )
    return project_path


def test_prepare_film_draft_builds_self_contained_package(tmp_path: Path) -> None:
    project = _ready_project(tmp_path)
    output = tmp_path / "draft"
    result = prepare_film_draft(project, output)

    assert result["mode"] == "PREPARE_ONLY"
    assert result["ready_for_model"] is True
    assert len(result["files"]) == 4
    assert any("未重新计算 SHA-256" in item for item in result["warnings"])

    readiness = json.loads(
        (output / "draft_readiness.json").read_text(encoding="utf-8")
    )
    assert readiness["counts"]["scenes"] == 11
    assert readiness["counts"]["human_insights"] == 2
    assert readiness["counts"]["confirmed_human_insights"] == 1

    context = json.loads((output / "draft_context.json").read_text(encoding="utf-8"))
    assert context["generation_contract"]["model_invoked"] is False
    assert context["human_insights"][0]["insight_id"] == "HINS-001"

    request = (output / "draft_request.md").read_text(encoding="utf-8")
    assert "钥匙不只是推动剧情的道具" in request
    assert "视频稿件与剪辑索引 Agent" in request
    assert "视频稿件完整写作规范" in request


def test_prepare_film_draft_writes_only_readiness_when_blocked(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "blocked-project"
    initialize_film_project(
        project_dir,
        project_id="blocked_movie",
        title="未准备电影",
        original_title="Unavailable Film",
        release_year=2000,
    )
    project = project_dir / "blocked_movie_FULL_project.json"
    output = tmp_path / "blocked-draft"
    result = prepare_film_draft(project, output)

    assert result["ready_for_model"] is False
    assert len(result["files"]) == 1
    assert (output / "draft_readiness.json").is_file()
    assert not (output / "draft_context.json").exists()
    assert not (output / "draft_request.md").exists()
    assert any("电影原片" in item for item in result["blockers"])
    assert any("场景地图没有任何数据行" in item for item in result["blockers"])


def test_prepare_film_draft_can_reverify_source_hash(tmp_path: Path) -> None:
    project = _ready_project(tmp_path)
    result = prepare_film_draft(
        project, tmp_path / "hash-check", verify_source_hash=True
    )
    assert result["ready_for_model"] is False
    assert any("SHA-256 与 film-init" in item for item in result["blockers"])


def test_prepare_film_draft_rejects_full_coverage_gap(tmp_path: Path) -> None:
    project = _ready_project(tmp_path)
    scene_map = project.parent / "movie_demo_FULL_scene_map.csv"
    content = scene_map.read_text(encoding="utf-8")
    content = "\n".join(
        line for line in content.splitlines() if not line.startswith("F001-W002,")
    )
    scene_map.write_text(content + "\n", encoding="utf-8")

    result = prepare_film_draft(project, tmp_path / "coverage-gap")
    assert result["ready_for_model"] is False
    assert any("未覆盖范围" in item for item in result["blockers"])
