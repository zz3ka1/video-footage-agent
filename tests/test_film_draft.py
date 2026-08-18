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


def _ready_footage_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "footage-project"
    project_dir.mkdir()
    source = project_dir / "part30.mp4"
    source.write_bytes(b"synthetic-footage-source")
    project = {
        "schema_version": "1.0",
        "project": {
            "project_id": "footage_demo",
            "task_mode": "FOOTAGE_FIRST",
            "topic": "博物馆纪念品商店",
            "content_domain": "旅游",
            "part_id": "PART30",
            "target_duration": "00:03:00",
            "speech_rate_profile": "teacher_v1",
            "style_profile_id": "footage_first_travel_zh_cn_v1",
        },
        "footage": {
            "source": {
                "status": "AVAILABLE",
                "path": str(source),
                "file_name": source.name,
                "sha256": "0" * 64,
                "size_bytes": source.stat().st_size,
                "duration": "00:01:00",
                "duration_seconds": 60.0,
            },
            "analysis_coverage": "00:00:00-00:01:00",
            "audio_policy": "不使用未经核验的现场对白",
        },
        "run_status": "RESEARCH_REQUIRED",
        "blocking_inputs": [],
    }
    project_path = project_dir / "footage_demo_PART30_project.json"
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (project_dir / "footage_demo_PART30_scene_map.csv").write_text(
        "window_id,source_in,source_out,coverage_status,summary,characters,"
        "dialogue_gist,visual_notes,confidence,human_review\n"
        "P30-W001,00:00:00,00:00:30,ANALYZED,进入商店,游客,无可靠对白,"
        "入口和货架,high,approved\n"
        "P30-W002,00:00:30,00:01:00,ANALYZED,浏览纪念品,游客,无可靠对白,"
        "杯具和服装,high,approved\n",
        encoding="utf-8",
    )
    (project_dir / "footage_demo_PART30_fact_sources.csv").write_text(
        ",".join(FACT_SOURCES_HEADER)
        + "\nF-P30-01,画面出现杯具和服装,LOCAL_VIDEO,测试素材,"
        + str(source)
        + ",00:00:30-00:01:00,LOCAL_CONFIRMED,2026-08-18,仅限画面观察\n",
        encoding="utf-8",
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
    assert "响应的第一行必须是第一个`===FILE: 文件名===`标记" in request


def test_prepare_film_draft_accepts_footage_first(tmp_path: Path) -> None:
    project = _ready_footage_project(tmp_path)
    output = tmp_path / "footage-draft"
    result = prepare_film_draft(project, output)

    assert result["ready_for_model"] is True
    context = json.loads((output / "draft_context.json").read_text(encoding="utf-8"))
    assert context["project"]["project"]["task_mode"] == "FOOTAGE_FIRST"
    assert context["human_insights"] == []
    assert context["style_profile"]["profile_id"] == "footage_first_travel_zh_cn_v1"
    request = (output / "draft_request.md").read_text(encoding="utf-8")
    assert "不得声称直接读取了本文件未包含的画面或原声" in request


def test_prepare_film_draft_can_redact_remote_context(tmp_path: Path) -> None:
    project = _ready_footage_project(tmp_path)
    output = tmp_path / "footage-redacted"
    result = prepare_film_draft(project, output, redact_local_paths=True)

    assert result["ready_for_model"] is True
    context_text = (output / "draft_context.json").read_text(encoding="utf-8")
    request_text = (output / "draft_request.md").read_text(encoding="utf-8")
    assert str(tmp_path) not in context_text
    assert str(tmp_path) not in request_text
    assert '"sha256": "REDACTED"' in context_text
    assert '"path": "part30.mp4"' in context_text


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
    assert any("SHA-256 与项目配置记录" in item for item in result["blockers"])


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
