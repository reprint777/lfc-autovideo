# lfc-autovideo

English | [简体中文](README.md)

A local-first Python CLI for authorized content. Give it a YouTube URL or a
local video and it uses `faster-whisper` to generate English subtitles on your
machine. After you manually add Chinese translations to a CSV file, FFmpeg
produces a video with burned-in Chinese and English subtitles.

This project does not call a paid cloud API and does not translate text
automatically. The selected Whisper model is downloaded the first time you use
it; once cached, speech recognition runs locally. YouTube inputs still require
an internet connection to download the source video. Local inputs can be
processed offline after the model has been cached.

> **Authorized use only:** Process content that you created, received explicit
> permission to use, or that is covered by a license allowing download,
> translation, and republication. Adding subtitles, attribution, or a source
> link does not grant republication rights. Broadcast footage, music, and
> images may have separate rightsholders. This tool does not bypass DRM,
> memberships, private access, or geographic restrictions.

## Workflow

1. Run `autovideo doctor` to check Python, FFmpeg, and runtime dependencies.
2. Run `autovideo prepare` with a YouTube URL or local video. The command
   prepares the media and transcribes the English speech locally.
3. Review `transcription.review.csv`, then correct English and add Chinese in
   `translation.csv`.
4. Run `autovideo render` to create bilingual subtitle files and a burned-in
   MP4.
5. Review the subtitles, rights, attribution, and upload details before
   manually publishing the video to Bilibili.

`translation.csv` is encoded as UTF-8 with a BOM so it opens cleanly in Excel,
Numbers, and common text editors. Its columns are fixed:

```text
index,start,end,english,chinese
```

Do not modify the header or the `index`, `start`, or `end` columns. Do not add,
delete, or reorder rows. You may correct names, spelling, and punctuation in
`english`, and enter the translation in `chinese`. Let your spreadsheet
application preserve CSV quoting around text containing commas.

## macOS Apple Silicon installation

These instructions target Apple Silicon arm64 Macs. Python 3.12 is recommended;
Python 3.10 is the minimum supported version.

### 1. Install Python, FFmpeg, and Deno

With Homebrew installed:

```bash
brew install python@3.12 ffmpeg deno
```

