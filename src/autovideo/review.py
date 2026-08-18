"""Generate a compact report for subtitle gaps that may hide missed speech."""

from __future__ import annotations

import csv
from dataclasses import dataclass
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

RECOVERY_COLUMNS = (
    "gap_start",
    "gap_end",
    "cue_count",
    "word_count",
    "average_probability",
    "coverage_ratio",
    "text",
)


@dataclass(frozen=True)
class GapReview:
    before_index: int
    after_index: int
    start: float
    end: float
    silence_seconds: float
    non_silent_seconds: float
    status: str

    @property
    def duration(self) -> float:
        return self.end - self.start


def _overlap(start: float, end: float, intervals: Iterable[tuple[float, float]]) -> float:
    return sum(max(0.0, min(end, right) - max(start, left)) for left, right in intervals)


def analyze_gaps(
    cues: Iterable[Cue],
    silence_intervals: Iterable[tuple[float, float]],
    *,
    min_gap: float = 2.0,
    audible_threshold: float = 0.75,
) -> list[GapReview]:
    """Classify subtitle gaps using measured silence overlap."""

    if min_gap <= 0 or audible_threshold < 0:
        raise ValueError("gap thresholds must be positive")
    ordered = sorted(cues, key=lambda cue: (cue.start, cue.end))
    silences = list(silence_intervals)
    result: list[GapReview] = []
    for before_index, (before, after) in enumerate(zip(ordered, ordered[1:]), start=1):
        start = before.end
        end = after.start
        duration = end - start
        if duration < min_gap:
            continue
        silence = min(duration, _overlap(start, end, silences))
        non_silent = max(0.0, duration - silence)
        result.append(
            GapReview(
                before_index=before_index,
                after_index=before_index + 1,
                start=start,
                end=end,
                silence_seconds=silence,
                non_silent_seconds=non_silent,
                status=(
                    "check_content"
                    if non_silent >= audible_threshold
                    else "likely_silence"
                ),
            )
        )
    return result


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
    gaps = analyze_gaps(ordered, silences, min_gap=min_gap)
    suspicious = sum(gap.status == "check_content" for gap in gaps)
    for gap in gaps:
        rows.append(
            {
                "before_index": gap.before_index,
                "after_index": gap.after_index,
                "start": format_srt_timestamp(gap.start),
                "end": format_srt_timestamp(gap.end),
                "duration_seconds": f"{gap.duration:.3f}",
                "silence_seconds": f"{gap.silence_seconds:.3f}",
                "non_silent_seconds": f"{gap.non_silent_seconds:.3f}",
                "status": gap.status,
            }
        )

    destination = Path(output_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return destination, suspicious


def write_recovery_review(
    items: Iterable[dict[str, object]], path: str | Path
) -> Path:
    """Write every automatically inserted gap-recovery result for human review."""

    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RECOVERY_COLUMNS)
        writer.writeheader()
        for item in items:
            writer.writerow({column: item.get(column, "") for column in RECOVERY_COLUMNS})
    return destination
