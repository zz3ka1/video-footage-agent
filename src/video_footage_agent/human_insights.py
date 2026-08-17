"""Parse and validate human interpretation cards for film-first projects."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

SCOPE_TYPES = ("WHOLE_FILM", "CHARACTER", "SCENE", "TIME_RANGE", "CHAPTER")
INSIGHT_TYPES = (
    "THEME",
    "CHARACTER_ARC",
    "MOTIVATION",
    "SYMBOLISM",
    "FORESHADOWING",
    "TONE",
    "EDITORIAL_DIRECTION",
    "FACT_CLAIM",
    "QUESTION",
)
PRESENTATION_MODES = (
    "FACT_CLAIM",
    "INTERPRETATION",
    "EDITORIAL_DIRECTION",
    "QUESTION",
)
PRIORITIES = ("MUST_USE", "SHOULD_USE", "OPTIONAL", "MUST_AVOID")
INSIGHT_STATUSES = ("DRAFT", "CONFIRMED", "REJECTED")

REQUIRED_FIELDS = (
    "insight_id",
    "scope_type",
    "scope_refs",
    "insight_type",
    "statement",
    "evidence_refs",
    "presentation_mode",
    "priority",
    "requested_section",
    "avoid",
    "status",
)

_JSON_FENCE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
_INSIGHT_ID = re.compile(r"^HINS-[0-9]{3,}$")
_SCENE_REF = re.compile(r"^[A-Za-z0-9._-]+-W[0-9]+$")
_TIME_RANGE = re.compile(
    r"^(?P<start>[0-9]{2,}:[0-5][0-9]:[0-5][0-9])\s*[-–]\s*"
    r"(?P<end>[0-9]{2,}:[0-5][0-9]:[0-5][0-9])$"
)


def human_insights_template(project_id: str, part_id: str) -> str:
    """Return an empty, human-editable insights document."""

    return f"""# 人类深层解读

- 项目：`{project_id}`
- Part：`{part_id}`
- 状态：尚未添加解读卡

AI 的场景观察只记录画面和声音中发生了什么。本文件用于补充主题、人物弧线、象征、伏笔、编辑方向和待讨论问题。

## 使用规则

1. 每条正式解读使用一个 `json` 代码块；编号格式为 `HINS-001`。
2. `FACT_CLAIM` 只是事实线索，进入净稿前仍须查证。
3. `INTERPRETATION` 必须作为解读表达，不得写成导演或主创确认的事实。
4. `EDITORIAL_DIRECTION` 是制作要求，不是电影事实。
5. `DRAFT` 不作为强制写稿依据；确定采用后改为 `CONFIRMED`。
6. 场景地图尚未生成时可以先引用时间范围，之后再补场景 ID。

## 允许值

- `scope_type`：`WHOLE_FILM | CHARACTER | SCENE | TIME_RANGE | CHAPTER`
- `insight_type`：`THEME | CHARACTER_ARC | MOTIVATION | SYMBOLISM | FORESHADOWING`
  或 `TONE | EDITORIAL_DIRECTION | FACT_CLAIM | QUESTION`
- `presentation_mode`：`FACT_CLAIM | INTERPRETATION | EDITORIAL_DIRECTION | QUESTION`
- `priority`：`MUST_USE | SHOULD_USE | OPTIONAL | MUST_AVOID`
- `status`：`DRAFT | CONFIRMED | REJECTED`

## 解读卡模板

把下面的 `text` 改为 `json`，复制到文末并填写。模板本身不会被校验器当成正式解读。

```text
{{
  "insight_id": "HINS-001",
  "scope_type": "SCENE",
  "scope_refs": ["F001-W004", "F001-W006"],
  "insight_type": "SYMBOLISM",
  "statement": "这里填写用户对场景的深层理解。",
  "evidence_refs": ["F001-W004", "F001-W006"],
  "presentation_mode": "INTERPRETATION",
  "priority": "SHOULD_USE",
  "requested_section": "Part2",
  "avoid": ["不要声称这是导演亲自确认的寓意。"],
  "status": "DRAFT"
}}
```

