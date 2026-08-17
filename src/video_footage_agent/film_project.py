"""Safe scaffolding for film-first script projects."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from video_footage_agent.human_insights import human_insights_template
from video_footage_agent.media import format_time, probe_media, video_stream

EDITING_INDEX_HEADER = [
    "asset_id",
    "source_kind",
    "classification",
    "source_file_or_url",
    "source_in",
    "source_out",
    "duration_s",
    "visual_content",
    "audio_content",
    "audio_mode",
    "chinese_gist",
    "suggested_use",
    "edit_instruction",
    "confidence",
    "human_review",
    "license_status",
    "attribution",
]

FACT_SOURCES_HEADER = [
    "fact_id",
    "claim",
    "source_type",
    "source_title",
    "source_url_or_file",
    "source_locator",
    "status",
    "checked_at",
    "notes",
]

SCENE_MAP_HEADER = [
    "window_id",
    "source_in",
    "source_out",
    "coverage_status",
    "summary",
    "characters",
    "dialogue_gist",
    "visual_notes",
    "confidence",
    "human_review",
]

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _validate_id(value: str, field: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(
            f"{field} must start with an ASCII letter or number and contain only "
            "letters, numbers, dots, underscores, or hyphens"
        )
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_metadata(source: Path | None) -> dict[str, Any]:
    if source is None:
        return {
            "status": "MISSING",
            "path": "",
            "file_name": "",
            "sha256": "",
            "size_bytes": None,
            "duration": "",
            "duration_seconds": None,
            "video_codec": "",
            "width": None,
            "height": None,
            "frame_rate": "",
        }

    resolved = source.expanduser().resolve()
    metadata = probe_media(resolved)
    stream = video_stream(metadata)
    duration_seconds = float(metadata["format"]["duration"])
    return {
        "status": "AVAILABLE",
        "path": str(resolved),
        "file_name": resolved.name,
        "sha256": _sha256(resolved),
        "size_bytes": resolved.stat().st_size,
        "duration": format_time(duration_seconds, include_hours=True),
        "duration_seconds": round(duration_seconds, 3),
        "video_codec": stream.get("codec_name", ""),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "frame_rate": stream.get("r_frame_rate", ""),
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_csv_header(path: Path, header: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(header)


def initialize_film_project(
    output: Path,
    *,
    project_id: str,
    title: str,
    original_title: str,
    release_year: int,
    part_id: str = "FULL",
    source: Path | None = None,
    target_duration: str = "UNKNOWN",
    spoiler_policy: str = "UNKNOWN",
    film_clip_policy: str = "UNKNOWN",
    max_web_assets: int | None = None,
    style_profile_id: str = "legacy_longform_movie_explainer_zh_cn_v1",
) -> dict[str, Any]:
    """Create a non-overwriting FILM_FIRST project scaffold."""

    project_id = _validate_id(project_id, "project_id")
    part_id = _validate_id(part_id, "part_id")
    if not title.strip() or not original_title.strip():
        raise ValueError("title and original_title must not be empty")
    if release_year <= 0:
        raise ValueError("release_year must be positive")
    if max_web_assets is not None and max_web_assets < 0:
        raise ValueError("max_web_assets must be non-negative")

    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(output)

    source_info = _source_metadata(source)
    blockers: list[str] = []
    if source_info["status"] != "AVAILABLE":
        blockers.append("缺少可定位且可合法访问的电影原片。")
    if spoiler_policy == "UNKNOWN":
        blockers.append("尚未确认剧透策略。")
    if film_clip_policy == "UNKNOWN":
        blockers.append("尚未确认电影片段、同步原声和字幕使用策略。")
    if max_web_assets is None:
        blockers.append("尚未设置网络补充素材数量上限。")

    run_status = "BLOCKED_INPUT" if blockers else "RESEARCH_REQUIRED"
    stem = f"{project_id}_{part_id}"
    names = {
        "project": f"{stem}_project.json",
        "human_insights": f"{stem}_human_insights.md",
        "annotated": f"{stem}_script_annotated.md",
        "clean": f"{stem}_script_clean.md",
        "scene_map": f"{stem}_scene_map.csv",
        "editing_index": f"{stem}_editing_index.csv",
        "fact_sources": f"{stem}_fact_sources.csv",
        "review_queue": f"{stem}_review_queue.md",
        "manifest": f"{stem}_run_manifest.json",
    }

    project = {
        "schema_version": "1.0",
        "project": {
            "project_id": project_id,
            "task_mode": "FILM_FIRST",
            "topic": title.strip(),
            "content_domain": "电影",
            "part_id": part_id,
            "target_duration": target_duration,
            "speech_rate_profile": "UNKNOWN",
            "style_profile_id": style_profile_id,
            "human_insights_file": names["human_insights"],
        },
        "film": {
            "film_title": title.strip(),
            "film_original_title": original_title.strip(),
            "film_release_year": release_year,
            "source": source_info,
            "film_analysis_coverage": "NOT_STARTED",
            "spoiler_policy": spoiler_policy,
            "film_clip_policy": film_clip_policy,
            "max_web_assets": max_web_assets,
            "cast_focus": [],
            "other_works_scope": [],
        },
        "legacy_reference_policy": {
            "style_reuse_allowed": True,
            "facts_reusable_without_verification": False,
            "timecodes_reusable": False,
            "asset_rights_reusable": False,
        },
        "run_status": run_status,
        "blocking_inputs": blockers,
    }

    output.mkdir(parents=True)
    try:
        _write_json(output / names["project"], project)
        (output / names["human_insights"]).write_text(
            human_insights_template(project_id, part_id), encoding="utf-8"
        )
        _write_csv_header(output / names["scene_map"], SCENE_MAP_HEADER)
        _write_csv_header(output / names["editing_index"], EDITING_INDEX_HEADER)
        _write_csv_header(output / names["fact_sources"], FACT_SOURCES_HEADER)

        missing = (
            "\n".join(f"- {item}" for item in blockers)
            or "- 无缺失配置；等待原片分析。"
        )
        annotated = f"""---
