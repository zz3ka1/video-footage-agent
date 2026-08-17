"""Generate and validate the six-file film script delivery package."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from video_footage_agent.audio_modes import AUDIO_MODES
from video_footage_agent.film_project import EDITING_INDEX_HEADER, FACT_SOURCES_HEADER

RUN_STATUSES = {
    "BLOCKED_INPUT",
    "RESEARCH_REQUIRED",
    "DRAFT_UNCALIBRATED",
    "REVIEW_REQUIRED",
    "READY_TO_RECORD",
}
SOURCE_KINDS = {
    "LOCAL_VIDEO",
    "FILM_SOURCE",
    "LOCAL_IMAGE",
    "WEB_IMAGE",
    "WEB_VIDEO",
    "GFX",
}
CLASSIFICATIONS = {
    "KEEP",
    "KEEP_CONTINUITY",
    "REFERENCE_ONLY",
    "SALVAGE",
    "REVIEW",
    "LOW_VALUE",
    "TECHNICAL_FAIL",
}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
HUMAN_REVIEW_STATUSES = {"approved", "pending", "rejected"}
LICENSE_STATUSES = {
    "OWNED",
    "VERIFIED",
    "HUMAN_REVIEW",
    "REJECTED",
    "NOT_APPLICABLE",
}
FACT_SOURCE_TYPES = {
    "USER_CONFIRMATION",
    "LOCAL_VIDEO",
    "FILM_SOURCE",
    "LOCAL_AUDIO",
    "OFFICIAL",
    "PAPER",
    "AUTHORITATIVE_SECONDARY",
}
FACT_STATUSES = {
    "VERIFIED",
    "LOCAL_CONFIRMED",
    "CONFLICT",
    "HUMAN_REVIEW",
    "UNVERIFIED",
    "OMIT",
}
READY_FACT_STATUSES = {"VERIFIED", "LOCAL_CONFIRMED"}
NOT_READY_CLEAN_SCRIPT = (
    "NOT_READY_TO_RECORD\n"
    "未生成录制净稿；请处理 review_queue.md 中的阻塞项。"
)

_FILE_HEADER = re.compile(r"===FILE: ([^\r\n]+)===[ \t]*\r?\n?$")
_FILE_END = re.compile(r"===END FILE===[ \t]*\r?\n?$")
_FACT_REFERENCE = re.compile(r"\[(F-[A-Za-z0-9._-]+)\]")
_ASSET_REFERENCE = re.compile(
    r"\[([A-Za-z0-9._-]+-(?:VID|IMG|WEB|GFX)-\d{2,})(?:[+-]|\s*\|)"
)
_REVIEW_REFERENCE = re.compile(r"\[REVIEW:([A-Za-z0-9._-]+)\]")
_INTERNAL_CLEAN_PATTERNS = (
    (re.compile(r"\[F-[A-Za-z0-9._-]+\]"), "事实编号"),
    (re.compile(r"[A-Za-z0-9._-]+-(?:VID|IMG|WEB|GFX)-\d{2,}"), "素材 ID"),
    (re.compile(r"\[REVIEW:"), "人工复核标记"),
    (re.compile(r"https?://", re.IGNORECASE), "网址"),
    (re.compile(r"(?<!\d)\d{2}:\d{2}(?::\d{2})?(?!\d)"), "时间码"),
    (re.compile(r"\bHUMAN_REVIEW\b"), "许可或事实内部状态"),
)


@dataclass(frozen=True)
class ModelResponse:
    """Provider-neutral text response and trace metadata."""

    text: str
    provider: str
    model: str
    response_id: str = ""
    usage: dict[str, Any] | None = None


class TextGenerationProvider(Protocol):
    """Minimal interface used by the film generation workflow."""

    def generate(self, request: str) -> ModelResponse:
        """Return the model's complete six-file text response."""


