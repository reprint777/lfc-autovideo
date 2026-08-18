from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autovideo.config import load_config
from autovideo.errors import AutovideoError
from autovideo.job import create_job, load_job, relative_to_job, save_job
from autovideo.models import Cue
from autovideo.pipeline import prepare_job, render_job, retranscribe_job
from autovideo.subtitles import write_translation_csv
from autovideo.subtitles import cue_timeline_digest


class PipelineTests(unittest.TestCase):
    def test_prepare_local_source_writes_manual_translation_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_video = root / "input.mp4"
            input_video.write_bytes(b"input")
            config = load_config()
            config["jobs_dir"] = str(root / "jobs")

            def fake_prepare(_spec, job_dir, max_height=1080):
                target = Path(job_dir) / "source" / "input.mp4"
                target.write_bytes(b"video")
                return target, {"max_height": max_height}

            def fake_extract(_source, output):
                Path(output).write_bytes(b"audio")
                return Path(output)

            cues = [Cue(0.0, 1.5, "Liverpool played well."), Cue(1.5, 3.0, "We go again.")]
            with (
                patch("autovideo.sources.prepare_source", side_effect=fake_prepare),
                patch("autovideo.media.extract_audio", side_effect=fake_extract),
                patch(
                    "autovideo.pipeline.transcribe_local",
                    return_value=(cues, {"language": "en"}),
                ),
            ):
                job_dir, manifest = prepare_job(
                    str(input_video), config, rights_confirmed=True
                )

            self.assertEqual(manifest["state"], "waiting_for_translation")
            self.assertTrue((job_dir / "subtitles" / "transcript.en.srt").is_file())
            self.assertTrue((job_dir / "subtitles" / "translation.csv").is_file())
            self.assertIn("cue_count", manifest["transcription"])

    def test_prepare_requires_rights_confirmation(self) -> None:
        with self.assertRaises(AutovideoError):
            prepare_job("anything", load_config(), rights_confirmed=False)

    def test_render_blocks_missing_translation_then_renders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config()
            job_dir, manifest = create_job(
                root / "jobs",
                "input.mp4",
                rights_confirmed=True,
                config=config,
            )
            source = job_dir / "source" / "input.mp4"
            source.write_bytes(b"video")
            csv_path = job_dir / "subtitles" / "translation.csv"
            cues = [Cue(0, 1, "Hello"), Cue(1, 2, "Liverpool", "利物浦")]
            write_translation_csv(cues, csv_path)
            manifest["paths"] = {
                "source_video": relative_to_job(job_dir, source),
                "translation_csv": relative_to_job(job_dir, csv_path),
            }
            save_job(job_dir, manifest)

            with self.assertRaises(AutovideoError):
                render_job(job_dir)
            self.assertEqual(load_job(job_dir)["state"], "waiting_for_translation")

            cues[0].chinese = "你好"
            write_translation_csv(cues, csv_path)

            def fake_render(_source, _ass, output, _config):
                Path(output).write_bytes(b"rendered")
                return Path(output)

            with patch("autovideo.pipeline.render_video", side_effect=fake_render):
                output, rendered_manifest, missing = render_job(job_dir)

            self.assertEqual(missing, 0)
            self.assertEqual(output.read_bytes(), b"rendered")
            self.assertEqual(rendered_manifest["state"], "completed")
            ass = (job_dir / "subtitles" / "subtitle.bilingual.ass").read_text()
            self.assertIn("你好", ass)
            self.assertIn("Hello", ass)
            self.assertEqual(load_job(job_dir)["state"], "completed")

    def test_render_allows_edited_english_but_locks_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config()
            job_dir, manifest = create_job(
                root / "jobs", "input.mp4", rights_confirmed=True, config=config
            )
            source = job_dir / "source" / "video.mp4"
            source.write_bytes(b"video")
            original = [Cue(0, 1, "Original", "原文")]
            csv_path = job_dir / "subtitles" / "translation.csv"
            write_translation_csv([Cue(0, 1, "Changed", "译文")], csv_path)
            manifest["paths"] = {
                "source_video": relative_to_job(job_dir, source),
                "translation_csv": relative_to_job(job_dir, csv_path),
            }
            manifest["transcription"] = {
                "cue_count": 1,
                "cue_timeline_sha256": cue_timeline_digest(original),
            }
            save_job(job_dir, manifest)

            def fake_render(_source, _ass, output, _config):
                Path(output).write_bytes(b"rendered")
                return Path(output)

            with patch("autovideo.pipeline.render_video", side_effect=fake_render):
                output, _, _ = render_job(job_dir)
            self.assertEqual(output.read_bytes(), b"rendered")

            write_translation_csv([Cue(0.1, 1, "Changed", "译文")], csv_path)
            with self.assertRaisesRegex(AutovideoError, "时间轴已被修改"):
                render_job(job_dir)
            self.assertEqual(load_job(job_dir)["state"], "translation_needs_attention")

    def test_retranscribe_reuses_audio_and_backs_up_previous_subtitles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config()
            job_dir, manifest = create_job(
                root / "jobs", "input.mp4", rights_confirmed=True, config=config
            )
            audio = job_dir / "audio" / "speech.m4a"
            audio.write_bytes(b"old audio")
            previous = job_dir / "subtitles" / "translation.csv"
            write_translation_csv([Cue(0, 1, "Old", "旧")], previous)
            manifest["paths"] = {
                "audio": relative_to_job(job_dir, audio),
                "translation_csv": relative_to_job(job_dir, previous),
            }
            save_job(job_dir, manifest)

            cues = [Cue(0, 1.2, "New transcript")]
            with (
                patch(
                    "autovideo.pipeline.transcribe_local",
                    return_value=(cues, {"language": "en"}),
                ) as transcribe,
                patch(
                    "autovideo.review.detect_silences", return_value=[]
                ),
            ):
                _, updated, backup = retranscribe_job(job_dir, config)

            self.assertIsNotNone(backup)
            self.assertTrue((backup / "translation.csv").is_file())  # type: ignore[operator]
            self.assertIn("New transcript", previous.read_text(encoding="utf-8-sig"))
            self.assertEqual(updated["state"], "waiting_for_translation")
            transcribe.assert_called_once()


if __name__ == "__main__":
    unittest.main()
