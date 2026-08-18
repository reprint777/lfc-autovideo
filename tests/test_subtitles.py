from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from autovideo.models import Cue
from autovideo.review import GapReview
from autovideo.subtitles import (
    cue_source_digest,
    cue_timeline_digest,
    escape_ass_text,
    format_ass_timestamp,
    format_srt_timestamp,
    parse_timestamp,
    read_translation_csv,
    write_ass,
    write_srt,
    write_translation_csv,
)
from autovideo.transcribe import (
    build_cues_from_words,
    cues_from_segments,
    normalize_transcript_text,
    recover_suspicious_gaps,
    transcribe_local,
)


@dataclass
class Word:
    start: float | None
    end: float | None
    word: str
    probability: float = 0.9


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] | None = None


class SubtitleTests(unittest.TestCase):
    def test_timestamps_round_and_parse(self) -> None:
        self.assertEqual(format_srt_timestamp(3661.2346), "01:01:01,235")
        self.assertAlmostEqual(parse_timestamp("01:01:01,235"), 3661.235)
        self.assertEqual(format_ass_timestamp(61.239), "0:01:01.24")

    def test_srt_bilingual_and_english_fallback(self) -> None:
        cues = [
            Cue(0, 1.25, "Welcome to Anfield.", "欢迎来到安菲尔德。"),
            Cue(1.25, 2.5, "You'll Never Walk Alone."),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bilingual.srt"
            returned = write_srt(cues, output, bilingual=True)
            text = output.read_text(encoding="utf-8")
        self.assertEqual(returned, output)
        self.assertIn("欢迎来到安菲尔德。\nWelcome to Anfield.", text)
        self.assertIn("You'll Never Walk Alone.", text)
        self.assertNotIn("\n\n\nYou'll Never", text)

    def test_translation_csv_has_bom_and_round_trips_quoted_text(self) -> None:
        original = [
            Cue(0.125, 2.5, 'Hello, "Reds"\nagain', "你好，红军\n再次见面"),
            Cue(3, 4, "Second line"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "translation.csv"
            write_translation_csv(original, output)
            raw = output.read_bytes()
            loaded = read_translation_csv(output)
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(loaded, original)

    def test_translation_csv_rejects_extra_columns_and_missing_indices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "translation.csv"
            output.write_text(
                "index,start,end,english,chinese\n"
                "1,0,1,Hello,你好,被错误拆出的文本\n",
                encoding="utf-8-sig",
            )
            with self.assertRaisesRegex(ValueError, "extra column"):
                read_translation_csv(output)

            output.write_text(
                "index,start,end,english,chinese\n"
                "2,0,1,Hello,你好\n",
                encoding="utf-8-sig",
            )
            with self.assertRaisesRegex(ValueError, "expected index 1"):
                read_translation_csv(output)

            output.write_text(
                "index,start,end,english,chinese\n",
                encoding="utf-8-sig",
            )
            with self.assertRaisesRegex(ValueError, "no subtitle rows"):
                read_translation_csv(output)

    def test_source_digest_ignores_chinese_but_locks_timing_and_english(self) -> None:
        cues = [Cue(0.1234, 1.2346, "Hello", "你好")]
        translated = [Cue(0.123, 1.235, "Hello", "另一种翻译")]
        edited_english = [Cue(0.123, 1.235, "Changed", "你好")]
        self.assertEqual(cue_source_digest(cues), cue_source_digest(translated))
        self.assertNotEqual(cue_source_digest(cues), cue_source_digest(edited_english))

    def test_timeline_digest_allows_english_corrections(self) -> None:
        original = [Cue(0.123, 1.235, "Liver pool")]
        corrected = [Cue(0.123, 1.235, "Liverpool", "利物浦")]
        retimed = [Cue(0.2, 1.235, "Liverpool")]
        self.assertEqual(cue_timeline_digest(original), cue_timeline_digest(corrected))
        self.assertNotEqual(cue_timeline_digest(original), cue_timeline_digest(retimed))

    def test_zero_duration_cue_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be after"):
            Cue(1, 1, "No duration")

    def test_ass_escapes_override_syntax_and_uses_english_fallback(self) -> None:
        self.assertEqual(escape_ass_text("a\\b{c}\nd"), r"a\\b\{c\}\Nd")
        cues = [Cue(0, 1, r"Text {\pos(0,0)}"), Cue(1, 2, "English", "中文")]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "captions.ass"
            write_ass(cues, output)
            text = output.read_text(encoding="utf-8")
        self.assertIn(r"Text \{\\pos(0,0)\}", text)
        self.assertIn(r"中文\N{\fs32}English", text)
        self.assertNotIn(r"\NText \{", text)

    def test_word_timestamps_form_readable_cues(self) -> None:
        words = [
            Word(0, 0.3, "Hello"),
            Word(0.3, 0.6, " Liverpool"),
            Word(0.6, 1.1, " fans!"),
            Word(2.5, 2.8, "A"),
            Word(2.8, 3.2, " new"),
            Word(3.2, 3.5, " sentence."),
        ]
        cues = build_cues_from_words(words, max_gap=0.8)
        self.assertEqual([cue.english for cue in cues], ["Hello Liverpool fans!", "A new sentence."])
        self.assertEqual((cues[0].start, cues[0].end), (0.0, 1.1))

    def test_broken_compound_hyphens_are_normalized(self) -> None:
        self.assertEqual(
            normalize_transcript_text("a 30 -year -old right -winger — maybe"),
            "a 30-year-old right-winger — maybe",
        )
        words = [Word(0, 0.4, "right"), Word(0.4, 0.9, " -winger")]
        self.assertEqual(build_cues_from_words(words)[0].english, "right-winger")

    def test_segment_without_words_is_preserved(self) -> None:
        cues = cues_from_segments([Segment(0, 2, "Fallback segment", None)])
        self.assertEqual(cues, [Cue(0, 2, "Fallback segment")])

    def test_segment_with_partly_untimed_words_uses_full_segment_fallback(self) -> None:
        segment = Segment(
            0,
            2,
            "Nothing from this segment is dropped.",
            [Word(0, 0.5, "Nothing"), Word(None, None, " dropped")],  # type: ignore[arg-type]
        )
        self.assertEqual(
            cues_from_segments([segment]),
            [Cue(0, 2, "Nothing from this segment is dropped.")],
        )

    def test_shifted_gap_recovery_keeps_only_words_inside_original_gap(self) -> None:
        class RecoveryModel:
            calls: list[dict[str, object]] = []

            def transcribe(self, _path: str, **kwargs: object):
                self.calls.append(kwargs)
                segment = Segment(
                    8,
                    21,
                    "neighbor recovered words neighbor",
                    [
                        Word(9.0, 9.5, "neighbor"),
                        Word(10.5, 11.0, " recovered"),
                        Word(11.0, 12.0, " words"),
                        Word(20.2, 20.8, " neighbor"),
                    ],
                )
                return iter([segment]), object()

        model = RecoveryModel()
        original = [Cue(0, 10, "Before"), Cue(20, 25, "After")]
        gaps = [GapReview(1, 2, 10, 20, 0, 10, "check_content")]
        merged, items = recover_suspicious_gaps(
            model,
            "audio.wav",
            original,
            gaps,
            minimum_coverage_ratio=0.1,
        )

        self.assertEqual(
            [cue.english for cue in merged], ["Before", "recovered words", "After"]
        )
        self.assertEqual(len(items), 1)
        self.assertIsNone(model.calls[0]["no_speech_threshold"])
        self.assertEqual(model.calls[0]["clip_timestamps"], [8.5, 22.0])

    def test_faster_whisper_is_imported_only_when_transcribing(self) -> None:
        fake_segment = Segment(
            0,
            1.1,
            "Hello Liverpool fans!",
            [Word(0, 0.3, "Hello"), Word(0.3, 0.7, " Liverpool"), Word(0.7, 1.1, " fans!")],
        )

        class FakeInfo:
            language = "en"
            language_probability = 0.99
            duration = 1.1

        class FakeModel:
            init_args: tuple[object, ...] | None = None
            transcribe_options: dict[str, object] | None = None

            def __init__(self, *args: object, **kwargs: object) -> None:
                FakeModel.init_args = (args, kwargs)

            def transcribe(self, path: str, **kwargs: object):
                FakeModel.transcribe_options = kwargs
                return iter([fake_segment]), FakeInfo()

        fake_module = types.ModuleType("faster_whisper")
        fake_module.WhisperModel = FakeModel  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"faster_whisper": fake_module}):
            cues, info = transcribe_local(
                "input.mp4",
                model_size="small.en",
                device="cpu",
                compute_type="int8",
                initial_prompt="Liverpool FC",
                hotwords="Szoboszlai, Liverpool",
            )

        self.assertEqual(cues[0].english, "Hello Liverpool fans!")
        self.assertEqual(info["language"], "en")
        self.assertEqual(FakeModel.init_args, (("small.en",), {"device": "cpu", "compute_type": "int8"}))
        self.assertEqual(FakeModel.transcribe_options["word_timestamps"], True)
        self.assertEqual(FakeModel.transcribe_options["initial_prompt"], "Liverpool FC")
        self.assertEqual(
            FakeModel.transcribe_options["hotwords"], "Szoboszlai, Liverpool"
        )
        self.assertFalse(FakeModel.transcribe_options["condition_on_previous_text"])
        self.assertEqual(
            FakeModel.transcribe_options["vad_parameters"]["threshold"], 0.35
        )
        self.assertEqual(info["model"], "small.en")


if __name__ == "__main__":
    unittest.main()
