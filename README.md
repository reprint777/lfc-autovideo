# lfc-autovideo

[English](README.en.md) | 简体中文

一个面向授权内容的本地 Python 命令行工具：输入 YouTube 链接或本地视频，使用
`faster-whisper` 在本机生成英文字幕；你在 CSV 中手动填写中文翻译后，再用 FFmpeg
生成带中英双语字幕的成片。

本项目不调用任何云端付费 API，也不会自动翻译。第一次转写时需要联网下载所选
Whisper 模型；模型下载完成后，语音识别推理在本机执行。YouTube 输入仍需要联网下载
视频，本地视频输入则可在模型已经缓存后离线处理。

> **使用范围：** 请只处理你自己创作、获得权利人明确授权，或许可条款明确允许下载、
> 翻译和再发布的内容。添加字幕、署名或原链接并不自动取得转载权；比赛转播画面、音乐、
> 图片等第三方素材也可能有独立权利人。本工具不会绕过 DRM、会员、私密或地区访问限制。

## 工作流程

1. `autovideo doctor` 检查 Python、FFmpeg 和运行依赖。
2. `autovideo prepare` 接收 YouTube URL 或本地视频，准备素材并在本机转写英文。
3. 检查 `transcription.review.csv`，再打开 `translation.csv` 校正英文并填写中文。
4. `autovideo render` 生成中英双语字幕及压制字幕的 MP4。
5. 人工检查字幕、授权和投稿信息后，手动上传 Bilibili。

`translation.csv` 使用 UTF-8 BOM 编码，Excel、Numbers 和常见文本编辑器均可打开。固定列为：

```text
index,start,end,english,chinese
```

请不要修改 `index`、`start`、`end` 或表头，也不要增删行；`english` 可用于修正人名、
拼写和标点，`chinese` 用于填写对应中文。CSV 文本内如有逗号，应让表格软件自动保留
引号转义。

## macOS Apple Silicon 安装

以下步骤适用于 Apple Silicon arm64 Mac。推荐 Python 3.12；项目最低要求为
Python 3.10。

### 1. 安装 Python 和 FFmpeg

如果已安装 Homebrew：

```bash
brew install python@3.12 ffmpeg deno
```