## 正式解读卡

尚无。
"""


def _time_seconds(value: str) -> int:
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def _load_scene_ids(scene_map: Path) -> set[str]:
    with scene_map.expanduser().resolve().open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "window_id" not in reader.fieldnames:
            raise ValueError("scene map must contain a window_id column")
        return {row["window_id"].strip() for row in reader if row["window_id"].strip()}


def _validate_string_list(
    card: dict[str, Any], field: str, label: str, errors: list[str]
) -> list[str]:
    value = card.get(field)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        errors.append(f"{label}: {field} must be a list of non-empty strings")
        return []
    return [item.strip() for item in value]


def validate_human_insights(
    path: Path, *, scene_map: Path | None = None
) -> dict[str, Any]:
    """Validate JSON cards embedded in a Markdown insights document."""

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    content = resolved.read_text(encoding="utf-8")
    blocks = _JSON_FENCE.findall(content)
    errors: list[str] = []
    warnings: list[str] = []
    cards: list[dict[str, Any]] = []

    for index, block in enumerate(blocks, start=1):
        label = f"card {index}"
        try:
            card = json.loads(block)
        except json.JSONDecodeError as exc:
            errors.append(f"{label}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(card, dict):
            errors.append(f"{label}: JSON value must be an object")
            continue
        cards.append(card)

    scene_ids: set[str] | None = None
    if scene_map is not None:
        scene_ids = _load_scene_ids(scene_map)
        if not scene_ids and any(card.get("scope_type") == "SCENE" for card in cards):
            warnings.append("scene map has no rows; SCENE references were not checked")

    seen_ids: set[str] = set()
    for index, card in enumerate(cards, start=1):
        raw_id = card.get("insight_id")
        label = raw_id if isinstance(raw_id, str) and raw_id else f"card {index}"
        missing = [field for field in REQUIRED_FIELDS if field not in card]
        if missing:
            errors.append(f"{label}: missing fields: {', '.join(missing)}")
            continue
        unknown = sorted(set(card) - set(REQUIRED_FIELDS))
        if unknown:
            errors.append(f"{label}: unknown fields: {', '.join(unknown)}")

        if not isinstance(raw_id, str) or not _INSIGHT_ID.fullmatch(raw_id):
            errors.append(f"{label}: insight_id must match HINS-001")
        elif raw_id in seen_ids:
            errors.append(f"{label}: duplicate insight_id")
        else:
            seen_ids.add(raw_id)

        scope_type = card.get("scope_type")
        if scope_type not in SCOPE_TYPES:
            errors.append(f"{label}: invalid scope_type")
        scope_refs = _validate_string_list(card, "scope_refs", label, errors)
        if not scope_refs:
            errors.append(f"{label}: scope_refs must not be empty")
        evidence_refs = _validate_string_list(card, "evidence_refs", label, errors)
        _validate_string_list(card, "avoid", label, errors)

        insight_type = card.get("insight_type")
        if insight_type not in INSIGHT_TYPES:
            errors.append(f"{label}: invalid insight_type")
        presentation_mode = card.get("presentation_mode")
        if presentation_mode not in PRESENTATION_MODES:
            errors.append(f"{label}: invalid presentation_mode")
        if card.get("priority") not in PRIORITIES:
            errors.append(f"{label}: invalid priority")
        status = card.get("status")
        if status not in INSIGHT_STATUSES:
            errors.append(f"{label}: invalid status")

        statement = card.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            errors.append(f"{label}: statement must be a non-empty string")
        if not isinstance(card.get("requested_section"), str):
            errors.append(f"{label}: requested_section must be a string")

        expected_mode = {
            "THEME": "INTERPRETATION",
            "CHARACTER_ARC": "INTERPRETATION",
            "MOTIVATION": "INTERPRETATION",
            "SYMBOLISM": "INTERPRETATION",
            "FORESHADOWING": "INTERPRETATION",
            "FACT_CLAIM": "FACT_CLAIM",
            "EDITORIAL_DIRECTION": "EDITORIAL_DIRECTION",
            "QUESTION": "QUESTION",
        }.get(insight_type)
        if expected_mode is not None and presentation_mode != expected_mode:
            errors.append(
                f"{label}: {insight_type} requires presentation_mode={expected_mode}"
            )
        if insight_type == "TONE" and presentation_mode not in {
            "INTERPRETATION",
            "EDITORIAL_DIRECTION",
        }:
            errors.append(
                f"{label}: TONE requires presentation_mode=INTERPRETATION "
                "or EDITORIAL_DIRECTION"
            )

        if scope_type == "WHOLE_FILM" and scope_refs != ["FULL"]:
            errors.append(f'{label}: WHOLE_FILM requires scope_refs=["FULL"]')
        if scope_type == "SCENE" and scene_ids:
            unknown_refs = sorted(set(scope_refs) - scene_ids)
            if unknown_refs:
                errors.append(
                    f"{label}: unknown scene references: {', '.join(unknown_refs)}"
                )
        if scene_ids:
            evidence_scene_refs = {
                reference
                for reference in evidence_refs
                if _SCENE_REF.fullmatch(reference)
            }
            unknown_evidence_refs = sorted(evidence_scene_refs - scene_ids)
            if unknown_evidence_refs:
                errors.append(
                    f"{label}: unknown evidence scene references: "
                    f"{', '.join(unknown_evidence_refs)}"
                )
        if scope_type == "TIME_RANGE":
            for reference in scope_refs:
                match = _TIME_RANGE.fullmatch(reference)
                if match is None or _time_seconds(match["end"]) <= _time_seconds(
                    match["start"]
                ):
                    errors.append(
                        f"{label}: invalid time range {reference!r}; use HH:MM:SS-HH:MM:SS"
                    )

        if insight_type == "FACT_CLAIM":
            warnings.append(f"{label}: FACT_CLAIM requires independent verification")
        if presentation_mode in {"FACT_CLAIM", "INTERPRETATION"} and not evidence_refs:
            warnings.append(f"{label}: no evidence_refs supplied")
        if status == "DRAFT" and card.get("priority") in {"MUST_USE", "MUST_AVOID"}:
            warnings.append(
                f"{label}: draft insight cannot yet be enforced as mandatory"
            )

    if not cards and not errors:
        warnings.append("no formal insight cards found")

    counts = Counter(
        card.get("presentation_mode")
        for card in cards
        if card.get("presentation_mode") in PRESENTATION_MODES
    )
    return {
        "path": str(resolved),
        "valid": not errors,
        "cards": len(cards),
        "presentation_mode_counts": dict(sorted(counts.items())),
        "scene_references_checked": bool(scene_ids),
        "errors": errors,
        "warnings": warnings,
    }


def require_valid_human_insights(
    path: Path, *, scene_map: Path | None = None
) -> dict[str, Any]:
    """Return validation details or raise one readable error."""

    result = validate_human_insights(path, scene_map=scene_map)
    if result["errors"]:
        detail = "\n".join(f"- {error}" for error in result["errors"])
        raise ValueError(f"Human insights validation failed:\n{detail}")
    return result


def load_human_insight_cards(
    path: Path, *, scene_map: Path | None = None
) -> list[dict[str, Any]]:
    """Return validated cards without exposing them in CLI validation output."""

    resolved = path.expanduser().resolve()
    require_valid_human_insights(resolved, scene_map=scene_map)
    content = resolved.read_text(encoding="utf-8")
    return [json.loads(block) for block in _JSON_FENCE.findall(content)]
