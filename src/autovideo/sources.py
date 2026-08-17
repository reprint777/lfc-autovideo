from __future__ import annotations

import importlib
import json
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .errors import AutovideoError
from .media import probe_media


class SourceKind(str, Enum):
    YOUTUBE = "youtube"
    LOCAL = "local"


@dataclass(frozen=True)
class SourceSpec:
    value: str
    kind: SourceKind
    path: Path | None = None


def _normalise_possible_youtube_url(value: str) -> str:
    lowered = value.lower()
    prefixes = ("youtube.com/", "www.youtube.com/", "m.youtube.com/", "youtu.be/")
    if lowered.startswith(prefixes):
        return f"https://{value}"
    return value


def _is_single_youtube_video(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"}:
        return False
    if host == "youtu.be":
        return bool(parsed.path.strip("/").split("/", 1)[0])
    if host != "youtube.com" and not host.endswith(".youtube.com"):
        return False

    path = parsed.path.rstrip("/")
    if path == "/watch":
        return bool(parse_qs(parsed.query).get("v", [""])[0])
    parts = [part for part in parsed.path.split("/") if part]
    return len(parts) >= 2 and parts[0] in {"shorts", "live", "embed", "v", "clip"}


def is_youtube_url(value: str) -> bool:
    return _is_single_youtube_video(_normalise_possible_youtube_url(value.strip()))


def resolve_source(value: str | Path) -> SourceSpec:
    """Classify a YouTube video URL or validate a local input file."""

    raw = str(value).strip()
    if not raw:
        raise AutovideoError("请提供 YouTube 视频链接或本地视频文件。")

    candidate_url = _normalise_possible_youtube_url(raw)
    if _is_single_youtube_video(candidate_url):
        return SourceSpec(value=candidate_url, kind=SourceKind.YOUTUBE)

    parsed = urlparse(candidate_url)
    if parsed.scheme in {"http", "https"}:
        host = (parsed.hostname or "").lower()
        if host == "youtube.com" or host == "youtu.be" or host.endswith(".youtube.com"):
            raise AutovideoError("仅支持单个 YouTube 视频，不支持播放列表或频道页。")
        raise AutovideoError("仅支持 YouTube 链接和本地视频文件。")

    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise AutovideoError(f"本地视频文件不存在：{path}")
    return SourceSpec(value=str(path), kind=SourceKind.LOCAL, path=path)


def _find_downloaded_video(source_dir: Path) -> Path:
    excluded_suffixes = {".json", ".part", ".ytdl"}
    candidates = [
        item
        for item in source_dir.glob("video.*")
        if item.is_file()
        and item.suffix.lower() not in excluded_suffixes
        and not item.name.endswith(".info.json")
    ]
    if not candidates:
        raise AutovideoError("yt-dlp 已结束，但未找到下载的视频文件。")
    return max(candidates, key=lambda item: item.stat().st_mtime)


def _download_youtube(url: str, source_dir: Path, max_height: int) -> Path:
    try:
        yt_dlp = importlib.import_module("yt_dlp")
    except ImportError as exc:
        raise AutovideoError(
            "未安装 yt-dlp。请安装项目依赖，再运行 autovideo doctor。"
        ) from exc

    height = min(max(int(max_height), 1), 1080)
    output_template = str(source_dir / "video.%(ext)s")
    options: dict[str, Any] = {
        "format": (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
        ),
        "outtmpl": output_template,
        "noplaylist": True,
        "playlist_items": "1",
        "merge_output_format": "mp4",
        "continuedl": True,
        "ignoreerrors": False,
    }
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            if not isinstance(info, dict) or info.get("_type") == "playlist" or "entries" in info:
                raise AutovideoError("仅支持单个 YouTube 视频，禁止下载播放列表。")
            sanitizer = getattr(downloader, "sanitize_info", None)
            clean_info = sanitizer(info) if callable(sanitizer) else info
    except AutovideoError:
        raise
    except Exception as exc:
        # yt-dlp exposes several changing exception classes; keep it a lazy optional
        # dependency and convert its failures into one stable CLI-facing error.
        raise AutovideoError(f"YouTube 视频下载失败：{exc}") from exc

    (source_dir / "info.json").write_text(
        json.dumps(clean_info, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return _find_downloaded_video(source_dir)


def prepare_source(
    spec: SourceSpec,
    job_dir: str | Path,
    max_height: int = 1080,
) -> tuple[Path, dict[str, Any]]:
    """Materialise a source under ``job_dir/source`` and return it with metadata."""

    source_dir = Path(job_dir).expanduser().resolve() / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    if spec.kind is SourceKind.YOUTUBE:
        video_path = _download_youtube(spec.value, source_dir, max_height)
    elif spec.kind is SourceKind.LOCAL:
        source_path = (spec.path or Path(spec.value)).expanduser().resolve()
        if not source_path.is_file():
            raise AutovideoError(f"本地视频文件不存在：{source_path}")
        # Use a fixed basename so a user file named info.json cannot collide
        # with this job's metadata file. FFmpeg probes content as well as suffix.
        suffix = source_path.suffix.lower() or ".bin"
        video_path = source_dir / f"video{suffix}"
        if source_path != video_path:
            shutil.copy2(source_path, video_path)
    else:  # pragma: no cover - defensive against hand-built invalid specs
        raise AutovideoError(f"不支持的输入类型：{spec.kind}")

    metadata = probe_media(video_path)
    info_path = source_dir / "info.json"
    if spec.kind is SourceKind.LOCAL:
        info_path.write_text(
            json.dumps(
                {
                    "source_type": SourceKind.LOCAL.value,
                    "original_path": spec.value,
                    "stored_filename": video_path.name,
                    "ffprobe": metadata,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return video_path, metadata
