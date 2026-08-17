from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autovideo.errors import AutovideoError
from autovideo.sources import SourceKind, prepare_source, resolve_source


class ResolveSourceTests(unittest.TestCase):
    def test_youtube_watch_and_short_urls(self) -> None:
        for value in (
            "https://www.youtube.com/watch?v=abcdefghijk",
            "https://youtu.be/abcdefghijk",
            "youtube.com/shorts/abcdefghijk",
        ):
            with self.subTest(value=value):
                spec = resolve_source(value)
                self.assertEqual(spec.kind, SourceKind.YOUTUBE)
                self.assertIsNone(spec.path)

    def test_playlist_and_other_remote_hosts_are_rejected(self) -> None:
        for value in (
            "https://www.youtube.com/playlist?list=PL123",
            "https://example.com/video.mp4",
            "https://youtube.com.evil.example/watch?v=abcdefghijk",
        ):
            with self.subTest(value=value):
                with self.assertRaises(AutovideoError):
                    resolve_source(value)

    def test_existing_local_file_is_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "input video.mp4"
            video.write_bytes(b"placeholder")
            spec = resolve_source(video)
        self.assertEqual(spec.kind, SourceKind.LOCAL)
        self.assertEqual(spec.path, video.resolve())

    def test_missing_local_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AutovideoError):
                resolve_source(Path(tmp) / "missing.mp4")


class PrepareSourceTests(unittest.TestCase):
    def test_local_source_is_copied_and_info_is_written(self) -> None:
        metadata = {"format": {"duration": "12.5"}, "streams": []}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "outside" / "clip.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video bytes")
            spec = resolve_source(source)

            with patch("autovideo.sources.probe_media", return_value=metadata) as probe:
                video, actual_metadata = prepare_source(spec, root / "job")

            self.assertEqual(video, (root / "job" / "source" / "video.mp4").resolve())
            self.assertEqual(video.read_bytes(), b"video bytes")
            self.assertEqual(actual_metadata, metadata)
            probe.assert_called_once_with(video)
            info = json.loads((root / "job" / "source" / "info.json").read_text())
            self.assertEqual(info["source_type"], "local")
            self.assertEqual(info["stored_filename"], "video.mp4")
            self.assertEqual(info["ffprobe"], metadata)

    def test_local_source_name_cannot_overwrite_metadata(self) -> None:
        metadata = {"format": {}, "streams": []}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "info.json"
            source.write_bytes(b"video bytes despite the name")
            spec = resolve_source(source)

            with patch("autovideo.sources.probe_media", return_value=metadata):
                video, _ = prepare_source(spec, root / "job")

            self.assertEqual(video.name, "video.json")
            self.assertEqual(video.read_bytes(), b"video bytes despite the name")
            info = json.loads((root / "job" / "source" / "info.json").read_text())
            self.assertEqual(info["stored_filename"], "video.json")


if __name__ == "__main__":
    unittest.main()
