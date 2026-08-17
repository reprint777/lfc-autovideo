"""Subtitle and manual-translation file helpers.

The module deliberately depends only on Python's standard library.  All text
files use explicit UTF-8 encodings; the translation CSV uses UTF-8 with a BOM so
that current spreadsheet applications detect Chinese text correctly.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

from .models import Cue


TRANSLATION_COLUMNS = ("index", "start", "end", "english", "chinese")


def _coerce_cues(cues: Iterable[Cue]) -> list[Cue]:
    result = list(cues)
    if not all(isinstance(cue, Cue) for cue in result):
        raise TypeError("all subtitle items must be Cue instances")
    return result


def _prepare_output(path: str | Path) -> Path:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def format_srt_timestamp(seconds: float) -> str:
    """Return a non-negative number of seconds as ``HH:MM:SS,mmm``."""

    seconds = float(seconds)
    if seconds < 0:
        raise ValueError("timestamp must be non-negative")
    total_milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


_TIMESTAMP_RE = re.compile(
    r"^\s*(?P<hours>\d+):(?P<minutes>\d{1,2}):(?P<seconds>\d{1,2})"
    r"(?:[,.](?P<fraction>\d{1,6}))?\s*$"
)


def parse_timestamp(value: str | float | int) -> float:
    """Parse an SRT/ASS-like timestamp or a numeric number of seconds."""

    if isinstance(value, (int, float)):
        result = float(value)
        if result < 0:
            raise ValueError("timestamp must be non-negative")
        return result

    text = str(value).strip()
    match = _TIMESTAMP_RE.match(text)
    if not match:
        try:
            result = float(text)
        except ValueError as exc:
            raise ValueError(f"invalid timestamp: {value!r}") from exc
        if result < 0:
            raise ValueError("timestamp must be non-negative")
        return result

    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds"))
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"invalid timestamp: {value!r}")
    fraction_text = match.group("fraction") or ""
    fraction = int(fraction_text) / (10 ** len(fraction_text)) if fraction_text else 0.0
    return int(match.group("hours")) * 3600 + minutes * 60 + seconds + fraction


def _srt_text(cue: Cue, bilingual: bool) -> str:
    english = cue.english.strip()
    chinese = cue.chinese.strip()
    if bilingual and chinese:
        # Put the translation on top: it remains legible when a player control
        # overlays the bottom edge of a video.
        return f"{chinese}\n{english}" if english else chinese
    return english


def write_srt(
    cues: Iterable[Cue],
    path: str | Path,
    bilingual: bool = False,
) -> Path:
    """Write cues as SRT, optionally adding non-empty Chinese translations."""

    destination = _prepare_output(path)
    blocks: list[str] = []
    for index, cue in enumerate(_coerce_cues(cues), start=1):
        blocks.append(
            f"{index}\n"
            f"{format_srt_timestamp(cue.start)} --> {format_srt_timestamp(cue.end)}\n"
            f"{_srt_text(cue, bilingual)}"
        )
    content = "\n\n".join(blocks)
    if blocks:
        content += "\n"
    destination.write_text(content, encoding="utf-8")
    return destination


def write_bilingual_srt(cues: Iterable[Cue], path: str | Path) -> Path:
    """Convenience wrapper for :func:`write_srt` in bilingual mode."""

    return write_srt(cues, path, bilingual=True)


def write_translation_csv(cues: Iterable[Cue], path: str | Path) -> Path:
    """Write a spreadsheet-friendly manual translation template.

    Only the ``chinese`` column is intended to be edited.  Timestamps are kept
    in an unambiguous SRT form and multiline/comma-containing text is safely
    quoted by :mod:`csv`.
    """

    destination = _prepare_output(path)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRANSLATION_COLUMNS)
        writer.writeheader()
        for index, cue in enumerate(_coerce_cues(cues), start=1):
            writer.writerow(
                {
                    "index": index,
                    "start": format_srt_timestamp(cue.start),
                    "end": format_srt_timestamp(cue.end),
                    "english": cue.english,
                    "chinese": cue.chinese,
                }
            )
    return destination


def cue_source_digest(cues: Iterable[Cue]) -> str:
    """Hash the read-only part of a translation sheet.

    Timestamps are normalized to the exact millisecond representation written
    to CSV, so the digest remains stable after a legitimate spreadsheet
    round-trip.  The Chinese column is intentionally excluded.
    """

    payload = [
        {
            "index": index,
            "start": format_srt_timestamp(cue.start),
            "end": format_srt_timestamp(cue.end),
            "english": cue.english,
        }
        for index, cue in enumerate(_coerce_cues(cues), start=1)
    ]
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def read_translation_csv(path: str | Path) -> list[Cue]:
    """Read cues from a CSV produced by :func:`write_translation_csv`."""

    source = Path(path).expanduser()
    cues: list[Cue] = []
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        missing = [column for column in TRANSLATION_COLUMNS if column not in columns]
        if missing:
            raise ValueError(
                f"translation CSV is missing required column(s): {', '.join(missing)}"
            )
        unexpected = [column for column in columns if column not in TRANSLATION_COLUMNS]
        if unexpected:
            raise ValueError(
                "translation CSV has unexpected column(s): " + ", ".join(unexpected)
            )

        seen_indices: set[int] = set()
        for row_number, row in enumerate(reader, start=2):
            # Ignore a completely blank line, but surface partially edited rows.
            if not any((row.get(column) or "").strip() for column in TRANSLATION_COLUMNS):
                continue
            try:
                extras = row.get(None)
                if extras and any(str(value or "").strip() for value in extras):
                    raise ValueError(
                        "unexpected extra column(s); text containing commas must remain CSV-quoted"
                    )
                index = int((row.get("index") or "").strip())
                if index < 1:
                    raise ValueError("index must be positive")
                if index in seen_indices:
                    raise ValueError(f"duplicate index {index}")
                expected_index = len(cues) + 1
                if index != expected_index:
                    raise ValueError(
                        f"expected index {expected_index}, found {index}; do not delete or reorder rows"
                    )
                seen_indices.add(index)
                cue = Cue(
                    start=parse_timestamp(row.get("start") or ""),
                    end=parse_timestamp(row.get("end") or ""),
                    english=row.get("english") or "",
                    chinese=row.get("chinese") or "",
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid translation CSV row {row_number}: {exc}") from exc
            if not cue.english.strip():
                raise ValueError(
                    f"invalid translation CSV row {row_number}: english must not be empty"
                )
            if cues and cue.start < cues[-1].start:
                raise ValueError(
                    f"invalid translation CSV row {row_number}: timestamps are out of order"
                )
            cues.append(cue)
    if not cues:
        raise ValueError("translation CSV contains no subtitle rows")
    return cues


def escape_ass_text(text: str) -> str:
    """Escape user-controlled text for the ASS dialogue field.

    Backslashes and braces are control characters in libass.  Escaping them
    prevents transcript text such as ``{\\pos(0,0)}`` from becoming an override
    tag.  Real line breaks are retained as ASS hard line breaks.
    """

    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\\", r"\\")
    normalized = normalized.replace("{", r"\{").replace("}", r"\}")
    return normalized.replace("\n", r"\N")


def format_ass_timestamp(seconds: float) -> str:
    """Return seconds in ASS's ``H:MM:SS.cc`` format."""

    seconds = float(seconds)
    if seconds < 0:
        raise ValueError("timestamp must be non-negative")
    total_centiseconds = int(round(seconds * 100))
    hours, remainder = divmod(total_centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def write_ass(
    cues: Iterable[Cue],
    path: str | Path,
    font_name: str = "PingFang SC",
    font_size: int = 52,
    english_font_size: int = 32,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
    margin_v: int = 70,
    outline: float = 3.0,
    shadow: float = 1.0,
) -> Path:
    """Write a burn-in-ready bilingual ASS file.

    Chinese is placed above English when supplied.  A cue whose Chinese field
    is empty contains only English, which makes the same function useful before
    and after manual translation.
    """

    destination = _prepare_output(path)
    safe_font_name = (
        str(font_name)
        .replace(",", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )
    if not safe_font_name:
        raise ValueError("font_name must not be empty")

    header = f"""[Script Info]
; Generated locally by autovideo
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {int(play_res_x)}
PlayResY: {int(play_res_y)}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{safe_font_name},{int(font_size)},&H00FFFFFF,&H00FFFFFF,&H00111111,&H80000000,0,0,0,0,100,100,0,0,1,{float(outline):g},{float(shadow):g},2,60,60,{int(margin_v)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for cue in _coerce_cues(cues):
        english = escape_ass_text(cue.english.strip())
        chinese = escape_ass_text(cue.chinese.strip())
        english_styled = rf"{{\fs{int(english_font_size)}}}{english}" if english else ""
        text = (
            f"{chinese}\\N{english_styled}"
            if chinese and english_styled
            else chinese or english_styled
        )
        lines.append(
            "Dialogue: 0,"
            f"{format_ass_timestamp(cue.start)},{format_ass_timestamp(cue.end)},"
            f"Default,,0,0,0,,{text}\n"
        )
    destination.write_text("".join(lines), encoding="utf-8")
    return destination


def write_bilingual_ass(
    cues: Iterable[Cue],
    path: str | Path,
    **kwargs: object,
) -> Path:
    """Named alias for :func:`write_ass`."""

    return write_ass(cues, path, **kwargs)