如果没有 Homebrew，可先从 [brew.sh](https://brew.sh/) 安装，或使用
[python.org](https://www.python.org/downloads/macos/) 的 Python 安装包。无论使用哪种方式，
都需要单独安装可在终端中调用的 FFmpeg。

确认环境：

```bash
/opt/homebrew/bin/python3.12 --version
ffmpeg -version
ffprobe -version
deno --version
```

若 Homebrew 提示了不同的 Python 路径，以提示为准。Intel Mac 的 Homebrew 通常位于
`/usr/local`，可直接使用 `python3.12`。

### 2. 创建虚拟环境并安装项目

在本仓库根目录执行：

```bash
cd /path/to/lfc-autovideo
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

以后每次打开新终端，先进入仓库并激活环境：

```bash
cd /path/to/lfc-autovideo
source .venv/bin/activate
```

### 3. 创建本地配置

```bash
autovideo init-config config.json
```

默认 `medium.en` 模型优先保证英文人名和足球术语的识别质量。可在 `config.json` 中改成
`small.en`（更快、质量较低）或其他兼容模型。首次使用新模型时会从
Hugging Face 下载模型并写入用户缓存；这不是云端转写，下载结束后的推理仍全部在本地。

## 使用

### 环境诊断

```bash
autovideo doctor
```

诊断通过后再开始长视频任务，尤其要确认 `ffmpeg` 和 `ffprobe` 均可用。
YouTube 输入还需要 Deno 2.3+ 和随 `yt-dlp[default]` 安装的 EJS 组件；它们只在本机
执行 YouTube 的 JavaScript 校验，不是付费云服务。具体依赖要求见
[yt-dlp 官方 EJS 指南](https://github.com/yt-dlp/yt-dlp/wiki/EJS)。

### 准备 YouTube 视频

```bash
autovideo --config config.json prepare --confirm-rights "https://www.youtube.com/watch?v=VIDEO_ID"
```

URL 请加引号，避免其中的 `&` 被 shell 解释。工具会使用 `yt-dlp` 下载可处理的视频，
然后提取音频并在本机转写。请勿用它规避网站访问控制或下载未获授权的内容。
`--confirm-rights` 表示你确认自己有权下载、翻译并重新发布该输入；未确认时工具会拒绝
创建任务。它不是自动版权检查，也不会替你取得许可。

### 准备本地视频

```bash
autovideo --config config.json prepare --confirm-rights "/absolute/path/to/video.mp4"
```

文件路径含空格时必须加引号。建议使用绝对路径；常见的 MP4、MOV、MKV 和 WebM 输入由
FFmpeg 负责读取。

若只想针对本次任务覆盖转写配置，可给 `prepare` 传入 `--model`、`--device`、
`--compute-type`、`--hotwords`、`--no-vad` 或 `--jobs-dir`。例如：

```bash
autovideo --config config.json prepare --confirm-rights --model medium.en \
  --device cpu --compute-type int8 \
  --hotwords "Szoboszlai, Wirtz, Liverpool, Anfield" "/absolute/path/to/video.mp4"
```

`prepare` 完成时会打印任务 ID 和任务目录。接着编辑：

```text
jobs/<任务ID>/subtitles/translation.csv
```

示例（实际 CSV 应由工具生成，不要手动新建）：

```csv
index,start,end,english,chinese
1,"00:00:00,000","00:00:03,240","Welcome back to the channel.","欢迎回到我们的频道。"
2,"00:00:03,240","00:00:06,800","Liverpool were excellent today.","利物浦今天表现非常出色。"
```

同时检查 `transcription.review.csv`：`check_content` 表示字幕空档中仍有明显声音，应回听；
`likely_silence` 通常是真实停顿。报告只是校对提示，不会自动捏造或插入文字。

### 复用已有音频重新转写

旧任务或存在漏识别的任务无需重新下载视频：

```bash
autovideo retranscribe --model medium.en \
  --hotwords "Szoboszlai, Wirtz, Liverpool, Anfield" "jobs/<任务ID>"
```

如果空档报告确认有声内容仍被跳过，可关闭 VAD 再试：

```bash
autovideo retranscribe --no-vad "jobs/<任务ID>"
```

每次重新转写前，现有字幕会自动复制到 `subtitles/backups/<时间>/`，不会直接丢失已完成的
英文校对或中文翻译。关闭 VAD 可能带来静音段幻觉，因此只建议用于漏识别任务并人工复核。

### 生成双语成片

翻译完并保存 CSV 后执行：

```bash
autovideo --config config.json render "jobs/<任务ID>"
```

渲染会生成中文在上、英文在下的双语字幕，并生成便于继续编辑的字幕文件和压制字幕的
MP4。上传前请从头到尾检查人名、比分、时间轴、字幕断句、音画同步和授权署名。
默认情况下，任何空白 `chinese` 单元格都会阻止渲染。仅在你明确接受部分字幕没有中文时，
才使用 `render --allow-missing-chinese "jobs/<任务ID>"`。

随时可以查看某个任务的状态和已生成路径：

```bash
autovideo status "jobs/<任务ID>"
```

## 任务与输出目录

默认所有工作文件位于 `jobs/`。每个输入拥有独立任务目录，典型结构如下：

```text
jobs/
└── <任务ID>/
    ├── source/
    │   ├── video.<扩展名>       # 复制的本地文件，或下载的视频
    │   └── info.json           # 输入来源元数据
    ├── audio/
    │   └── speech.wav          # 供转写使用的无损 PCM 音频
    ├── job.json                # 任务状态、配置和相对路径记录
    ├── subtitles/
    │   ├── transcript.en.srt       # 英文转写字幕
    │   ├── translation.csv         # 校正 english 并填写 chinese
    │   ├── transcription.review.csv # 非静音字幕空档检查
    │   ├── backups/                # 重新转写前的字幕备份
    │   ├── subtitle.bilingual.srt  # 可编辑双语字幕
    │   └── subtitle.bilingual.ass  # 用于排版/压制的双语字幕
    └── output/
        └── final.bilingual.mp4 # 双语字幕成片
```

`jobs/` 已加入 `.gitignore`，因为其中可能包含受版权保护的视频、未公开的授权材料和体积很大
的输出。不要用 `git add -f jobs/` 将它们提交到公开仓库。删除任务目录会删除该任务的源素材、
人工翻译和成片，请先自行备份。

若通过 `--jobs-dir` 把任务写到仓库内的其他目录，请自行把该目录加入 `.gitignore`；任务
记录包含原始 URL 或本地绝对路径，不应提交到公开仓库。

## 配置说明

`config.example.json` 是可提交的示例；`config.json` 是你的本地配置并已被 Git 忽略。

- `jobs_dir`：任务根目录。
- `download.max_height`：YouTube 下载的最高画面高度。
- `transcription.model`：本地 Whisper 模型名。
- `transcription.device`：默认 `cpu`，兼容 Apple Silicon 的本地 CPU 推理。
- `transcription.compute_type`：默认 `int8`，降低内存占用。
- `transcription.language`：固定英文识别时使用 `en`。
- `transcription.beam_size`：增大可能改善结果，但会增加耗时。
- `transcription.condition_on_previous_text`：默认关闭，减少重复循环和时间戳漂移。
- `transcription.vad_filter`：过滤长静音片段；有漏识别时可用 `--no-vad` 重试。
- `transcription.vad_threshold` / `vad_min_silence_duration_ms` /
  `vad_speech_pad_ms`：控制 VAD 灵敏度与语音边缘保留范围。
- `transcription.hotwords`：每期可更新的球员、教练和俱乐部英文专名。
- `transcription.initial_prompt`：帮助识别利物浦相关专名的英文上下文提示。
- `transcription.max_chars` / `max_duration`：字幕拆分的最大字符数和时长。
- `transcription.review_*`：空档报告的最短空档和静音检测参数。
- `subtitles`：双语字幕字体、两种语言的字号、边距、描边和阴影。
- `render`：FFmpeg 视频编码器、预设、CRF 质量和音频码率。CRF 越低通常质量越高、
  文件越大。

中文字体需要已安装在系统中。若英文可显示但中文出现方框，请在配置中把
`subtitles.font_name` 改为本机已有的中文字体，例如 `PingFang SC`。

## 常见故障

### `autovideo: command not found`

确认当前终端已经执行 `source .venv/bin/activate`，然后重新运行
`python -m pip install -e .`。也可用 `python -m autovideo.cli ...` 辅助定位入口问题。

### 找不到 `ffmpeg` 或 `ffprobe`

执行 `brew install ffmpeg`，然后重开终端。Apple Silicon Homebrew 的命令通常位于
`/opt/homebrew/bin`；必要时把它加入 `PATH`，再运行 `autovideo doctor`。

### 第一次转写很慢或停在下载

首次使用某个模型必须下载模型文件，所需空间和时间取决于模型及网络。不要在下载过程中
强制关机。下载完成后再次运行同一模型会读取本地缓存。若磁盘空间不足，先清理空间或换用
`tiny.en` / `small.en`。

### Apple Silicon 上转写报设备或计算类型错误

先使用示例配置中的 `device: "cpu"` 和 `compute_type: "int8"`，并确认虚拟环境
使用 arm64 Python：

```bash
python -c "import platform; print(platform.machine())"
```

预期输出为 `arm64`。如果输出 `x86_64`，说明终端或 Python 正通过 Rosetta 运行，建议重建
arm64 虚拟环境。

### YouTube 下载失败

先升级带 EJS 组件的 `yt-dlp`，并确认 Deno 可用：

```bash
python -m pip install --upgrade "yt-dlp[default]"
deno --version
autovideo doctor
```

如果视频需要登录、会员资格、DRM、地区绕过或其他访问控制，请停止处理并改用权利人直接
提供的授权文件。本项目不提供绕过方式。普通公开视频仍失败时，可用 `yt-dlp --verbose URL`
查看上游错误，或改用已获得授权的本地文件。

### CSV 保存后无法读取或中文乱码

保留原有表头和行数，并以 UTF-8（推荐 UTF-8 BOM）保存。不要合并单元格；不要让表格软件
把时间戳转换成日期或数值。可先复制一份 CSV 备份，再修正格式。

### 渲染时提示缺少中文翻译

检查每一行 `chinese` 是否都已填写，特别留意表格末尾和只有语气词的短行。不要删除该行。
如果确实要让部分字幕只显示英文，请保持该格为空，并使用 `--allow-missing-chinese` 渲染。

### 明明有说话但字幕跳过一段

先查看 `transcription.review.csv` 中的 `check_content` 行并回听对应时间。确认漏识别后运行
`autovideo retranscribe --no-vad "jobs/<任务ID>"`；如果只有专名错误，优先保留 VAD 并用
`--hotwords` 加入当期球员姓名。重新转写后仍须人工从头检查，尤其是背景音乐和多人重叠语音。

### 字幕样式正确但画面质量或文件体积不合适

在 `config.json` 中调整 `render.crf`。常用范围约为 18–28：更低通常更清晰、文件更大。
长视频渲染耗时较长属正常现象，建议先保留源文件和 `translation.csv`，确认最终成片无误后
再清理中间文件。

## 隐私与成本

- 无翻译 API、无语音识别 API、无订阅费用或按量调用费用。
- 转写音频不会由本项目上传到付费云服务。
- 模型首次下载和 YouTube 素材下载会产生普通网络流量。
- 本地推理和视频编码会占用 CPU/GPU、内存、磁盘和电力。

## License

[MIT](LICENSE)
