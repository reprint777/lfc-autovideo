from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autovideo.models import Cue
from autovideo.review import write_gap_review


class ReviewTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
