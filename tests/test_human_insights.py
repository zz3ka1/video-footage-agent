from pathlib import Path

import pytest

from video_footage_agent.human_insights import (
    human_insights_template,
    require_valid_human_insights,
    validate_human_insights,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "film_first" / "human_insights_example.md"
SCENE_MAP = ROOT / "examples" / "film_first" / "scene_map_example.csv"


def test_empty_template_is_valid_but_warns(tmp_path: Path) -> None:
    content = human_insights_template("movie_demo", "FULL")
    assert "```text" in content
    assert "```json" not in content
    path = tmp_path / "human_insights.md"
    path.write_text(content, encoding="utf-8")
    result = require_valid_human_insights(path)
    assert result["valid"] is True
    assert result["cards"] == 0
    assert "no formal insight cards found" in result["warnings"]


def test_example_insights_and_scene_references_are_valid() -> None:
    result = require_valid_human_insights(EXAMPLE, scene_map=SCENE_MAP)
    assert result["valid"] is True
    assert result["cards"] == 2
    assert result["scene_references_checked"] is True
    assert result["presentation_mode_counts"] == {
        "INTERPRETATION": 1,
        "QUESTION": 1,
    }


def test_duplicate_insight_id_is_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.md"
    duplicate.write_text(
        EXAMPLE.read_text(encoding="utf-8").replace("HINS-002", "HINS-001"),
        encoding="utf-8",
    )
    result = validate_human_insights(duplicate, scene_map=SCENE_MAP)
    assert result["valid"] is False
    assert any("duplicate insight_id" in error for error in result["errors"])


def test_unknown_scene_reference_is_rejected(tmp_path: Path) -> None:
    unknown = tmp_path / "unknown.md"
    unknown.write_text(
        EXAMPLE.read_text(encoding="utf-8").replace("F001-W004", "F001-W999"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown scene references"):
        require_valid_human_insights(unknown, scene_map=SCENE_MAP)


def test_interpretation_type_cannot_be_presented_as_fact(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid-mode.md"
    invalid.write_text(
        EXAMPLE.read_text(encoding="utf-8").replace(
            '"presentation_mode": "INTERPRETATION"',
            '"presentation_mode": "FACT_CLAIM"',
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="SYMBOLISM requires"):
        require_valid_human_insights(invalid, scene_map=SCENE_MAP)


def test_fact_claim_is_valid_but_requires_verification(tmp_path: Path) -> None:
    claim = tmp_path / "claim.md"
    claim.write_text(
        """```json
{
  "insight_id": "HINS-003",
  "scope_type": "WHOLE_FILM",
  "scope_refs": ["FULL"],
  "insight_type": "FACT_CLAIM",
  "statement": "用户认为这可能是演员首次出演电影。",
  "evidence_refs": [],
  "presentation_mode": "FACT_CLAIM",
  "priority": "OPTIONAL",
  "requested_section": "",
  "avoid": ["未经查证不得写入净稿。"],
  "status": "DRAFT"
}
```
""",
        encoding="utf-8",
    )
    result = require_valid_human_insights(claim)
    assert result["valid"] is True
    assert any("independent verification" in item for item in result["warnings"])