If you do not have Homebrew, install it from [brew.sh](https://brew.sh/) or use
the macOS installer from [python.org](https://www.python.org/downloads/macos/).
FFmpeg must still be installed separately and available from your terminal.

Check the tools:

```bash
/opt/homebrew/bin/python3.12 --version
ffmpeg -version
ffprobe -version
deno --version
```

Use the Python path reported by Homebrew if it differs. Homebrew is commonly
installed under `/usr/local` on Intel Macs, where `python3.12` may be available
directly.

### 2. Create a virtual environment and install the project

Run these commands from the repository root:

```bash
cd /path/to/lfc-autovideo
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

When opening a new terminal later, enter the repository and reactivate the
environment:

```bash
cd /path/to/lfc-autovideo
source .venv/bin/activate
```

### 3. Create a local configuration

```bash
autovideo init-config config.json
```

The default `medium.en` model prioritizes names and football terminology. In
`config.json`, you can switch to `small.en` for faster, lower-quality results.
A new model is downloaded from Hugging Face on first use and stored
in your user cache. The download is not cloud transcription; inference remains
local after the model is available.

## Usage

### Check the environment

```bash
autovideo doctor
```

Run this before starting a long video and make sure `ffmpeg` and `ffprobe` are
available. YouTube inputs also require Deno 2.3+ and the EJS component installed
with `yt-dlp[default]`. These components execute YouTube's JavaScript challenges
locally and are not paid cloud services. See the
[official yt-dlp EJS guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS) for the
current requirements.

### Prepare a YouTube video

```bash
autovideo --config config.json prepare --confirm-rights "https://www.youtube.com/watch?v=VIDEO_ID"
```

Quote the URL so characters such as `&` are not interpreted by your shell. The
tool uses `yt-dlp` to download a supported source, extracts its audio, and
transcribes it locally. Do not use it to evade access controls or download
unauthorized material.

`--confirm-rights` confirms that you have the rights needed to download,
translate, and republish that input. The command refuses to create a job without
this confirmation. It is not an automated copyright check and does not obtain
permission on your behalf.

### Prepare a local video

```bash
autovideo --config config.json prepare --confirm-rights "/absolute/path/to/video.mp4"
```

Quote paths containing spaces. Absolute paths are recommended. FFmpeg handles
common inputs such as MP4, MOV, MKV, and WebM.

You can override selected transcription settings for one job with `--model`,
`--device`, `--compute-type`, `--hotwords`, `--no-vad`, or `--jobs-dir`:

```bash
autovideo --config config.json prepare --confirm-rights --model medium.en \
  --device cpu --compute-type int8 \
  --hotwords "Szoboszlai, Wirtz, Liverpool, Anfield" "/absolute/path/to/video.mp4"
```

When `prepare` finishes, it prints the job ID and job directory. Edit this file
next:

```text
jobs/<job-id>/subtitles/translation.csv
```

Example (always let the tool generate the real file):

```csv
index,start,end,english,chinese
1,"00:00:00,000","00:00:03,240","Welcome back to the channel.","欢迎回到我们的频道。"
2,"00:00:03,240","00:00:06,800","Liverpool were excellent today.","利物浦今天表现非常出色。"
```

The English-only subtitle file is immediately available at:

```text
jobs/<job-id>/subtitles/transcript.en.srt
```

Also inspect `transcription.review.csv`. A `check_content` row means a subtitle
gap still contains audible audio and should be reviewed; `likely_silence` is
usually a real pause. The report never invents or inserts text automatically.

### Retranscribe an existing job

Reuse an existing job's audio without downloading the video again:

```bash
autovideo retranscribe --model medium.en \
  --hotwords "Szoboszlai, Wirtz, Liverpool, Anfield" "jobs/<job-id>"
```

If an audible section is still skipped, retry without VAD:

```bash
autovideo retranscribe --no-vad "jobs/<job-id>"
```

Before retranscription, current subtitle files are copied to
`subtitles/backups/<timestamp>/`. Disabling VAD can produce text during true
silence, so use it for missed-speech cases and review the result manually.

### Render the bilingual video

After completing and saving the CSV, run:

```bash
autovideo --config config.json render "jobs/<job-id>"
```

The renderer places Chinese above English and creates editable subtitle files
as well as an MP4 with burned-in subtitles. Before uploading, review names,
scores, timing, line breaks, audio/video synchronization, rights, and
attribution from beginning to end.

By default, an empty `chinese` cell blocks rendering. Use the following only
when you intentionally accept some English-only cues:

```bash
autovideo render --allow-missing-chinese "jobs/<job-id>"
```

Check a job's current state and generated paths at any time:

```bash
autovideo status "jobs/<job-id>"
```

## Job and output directories

All work files are stored under `jobs/` by default. Each input receives a
separate job directory:

```text
jobs/
└── <job-id>/
    ├── source/
    │   ├── video.<extension>       # Copied local file or downloaded video
    │   └── info.json               # Source metadata
    ├── audio/
    │   └── speech.wav              # Lossless PCM audio used for transcription
    ├── job.json                    # Job state, configuration, and paths
    ├── subtitles/
    │   ├── transcript.en.srt       # English transcript
    │   ├── translation.csv         # Correct english and fill in chinese
    │   ├── transcription.review.csv # Audible subtitle-gap report
    │   ├── backups/                # Subtitles saved before retranscription
    │   ├── subtitle.bilingual.srt  # Editable bilingual subtitles
    │   └── subtitle.bilingual.ass  # Styled subtitles used for burn-in
    └── output/
        └── final.bilingual.mp4     # Final video with burned-in subtitles
```

`jobs/` is excluded by `.gitignore` because it may contain copyrighted media,
private rights records, and large output files. Do not use `git add -f jobs/`
to commit it to a public repository. Back up anything important before deleting
a job directory because doing so removes its source, translation, and output.

If `--jobs-dir` points to another directory inside the repository, add that
directory to `.gitignore` yourself. A job record can contain the original URL
or an absolute local path and should not be committed publicly.

## Configuration reference

`config.example.json` is the tracked example. Your local `config.json` is
ignored by Git.

- `jobs_dir`: root directory for generated jobs.
- `download.max_height`: maximum height for a downloaded YouTube video.
- `transcription.model`: local Whisper model name.
- `transcription.device`: defaults to `cpu` for Apple Silicon-compatible local
  inference.
- `transcription.compute_type`: defaults to `int8` to reduce memory use.
- `transcription.language`: use `en` to force English recognition.
- `transcription.beam_size`: larger values may improve results but take longer.
- `transcription.condition_on_previous_text`: disabled by default to reduce
  repetition loops and timestamp drift.
- `transcription.vad_filter`: filters long silent sections; retry with
  `--no-vad` when speech was missed.
- `transcription.vad_threshold`, `vad_min_silence_duration_ms`, and
  `vad_speech_pad_ms`: tune VAD sensitivity and speech-edge padding.
- `transcription.hotwords`: per-video player, manager, and club names.
- `transcription.initial_prompt`: English context that helps preserve Liverpool
  player, manager, club, competition, scoreline, and tactical names.
- `transcription.max_chars` / `max_duration`: maximum subtitle length and
  duration before splitting.
- `transcription.review_*`: gap-report and silence-detection thresholds.
- `subtitles`: font, Chinese and English sizes, margin, outline, and shadow.
- `render`: FFmpeg video encoder, preset, CRF quality, and audio bitrate. A
  lower CRF usually means higher quality and a larger file.

A Chinese-capable font must be installed on the system. If English appears but
Chinese is rendered as boxes, set `subtitles.font_name` in `config.json` to an
installed CJK font such as `PingFang SC`.

## Troubleshooting

### `autovideo: command not found`

Make sure the current terminal has run `source .venv/bin/activate`, then run
`python -m pip install -e .` again. You can also use
`python -m autovideo.cli ...` to help diagnose the entry point.

### `ffmpeg` or `ffprobe` is missing

Run `brew install ffmpeg` and open a new terminal. Apple Silicon Homebrew
commands are normally under `/opt/homebrew/bin`. Add that location to `PATH` if
necessary, then run `autovideo doctor` again.

### The first transcription is slow or appears stuck while downloading

Each new model must be downloaded once. The required storage and time depend on
the model and your network. Do not shut down the machine during the download.
Later jobs using the same model read it from the local cache. Free disk space or
switch to `tiny.en` or `small.en` if needed.

### Device or compute-type errors on Apple Silicon

Start with `device: "cpu"` and `compute_type: "int8"` from the example
configuration. Confirm that the virtual environment uses an arm64 Python:

```bash
python -c "import platform; print(platform.machine())"
```

The expected output is `arm64`. An `x86_64` result means the terminal or Python
is running through Rosetta; create a new arm64 virtual environment.

### YouTube download failure

Upgrade yt-dlp with its EJS component and confirm Deno is available:

```bash
python -m pip install --upgrade "yt-dlp[default]"
deno --version
autovideo doctor
```

If the video requires login, membership, DRM, geographic circumvention, or
another access-control bypass, stop processing it and request an authorized
local file from the rightsholder. This project does not provide bypasses. For
an ordinary public video, `yt-dlp --verbose URL` can expose an upstream error;
otherwise use an authorized local copy.

### CSV cannot be read or Chinese text is garbled

Preserve the original header and row count, and save the file as UTF-8
(preferably UTF-8 with BOM). Do not merge cells or let the spreadsheet convert
timestamps into dates or numbers. Make a backup before repairing the file.

### Rendering reports missing Chinese translations

Check every `chinese` cell, especially the final rows and short interjections.
Do not delete those rows. To intentionally leave some cues in English, keep the
cell empty and render with `--allow-missing-chinese`.

### Speech is audible but a subtitle section is missing

Review `check_content` rows in `transcription.review.csv`. If speech is truly
missing, run `autovideo retranscribe --no-vad "jobs/<job-id>"`. If only proper
names are wrong, keep VAD enabled and pass the current names with `--hotwords`.
Always review the new transcript, especially over music or overlapping voices.

### Subtitle styling, quality, or file size is unsuitable

Adjust `render.crf` in `config.json`. A typical range is 18–28: lower values are
usually clearer and larger. Long videos naturally take time to encode. Keep the
source and `translation.csv` until you have reviewed the final output.

## Privacy and cost

- No translation API, speech-recognition API, subscription, or usage-based API
  charge.
- This project does not upload transcription audio to a paid cloud service.
- The initial model download and YouTube source download use ordinary network
  traffic.
- Local inference and video encoding consume CPU/GPU time, memory, storage, and
  electricity.

## License

[MIT](LICENSE)
