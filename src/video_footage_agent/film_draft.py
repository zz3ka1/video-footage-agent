"""Validate film-first inputs and build a self-contained model draft package."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from video_footage_agent.film_project import FACT_SOURCES_HEADER, SCENE_MAP_HEADER
from video_footage_agent.human_insights import load_human_insight_cards

SCENE_COVERAGE_STATUSES = (
    "ANALYZED",
    "REVIEW_REQUIRED",
    "NO_NARRATIVE_VALUE",
    "UNANALYZED",
)
FACT_STATUSES = (
    "VERIFIED",
    "LOCAL_CONFIRMED",
    "CONFLICT",
    "HUMAN_REVIEW",
    "UNVERIFIED",
    "OMIT",
)
SPOILER_POLICIES = (
    "NO_MAJOR_SPOILERS",
    "PARTIAL_SPOILERS",
    "FULL_SPOILERS",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return data


def _read_csv_rows(
    path: Path, expected_header: list[str], label: str
) -> list[dict[str, str]]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    with resolved.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != expected_header:
            raise ValueError(
                f"{label} header mismatch; expected: {','.join(expected_header)}"
            )
        return list(reader)


def _time_seconds(value: str) -> int | None:
    parts = value.split(":")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        return None
    hours, minutes, seconds = (int(part) for part in parts)
    if minutes > 59 or seconds > 59:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _validate_scene_rows(
    rows: list[dict[str, str]], blockers: list[str], warnings: list[str]
) -> None:
    if not rows:
        blockers.append("场景地图没有任何数据行。")
        return

    seen: set[str] = set()
    previous_start: int | None = None
    for number, row in enumerate(rows, start=2):
        window_id = row["window_id"].strip()
        label = window_id or f"scene_map row {number}"
        if not window_id:
            blockers.append(f"{label} 缺少 window_id。")
        elif window_id in seen:
            blockers.append(f"场景地图包含重复 window_id：{window_id}。")
        else:
            seen.add(window_id)

        source_in = _time_seconds(row["source_in"].strip())
        source_out = _time_seconds(row["source_out"].strip())
        if source_in is None or source_out is None or source_out <= source_in:
            blockers.append(f"{label} 的 source_in/source_out 无效。")
        elif previous_start is not None and source_in < previous_start:
            blockers.append(f"{label} 没有按照 source_in 时间顺序排列。")
        if source_in is not None:
            previous_start = source_in

        coverage_status = row["coverage_status"].strip()
        if coverage_status not in SCENE_COVERAGE_STATUSES:
            blockers.append(f"{label} 使用了非法 coverage_status。")
        elif coverage_status == "UNANALYZED":
            blockers.append(f"{label} 尚未分析，不能进入电影草稿包。")
        elif coverage_status == "REVIEW_REQUIRED":
            warnings.append(f"{label} 仍需人工复核。")

        if row["confidence"].strip() not in {"high", "medium", "low"}:
            blockers.append(f"{label} 使用了非法 confidence。")
        if row["human_review"].strip() not in {"approved", "pending", "rejected"}:
            blockers.append(f"{label} 使用了非法 human_review。")
        if coverage_status == "ANALYZED" and not (
            row["summary"].strip() or row["visual_notes"].strip()
        ):
            blockers.append(f"{label} 已标为 ANALYZED，但没有内容摘要或画面说明。")


def _validate_fact_rows(
    rows: list[dict[str, str]], blockers: list[str], warnings: list[str]
) -> None:
    for number, row in enumerate(rows, start=2):
        label = row["fact_id"].strip() or f"fact_sources row {number}"
        if not row["fact_id"].strip():
            blockers.append(f"{label} 缺少 fact_id。")
        status = row["status"].strip()
        if status not in FACT_STATUSES:
            blockers.append(f"{label} 使用了非法事实状态。")
        elif status in {"CONFLICT", "HUMAN_REVIEW", "UNVERIFIED"}:
            warnings.append(f"{label} 尚不能进入净稿：{status}。")


def _validate_full_coverage(
    rows: list[dict[str, str]], duration_seconds: float, blockers: list[str]
) -> None:
    intervals = []
    for row in rows:
        start = _time_seconds(row["source_in"].strip())
        end = _time_seconds(row["source_out"].strip())
        if start is not None and end is not None and end > start:
            intervals.append((start, end))
    if not intervals:
        return

    intervals.sort()
    cursor = 0
    for start, end in intervals:
        if start > cursor + 1:
            blockers.append(f"FULL 场景地图存在未覆盖范围：{cursor}–{start} 秒。")
        cursor = max(cursor, end)
    if cursor < duration_seconds - 1:
        blockers.append(
            f"FULL 场景地图只覆盖到 {cursor} 秒，原片为 {duration_seconds:g} 秒。"
        )
    if cursor > duration_seconds + 1:
        blockers.append("场景地图时间码超过了项目记录的原片总时长。")


def _default_repo_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[2].joinpath(*parts)


def _resolve_input(explicit: Path | None, inferred: Path) -> Path:
    return (explicit or inferred).expanduser().resolve()


def _input_record(role: str, path: Path) -> dict[str, Any]:
    return {
        "role": role,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def prepare_film_draft(
    project_config: Path,
    output: Path,
    *,
    scene_map: Path | None = None,
    human_insights: Path | None = None,
    fact_sources: Path | None = None,
    style_profile: Path | None = None,
    strict_prompt: Path | None = None,
    style_guide: Path | None = None,
    verify_source_hash: bool = False,
) -> dict[str, Any]:
    """Prepare a traceable draft package without invoking an online model."""

    project_config = project_config.expanduser().resolve()
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(output)

    project_data = _read_json_object(project_config, "project config")
    project = project_data.get("project")
    film = project_data.get("film")
    if not isinstance(project, dict) or not isinstance(film, dict):
        raise ValueError("project config must contain project and film objects")

    project_id = project.get("project_id")
    part_id = project.get("part_id")
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project.project_id is required")
    if not isinstance(part_id, str) or not part_id:
        raise ValueError("project.part_id is required")
    if project.get("task_mode") != "FILM_FIRST":
        raise ValueError("film-draft only accepts task_mode=FILM_FIRST")

    stem = f"{project_id}_{part_id}"
    project_dir = project_config.parent
    paths = {
        "project_config": project_config,
        "scene_map": _resolve_input(scene_map, project_dir / f"{stem}_scene_map.csv"),
        "human_insights": _resolve_input(
            human_insights, project_dir / f"{stem}_human_insights.md"
        ),
        "fact_sources": _resolve_input(
            fact_sources, project_dir / f"{stem}_fact_sources.csv"
        ),
        "style_profile": _resolve_input(
            style_profile,
            _default_repo_path("examples", "film_first", "legacy_longform_style.json"),
        ),
        "strict_prompt": _resolve_input(
            strict_prompt,
            _default_repo_path("prompts", "script-writer.zh-CN.md"),
        ),
        "style_guide": _resolve_input(
            style_guide,
            _default_repo_path("docs", "script-style-guide.zh-CN.md"),
        ),
    }

    blockers: list[str] = []
    warnings: list[str] = []
    for role, path in paths.items():
        if not path.is_file():
            blockers.append(f"缺少 {role}：{path}。")

    source = film.get("source")
    if not isinstance(source, dict) or source.get("status") != "AVAILABLE":
        blockers.append("项目没有状态为 AVAILABLE 的电影原片。")
        source_path = None
    else:
        raw_source_path = source.get("path")
        source_path = (
            Path(raw_source_path).expanduser().resolve()
            if isinstance(raw_source_path, str) and raw_source_path
            else None
        )
        if source_path is None or not source_path.is_file():
            blockers.append("项目记录的电影原片路径当前不可访问。")
        else:
            expected_size = source.get("size_bytes")
            if not isinstance(expected_size, int) or isinstance(expected_size, bool):
                blockers.append("项目没有记录有效的电影原片文件大小。")
            elif source_path.stat().st_size != expected_size:
                blockers.append("电影原片大小与 film-init 记录不一致。")
            recorded_hash = source.get("sha256")
            if not isinstance(recorded_hash, str) or (
                len(recorded_hash) != 64
                or any(
                    character not in "0123456789abcdef" for character in recorded_hash
                )
            ):
                blockers.append("项目没有有效的电影原片 SHA-256 指纹。")
            elif verify_source_hash:
                if _sha256(source_path) != recorded_hash:
                    blockers.append("电影原片 SHA-256 与 film-init 记录不一致。")
            else:
                warnings.append("本次只核对原片路径和大小；未重新计算 SHA-256。")

    film_title = film.get("film_title")
    original_title = film.get("film_original_title")
    release_year = film.get("film_release_year")
    if not isinstance(film_title, str) or not film_title.strip():
        blockers.append("film_title 不能为空。")
    if not isinstance(original_title, str) or not original_title.strip():
        blockers.append("film_original_title 不能为空。")
    if (
        not isinstance(release_year, int)
        or isinstance(release_year, bool)
        or release_year <= 0
    ):
        blockers.append("film_release_year 必须是正整数。")
    source_duration = (
        source.get("duration_seconds") if isinstance(source, dict) else None
    )
    if (
        not isinstance(source_duration, (int, float))
        or isinstance(source_duration, bool)
        or source_duration <= 0
    ):
        blockers.append("项目没有记录有效的电影原片总时长。")

    if film.get("film_analysis_coverage") in {None, "", "UNKNOWN", "NOT_STARTED"}:
        blockers.append("film_analysis_coverage 尚未完成。")
    if film.get("spoiler_policy") not in SPOILER_POLICIES:
        blockers.append("spoiler_policy 尚未确认或使用了非法值。")
    if film.get("film_clip_policy") in {None, "", "UNKNOWN"}:
        blockers.append("film_clip_policy 尚未确认。")
    max_web_assets = film.get("max_web_assets")
    if (
        not isinstance(max_web_assets, int)
        or isinstance(max_web_assets, bool)
        or max_web_assets < 0
    ):
        blockers.append("max_web_assets 必须是非负整数。")

    scene_rows: list[dict[str, str]] = []
    fact_rows: list[dict[str, str]] = []
    insight_cards: list[dict[str, Any]] = []
    style_data: dict[str, Any] = {}
    prompt_text = ""
    guide_text = ""
    scene_map_valid = False

    if paths["scene_map"].is_file():
        try:
            scene_rows = _read_csv_rows(
                paths["scene_map"], SCENE_MAP_HEADER, "scene map"
            )
            scene_map_valid = True
            _validate_scene_rows(scene_rows, blockers, warnings)
            if part_id == "FULL" and isinstance(source_duration, (int, float)):
                _validate_full_coverage(scene_rows, float(source_duration), blockers)
        except ValueError as exc:
            blockers.append(str(exc))
    if paths["fact_sources"].is_file():
        try:
            fact_rows = _read_csv_rows(
                paths["fact_sources"], FACT_SOURCES_HEADER, "fact sources"
            )
            _validate_fact_rows(fact_rows, blockers, warnings)
        except ValueError as exc:
            blockers.append(str(exc))
    if paths["human_insights"].is_file() and paths["scene_map"].is_file():
        try:
            insight_cards = load_human_insight_cards(
                paths["human_insights"],
                scene_map=paths["scene_map"] if scene_map_valid else None,
            )
        except ValueError as exc:
            blockers.append(str(exc))
    if paths["style_profile"].is_file():
        try:
            style_data = _read_json_object(paths["style_profile"], "style profile")
            expected_profile_id = project.get("style_profile_id")
            if (
                isinstance(expected_profile_id, str)
                and expected_profile_id
                and style_data.get("profile_id") != expected_profile_id
            ):
                blockers.append("style profile ID 与项目配置不一致。")
        except ValueError as exc:
            blockers.append(str(exc))
    if paths["strict_prompt"].is_file():
        prompt_text = paths["strict_prompt"].read_text(encoding="utf-8")
    if paths["style_guide"].is_file():
        guide_text = paths["style_guide"].read_text(encoding="utf-8")

    if any(card["insight_type"] == "FACT_CLAIM" for card in insight_cards):
        warnings.append("人类解读包含 FACT_CLAIM；模型必须等待独立来源核验。")
    if any(card["status"] == "DRAFT" for card in insight_cards):
        warnings.append("存在 DRAFT 解读卡；不得作为强制写稿要求。")

    readiness = {
        "schema_version": "1.0",
        "mode": "PREPARE_ONLY",
        "project_id": project_id,
        "part_id": part_id,
        "ready_for_model": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "counts": {
            "scenes": len(scene_rows),
            "human_insights": len(insight_cards),
            "confirmed_human_insights": sum(
                card["status"] == "CONFIRMED" for card in insight_cards
            ),
            "facts": len(fact_rows),
            "verified_facts": sum(
                row["status"].strip() in {"VERIFIED", "LOCAL_CONFIRMED"}
                for row in fact_rows
            ),
        },
    }

    output.mkdir(parents=True)
    try:
        readiness_path = output / "draft_readiness.json"
        readiness_path.write_text(
            json.dumps(readiness, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        generated = [readiness_path]

        if not blockers:
            context = {
                "schema_version": "1.0",
                "generation_contract": {
                    "prompt_version": "1.2",
                    "style_guide_version": "1.2",
                    "model_invoked": False,
                },
                "project": project_data,
                "scene_map": scene_rows,
                "human_insights": insight_cards,
                "fact_sources": fact_rows,
                "style_profile": style_data,
            }
            context_json = json.dumps(context, ensure_ascii=False, indent=2)
            context_path = output / "draft_context.json"
            context_path.write_text(context_json + "\n", encoding="utf-8")

            request = f"""# 电影稿件模型请求包

