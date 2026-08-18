"""Local-only speech transcription using faster-whisper.

``faster_whisper`` is imported inside :func:`transcribe_local`, so commands that
only render a previously translated CSV remain usable without the optional,
heavy transcription dependency installed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
import re
from typing import Any

from .models import Cue


_NO_SPACE_BEFORE = re.compile(r"^[,.;:!?%\]\)}’”]+")
_CONTRACTION = re.compile(r"^(?:['’](?:s|d|m|re|ve|ll)|n['’]t)$", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?…][\"'’”\])}]*$")
_SOFT_END = re.compile(r"[,;:][\"'’”\])}]*$")
_BROKEN_COMPOUND_HYPHEN = re.compile(r"(?<=[A-Za-z0-9])\s+-(?=[A-Za-z0-9])")


def _value(item: object, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _append_word(text: str, raw_word: object) -> str:
    raw = str(raw_word or "")
    word = raw.strip()
    if not word:
        return text
    if not text:
        return word
    if raw[:1].isspace():
        return text + raw.rstrip()
    if _NO_SPACE_BEFORE.match(word) or _CONTRACTION.match(word):
        return text + word
    if text.endswith(("-", "—", "/", "(", "[", "{", "‘", "“")):
        return text + word
    return text + " " + word


def normalize_transcript_text(text: str) -> str:
    """Repair spacing artifacts without changing real punctuation dashes."""

    return _BROKEN_COMPOUND_HYPHEN.sub("-", str(text).strip())


def build_cues_from_words(
    words: Iterable[object],
    *,
    max_chars: int = 84,
    max_duration: float = 6.0,
    max_gap: float = 0.8,
    max_words: int = 16,
    min_punctuation_duration: float = 1.0,
) -> list[Cue]:
    """Group faster-whisper word timestamps into readable subtitle cues.

    ``words`` may contain faster-whisper ``Word`` objects or dictionaries with
    ``start``, ``end`` and ``word`` keys.  Boundaries favor sentence punctuation,
    but duration, character, word-count and silence limits keep long speech
    readable on screen.
    """

    if max_chars < 1 or max_duration <= 0 or max_gap < 0 or max_words < 1:
        raise ValueError("cue grouping limits must be positive")

    cues: list[Cue] = []
    current_text = ""
    current_start: float | None = None
    current_end: float | None = None
    current_count = 0

    def flush() -> None:
        nonlocal current_text, current_start, current_end, current_count
        text = normalize_transcript_text(current_text)
        if (
            text
            and current_start is not None
            and current_end is not None
            and current_end > current_start
        ):
            cues.append(Cue(current_start, current_end, text))
        current_text = ""
        current_start = None
        current_end = None
        current_count = 0

    for item in words:
        raw_start = _value(item, "start")
        raw_end = _value(item, "end")
        raw_word = _value(item, "word", _value(item, "text", ""))
        if raw_start is None or raw_end is None or not str(raw_word or "").strip():
            continue
        start = max(0.0, float(raw_start))
        end = max(start, float(raw_end))
        candidate = _append_word(current_text, raw_word)

        if current_start is not None:
            gap = max(0.0, start - (current_end if current_end is not None else start))
            projected_duration = end - current_start
            over_limit = (
                gap > max_gap
                or projected_duration > max_duration
                or len(candidate) > max_chars
                or current_count >= max_words
            )
            if over_limit:
                flush()
                candidate = _append_word("", raw_word)

        if current_start is None:
            current_start = start
        current_text = candidate
        current_end = end
        current_count += 1

        duration = end - current_start
        if _SENTENCE_END.search(current_text) and duration >= min_punctuation_duration:
            flush()
        elif _SOFT_END.search(current_text) and (
            len(current_text) >= int(max_chars * 0.65) or duration >= max_duration * 0.7
        ):
            flush()

    flush()
    return cues


def cues_from_segments(
    segments: Iterable[object],
    *,
    max_chars: int = 84,
    max_duration: float = 6.0,
    max_gap: float = 0.8,
    max_words: int = 16,
) -> list[Cue]:
    """Convert faster-whisper segments (preferably with words) to cues."""

    result: list[Cue] = []
    pending_words: list[object] = []

    def flush_words() -> None:
        nonlocal pending_words
        if pending_words:
            result.extend(
                build_cues_from_words(
                    pending_words,
                    max_chars=max_chars,
                    max_duration=max_duration,
                    max_gap=max_gap,
                    max_words=max_words,
                )
            )
            pending_words = []

    for segment in segments:
        words = list(_value(segment, "words", None) or [])
        timed_words = [
            word
            for word in words
            if _value(word, "start") is not None and _value(word, "end") is not None
        ]
        if words and len(timed_words) == len(words):
            pending_words.extend(timed_words)
            continue

        flush_words()
        text = normalize_transcript_text(str(_value(segment, "text", "") or ""))
        start = _value(segment, "start")
        end = _value(segment, "end")
        if text and start is not None and end is not None:
            cue_start = max(0.0, float(start))
            cue_end = float(end)
            if cue_end > cue_start:
                result.append(Cue(cue_start, cue_end, text))

    flush_words()
    result.sort(key=lambda cue: (cue.start, cue.end))
    return result


def _info_to_dict(info: object) -> dict[str, object]:
    result: dict[str, object] = {}
    for name in (
        "language",
        "language_probability",
        "duration",
        "duration_after_vad",
        "all_language_probs",
    ):
        value = getattr(info, name, None)
        if value is not None:
            # faster-whisper currently returns a tuple for all_language_probs;
            # make the common metadata easy to serialize as JSON.
            result[name] = list(value) if isinstance(value, tuple) else value
    return result


def transcribe_local(
    audio_path: str | Path,
    model_size: str = "medium.en",
    device: str = "auto",
    compute_type: str = "default",
    language: str | None = "en",
    initial_prompt: str | None = None,
    beam_size: int = 5,
    vad_filter: bool = True,
    vad_threshold: float = 0.35,
    vad_min_silence_duration_ms: int = 2000,
    vad_speech_pad_ms: int = 600,
    condition_on_previous_text: bool = False,
    hotwords: str | None = None,
    max_chars: int = 84,
    max_duration: float = 6.0,
) -> tuple[list[Cue], dict[str, object]]:
    """Transcribe a local media file without calling a cloud API.

    The first invocation may download the selected faster-whisper model unless
    it already exists in the local model cache.  Thereafter inference is local.
    """

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - exact message tested indirectly
        raise RuntimeError(
            "Local transcription requires faster-whisper. Install the project's "
            "transcription dependencies before running this command."
        ) from exc

    model = WhisperModel(str(model_size), device=str(device), compute_type=str(compute_type))
    options: dict[str, object] = {
        "word_timestamps": True,
        "vad_filter": bool(vad_filter),
        "beam_size": int(beam_size),
        "condition_on_previous_text": bool(condition_on_previous_text),
    }
    if vad_filter:
        options["vad_parameters"] = {
            "threshold": float(vad_threshold),
            "min_silence_duration_ms": int(vad_min_silence_duration_ms),
            "speech_pad_ms": int(vad_speech_pad_ms),
        }
    if language:
        options["language"] = language
    if initial_prompt:
        options["initial_prompt"] = initial_prompt
    if hotwords:
        options["hotwords"] = str(hotwords)

    segments, info = model.transcribe(str(Path(audio_path).expanduser()), **options)
    cues = cues_from_segments(
        segments,
        max_chars=int(max_chars),
        max_duration=float(max_duration),
    )
    metadata = _info_to_dict(info)
    metadata.update(
        {
            "model": str(model_size),
            "device": str(device),
            "compute_type": str(compute_type),
            "beam_size": int(beam_size),
            "vad_filter": bool(vad_filter),
            "condition_on_previous_text": bool(condition_on_previous_text),
        }
    )
    if vad_filter:
        metadata["vad_parameters"] = dict(options["vad_parameters"])
    return cues, metadata
