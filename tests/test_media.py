from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autovideo.media import detect_silences, extract_audio


class MediaTests(unittest.TestCase):
    def test_extract_audio_uses_lossless_pcm_wav(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "video.mp4"
            output = Path(tmp) / "speech.wav"
            source.write_bytes(b"video")
            with (
                patch("autovideo.media.shutil.which", return_value="/usr/bin/ffmpeg"),
                patch(
                    "autovideo.media.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0),
                ) as run,
            ):
                extract_audio(source, output)
            command = run.call_args.args[0]

        self.assertEqual(command[command.index("-c:a") + 1], "pcm_s16le")
        self.assertNotIn("64k", command)

    def test_detect_silences_parses_closed_and_open_intervals(self) -> None:
        stderr = "\n".join(
            (
                "[silencedetect] silence_start: -0",
                "[silencedetect] silence_end: 1.25 | silence_duration: 1.25",
                "[silencedetect] silence_start: 9.5",
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.wav"
            audio.write_bytes(b"audio")
            with patch(
                "autovideo.media.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", stderr),
            ):
                intervals = detect_silences(audio, ffmpeg_bin="ffmpeg")

        self.assertEqual(intervals[0], (0.0, 1.25))
        self.assertEqual(intervals[1][0], 9.5)
        self.assertEqual(intervals[1][1], float("inf"))


if __name__ == "__main__":
    unittest.main()
