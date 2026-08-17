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

## 音频状态

后续稿件和剪辑索引建议使用以下值：

| 状态 | 含义 |
|---|---|
| `ORIGINAL_GUIDE` | 保留讲解或现场主要原声 |
| `AMBIENT_LOW` | 降低原声音量，只保留环境感 |
| `MUTE_VO` | 静音，改用旁白 |
| `MUTE_DELETE` | 不进入时间线 |

可直接复用[`examples/editing_index_template.csv`](examples/editing_index_template.csv)作为剪辑索引字段模板。

## 稿件生成规范

- [`docs/script-style-guide.zh-CN.md`](docs/script-style-guide.zh-CN.md)：面向人类的完整写稿规范，覆盖两种任务模式、事实核验、叙事风格、术语、素材标注、音频策略、人工复核和净稿红线。
- [`prompts/script-writer.zh-CN.md`](prompts/script-writer.zh-CN.md)：写稿 Agent 可直接使用的严格提示词，定义输入校验、运行状态、六文件输出协议和质量门。

当前 CLI 负责素材整理、技术粗筛和转写，还没有直接调用多模态大模型。上述提示词定义的是后续语义写稿层的行为契约，不代表现有代码已经能够自动完成最终稿件。

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
