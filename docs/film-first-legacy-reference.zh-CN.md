# 电影旧稿参考的使用边界

## 1. 参考样本状态

现有《绣春刀 1》旧稿只作为写作与制作流程的风格参考。对应电影原片已不可用，原 Google Docs comments 也没有保存在 Markdown 导出文件中，因此旧稿不是电影时间码、事实或素材授权的真值数据集。

仓库不保存旧电影、原始旧稿、失效来源链接或旧稿内嵌图片，只保存从中抽象出的非剧情文本风格配置。

## 2. 可以继承的内容

- 长篇电影解说按引言、剧情章节和结语组织。
- 主线通常按照电影剧情顺序推进。
- 可以在不打断主线时补充时代背景、演员信息和其他参演作品。
- 可以使用七言诗、现代类比和适量的梗，但这些表现手法不能替代事实核验。
- 电影原片承担主要画面，网络图片只解决明确的补充画面缺口。

机器可读版本见 [`examples/film_first/legacy_longform_style.json`](../examples/film_first/legacy_longform_style.json)。其中的数量是旧项目观察值，不是所有电影项目的强制默认值。

## 3. 不能继承的内容

- 旧稿中的素材编号及其对应画面。
- 已丢失的电影片段起止时间。
- 旧电影来源的版本、片头长度、帧率或总时长。
- 未经新来源重新核验的剧情、历史背景、演员作品和人物关系。
- 旧图片、视频、音乐和电影片段的权利状态。
- 当时没有明确决定的电影原声处理方式。

任何新电影项目都必须从实际提供的合法可访问原片重新建立场景地图和时间码。

## 4. 新项目初始化

使用 `film-init` 创建独立项目目录。命令不会复制或修改电影文件；如果提供原片，它会记录实际时长、画面参数、文件大小和 SHA-256 指纹，以固定本次分析使用的具体版本。

```bash
footage-agent film-init \
  --output artifacts/movie-demo \
  --project-id movie_demo \
  --title "示例片名" \
  --original-title "Example Film" \
  --release-year 2000 \
  --source /path/to/legally-accessible-film.mp4 \
  --spoiler-policy PARTIAL_SPOILERS \
  --clip-policy "由项目负责人确认的片段、原声和字幕规则" \
  --max-web-assets 6
```

示例中的数字不是全局默认值。每个项目必须单独确认 `max_web_assets` 和 `film_clip_policy`。

如果暂时没有原片或策略，可以省略相应参数。命令仍会生成模板，但状态保持 `BLOCKED_INPUT`，净稿只包含 `NOT_READY_TO_RECORD`。

初始化目录包含：

```text
{project_id}_{part_id}_project.json
{project_id}_{part_id}_human_insights.md
{project_id}_{part_id}_script_annotated.md
{project_id}_{part_id}_script_clean.md
{project_id}_{part_id}_scene_map.csv
{project_id}_{part_id}_editing_index.csv
{project_id}_{part_id}_fact_sources.csv
{project_id}_{part_id}_review_queue.md
{project_id}_{part_id}_run_manifest.json
```

输出目录必须不存在；`film-init` 不会覆盖已有项目。

## 5. 添加和校验人类解读

`human_insights.md` 用于记录用户对全片、人物、场景、时间范围或章节的深层理解。每条解读卡必须区分：

- 需要独立核验的事实线索 `FACT_CLAIM`。
- 必须按分析口吻表达的个人解读 `INTERPRETATION`。
- 只约束制作方式的 `EDITORIAL_DIRECTION`。
- 尚待结合后文或资料解决的 `QUESTION`。

用户可以直接用自然语言告诉 Agent，不必手写 JSON。Agent 应把原话整理成 `DRAFT` 解读卡供用户确认；只有用户确认后才改为 `CONFIRMED`。

填写后执行：

```bash
footage-agent film-insights-validate \
  artifacts/movie-demo/movie_demo_FULL_human_insights.md \
  --scene-map artifacts/movie-demo/movie_demo_FULL_scene_map.csv
```

如果场景地图尚未生成，可以省略 `--scene-map`。校验器会检查 JSON、重复编号、枚举、时间范围以及已存在场景地图中的引用，但不会判断某项电影解读是否正确。

虚构示例见 [`examples/film_first/human_insights_example.md`](../examples/film_first/human_insights_example.md)。
