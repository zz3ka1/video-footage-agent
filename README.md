# Video Footage Agent

面向长视频原始素材的“人机协作”整理工具。它不会假装自动理解并剪完几个小时的视频，而是先生成可核对的素材清单、技术粗筛、接触表、转写和统一文件目录，让AI或人类在此基础上写稿和建立剪辑索引。

English summary: a local-first, human-in-the-loop toolkit for inventorying, technically preflighting, transcribing, and safely consolidating long-form raw footage.

## 当前能力

- 递归发现MP4、MOV、MKV等视频并用FFprobe建立清单。
- 根据`part(\d+)`等正则识别编号，检测重复part并选择确定性的主文件。
- 为整个项目生成“每个文件三张代表画面”的总览接触表。
- 对单个长视频按低分辨率代理帧检测亮度、过曝、清晰度和画面变化。
- 按固定窗口输出技术预警，不把“手持运动”直接等同于废片。
- 调用本地Whisper生成带时间段的JSON转写。
- 用硬链接、符号链接或复制把分散素材安全集中到新目录。
- 为后续稿件和剪辑索引定义统一音频状态。
- 初始化不会覆盖文件的 `FILM_FIRST` 项目目录，并固定原片版本信息。
- 校验人类深层解读卡的格式、编号、枚举和场景引用。
- 在不调用在线模型的前提下，校验并打包电影稿件所需的全部结构化输入。
- 通过可替换的 OpenAI、DeepSeek 或离线 provider 生成稿件，并在原子写入前验收六个标准交付文件。

## 设计原则

1. **原素材只读**：视觉扫描和转写不修改视频。
2. **技术判断与内容判断分离**：`REVIEW`只是技术预警，不等于删除。
3. **默认拒绝覆盖**：整理目标目录已存在时直接停止。
4. **先预演再操作**：`consolidate --dry-run`可以查看计划而不创建文件。
5. **本地优先**：没有任何自动上传视频、转写或绝对路径的功能。
6. **人类最终确认**：专业词、专名、数字、授权和最终剪切点必须复核。

## 环境要求

- Python 3.10+
- FFmpeg与FFprobe
- 可选：OpenAI Whisper命令行工具，用于本地转写

macOS可以先安装FFmpeg：

```bash
brew install ffmpeg
```

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
footage-agent doctor
```

如果需要本地Whisper：

```bash
pip install -e ".[whisper]"
```

OpenAI 和 DeepSeek provider 都复用 Python `openai` SDK：

```bash
pip install -e ".[openai]"
```

## 快速开始

### 1. 扫描整个素材项目

```bash
footage-agent scan-project /path/to/raw-footage \
  --output artifacts/project-scan \
  --part-regex 'part(\d+)'
```

输出：

```text
artifacts/project-scan/
├── inventory.csv
├── inventory.json
└── overview/
    ├── overview_01.png
    └── overview_summary.json
```

`inventory.csv`含本机绝对路径，不应提交到公开仓库。

### 2. 单独生成素材清单

```bash
footage-agent inventory /path/to/raw-footage \
  --output artifacts/inventory.csv \
  --json artifacts/inventory.json \
  --extensions .mp4,.mov
```

### 3. 对一个长视频做技术粗筛

```bash
footage-agent triage /path/to/part18.MP4 \
  --output artifacts/part18 \
  --sample-fps 1 \
  --window-seconds 10 \
  --contact-every 5
```

主要输出：

- `technical_preflight.md`：技术预检报告。
- `frame_metrics.csv`：代理帧指标。
- `window_metrics.csv`：时间窗口指标。
- `contact_sheets/`：带时间码的接触表。
- `proxy_frames/`：低分辨率代理帧和缓存清单。

如果源文件或采样参数改变，工具会拒绝复用不匹配的代理缓存；明确需要重建时使用`--fresh`。

### 4. 本地转写

```bash
footage-agent transcribe /path/to/part18.MP4 \
  --output artifacts/part18/transcript \
  --model small \
  --language en
```

可用`--whisper-command /absolute/path/to/whisper`指定其他Whisper命令。自动转写适合定位主题和时间码，不应直接作为最终专业文稿。

### 5. 安全集中分散素材

先预演：

```bash
footage-agent consolidate artifacts/inventory.csv /path/to/all-parts \
  --mode hardlink \
  --name-template 'part{part:02d}{suffix}' \
  --dry-run
```

确认后去掉`--dry-run`：

```bash
footage-agent consolidate artifacts/inventory.csv /path/to/all-parts \
  --mode hardlink \
  --name-template 'part{part:02d}{suffix}'
