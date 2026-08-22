import csv
import hashlib
import io
import json
import sys
import types
from pathlib import Path

import pytest

from video_footage_agent.film_generate import (
    DeepSeekChatProvider,
    ModelResponse,
    OpenAIResponsesProvider,
    build_light_editing_index,
    generate_film_draft,
    parse_six_file_response,
    validate_generated_files,
)
from video_footage_agent.film_project import EDITING_INDEX_HEADER, FACT_SOURCES_HEADER


def _csv_text(header: list[str], row: list[str]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerow(row)
    return stream.getvalue()


def _draft_package(tmp_path: Path) -> Path:
    package = tmp_path / "draft-package"
    package.mkdir()
    context = {
        "schema_version": "1.0",
        "generation_contract": {
            "prompt_version": "1.2",
            "style_guide_version": "1.2",
            "model_invoked": False,
        },
        "project": {
            "project": {
                "project_id": "movie_demo",
                "part_id": "FULL",
                "task_mode": "FILM_FIRST",
                "target_duration": "00:03:00",
                "speech_rate_profile": "teacher_v1",
            },
            "film": {
                "film_title": "示例电影",
                "film_original_title": "Example Film",
                "film_release_year": 2000,
                "source": {"duration": "00:10:00"},
                "film_analysis_coverage": "00:00:00-00:10:00",
                "spoiler_policy": "PARTIAL_SPOILERS",
                "max_web_assets": 2,
            },
        },
        "human_insights": [{"insight_id": "HINS-001", "status": "CONFIRMED"}],
    }
    request = "# deterministic test request\n"
    (package / "draft_readiness.json").write_text(
        json.dumps(
            {
                "mode": "PREPARE_ONLY",
                "project_id": "movie_demo",
                "part_id": "FULL",
                "ready_for_model": True,
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )
    (package / "draft_context.json").write_text(
        json.dumps(context, ensure_ascii=False), encoding="utf-8"
    )
    request_path = package / "draft_request.md"
    request_path.write_text(request, encoding="utf-8")
    (package / "draft_package_manifest.json").write_text(
        json.dumps(
            {
                "mode": "PREPARE_ONLY",
                "project_id": "movie_demo",
                "part_id": "FULL",
                "outputs": [
                    {
                        "path": str(request_path),
                        "sha256": hashlib.sha256(request.encode()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return package


def _valid_files() -> dict[str, str]:
    stem = "movie_demo_FULL"
    names = {
        "annotated": f"{stem}_script_annotated.md",
        "clean": f"{stem}_script_clean.md",
        "editing": f"{stem}_editing_index.csv",
        "facts": f"{stem}_fact_sources.csv",
        "review": f"{stem}_review_queue.md",
        "manifest": f"{stem}_run_manifest.json",
    }
    annotated = """---
project_id: "movie_demo"
part_id: "FULL"
run_status: "REVIEW_REQUIRED"
task_mode: "FILM_FIRST"
target_duration: "00:03:00"
speech_rate_profile: "teacher_v1"
version: 1
---

# 示例电影

## 0. 输入校验

- 当前状态：`REVIEW_REQUIRED`。

## 1. 结构与时长预算

待复核。

## 1A. 电影覆盖与角色—演员映射

已根据输入建立。

## 1B. 人类深层解读处理

已处理 HINS-001。

## 2. 带标注稿

[FULL-VID-01+ | 源 00:00:01–00:00:05 | MUTE_VO | 开场]
这是一句仍待最终人工复核的旁白。[F-FULL-01]
[FULL-VID-01-]
[REVIEW:H-FILM-01]

## 3. 术语表

无。

## 4. 待补素材摘要

无。

## 5. QA 结果

- [x] 事实均有来源
"""
    clean = "NOT_READY_TO_RECORD\n未生成录制净稿；请处理 review_queue.md 中的阻塞项。\n"
    editing = _csv_text(
        EDITING_INDEX_HEADER,
        [
            "FULL-VID-01",
            "FILM_SOURCE",
            "KEEP",
            "source.mp4",
            "00:00:01",
            "00:00:05",
            "4",
            "开场画面",
            "电影原声",
            "MUTE_VO",
            "",
            "开场",
            "配旁白",
            "high",
            "approved",
            "NOT_APPLICABLE",
            "",
        ],
    )
    facts = _csv_text(
        FACT_SOURCES_HEADER,
        [
            "F-FULL-01",
            "可核验事实",
            "FILM_SOURCE",
            "示例电影",
            "source.mp4",
            "00:00:01-00:00:05",
            "VERIFIED",
            "2026-08-17",
            "",
        ],
    )
    review = """# 人工复核队列

## 阻塞项

### H-FILM-01：确认表达

- 位置：开场
- 候选：保留／改写
- 证据：带标注稿
- 不确定性：老师尚未确认
- 问题：是否采用？
- 未确认时的默认处理：不生成净稿

## 非阻塞项

暂无。
"""
    manifest = {
        "schema_version": "1.2",
        "project_id": "movie_demo",
        "part_id": "FULL",
        "run_status": "REVIEW_REQUIRED",
        "task_mode": "FILM_FIRST",
        "prompt_version": "1.2",
        "style_guide_version": "1.2",
        "inputs": [],
        "outputs": list(names.values()),
        "counts": {
            "verified_facts": 1,
            "local_assets": 1,
            "web_assets": 0,
            "human_insights": 1,
            "confirmed_human_insights": 1,
            "blocking_reviews": 1,
            "non_blocking_reviews": 0,
        },
        "duration": {
            "target": "00:03:00",
            "estimated": "00:02:50",
            "calibrated": True,
        },
        "film": {
            "title": "示例电影",
            "original_title": "Example Film",
            "release_year": "2000",
            "source_duration": "00:10:00",
            "analysis_coverage": "00:00:00-00:10:00",
            "spoiler_policy": "PARTIAL_SPOILERS",
            "clip_policy_checked": True,
            "max_web_assets": 2,
            "selected_web_assets": 0,
        },
        "quality_gates": {
            "facts_traceable": True,
            "assets_traceable": True,
            "terminology_checked": True,
            "licenses_checked": True,
            "continuity_checked": True,
            "film_coverage_checked": True,
            "cast_mapping_checked": True,
            "clip_policy_checked": True,
            "human_insights_checked": True,
            "clean_script_allowed": False,
        },
    }
    return {
        names["annotated"]: annotated,
        names["clean"]: clean,
        names["editing"]: editing,
        names["facts"]: facts,
        names["review"]: review,
        names["manifest"]: json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    }


def _response_text(files: dict[str, str]) -> str:
    return "".join(
        f"===FILE: {name}===\n{content.rstrip()}\n===END FILE===\n"
        for name, content in files.items()
    )


def _ready_files() -> dict[str, str]:
    files = _valid_files()
    annotated_name = "movie_demo_FULL_script_annotated.md"
    clean_name = "movie_demo_FULL_script_clean.md"
    review_name = "movie_demo_FULL_review_queue.md"
    manifest_name = "movie_demo_FULL_run_manifest.json"
    files[annotated_name] = files[annotated_name].replace(
        'run_status: "REVIEW_REQUIRED"', 'run_status: "READY_TO_RECORD"'
    ).replace("- 当前状态：`REVIEW_REQUIRED`。", "- 当前状态：`READY_TO_RECORD`。")
    files[annotated_name] = files[annotated_name].replace(
        "[REVIEW:H-FILM-01]\n", ""
    )
    files[clean_name] = "# 示例电影\n\n这是一句已经通过质量门的可录制旁白。\n"
    files[review_name] = """# 人工复核队列

## 阻塞项

暂无。

## 非阻塞项

暂无。
"""
    manifest = json.loads(files[manifest_name])
    manifest["run_status"] = "READY_TO_RECORD"
    manifest["counts"]["blocking_reviews"] = 0
    manifest["quality_gates"]["clean_script_allowed"] = True
    files[manifest_name] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    return files


class _FakeProvider:
    def __init__(self, text: str) -> None:
        self.text = text
        self.request = ""

    def generate(self, request: str) -> ModelResponse:
        self.request = request
        return ModelResponse(
            text=self.text,
            provider="fake",
            model="fake-model",
            response_id="resp_test",
            usage={"input_tokens": 10, "output_tokens": 20},
        )


def test_build_light_editing_index_keeps_only_user_facing_fields() -> None:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(EDITING_INDEX_HEADER)
    rows = [
        {
            "asset_id": "FULL-VID-01",
            "source_kind": "LOCAL_VIDEO",
            "source_file_or_url": "/private/source.mp4",
            "source_in": "00:00:01",
            "source_out": "00:00:05",
            "duration_s": "4",
            "suggested_use": "开场",
        },
        {
            "asset_id": "FULL-WEB-01",
            "source_kind": "WEB_IMAGE",
            "source_file_or_url": "https://example.com/midway.jpg",
            "duration_s": "4.0",
            "suggested_use": "历史背景",
        },
    ]
    for values in rows:
        writer.writerow([values.get(field, "") for field in EDITING_INDEX_HEADER])

    light_rows = list(csv.reader(io.StringIO(build_light_editing_index(stream.getvalue()))))

    assert light_rows == [
        ["素材编号", "素材文件或网址", "使用范围", "插入位置"],
        ["FULL-VID-01", "source.mp4", "00:00:01–00:00:05", "开场"],
        ["FULL-WEB-01", "https://example.com/midway.jpg", "4秒", "历史背景"],
    ]


def test_generate_film_draft_writes_six_model_files_and_light_index(
    tmp_path: Path,
) -> None:
    package = _draft_package(tmp_path)
    provider = _FakeProvider(_response_text(_valid_files()))
    output = tmp_path / "generated"

    result = generate_film_draft(package, output, provider=provider)

    assert result["mode"] == "GENERATED"
    assert result["run_status"] == "REVIEW_REQUIRED"
    assert len(result["files"]) == 7
    assert provider.request == "# deterministic test request\n"
    assert len(list(output.iterdir())) == 7
    light_index = output / "movie_demo_FULL_editing_index_light.csv"
    assert list(csv.reader(light_index.open(encoding="utf-8"))) == [
        ["素材编号", "素材文件或网址", "使用范围", "插入位置"],
        ["FULL-VID-01", "source.mp4", "00:00:01–00:00:05", "开场"],
    ]
    manifest = json.loads(
        (output / "movie_demo_FULL_run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["generation"]["provider"] == "fake"
    assert manifest["generation"]["response_id"] == "resp_test"
    assert manifest["generation"]["response_sha256"]
    assert manifest["derived_outputs"] == ["movie_demo_FULL_editing_index_light.csv"]


def test_generate_film_draft_can_capture_raw_response_before_validation(
    tmp_path: Path,
) -> None:
    package = _draft_package(tmp_path)
    raw_response = tmp_path / "diagnostics" / "raw.txt"
    invalid = "Unexpected preamble\n" + _response_text(_valid_files())

    with pytest.raises(ValueError, match="outside file blocks"):
        generate_film_draft(
            package,
            tmp_path / "generated",
            provider=_FakeProvider(invalid),
            raw_response_path=raw_response,
        )

    assert raw_response.read_text(encoding="utf-8") == invalid
    assert not (tmp_path / "generated").exists()


def test_generate_film_draft_rejects_partial_response_without_writing(
    tmp_path: Path,
) -> None:
    package = _draft_package(tmp_path)
    files = _valid_files()
    files.pop("movie_demo_FULL_script_clean.md")
    output = tmp_path / "generated"

    with pytest.raises(ValueError, match="缺少文件"):
        generate_film_draft(
            package, output, provider=_FakeProvider(_response_text(files))
        )

    assert not output.exists()


def test_generate_film_draft_accepts_ready_package_that_passes_every_gate(
    tmp_path: Path,
) -> None:
    output = tmp_path / "ready"
    result = generate_film_draft(
        _draft_package(tmp_path),
        output,
        provider=_FakeProvider(_response_text(_ready_files())),
    )

    assert result["run_status"] == "READY_TO_RECORD"
    assert (output / "movie_demo_FULL_script_clean.md").read_text(
        encoding="utf-8"
    ).startswith("# 示例电影")


def test_validate_generated_files_accepts_ready_footage_without_film_gates(
    tmp_path: Path,
) -> None:
    package = _draft_package(tmp_path)
    context = json.loads(
        (package / "draft_context.json").read_text(encoding="utf-8")
    )
    context["project"]["project"]["task_mode"] = "FOOTAGE_FIRST"
    files = _ready_files()
    annotated_name = "movie_demo_FULL_script_annotated.md"
    editing_name = "movie_demo_FULL_editing_index.csv"
    facts_name = "movie_demo_FULL_fact_sources.csv"
    manifest_name = "movie_demo_FULL_run_manifest.json"
    files[annotated_name] = files[annotated_name].replace(
        'task_mode: "FILM_FIRST"', 'task_mode: "FOOTAGE_FIRST"'
    )
    files[editing_name] = files[editing_name].replace("FILM_SOURCE", "LOCAL_VIDEO")
    files[facts_name] = files[facts_name].replace("FILM_SOURCE", "LOCAL_VIDEO")
    manifest = json.loads(files[manifest_name])
    manifest["task_mode"] = "FOOTAGE_FIRST"
    manifest["film"] = {
        "title": "",
        "original_title": "",
        "release_year": "",
        "source_duration": "",
        "analysis_coverage": "",
        "spoiler_policy": "",
        "clip_policy_checked": False,
        "max_web_assets": None,
        "selected_web_assets": 0,
    }
    manifest["quality_gates"]["film_coverage_checked"] = False
    manifest["quality_gates"]["cast_mapping_checked"] = False
    manifest["quality_gates"]["clip_policy_checked"] = False
    files[manifest_name] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"

    validated, warnings = validate_generated_files(files, context)

    assert validated[annotated_name] == files[annotated_name]
    assert warnings == []


def test_generate_film_draft_rejects_internal_marker_in_ready_clean_script(
    tmp_path: Path,
) -> None:
    files = _ready_files()
    files["movie_demo_FULL_script_clean.md"] += "[F-FULL-01]\n"
    output = tmp_path / "invalid-ready"

    with pytest.raises(ValueError, match="录制净稿仍含事实编号"):
        generate_film_draft(
            _draft_package(tmp_path),
            output,
            provider=_FakeProvider(_response_text(files)),
        )

    assert not output.exists()


def test_parse_six_file_response_rejects_prose_and_path_traversal() -> None:
    with pytest.raises(ValueError, match="outside file blocks"):
        parse_six_file_response("Here are the files.\n")
    with pytest.raises(ValueError, match="unsafe generated filename"):
        parse_six_file_response(
            "===FILE: ../secret.md===\ncontent\n===END FILE===\n"
        )


def test_openai_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIResponsesProvider(model="explicit-model")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        provider.generate("request")


def test_openai_provider_uses_responses_api_without_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Usage:
        def model_dump(self) -> dict[str, int]:
            return {"input_tokens": 12, "output_tokens": 34}

    class Responses:
        def create(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return types.SimpleNamespace(
                output_text="model output",
                status="completed",
                id="resp_123",
                model="resolved-model",
                usage=Usage(),
            )

    class Client:
        def __init__(self) -> None:
            self.responses = Responses()

    module = types.ModuleType("openai")
    module.OpenAI = Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")

    response = OpenAIResponsesProvider(
        model="explicit-model",
        reasoning_effort="high",
        verbosity="high",
        max_output_tokens=5000,
    ).generate("request")

    assert captured == {
        "model": "explicit-model",
        "input": "request",
        "store": False,
        "reasoning": {"effort": "high"},
        "text": {"verbosity": "high"},
        "max_output_tokens": 5000,
    }
    assert response.model == "resolved-model"
    assert response.response_id == "resp_123"
    assert response.usage == {"input_tokens": 12, "output_tokens": 34}


def test_deepseek_provider_requires_its_own_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    provider = DeepSeekChatProvider(model="deepseek-v4-flash")
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        provider.generate("request")


def test_deepseek_provider_uses_official_openai_compatible_chat_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_arguments: dict[str, object] = {}
    request_arguments: dict[str, object] = {}

    class Usage:
        def model_dump(self) -> dict[str, int]:
            return {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50}

    class Completions:
        def create(self, **kwargs: object) -> object:
            request_arguments.update(kwargs)
            return types.SimpleNamespace(
                id="deepseek_resp_123",
                model="deepseek-v4-flash",
                choices=[
                    types.SimpleNamespace(
                        finish_reason="stop",
                        message=types.SimpleNamespace(content="six file response"),
                    )
                ],
                usage=Usage(),
            )

    class Client:
        def __init__(self, **kwargs: object) -> None:
            client_arguments.update(kwargs)
            self.chat = types.SimpleNamespace(completions=Completions())

    module = types.ModuleType("openai")
    module.OpenAI = Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key-not-real")

    response = DeepSeekChatProvider(
        model="deepseek-v4-flash",
        thinking="enabled",
        reasoning_effort="high",
        max_output_tokens=50000,
    ).generate("request")

    assert client_arguments == {
        "api_key": "deepseek-test-key-not-real",
        "base_url": "https://api.deepseek.com",
    }
    assert request_arguments == {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "request"}],
        "stream": False,
        "reasoning_effort": "high",
        "extra_body": {"thinking": {"type": "enabled"}},
        "max_tokens": 50000,
    }
    assert response.provider == "deepseek"
    assert response.model == "deepseek-v4-flash"
    assert response.response_id == "deepseek_resp_123"
    assert response.usage == {
        "prompt_tokens": 20,
        "completion_tokens": 30,
        "total_tokens": 50,
    }


def test_deepseek_provider_rejects_reasoning_effort_when_thinking_is_disabled() -> None:
    with pytest.raises(ValueError, match="cannot be set"):
        DeepSeekChatProvider(
            model="deepseek-v4-flash",
            thinking="disabled",
            reasoning_effort="high",
        )
