"""Local-only speech transcription using faster-whisper.

``faster_whisper`` is imported inside :func:`transcribe_local`, so commands that
only render a previously translated CSV remain usable without the optional,
heavy transcription dependency installed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
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


def recover_suspicious_gaps(
    model: object,
    audio_path: str | Path,
    cues: Iterable[Cue],
    gaps: Iterable[object],
    *,
    language: str | None = "en",
    initial_prompt: str | None = None,
    hotwords: str | None = None,
    beam_size: int = 5,
    left_padding_seconds: Sequence[float] = (1.5, 6.0),
    right_padding_seconds: float = 2.0,
    minimum_probability: float = 0.45,
    minimum_coverage_ratio: float = 0.35,
    maximum_gap_seconds: float = 30.0,
    max_chars: int = 84,
    max_duration: float = 6.0,
) -> tuple[list[Cue], list[dict[str, object]]]:
    """Recover audible gaps with shifted local decoding windows.

    Whisper decoding is sensitive to its approximately 30-second window
    boundaries.  Trying a small set of padded starts can recover speech that a
    full-file pass skipped.  Only words whose midpoint is inside the original
    gap are retained, which prevents duplicated neighboring subtitles.
    """

    original = sorted(cues, key=lambda cue: (cue.start, cue.end))
    recovered: list[Cue] = []
    review_items: list[dict[str, object]] = []
    transcribe = getattr(model, "transcribe")

    for gap in gaps:
        if _value(gap, "status") != "check_content":
            continue
        gap_start = float(_value(gap, "start", 0.0))
        gap_end = float(_value(gap, "end", gap_start))
        gap_duration = gap_end - gap_start
        if gap_duration <= 0 or gap_duration > maximum_gap_seconds:
            continue

        best: tuple[tuple[float, float, int], list[Cue], int, float, float] | None = None
        for raw_padding in left_padding_seconds:
            clip_start = max(0.0, gap_start - max(0.0, float(raw_padding)))
            clip_end = gap_end + max(0.0, float(right_padding_seconds))
            options: dict[str, object] = {
                "word_timestamps": True,
                "vad_filter": False,
                "beam_size": int(beam_size),
                "condition_on_previous_text": False,
                "clip_timestamps": [clip_start, clip_end],
                # This recovery pass is already restricted to measured audible
                # gaps. Disable the decoder's independent silence shortcut.
                "no_speech_threshold": None,
                "temperature": 0.0,
            }
            if language:
                options["language"] = language
            if initial_prompt:
                options["initial_prompt"] = initial_prompt
            if hotwords:
                options["hotwords"] = hotwords

            segments, _info = transcribe(str(Path(audio_path).expanduser()), **options)
            selected_words: list[dict[str, object]] = []
            probabilities: list[float] = []
            for segment in segments:
                for word in list(_value(segment, "words", None) or []):
                    raw_start = _value(word, "start")
                    raw_end = _value(word, "end")
                    text = str(_value(word, "word", "") or "")
                    if raw_start is None or raw_end is None or not text.strip():
                        continue
                    word_start = float(raw_start)
                    word_end = float(raw_end)
                    midpoint = (word_start + word_end) / 2
                    if midpoint < gap_start or midpoint > gap_end:
                        continue
                    clipped_start = max(gap_start, word_start)
                    clipped_end = min(gap_end, word_end)
                    if clipped_end <= clipped_start:
                        continue
                    selected_words.append(
                        {"start": clipped_start, "end": clipped_end, "word": text}
                    )
                    probability = _value(word, "probability")
                    if probability is not None:
                        probabilities.append(float(probability))

            candidate = build_cues_from_words(
                selected_words,
                max_chars=max_chars,
                max_duration=max_duration,
            )
            word_count = len(selected_words)
            average_probability = (
                sum(probabilities) / len(probabilities) if probabilities else 0.5
            )
            coverage_ratio = (
                (candidate[-1].end - candidate[0].start) / gap_duration
                if candidate
                else 0.0
            )
            if (
                word_count < 2
                or average_probability < minimum_probability
                or coverage_ratio < minimum_coverage_ratio
            ):
                continue
            score = (coverage_ratio, average_probability, word_count)
            if best is None or score > best[0]:
                best = (
                    score,
                    candidate,
                    word_count,
                    average_probability,
                    coverage_ratio,
                )
            if coverage_ratio >= 0.75:
                break

        if best is None:
            continue
        _score, candidate, word_count, average_probability, coverage_ratio = best
        recovered.extend(candidate)
        review_items.append(
            {
                "gap_start": gap_start,
                "gap_end": gap_end,
                "cue_count": len(candidate),
                "word_count": word_count,
                "average_probability": f"{average_probability:.3f}",
                "coverage_ratio": f"{coverage_ratio:.3f}",
                "text": " ".join(cue.english for cue in candidate),
            }
        )

    merged = original + recovered
    merged.sort(key=lambda cue: (cue.start, cue.end))
    return merged, review_items


def repair_gaps_local(
    audio_path: str | Path,
    cues: Iterable[Cue],
    *,
    model_size: str = "medium.en",
    device: str = "auto",
    compute_type: str = "default",
    language: str | None = "en",
    initial_prompt: str | None = None,
    hotwords: str | None = None,
    beam_size: int = 5,
    gap_seconds: float = 2.0,
    silence_noise_db: float = -35.0,
    silence_min_duration: float = 0.6,
    left_padding_seconds: Sequence[float] = (1.5, 6.0),
    right_padding_seconds: float = 2.0,
    minimum_probability: float = 0.45,
    minimum_coverage_ratio: float = 0.35,
    maximum_gap_seconds: float = 30.0,
    max_chars: int = 84,
    max_duration: float = 6.0,
) -> tuple[list[Cue], list[dict[str, object]]]:
    """Repair gaps in an existing transcript without retranscribing the full file."""

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Local transcription requires faster-whisper. Install the project's "
            "transcription dependencies before running this command."
        ) from exc
    from .media import detect_silences
    from .review import analyze_gaps

    model = WhisperModel(str(model_size), device=str(device), compute_type=str(compute_type))
    silences = detect_silences(
        audio_path,
        noise_db=float(silence_noise_db),
        min_duration=float(silence_min_duration),
    )
    gaps = analyze_gaps(cues, silences, min_gap=float(gap_seconds))
    return recover_suspicious_gaps(
        model,
        audio_path,
        cues,
        gaps,
        language=language,
        initial_prompt=initial_prompt,
        hotwords=hotwords,
        beam_size=beam_size,
        left_padding_seconds=left_padding_seconds,
        right_padding_seconds=right_padding_seconds,
        minimum_probability=minimum_probability,
        minimum_coverage_ratio=minimum_coverage_ratio,
        maximum_gap_seconds=maximum_gap_seconds,
        max_chars=max_chars,
        max_duration=max_duration,
    )


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
    recover_gaps: bool = True,
    recovery_gap_seconds: float = 2.0,
    recovery_silence_noise_db: float = -35.0,
    recovery_silence_min_duration: float = 0.6,
    recovery_left_padding_seconds: Sequence[float] = (1.5, 6.0),
    recovery_right_padding_seconds: float = 2.0,
    recovery_min_probability: float = 0.45,
    recovery_min_coverage_ratio: float = 0.35,
    recovery_max_gap_seconds: float = 30.0,
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
    recovery_items: list[dict[str, object]] = []
    if recover_gaps and cues:
        try:
            from .media import detect_silences
            from .review import analyze_gaps

            silences = detect_silences(
                audio_path,
                noise_db=float(recovery_silence_noise_db),
                min_duration=float(recovery_silence_min_duration),
            )
            gaps = analyze_gaps(
                cues,
                silences,
                min_gap=float(recovery_gap_seconds),
            )
            cues, recovery_items = recover_suspicious_gaps(
                model,
                audio_path,
                cues,
                gaps,
                language=language,
                initial_prompt=initial_prompt,
                hotwords=hotwords,
                beam_size=beam_size,
                left_padding_seconds=recovery_left_padding_seconds,
                right_padding_seconds=recovery_right_padding_seconds,
                minimum_probability=recovery_min_probability,
                minimum_coverage_ratio=recovery_min_coverage_ratio,
                maximum_gap_seconds=recovery_max_gap_seconds,
                max_chars=max_chars,
                max_duration=max_duration,
            )
        except Exception as exc:  # Recovery must not discard the primary transcript.
            metadata["recovery_error"] = str(exc)
    metadata.update(
        {
            "model": str(model_size),
            "device": str(device),
            "compute_type": str(compute_type),
            "beam_size": int(beam_size),
            "vad_filter": bool(vad_filter),
            "condition_on_previous_text": bool(condition_on_previous_text),
            "gap_recovery": bool(recover_gaps),
            "recovered_gap_count": len(recovery_items),
        }
    )
    # Keep detailed recovered text out of job.json; the pipeline exports it to CSV.
    metadata["recovery_items"] = recovery_items
    metadata["recovered_cue_count"] = sum(
        int(item["cue_count"]) for item in recovery_items
    )
    if vad_filter:
        metadata["vad_parameters"] = dict(options["vad_parameters"])
    return cues, metadata
