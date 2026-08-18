from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from autovideo.config import load_config, write_default_config
from autovideo.errors import AutovideoError


class ConfigTests(unittest.TestCase):
    def test_nested_override_keeps_other_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"transcription": {"model": "medium.en"}}))
            config = load_config(path)
        self.assertEqual(config["transcription"]["model"], "medium.en")
        self.assertEqual(config["transcription"]["language"], "en")
        self.assertTrue(config["transcription"]["gap_recovery"])
        self.assertIn("render", config)

    def test_invalid_json_is_user_facing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{")
            with self.assertRaises(AutovideoError):
                load_config(path)

    def test_default_config_does_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            write_default_config(path)
            with self.assertRaises(AutovideoError):
                write_default_config(path)


if __name__ == "__main__":
    unittest.main()