```

三种模式：

- `hardlink`：同一文件系统内不复制视频数据，适合本机整理。
- `symlink`：只创建路径引用；部分剪辑软件或跨机器流程可能不适用。
- `copy`：生成独立副本，占用完整磁盘空间。

目标目录必须不存在，工具不会把文件混入已有目录，也不会覆盖同名文件。发生中途错误时，会回滚本次新建的文件。

### 6. 初始化电影解说项目

有合法可访问的电影原片时：

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

`film-init` 不会复制或修改原片。它记录原片实际时长、画面参数、文件大小和 SHA-256 指纹，并创建项目配置、人类解读模板、场景地图及六个标准交付文件。读取大型原片计算指纹可能需要一些时间。

没有原片或制作策略时可以先省略相应参数。生成目录会保持 `BLOCKED_INPUT`，不会产生看似可录制的净稿。输出目录必须不存在，命令不会覆盖已有项目。命令中的数量只是调用示例，不是全局默认值。

填写人类解读卡后运行：

```bash
footage-agent film-insights-validate \
  artifacts/movie-demo/movie_demo_FULL_human_insights.md \
  --scene-map artifacts/movie-demo/movie_demo_FULL_scene_map.csv
```

场景地图尚未生成时可以省略 `--scene-map`，此时只校验解读卡本身。示例见 [`examples/film_first/human_insights_example.md`](examples/film_first/human_insights_example.md)。

### 7. 准备稿件模型请求

`FILM_FIRST` 或 `FOOTAGE_FIRST` 项目的配置、场景地图和事实来源准备完成后运行：

```bash
footage-agent film-draft \
  artifacts/movie-demo/movie_demo_FULL_project.json \
  --output artifacts/movie-demo/draft-package
```

默认从项目配置所在目录寻找同项目的 `scene_map.csv` 和 `fact_sources.csv`；电影模式还会读取 `human_insights.md`。两种模式分别使用电影或实拍风格配置，并共享严格提示词和写稿规范。需要完整重新核对源文件指纹时增加 `--verify-source-hash`。

向外部模型发送私人素材的文字摘要时，建议生成脱敏请求包：

```bash
footage-agent film-draft \
  artifacts/footage-demo/footage_demo_PART30_project.json \
  --output artifacts/footage-demo/draft-package-redacted \
  --redact-local-paths
```

`--redact-local-paths` 只影响模型可见的 `draft_context.json` 和 `draft_request.md`：绝对路径缩短为文件名，源文件 SHA-256 改为 `REDACTED`。本地输入核验和草稿包清单仍保留完整路径及指纹，且不会发送给 provider。

本命令当前使用 `PREPARE_ONLY` 模式，不调用在线模型，也不生成伪装成成稿的旁白。输入完备时输出：

```text
draft_readiness.json
draft_context.json
draft_request.md
draft_package_manifest.json
```

`draft_request.md` 自包含严格提示词、写稿规范和本次结构化输入，可以交给后续模型调用层。存在阻塞项时只生成 `draft_readiness.json`，不会生成模型请求。

### 8. 调用模型并验收六个标准文件

#### OpenAI

先在环境中配置 API Key；不要把 Key 写入命令参数、项目文件或 Git：

```bash
export OPENAI_API_KEY="your-key"
```

然后显式选择账号可用的模型。仓库不默认替用户选择价格、速度或推理强度：

```bash
footage-agent film-generate \
  artifacts/movie-demo/draft-package \
  --output artifacts/movie-demo/generated-v1 \
  --provider openai \
  --model "your-model-id" \
  --reasoning-effort high \
  --verbosity high \
  --max-output-tokens 50000
```

`--reasoning-effort`、`--verbosity` 和 `--max-output-tokens` 都是可选项；`--model` 在 API provider 下必填。该调用只发送 `draft_request.md` 中的文本和结构化场景记录，不上传电影原片。OpenAI 请求固定使用 `store=false`；这不等同于账号已经启用 Zero Data Retention，数据控制仍以 API 账号配置为准。

#### DeepSeek

DeepSeek Key 使用独立环境变量。下面的输入方式不会显示 Key，也不会把 Key 写入 shell 历史；变量只在当前终端有效：

```bash
read -s -p "粘贴 DeepSeek API Key: " DEEPSEEK_API_KEY
export DEEPSEEK_API_KEY
echo
```

生成时使用已经确认的模型名：

```bash
footage-agent film-generate \
  artifacts/movie-demo/draft-package \
  --output artifacts/movie-demo/generated-v1 \
  --provider deepseek \
  --model deepseek-v4-flash \
  --thinking disabled \
  --max-output-tokens 20000 \
  --raw-response artifacts/movie-demo/deepseek-response.txt
```

DeepSeek provider 固定连接 `https://api.deepseek.com`，使用 OpenAI-compatible Chat Completions。`--thinking` 可以是 `enabled` 或 `disabled`；省略时采用 DeepSeek 的服务端默认值。思考开启时，`--reasoning-effort` 只接受 `low`、`high` 或 `max`；思考关闭时不要传 reasoning effort。严格六文件任务通常优先关闭思考，把输出预算留给最终文件；任何 `finish_reason=length` 响应都会被拒绝。`--verbosity` 只适用于 OpenAI provider。

