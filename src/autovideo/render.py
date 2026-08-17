from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping

from .errors import AutovideoError


def render_video(
    source_video: str | Path,
    subtitle_ass: str | Path,
    output_video: str | Path,
    render_config: Mapping[str, Any],
) -> Path:
    """Burn an ASS subtitle file into a Bilibili-friendly MP4."""

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise AutovideoError("未找到 ffmpeg。请先安装 FFmpeg，再运行 autovideo doctor。")

    source = Path(source_video).expanduser().resolve()
    ass_path = Path(subtitle_ass).expanduser().resolve()
    output = Path(output_video).expanduser().resolve()
    if not source.is_file():
        raise AutovideoError(f"源视频不存在：{source}")
    if not ass_path.is_file():
        raise AutovideoError(f"字幕文件不存在：{ass_path}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.parent / (
        f".{output.stem}.{uuid.uuid4().hex}.rendering{output.suffix or '.mp4'}"
    )
    try:
        # A fixed local ASS name avoids FFmpeg filtergraph escaping problems for
        # user paths containing commas, colons, quotes, or brackets.
        with tempfile.TemporaryDirectory(
            prefix=".autovideo-subtitle-", dir=output.parent
        ) as subtitle_workdir:
            workdir = Path(subtitle_workdir)
            shutil.copy2(ass_path, workdir / "subtitle.ass")
            command = [
                ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-vf",
                "ass=subtitle.ass",
                "-c:v",
                str(render_config.get("video_encoder", "libx264")),
                "-preset",
                str(render_config.get("preset", "medium")),
                "-crf",
                str(render_config.get("crf", 20)),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                str(render_config.get("audio_bitrate", "192k")),
                "-movflags",
                "+faststart",
                str(temporary_output),
            ]
            subprocess.run(command, cwd=workdir, check=True, shell=False)
        if not temporary_output.is_file():
            raise AutovideoError("FFmpeg 已结束，但没有生成输出文件。")
        temporary_output.replace(output)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AutovideoError(
            "FFmpeg 渲染失败。请运行 autovideo doctor，并检查字幕字体和磁盘空间。"
        ) from exc
    finally:
        temporary_output.unlink(missing_ok=True)
    return output