project_id: "{project_id}"
part_id: "{part_id}"
run_status: "{run_status}"
task_mode: "FILM_FIRST"
target_duration: "{target_duration}"
speech_rate_profile: "UNKNOWN"
version: 1
---

# {title.strip()}

## 0. 输入校验

- 可用输入：见 `{names["project"]}`；人类解读填写在 `{names["human_insights"]}`。
- 缺失输入：
{missing}
- 冲突：无已确认冲突。
- 当前状态：`{run_status}`。

## 1. 结构与时长预算

尚未生成。不得从旧稿推断原片时间码。

## 1A. 电影覆盖与角色—演员映射

尚未开始原片分析。

## 2. 带标注稿

尚未生成。

## 3. 术语表

尚未生成。

## 4. 待补素材摘要

尚未生成；必须先建立原片画面缺口。

## 5. QA 结果

- [ ] 事实均有来源
- [ ] 素材 ID 均可定位
- [ ] 音频模式合法
- [ ] 术语已核验
- [ ] 人工问题未进入净稿
- [ ] 电影覆盖、剧透和片段策略已检查
"""
        (output / names["annotated"]).write_text(annotated, encoding="utf-8")
        (output / names["clean"]).write_text(
            "NOT_READY_TO_RECORD\n未生成录制净稿；请处理 review_queue.md 中的阻塞项。\n",
            encoding="utf-8",
        )

        review_items = blockers + [
            "完成原片覆盖分析并核对角色—演员映射后，才能生成正文。"
        ]
        review_sections = []
        for number, item in enumerate(review_items, start=1):
            review_sections.append(
                f"""### H-FILM-{number:02d}：待确认

- 位置：项目配置／电影覆盖
- 候选：无
- 证据：当前项目初始化状态
- 不确定性：{item}
- 问题：请提供或确认该项。
- 未确认时的默认处理：不生成录制净稿
"""
            )
        review = "# 人工复核队列\n\n## 阻塞项\n\n" + "\n".join(review_sections)
        review += "\n## 非阻塞项\n\n暂无。\n"
        (output / names["review_queue"]).write_text(review, encoding="utf-8")

        manifest = {
            "schema_version": "1.2",
            "project_id": project_id,
            "part_id": part_id,
            "run_status": run_status,
            "task_mode": "FILM_FIRST",
            "prompt_version": "1.2",
            "style_guide_version": "1.2",
            "inputs": [
                *([source_info["path"]] if source_info["path"] else []),
                names["human_insights"],
            ],
            "outputs": list(names.values()),
            "counts": {
                "verified_facts": 0,
                "local_assets": 0,
                "web_assets": 0,
                "human_insights": 0,
                "confirmed_human_insights": 0,
                "blocking_reviews": len(review_items),
                "non_blocking_reviews": 0,
            },
            "duration": {
                "target": target_duration,
                "estimated": "",
                "calibrated": False,
            },
            "film": {
                "title": title.strip(),
                "original_title": original_title.strip(),
                "release_year": str(release_year),
                "source_duration": source_info["duration"],
                "analysis_coverage": "NOT_STARTED",
                "spoiler_policy": spoiler_policy,
                "clip_policy_checked": False,
                "max_web_assets": max_web_assets,
                "selected_web_assets": 0,
            },
            "quality_gates": {
                "facts_traceable": False,
                "assets_traceable": False,
                "terminology_checked": False,
                "licenses_checked": False,
                "continuity_checked": False,
                "film_coverage_checked": False,
                "cast_mapping_checked": False,
                "clip_policy_checked": False,
                "human_insights_checked": False,
                "clean_script_allowed": False,
            },
        }
        _write_json(output / names["manifest"], manifest)
    except Exception:
        shutil.rmtree(output)
        raise

    return {
        "output": str(output),
        "run_status": run_status,
        "source_status": source_info["status"],
        "blocking_inputs": blockers,
        "files": [str(output / name) for name in names.values()],
    }
