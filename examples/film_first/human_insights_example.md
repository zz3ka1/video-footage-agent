# 人类深层解读示例

本文件使用虚构电影片段，不对应任何真实影片。配套场景见 `scene_map_example.csv`。

```json
{
  "insight_id": "HINS-001",
  "scope_type": "SCENE",
  "scope_refs": ["F001-W004", "F001-W006"],
  "insight_type": "SYMBOLISM",
  "statement": "钥匙不只是推动剧情的道具，也代表男主第一次主动进入一个不受自己控制的世界。",
  "evidence_refs": ["F001-W004", "F001-W006"],
  "presentation_mode": "INTERPRETATION",
  "priority": "MUST_USE",
  "requested_section": "Part2",
  "avoid": ["不要声称这是导演亲自确认的寓意。"],
  "status": "CONFIRMED"
}
```

```json
{
  "insight_id": "HINS-002",
  "scope_type": "SCENE",
  "scope_refs": ["F001-W010"],
  "insight_type": "QUESTION",
  "statement": "门后的女声是否与车站里的陌生女子属于同一人物？",
  "evidence_refs": ["F001-W003", "F001-W010"],
  "presentation_mode": "QUESTION",
  "priority": "SHOULD_USE",
  "requested_section": "Part2",
  "avoid": ["未结合后文确认前，不要把两人写成同一人物。"],
  "status": "DRAFT"
}
```
