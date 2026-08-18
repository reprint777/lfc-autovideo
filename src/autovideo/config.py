from __future__ import annotations

import copy
import json
import platform
from pathlib import Path
from typing import Any, Mapping

from .errors import AutovideoError


def _default_font() -> str:
    if platform.system() == "Darwin":
        return "PingFang SC"
    if platform.system() == "Windows":
        return "Microsoft YaHei"
    return "Noto Sans CJK SC"


DEFAULT_CONFIG: dict[str, Any] = {
    "jobs_dir": "jobs",
    "download": {
        "max_height": 1080,
    },
    "transcription": {
        "model": "medium.en",
        "device": "cpu",
        "compute_type": "int8",
        "language": "en",
        "beam_size": 5,
        "condition_on_previous_text": False,
        "vad_filter": True,
        "vad_threshold": 0.35,
        "vad_min_silence_duration_ms": 2000,
        "vad_speech_pad_ms": 600,
        "hotwords": (
            "Liverpool FC, Liverpool, Anfield, Arne Slot, Premier League, "
            "Champions League"
        ),
        "initial_prompt": (
            "Liverpool FC football discussion. Preserve player names, manager names, "
            "club names, competitions, scorelines, and tactical terminology."
        ),
        "max_chars": 84,
        "max_duration": 6.0,
        "review_gap_seconds": 2.0,
        "review_silence_noise_db": -35.0,
        "review_silence_min_duration": 0.6,
        "gap_recovery": True,
        "recovery_left_padding_seconds": [1.5, 6.0],
        "recovery_right_padding_seconds": 2.0,
        "recovery_min_probability": 0.45,
        "recovery_min_coverage_ratio": 0.35,
        "recovery_max_gap_seconds": 30.0,
    },
    "subtitles": {
        "font_name": _default_font(),
        "chinese_font_size": 48,
        "english_font_size": 30,
        "margin_vertical": 58,
        "outline": 3,
        "shadow": 1,
    },
    "render": {
        "video_encoder": "libx264",
        "preset": "medium",
        "crf": 20,
        "audio_bitrate": "192k",
    },
}


def _merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def merge_config(override: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return current defaults merged with a full or legacy config snapshot."""

    config = copy.deepcopy(DEFAULT_CONFIG)
    return _merge(config, override) if override else config


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config = merge_config()
    if path is None:
        return config

    config_path = Path(path).expanduser().resolve()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AutovideoError(f"配置文件不存在：{config_path}") from exc
    except json.JSONDecodeError as exc:
        raise AutovideoError(
            f"配置文件不是有效 JSON：{config_path}（第 {exc.lineno} 行）"
        ) from exc
    if not isinstance(raw, dict):
        raise AutovideoError("配置文件的顶层必须是 JSON 对象。")
    return _merge(config, raw)


def write_default_config(path: str | Path, *, overwrite: bool = False) -> Path:
    output = Path(path).expanduser().resolve()
    if output.exists() and not overwrite:
        raise AutovideoError(f"文件已存在：{output}；如需覆盖请使用 --force。")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output
