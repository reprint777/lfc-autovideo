from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autovideo.models import Cue
from autovideo.review import analyze_gaps, write_gap_review, write_recovery_review


class ReviewTests(unittest.TestCase):
    def test_gap_analysis_exposes_machine_readable_intervals(self) -> None:
        gaps = analyze_gaps(
            [Cue(0, 1, "One"), Cue(4, 5, "Two")],
            [(1, 3.8)],
            min_gap=2,
        )
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].status, "likely_silence")
        self.assertAlmostEqual(gaps[0].non_silent_seconds, 0.2)

    def test_gap_report_distinguishes_silence_from_audible_gaps(self) -> None:
        cues = [
            Cue(0, 1, "One"),
            Cue(4, 5, "Two"),
            Cue(9, 10, "Three"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "review.csv"
            with patch(
                "autovideo.review.detect_silences",
                return_value=[(1.0, 3.8)],
            ):
                path, suspicious = write_gap_review(
                    cues, "audio.wav", output, min_gap=2
                )
            text = path.read_text(encoding="utf-8-sig")

        self.assertEqual(suspicious, 1)
        self.assertIn("likely_silence", text)
        self.assertIn("check_content", text)

    def test_recovery_report_records_inserted_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_recovery_review(
                [
                    {
                        "gap_start": 10,
                        "gap_end": 20,
                        "cue_count": 1,
                        "word_count": 2,
                        "average_probability": "0.900",
                        "coverage_ratio": "0.700",
                        "text": "recovered words",
                    }
                ],
                Path(tmp) / "recovery.csv",
            )
            text = path.read_text(encoding="utf-8-sig")
        self.assertIn("recovered words", text)


if __name__ == "__main__":
    unittest.main()