本文件由 `film-draft` 的 `PREPARE_ONLY` 模式生成，尚未调用模型。
只允许依据下方结构化输入写稿；不得声称直接读取了本文件未包含的电影画面。

## 严格提示词

{prompt_text}

## 写稿规范

{guide_text}

## 本次结构化输入

```json
{context_json}
```
"""
            request_path = output / "draft_request.md"
            request_path.write_text(request, encoding="utf-8")
            generated.extend([context_path, request_path])

            input_records = [
                _input_record(role, path)
                for role, path in paths.items()
                if path.is_file()
            ]
            if source_path is not None and source_path.is_file():
                input_records.append(
                    {
                        "role": "film_source",
                        "path": str(source_path),
                        "size_bytes": source_path.stat().st_size,
                        "sha256": source.get("sha256", ""),
                        "hash_reverified": verify_source_hash,
                    }
                )
            manifest = {
                "schema_version": "1.0",
                "mode": "PREPARE_ONLY",
                "project_id": project_id,
                "part_id": part_id,
                "inputs": input_records,
                "outputs": [
                    _input_record("generated", path)
                    for path in (readiness_path, context_path, request_path)
                ],
                "scene_status_counts": dict(
                    sorted(
                        Counter(row["coverage_status"] for row in scene_rows).items()
                    )
                ),
            }
            manifest_path = output / "draft_package_manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            generated.append(manifest_path)
    except Exception:
        shutil.rmtree(output)
        raise

    return {
        "mode": "PREPARE_ONLY",
        "ready_for_model": not blockers,
        "output": str(output),
        "blockers": blockers,
        "warnings": warnings,
        "files": [str(path) for path in generated],
    }