`--raw-response` 会在跨文件验收前把完整模型响应保存到指定本地文件。即使模型只漏了分隔符或计数，仍可离线检查和修复，不必再次付费调用。该文件可能包含项目文字上下文，应继续保存在 Git 忽略的 `artifacts/` 中。

模型响应只有在以下检查全部通过后才会写入目标目录：

- 六个文件名称完整且没有额外文件或路径穿越。
- YAML front matter、JSON、CSV 表头与枚举合法。
- 带标注稿引用的事实 ID、素材 ID 和人工复核 ID 都能跨文件定位。
- 清单计数、网络素材上限、许可状态和人工复核状态一致。
- 非 `READY_TO_RECORD` 使用严格的 `NOT_READY` 净稿；录制净稿不含事实编号、素材 ID、网址或时间码。
- `READY_TO_RECORD` 的全部质量门、时长校准和阻塞项状态成立。

目标目录已存在时命令会停止。模型响应无效时也不会创建半成品目录。成功后，`run_manifest.json` 会增加 provider、实际返回模型、响应 ID、请求/响应 SHA-256 和 token usage（若 provider 返回）的生成记录。API Key 和 DeepSeek 的思考内容都不会写入交付文件。

六个标准文件验收通过后，工作流还会从完整剪辑索引自动派生 `{project_id}_{part_id}_editing_index_light.csv`。轻量版只有“素材编号、素材文件或网址、使用范围、插入位置”四列，不要求模型额外生成，也不改变六文件验收协议。

如果已经从其他工具取得了符合 `===FILE: ...===` 协议的完整响应，可以只运行同一套离线验收，不发起 API 请求：

```bash
footage-agent film-generate \
  artifacts/movie-demo/draft-package \
  --output artifacts/movie-demo/generated-v1 \
  --provider response-file \
  --response-file /path/to/model-response.txt
```

## 音频状态

后续稿件和剪辑索引建议使用以下值：

| 状态 | 含义 |
|---|---|
| `ORIGINAL_GUIDE` | 保留讲解或现场主要原声 |
| `ORIGINAL_FILM` | 保留电影片段的同步对白、音乐和环境声；须遵守项目片段使用规则 |
| `AMBIENT_LOW` | 降低原声音量，只保留环境感 |
| `MUTE_VO` | 静音，改用旁白 |
| `MUTE_DELETE` | 不进入时间线 |

可直接复用[`examples/editing_index_template.csv`](examples/editing_index_template.csv)作为剪辑索引字段模板。

## 稿件生成规范

- [`docs/script-style-guide.zh-CN.md`](docs/script-style-guide.zh-CN.md)：面向人类的完整写稿规范，覆盖选题优先、实拍素材优先和电影原片优先三种任务模式，以及事实核验、叙事风格、术语、素材标注、音频策略、人工复核和净稿红线。
- [`prompts/script-writer.zh-CN.md`](prompts/script-writer.zh-CN.md)：写稿 Agent 可直接使用的严格提示词，定义输入校验、运行状态、六文件输出协议和质量门。
- [`docs/film-first-legacy-reference.zh-CN.md`](docs/film-first-legacy-reference.zh-CN.md)：说明旧电影稿可以继承的风格，以及不得复用的时间码、事实和授权信息。
- [`examples/film_first/legacy_longform_style.json`](examples/film_first/legacy_longform_style.json)：从旧稿提炼的机器可读风格配置，只用于新项目的写作倾向。
- [`examples/film_first/human_insights_example.md`](examples/film_first/human_insights_example.md)：虚构场景的人类深层解读卡示例。

当前 CLI 可以把已经完成场景地图、事实表和人类解读的请求包交给 OpenAI 或 DeepSeek 文本模型生成稿件，但不会把电影文件直接上传给模型，也不会把模型结果自动视为可录制净稿。最终状态仍由六文件质量门和人工复核共同决定。

## 工具边界

技术粗筛无法独立判断：

- 一个普通画面是否包含非常重要的讲解。
- 长手持镜头中是否藏有两三秒可抢救素材。
- 专业名词、人物、飞机或设备的准确身份。
- 网络素材是否满足项目的授权要求。
- 某段内容是否符合频道风格或发布标准。

推荐工作流见[`docs/agent-workflow.zh-CN.md`](docs/agent-workflow.zh-CN.md)。

## 开发与测试

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

测试包含一个由FFmpeg临时生成的短视频，不需要下载示例媒体。GitHub Actions同样不会访问用户素材。

## 隐私

- `.gitignore`默认排除常见视频、音频、代理帧、转写和输出目录。
- 本地`inventory.csv/json`可能包含绝对路径，默认排除。
- 上传代码前仍应运行`git status`，确认没有个人素材、转写、密钥或本机路径。
