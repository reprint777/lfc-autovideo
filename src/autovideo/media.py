from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .errors import AutovideoError


def _executable(name: str, supplied: str | Path | None) -> str:
    if supplied is not None:
        return str(supplied)
    found = shutil.which(name)
    if found is None:
        raise AutovideoError(
            f"未找到 {name}。请先安装 FFmpeg，再运行 autovideo doctor。"
        )
    return found


def probe_media(
    media_path: str | Path,
    *,
    ffprobe_bin: str | Path | None = None,
) -> dict[str, Any]:
    """Return ffprobe's JSON metadata for a local media file."""

    path = Path(media_path).expanduser().resolve()
    if not path.is_file():
        raise AutovideoError(f"媒体文件不存在：{path}")

    command = [
        _executable("ffprobe", ffprobe_bin),
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            shell=False,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or ""
        suffix = f"：{detail.strip()}" if detail.strip() else ""
        raise AutovideoError(f"ffprobe 无法读取媒体文件{suffix}") from exc

    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AutovideoError("ffprobe 返回了无效的 JSON 数据。") from exc
    if not isinstance(result, dict):
        raise AutovideoError("ffprobe 返回的媒体信息格式不正确。")
    return result


def extract_audio(
    source_video: str | Path,
    output_audio: str | Path,
    *,
    ffmpeg_bin: str | Path | None = None,
) -> Path:
    """Extract the first audio stream as lossless mono 16 kHz PCM WAV."""

    source = Path(source_video).expanduser().resolve()
    output = Path(output_audio).expanduser().resolve()
    if not source.is_file():
        raise AutovideoError(f"源视频不存在：{source}")
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        _executable("ffmpeg", ffmpeg_bin),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            shell=False,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or ""
        suffix = f"：{detail.strip()}" if detail.strip() else ""
        raise AutovideoError(f"FFmpeg 音频抽取失败{suffix}") from exc
    return output


_SILENCE_START_RE = re.compile(r"silence_start:\s*(?P<time>-?\d+(?:\.\d+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(?P<time>-?\d+(?:\.\d+)?)")


def detect_silences(
    audio_path: str | Path,
    *,
    noise_db: float = -35.0,
    min_duration: float = 0.6,
    ffmpeg_bin: str | Path | None = None,
) -> list[tuple[float, float]]:
    """Return silence intervals detected by FFmpeg's ``silencedetect`` filter."""

    source = Path(audio_path).expanduser().resolve()
    if not source.is_file():
        raise AutovideoError(f"音频文件不存在：{source}")
    if min_duration <= 0:
        raise ValueError("min_duration must be positive")

    command = [
        _executable("ffmpeg", ffmpeg_bin),
        "-hide_banner",
        "-nostats",
        "-i",
        str(source),
        "-af",
        f"silencedetect=noise={float(noise_db):g}dB:d={float(min_duration):g}",
        "-f",
        "null",
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            shell=False,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or ""
        suffix = f"：{detail.strip()}" if detail.strip() else ""
        raise AutovideoError(f"FFmpeg 静音检测失败{suffix}") from exc

    intervals: list[tuple[float, float]] = []
    pending_start: float | None = None
    for line in completed.stderr.splitlines():
        start_match = _SILENCE_START_RE.search(line)
        if start_match:
            pending_start = max(0.0, float(start_match.group("time")))
        end_match = _SILENCE_END_RE.search(line)
        if end_match and pending_start is not None:
            end = float(end_match.group("time"))
            if end > pending_start:
                intervals.append((pending_start, end))
            pending_start = None
    if pending_start is not None:
        intervals.append((pending_start, float("inf")))
    return intervals
