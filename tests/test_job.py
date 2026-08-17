from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autovideo.job import create_job, load_job, path_from_manifest, relative_to_job, set_state


class JobTests(unittest.TestCase):
    def test_job_roundtrip_and_state_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir, manifest = create_job(
                Path(tmp) / "jobs",
                "video.mp4",
                rights_confirmed=True,
                config={"sample": True},
            )
            set_state(job_dir, manifest, "transcribed")
            loaded = load_job(job_dir)
        self.assertEqual(loaded["state"], "transcribed")
        self.assertEqual(len(loaded["history"]), 2)
        self.assertTrue(loaded["rights_confirmed"])

    def test_relative_job_path_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / "job"
            file_path = job / "source" / "input.mp4"
            file_path.parent.mkdir(parents=True)
            file_path.touch()
            stored = relative_to_job(job, file_path)
            self.assertEqual(path_from_manifest(job, stored), file_path.resolve())


if __name__ == "__main__":
    unittest.main()
