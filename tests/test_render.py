from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autovideo.errors import AutovideoError
from autovideo.render import render_video


class RenderTests(unittest.TestCase):
    def test_failed_rerender_preserves_previous_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            subtitle = root / "subtitle,with:metacharacters.ass"
            output = root / "final.mp4"
            source.write_bytes(b"source")
            subtitle.write_text("[Script Info]\n", encoding="utf-8")
            output.write_bytes(b"previous good render")

            def fail_after_writing(command, **_kwargs):
                Path(command[-1]).write_bytes(b"partial")
                raise subprocess.CalledProcessError(1, command)

            with (
                patch("autovideo.render.shutil.which", return_value="/usr/bin/ffmpeg"),
                patch("autovideo.render.subprocess.run", side_effect=fail_after_writing),
            ):
                with self.assertRaises(AutovideoError):
                    render_video(source, subtitle, output, {})

            self.assertEqual(output.read_bytes(), b"previous good render")
            self.assertEqual(list(root.glob("*.rendering.mp4")), [])

    def test_successful_render_atomically_replaces_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            subtitle = root / "subtitle.ass"
            output = root / "final.mp4"
            source.write_bytes(b"source")
            subtitle.write_text("[Script Info]\n", encoding="utf-8")
            output.write_bytes(b"old")

            def succeed(command, **kwargs):
                self.assertEqual(command[command.index("-vf") + 1], "ass=subtitle.ass")
                self.assertTrue((Path(kwargs["cwd"]) / "subtitle.ass").is_file())
                Path(command[-1]).write_bytes(b"new")
                return subprocess.CompletedProcess(command, 0)

            with (
                patch("autovideo.render.shutil.which", return_value="/usr/bin/ffmpeg"),
                patch("autovideo.render.subprocess.run", side_effect=succeed),
            ):
                returned = render_video(source, subtitle, output, {})

            self.assertEqual(returned, output.resolve())
            self.assertEqual(output.read_bytes(), b"new")


if __name__ == "__main__":
    unittest.main()
