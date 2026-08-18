"""Generate a compact report for subtitle gaps that may hide missed speech."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .media import detect_silences
from .models import Cue
from .subtitles import format_srt_timestamp


REVIEW_COLUMNS = (
    "before_index",
    "after_index",
    "start",
    "end",
    "duration_seconds",
    "silence_seconds",
    "non_silent_seconds",
    "status",
)


def _overlap(start: float, end: float, intervals: Iterable[tuple[float, float]]) -> float:
    return sum(max(0.0, min(end, right) - max(start, left)) for left, right in intervals)


def write_gap_review(
    cues: Iterable[Cue],
    audio_path: str | Path,
    output_path: str | Path,
    *,
    min_gap: float = 2.0,
    noise_db: float = -35.0,
    silence_min_duration: float = 0.6,
    ffmpeg_bin: str | Path | None = None,
) -> tuple[Path, int]:
    """Write gaps of at least ``min_gap`` and flag gaps containing audible audio."""

    if min_gap <= 0:
        raise ValueError("min_gap must be positive")
    ordered = sorted(cues, key=lambda cue: (cue.start, cue.end))
    silences = detect_silences(
        audio_path,
        noise_db=noise_db,
        min_duration=silence_min_duration,
        ffmpeg_bin=ffmpeg_bin,
    )
    rows: list[dict[str, object]] = []
    suspicious = 0
    for before_index, (before, after) in enumerate(zip(ordered, ordered[1:]), start=1):
        start = before.end
        end = after.start
        duration = end - start
        if duration < min_gap:
            continue
        silence = min(duration, _overlap(start, end, silences))
        non_silent = max(0.0, duration - silence)
        status = "check_content" if non_silent >= 0.75 else "likely_silence"
        if status == "check_content":
            suspicious += 1
        rows.append(
            {
                "before_index": before_index,
                "after_index": before_index + 1,
                "start": format_srt_timestamp(start),
                "end": format_srt_timestamp(end),
                "duration_seconds": f"{duration:.3f}",
                "silence_seconds": f"{silence:.3f}",
                "non_silent_seconds": f"{non_silent:.3f}",
                "status": status,
            }
        )

    destination = Path(output_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return destination, suspicious