class OpenAIResponsesProvider:
    """OpenAI Responses API adapter loaded only when explicitly requested."""

    def __init__(
        self,
        *,
        model: str,
        reasoning_effort: str | None = None,
        verbosity: str | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("OpenAI model must not be empty")
        if reasoning_effort not in {None, "none", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("unsupported reasoning effort")
        if verbosity not in {None, "low", "medium", "high"}:
            raise ValueError("unsupported verbosity")
        if max_output_tokens is not None and max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        self.model = model.strip()
        self.reasoning_effort = reasoning_effort
        self.verbosity = verbosity
        self.max_output_tokens = max_output_tokens

    def generate(self, request: str) -> ModelResponse:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY is not configured; set it in the environment before "
                "using --provider openai"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                'OpenAI SDK is not installed; run pip install -e ".[openai]"'
            ) from exc

        parameters: dict[str, Any] = {
            "model": self.model,
            "input": request,
            "store": False,
        }
        if self.reasoning_effort is not None:
            parameters["reasoning"] = {"effort": self.reasoning_effort}
        if self.verbosity is not None:
            parameters["text"] = {"verbosity": self.verbosity}
        if self.max_output_tokens is not None:
            parameters["max_output_tokens"] = self.max_output_tokens

        try:
            response = OpenAI().responses.create(**parameters)
        except Exception as exc:
            raise RuntimeError(
                f"OpenAI Responses API call failed ({type(exc).__name__}): {exc}"
            ) from exc

        response_status = getattr(response, "status", None)
        if isinstance(response_status, str) and response_status != "completed":
            raise RuntimeError(
                f"OpenAI response was not completed (status={response_status})"
            )
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise RuntimeError("OpenAI response did not contain non-empty output_text")
        usage = _serializable_usage(getattr(response, "usage", None))
        response_model = getattr(response, "model", self.model)
        return ModelResponse(
            text=output_text,
            provider="openai",
            model=response_model if isinstance(response_model, str) else self.model,
            response_id=_string_value(getattr(response, "id", "")),
            usage=usage,
        )


class ResponseFileProvider:
    """Offline provider for validating an externally captured model response."""

    def __init__(self, response_file: Path) -> None:
        self.response_file = response_file.expanduser().resolve()

    def generate(self, request: str) -> ModelResponse:
        del request
        if not self.response_file.is_file():
            raise FileNotFoundError(self.response_file)
        text = self.response_file.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError("response file is empty")
        return ModelResponse(text=text, provider="response_file", model="external")


def _string_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _serializable_usage(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if isinstance(usage, dict):
        candidate = usage
    else:
        dump = getattr(usage, "model_dump", None)
        candidate = dump() if callable(dump) else None
    if not isinstance(candidate, dict):
        return None
    try:
        json.dumps(candidate)
    except (TypeError, ValueError):
        return None
    return candidate


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return data


def _expected_names(project_id: str, part_id: str) -> dict[str, str]:
    stem = f"{project_id}_{part_id}"
    return {
        "annotated": f"{stem}_script_annotated.md",
        "clean": f"{stem}_script_clean.md",
        "editing": f"{stem}_editing_index.csv",
        "facts": f"{stem}_fact_sources.csv",
        "review": f"{stem}_review_queue.md",
        "manifest": f"{stem}_run_manifest.json",
    }


def parse_six_file_response(text: str) -> dict[str, str]:
    """Parse strict ``===FILE: ...===`` blocks without accepting extra prose."""

    lines = text.splitlines(keepends=True)
    files: dict[str, str] = {}
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        match = _FILE_HEADER.fullmatch(lines[index])
        if match is None:
            raise ValueError(
                f"unexpected text outside file blocks at response line {index + 1}"
            )
        filename = match.group(1).strip()
        if not filename or Path(filename).name != filename or filename in {".", ".."}:
            raise ValueError(f"unsafe generated filename: {filename!r}")
        if filename in files:
            raise ValueError(f"duplicate generated file block: {filename}")
        index += 1
        content_start = index
        while index < len(lines) and _FILE_END.fullmatch(lines[index]) is None:
            index += 1
        if index >= len(lines):
            raise ValueError(f"file block is missing ===END FILE===: {filename}")
        files[filename] = "".join(lines[content_start:index])
        index += 1
    if not files:
        raise ValueError("model response did not contain any file blocks")
    return files


def _csv_rows(
    content: str, expected_header: list[str], label: str, issues: list[str]
) -> list[dict[str, str]]:
    try:
        reader = csv.DictReader(io.StringIO(content, newline=""))
        if reader.fieldnames != expected_header:
            issues.append(
                f"{label} 表头不一致；必须为：{','.join(expected_header)}。"
            )
            return []
        rows = list(reader)
    except (csv.Error, UnicodeError) as exc:
        issues.append(f"{label} 无法解析：{exc}。")
        return []
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        issues.append(f"{label} 含有列数不一致的数据行。")
        return []
    return rows


def _front_matter(content: str, issues: list[str]) -> dict[str, str]:
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", content, re.DOTALL)
    if match is None:
        issues.append("带标注稿缺少合法的开头 YAML front matter。")
        return {}
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, raw_value = line.partition(":")
        if not separator:
            issues.append(f"带标注稿 front matter 行无法解析：{line!r}。")
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _timecode_seconds(value: str) -> int | None:
    parts = value.strip().split(":")
    if len(parts) not in {2, 3} or any(not part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if numbers[-1] > 59 or (len(numbers) == 3 and numbers[-2] > 59):
        return None
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


def _review_counts(content: str) -> tuple[int, int, set[str]]:
    section: str | None = None
    blocking = 0
    non_blocking = 0
    identifiers: set[str] = set()
    for line in content.splitlines():
        if line.strip() == "## 阻塞项":
            section = "blocking"
            continue
        if line.strip() == "## 非阻塞项":
            section = "non_blocking"
            continue
        match = re.match(r"^###\s+([A-Za-z0-9._-]+)：", line)
        if match is None:
            continue
        identifiers.add(match.group(1))
        if section == "blocking":
            blocking += 1
        elif section == "non_blocking":
            non_blocking += 1
    return blocking, non_blocking, identifiers


def _validate_editing_rows(
    rows: list[dict[str, str]], part_id: str, issues: list[str]
) -> dict[str, dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    asset_pattern = re.compile(
        rf"^{re.escape(part_id)}-(?:VID|IMG|WEB|GFX)-\d{{2,}}$"
    )
    video_kinds = {"LOCAL_VIDEO", "FILM_SOURCE", "WEB_VIDEO"}
    image_kinds = {"LOCAL_IMAGE", "WEB_IMAGE", "GFX"}
    expected_id_types = {
        "LOCAL_VIDEO": "VID",
        "FILM_SOURCE": "VID",
        "LOCAL_IMAGE": "IMG",
        "WEB_IMAGE": "WEB",
        "WEB_VIDEO": "WEB",
        "GFX": "GFX",
    }
    for line_number, row in enumerate(rows, start=2):
        asset_id = row["asset_id"].strip()
        label = asset_id or f"editing_index 第 {line_number} 行"
        if not asset_pattern.fullmatch(asset_id):
            issues.append(f"{label} 不符合 {part_id}-TYPE-NN 素材 ID 格式。")
        if asset_id in by_id:
            issues.append(f"剪辑索引包含重复素材 ID：{asset_id}。")
        elif asset_id:
            by_id[asset_id] = row
        source_kind = row["source_kind"].strip()
        if source_kind not in SOURCE_KINDS:
            issues.append(f"{label} 使用了非法 source_kind。")
        elif asset_id:
            id_type = asset_id.rsplit("-", 2)[-2]
            if id_type != expected_id_types[source_kind]:
                issues.append(f"{label} 的素材 ID 类型与 source_kind 不一致。")
        if row["classification"].strip() not in CLASSIFICATIONS:
            issues.append(f"{label} 使用了非法 classification。")
        audio_mode = row["audio_mode"].strip()
        if source_kind in video_kinds and audio_mode not in AUDIO_MODES:
            issues.append(f"{label} 的视频 audio_mode 缺失或非法。")
        if audio_mode == "ORIGINAL_FILM" and source_kind != "FILM_SOURCE":
            issues.append(f"{label} 只有 FILM_SOURCE 可以使用 ORIGINAL_FILM。")
        if audio_mode == "ORIGINAL_GUIDE" and not row["chinese_gist"].strip():
            issues.append(f"{label} 使用 ORIGINAL_GUIDE 时必须填写 chinese_gist。")
        if source_kind in image_kinds and audio_mode:
            issues.append(f"{label} 是图片或 GFX，audio_mode 必须留空。")
        if row["confidence"].strip() not in CONFIDENCE_LEVELS:
            issues.append(f"{label} 使用了非法 confidence。")
        if row["human_review"].strip() not in HUMAN_REVIEW_STATUSES:
            issues.append(f"{label} 使用了非法 human_review。")
        if row["license_status"].strip() not in LICENSE_STATUSES:
            issues.append(f"{label} 使用了非法 license_status。")

        source_in = row["source_in"].strip()
        source_out = row["source_out"].strip()
        if source_kind in video_kinds:
            start = _timecode_seconds(source_in)
            end = _timecode_seconds(source_out)
            if start is None or end is None or end <= start:
                issues.append(f"{label} 的视频 source_in/source_out 缺失或无效。")
        elif source_kind in image_kinds and (source_in or source_out):
            issues.append(f"{label} 是图片或 GFX，source_in/source_out 必须留空。")

        duration = row["duration_s"].strip()
        if duration:
            try:
                if float(duration) <= 0:
                    raise ValueError
            except ValueError:
                issues.append(f"{label} 的 duration_s 必须是正数或留空。")

        if source_kind in {"WEB_IMAGE", "WEB_VIDEO"}:
            source = row["source_file_or_url"].strip()
            if not re.match(r"https?://", source, re.IGNORECASE):
                issues.append(f"{label} 的网络素材缺少可追溯来源 URL。")
            if not row["attribution"].strip():
                issues.append(f"{label} 的网络素材缺少 attribution。")
        elif source_kind != "GFX" and not row["source_file_or_url"].strip():
            issues.append(f"{label} 缺少 source_file_or_url。")
    return by_id


def _validate_fact_rows(
    rows: list[dict[str, str]], issues: list[str]
) -> dict[str, list[dict[str, str]]]:
    by_id: dict[str, list[dict[str, str]]] = {}
    for line_number, row in enumerate(rows, start=2):
        fact_id = row["fact_id"].strip()
        label = fact_id or f"fact_sources 第 {line_number} 行"
        if not re.fullmatch(r"F-[A-Za-z0-9._-]+", fact_id):
            issues.append(f"{label} 使用了非法事实 ID；必须以 F- 开头。")
        elif fact_id:
            by_id.setdefault(fact_id, []).append(row)
        if row["source_type"].strip() not in FACT_SOURCE_TYPES:
            issues.append(f"{label} 使用了非法 source_type。")
        status = row["status"].strip()
        if status not in FACT_STATUSES:
            issues.append(f"{label} 使用了非法事实状态。")
        for field in ("claim", "source_title", "source_url_or_file", "source_locator"):
            if not row[field].strip():
                issues.append(f"{label} 缺少 {field}，事实无法追溯。")
        checked_at = row["checked_at"].strip()
        if checked_at:
            try:
                if date.fromisoformat(checked_at).isoformat() != checked_at:
                    raise ValueError
            except ValueError:
                issues.append(f"{label} 的 checked_at 必须是 YYYY-MM-DD 或留空。")
        elif status in READY_FACT_STATUSES:
            issues.append(f"{label} 已标为 {status}，但 checked_at 为空。")
    return by_id


def _manifest_count(manifest: dict[str, Any], key: str, expected: int, issues: list[str]) -> None:
    counts = manifest.get("counts")
    actual = counts.get(key) if isinstance(counts, dict) else None
    if actual != expected:
        issues.append(f"run_manifest counts.{key} 应为 {expected}，实际为 {actual!r}。")


def validate_generated_files(
    files: dict[str, str], context: dict[str, Any]
) -> tuple[dict[str, str], list[str]]:
    """Validate names, schemas, enums, references, counts, and readiness gates."""

    issues: list[str] = []
    warnings: list[str] = []
    project_root = context.get("project")
    project = project_root.get("project") if isinstance(project_root, dict) else None
    film = project_root.get("film") if isinstance(project_root, dict) else None
    if not isinstance(project, dict) or not isinstance(film, dict):
        raise ValueError("draft_context.json must contain project.project and project.film")
    project_id = _string_value(project.get("project_id"))
    part_id = _string_value(project.get("part_id"))
    if not project_id or not part_id:
        raise ValueError("draft context is missing project_id or part_id")

    names = _expected_names(project_id, part_id)
    expected = set(names.values())
    actual = set(files)
    for missing in sorted(expected - actual):
        issues.append(f"模型响应缺少文件：{missing}。")
    for unexpected in sorted(actual - expected):
        issues.append(f"模型响应包含协议外文件：{unexpected}。")
    if issues:
        raise ValueError("生成文件验收失败：\n- " + "\n- ".join(issues))

    annotated = files[names["annotated"]]
    clean = files[names["clean"]]
    review = files[names["review"]]
    front = _front_matter(annotated, issues)
    for key, expected_value in {
        "project_id": project_id,
        "part_id": part_id,
        "task_mode": "FILM_FIRST",
        "version": "1",
    }.items():
        if front.get(key) != expected_value:
            issues.append(
                f"带标注稿 front matter 的 {key} 必须为 {expected_value!r}。"
            )
    run_status = front.get("run_status", "")
    if run_status not in RUN_STATUSES:
        issues.append("带标注稿使用了非法 run_status。")
    for heading in ("## 0. 输入校验", "## 1A. 电影覆盖与角色—演员映射", "## 5. QA 结果"):
        if heading not in annotated:
            issues.append(f"带标注稿缺少章节：{heading}。")
    if run_status != "BLOCKED_INPUT" and "## 2. 带标注稿" not in annotated:
        issues.append("非 BLOCKED_INPUT 带标注稿缺少“## 2. 带标注稿”。")

    editing_rows = _csv_rows(
        files[names["editing"]], EDITING_INDEX_HEADER, "editing_index.csv", issues
    )
    fact_rows = _csv_rows(
        files[names["facts"]], FACT_SOURCES_HEADER, "fact_sources.csv", issues
    )
    assets = _validate_editing_rows(editing_rows, part_id, issues)
    facts = _validate_fact_rows(fact_rows, issues)

    fact_references = set(_FACT_REFERENCE.findall(annotated))
    asset_references = set(_ASSET_REFERENCE.findall(annotated))
    review_references = set(_REVIEW_REFERENCE.findall(annotated))
    blocking_reviews, non_blocking_reviews, review_ids = _review_counts(review)
    for heading in ("# 人工复核队列", "## 阻塞项", "## 非阻塞项"):
        if heading not in review:
            issues.append(f"review_queue.md 缺少章节：{heading}。")
    for fact_id in sorted(fact_references - facts.keys()):
        issues.append(f"带标注稿引用的事实 ID 不在来源表中：{fact_id}。")
    for asset_id in sorted(asset_references - assets.keys()):
        issues.append(f"带标注稿引用的素材 ID 不在剪辑索引中：{asset_id}。")
    for review_id in sorted(review_references - review_ids):
        issues.append(f"带标注稿引用的复核 ID 不在 review_queue 中：{review_id}。")

    try:
        manifest = json.loads(files[names["manifest"]])
    except json.JSONDecodeError as exc:
        issues.append(f"run_manifest.json 无法解析：{exc.msg}。")
        manifest = {}
    if not isinstance(manifest, dict):
        issues.append("run_manifest.json 顶层必须是 JSON object。")
        manifest = {}

    contract = context.get("generation_contract")
    prompt_version = contract.get("prompt_version") if isinstance(contract, dict) else None
    style_version = (
        contract.get("style_guide_version") if isinstance(contract, dict) else None
    )
    for key, expected_value in {
        "schema_version": "1.2",
        "project_id": project_id,
        "part_id": part_id,
        "run_status": run_status,
        "task_mode": "FILM_FIRST",
        "prompt_version": prompt_version,
        "style_guide_version": style_version,
    }.items():
        if manifest.get(key) != expected_value:
            issues.append(f"run_manifest.{key} 必须为 {expected_value!r}。")

    output_names = manifest.get("outputs")
    if not isinstance(output_names, list) or set(output_names) != expected:
        issues.append("run_manifest.outputs 必须准确列出六个标准输出文件名。")

    verified_fact_ids = {
        fact_id
        for fact_id, rows in facts.items()
        if any(row["status"].strip() in READY_FACT_STATUSES for row in rows)
    }
    local_assets = sum(
        row["source_kind"].strip() in {"LOCAL_VIDEO", "FILM_SOURCE", "LOCAL_IMAGE"}
        for row in editing_rows
    )
    web_assets = sum(
        row["source_kind"].strip() in {"WEB_IMAGE", "WEB_VIDEO"}
        for row in editing_rows
    )
    insights = context.get("human_insights")
    if not isinstance(insights, list):
        insights = []
    confirmed_insights = sum(
        isinstance(item, dict) and item.get("status") == "CONFIRMED" for item in insights
    )
    _manifest_count(manifest, "verified_facts", len(verified_fact_ids), issues)
    _manifest_count(manifest, "local_assets", local_assets, issues)
    _manifest_count(manifest, "web_assets", web_assets, issues)
    _manifest_count(manifest, "human_insights", len(insights), issues)
    _manifest_count(
        manifest, "confirmed_human_insights", confirmed_insights, issues
    )
    _manifest_count(manifest, "blocking_reviews", blocking_reviews, issues)
    _manifest_count(manifest, "non_blocking_reviews", non_blocking_reviews, issues)

    manifest_film = manifest.get("film")
    if not isinstance(manifest_film, dict):
        issues.append("run_manifest.film 必须是 object。")
        manifest_film = {}
    max_web_assets = film.get("max_web_assets")
    source = film.get("source")
    expected_film_values = {
        "title": film.get("film_title"),
        "original_title": film.get("film_original_title"),
        "release_year": str(film.get("film_release_year", "")),
        "source_duration": source.get("duration") if isinstance(source, dict) else "",
        "analysis_coverage": film.get("film_analysis_coverage", ""),
        "spoiler_policy": film.get("spoiler_policy", ""),
    }
    for key, expected_value in expected_film_values.items():
        if manifest_film.get(key) != expected_value:
            issues.append(
                f"run_manifest.film.{key} 必须与 draft_context.json 一致。"
            )
    if manifest_film.get("max_web_assets") != max_web_assets:
        issues.append("run_manifest.film.max_web_assets 与项目配置不一致。")
    if manifest_film.get("selected_web_assets") != web_assets:
        issues.append("run_manifest.film.selected_web_assets 与剪辑索引不一致。")
    if isinstance(max_web_assets, int) and web_assets > max_web_assets:
        issues.append(
            f"网络素材共 {web_assets} 个，超过项目上限 {max_web_assets} 个。"
        )

    quality_gates = manifest.get("quality_gates")
    if not isinstance(quality_gates, dict):
        issues.append("run_manifest.quality_gates 必须是 object。")
        quality_gates = {}
    required_gates = {
        "facts_traceable",
        "assets_traceable",
        "terminology_checked",
        "licenses_checked",
        "continuity_checked",
        "film_coverage_checked",
        "cast_mapping_checked",
        "clip_policy_checked",
        "human_insights_checked",
        "clean_script_allowed",
    }
    for gate in sorted(required_gates):
        if not isinstance(quality_gates.get(gate), bool):
            issues.append(f"run_manifest.quality_gates.{gate} 必须是布尔值。")

    duration = manifest.get("duration")
    if not isinstance(duration, dict):
        issues.append("run_manifest.duration 必须是 object。")
        duration = {}
    if duration.get("target") != project.get("target_duration", ""):
        issues.append("run_manifest.duration.target 与项目配置不一致。")

    if run_status == "READY_TO_RECORD":
        if clean.strip() == NOT_READY_CLEAN_SCRIPT:
            issues.append("READY_TO_RECORD 不能使用 NOT_READY 净稿。")
        if not clean.strip():
            issues.append("READY_TO_RECORD 的净稿不能为空。")
        for pattern, label in _INTERNAL_CLEAN_PATTERNS:
            if pattern.search(clean):
                issues.append(f"录制净稿仍含{label}。")
        if blocking_reviews:
            issues.append("READY_TO_RECORD 仍包含阻塞人工复核项。")
        for gate in sorted(required_gates):
            if quality_gates.get(gate) is not True:
                issues.append(f"READY_TO_RECORD 要求质量门 {gate}=true。")
        if duration.get("calibrated") is not True:
            issues.append("READY_TO_RECORD 要求 duration.calibrated=true。")
        for fact_id in sorted(fact_references):
            statuses = {row["status"].strip() for row in facts.get(fact_id, [])}
            if not statuses or not statuses.issubset(READY_FACT_STATUSES):
                issues.append(f"净稿相关事实 {fact_id} 尚未全部核验。")
        for asset_id in sorted(asset_references):
            row = assets.get(asset_id)
            if row is None:
                continue
            if row["human_review"].strip() != "approved":
                issues.append(f"正式稿引用的素材 {asset_id} 尚未人工批准。")
            if row["source_kind"].strip() in {"WEB_IMAGE", "WEB_VIDEO"} and row[
                "license_status"
            ].strip() != "VERIFIED":
                issues.append(f"正式稿引用的网络素材 {asset_id} 许可尚未确认。")
    else:
        if clean.strip() != NOT_READY_CLEAN_SCRIPT:
            issues.append(
                "非 READY_TO_RECORD 的 script_clean.md 必须严格使用 NOT_READY 文本。"
            )
        if quality_gates.get("clean_script_allowed") is True:
            issues.append("非 READY_TO_RECORD 不得设置 clean_script_allowed=true。")

    if not issues and not fact_references:
        warnings.append("带标注稿没有引用任何事实 ID。")
    if issues:
        raise ValueError("生成文件验收失败：\n- " + "\n- ".join(issues))
    return files, warnings


def _load_draft_package(draft_package: Path) -> tuple[str, dict[str, Any]]:
    package = draft_package.expanduser().resolve()
    if not package.is_dir():
        raise FileNotFoundError(package)
    readiness = _read_json_object(package / "draft_readiness.json", "draft readiness")
    if readiness.get("mode") != "PREPARE_ONLY":
        raise ValueError("draft package mode must be PREPARE_ONLY")
    if readiness.get("ready_for_model") is not True:
        blockers = readiness.get("blockers")
        detail = "; ".join(blockers) if isinstance(blockers, list) else "unknown blockers"
        raise ValueError(f"draft package is not ready for a model: {detail}")
    context = _read_json_object(package / "draft_context.json", "draft context")
    manifest = _read_json_object(
        package / "draft_package_manifest.json", "draft package manifest"
    )
    request_path = package / "draft_request.md"
    if not request_path.is_file():
        raise FileNotFoundError(request_path)
    request = request_path.read_text(encoding="utf-8")
    if not request.strip():
        raise ValueError("draft_request.md is empty")
    for source, label in ((readiness, "readiness"), (manifest, "package manifest")):
        for key in ("project_id", "part_id"):
            if source.get(key) != _context_project_value(context, key):
                raise ValueError(f"{label} {key} does not match draft_context.json")
    output_records = manifest.get("outputs")
    if not isinstance(output_records, list):
        raise ValueError("draft package manifest outputs must be a list")
    request_record = next(
        (
            item
            for item in output_records
            if isinstance(item, dict)
            and Path(_string_value(item.get("path"))).name == "draft_request.md"
        ),
        None,
    )
    request_hash = _sha256_bytes(request.encode("utf-8"))
    if request_record is None or request_record.get("sha256") != request_hash:
        raise ValueError("draft_request.md hash does not match draft package manifest")
    return request, context


def _context_project_value(context: dict[str, Any], key: str) -> Any:
    root = context.get("project")
    project = root.get("project") if isinstance(root, dict) else None
    return project.get(key) if isinstance(project, dict) else None


def generate_film_draft(
    draft_package: Path,
    output: Path,
    *,
    provider: TextGenerationProvider,
) -> dict[str, Any]:
    """Invoke a provider, validate all outputs, and atomically write six files."""

    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(output)
    request, context = _load_draft_package(draft_package)
    response = provider.generate(request)
    files = parse_six_file_response(response.text)
    files, warnings = validate_generated_files(files, context)

    project_id = _string_value(_context_project_value(context, "project_id"))
    part_id = _string_value(_context_project_value(context, "part_id"))
    names = _expected_names(project_id, part_id)
    manifest_name = names["manifest"]
    manifest = json.loads(files[manifest_name])
    receipt = {
        "provider": response.provider,
        "model": response.model,
        "response_id": response.response_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "request_sha256": _sha256_bytes(request.encode("utf-8")),
        "response_sha256": _sha256_bytes(response.text.encode("utf-8")),
        "store_requested": False if response.provider == "openai" else None,
        "usage": response.usage,
    }
    manifest["generation"] = receipt
    files[manifest_name] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}-", dir=str(output.parent))
    )
    try:
        for filename in names.values():
            destination = temporary / filename
            content = files[filename]
            if not content.endswith("\n"):
                content += "\n"
            destination.write_text(content, encoding="utf-8")
        if output.exists():
            raise FileExistsError(output)
        temporary.rename(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return {
        "mode": "GENERATED",
        "provider": response.provider,
        "model": response.model,
        "response_id": response.response_id or None,
        "run_status": manifest.get("run_status"),
        "output": str(output),
        "warnings": warnings,
        "files": [str(output / filename) for filename in names.values()],
    }
