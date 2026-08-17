from __future__ import annotations

import json
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
    """Extract the first audio stream as mono 16 kHz, 64 kbit/s AAC."""

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
        "aac",
        "-b:a",
        "64k",
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
