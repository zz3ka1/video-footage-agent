import csv
from pathlib import Path

from video_footage_agent.audio_modes import AUDIO_MODES

ROOT = Path(__file__).resolve().parents[1]
STYLE_GUIDE = ROOT / "docs" / "script-style-guide.zh-CN.md"
AGENT_PROMPT = ROOT / "prompts" / "script-writer.zh-CN.md"
EDITING_INDEX = ROOT / "examples" / "editing_index_template.csv"

EXPECTED_EDITING_INDEX_HEADER = [
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
TASK_MODES = ("TOPIC_FIRST", "FOOTAGE_FIRST", "FILM_FIRST")


def test_script_documents_exist_and_have_balanced_fences() -> None:
    for path in (STYLE_GUIDE, AGENT_PROMPT):
        content = path.read_text(encoding="utf-8")
        assert content.count("```") % 2 == 0
        assert "/Users/" not in content


def test_prompt_uses_the_code_audio_modes() -> None:
    prompt = AGENT_PROMPT.read_text(encoding="utf-8")
    guide = STYLE_GUIDE.read_text(encoding="utf-8")
    for mode in AUDIO_MODES:
        assert f"`{mode}`" in prompt
        assert f"`{mode}`" in guide


def test_task_modes_are_documented_in_both_contracts() -> None:
    prompt = AGENT_PROMPT.read_text(encoding="utf-8")
    guide = STYLE_GUIDE.read_text(encoding="utf-8")
    for mode in TASK_MODES:
        assert f"`{mode}`" in prompt
        assert f"`{mode}`" in guide


def test_film_mode_contract_is_complete() -> None:
    prompt = AGENT_PROMPT.read_text(encoding="utf-8")
    guide = STYLE_GUIDE.read_text(encoding="utf-8")
    required_terms = (
        "FILM_SOURCE",
        "REFERENCE_ONLY",
        "film_analysis_coverage",
        "spoiler_policy",
        "film_clip_policy",
        "max_web_assets",
        "cast_focus",
        "other_works_scope",
    )
    for term in required_terms:
        assert term in prompt
        assert term in guide


def test_editing_index_template_matches_prompt_contract() -> None:
    with EDITING_INDEX.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == EXPECTED_EDITING_INDEX_HEADER
    assert len(rows[1]) == len(rows[0])

    prompt = AGENT_PROMPT.read_text(encoding="utf-8")
    assert ",".join(EXPECTED_EDITING_INDEX_HEADER) in prompt
