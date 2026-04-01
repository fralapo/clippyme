import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app
import editor


class MainModuleSmokeTests(unittest.TestCase):
    def test_main_py_compiles(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        compile(source, str(ROOT / "main.py"), "exec")


class ConfigPersistenceTests(unittest.TestCase):
    def test_save_persistent_config_filters_unknown_keys_and_clears_deleted_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            with patch.dict(os.environ, {"YOUTUBE_COOKIES": "stale-cookie"}, clear=False):
                with patch.object(app, "CONFIG_FILE", str(config_path)):
                    self.assertTrue(
                        app.save_persistent_config(
                            {"YOUTUBE_COOKIES": "fresh-cookie", "BAD_KEY": "ignore-me"}
                        )
                    )

                    with config_path.open("r", encoding="utf-8") as handle:
                        data = json.load(handle)

                    self.assertEqual(data["YOUTUBE_COOKIES"], "fresh-cookie")
                    self.assertNotIn("BAD_KEY", data)
                    self.assertEqual(os.environ["YOUTUBE_COOKIES"], "fresh-cookie")

                    self.assertTrue(app.save_persistent_config({"YOUTUBE_COOKIES": ""}))
                    self.assertNotIn("YOUTUBE_COOKIES", os.environ)

    def test_is_trusted_origin_defaults_to_local_dashboard_origins(self):
        self.assertTrue(app.is_trusted_origin("http://localhost:5175"))
        self.assertTrue(app.is_trusted_origin("http://127.0.0.1:5173"))
        self.assertFalse(app.is_trusted_origin("https://evil.example"))


class EditPathTests(unittest.TestCase):
    def test_build_edit_temp_paths_are_unique(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = app.build_edit_temp_paths("job-123", temp_dir)
            second = app.build_edit_temp_paths("job-123", temp_dir)

            self.assertNotEqual(first["input_path"], second["input_path"])
            self.assertNotEqual(first["output_path"], second["output_path"])
            self.assertTrue(first["input_path"].startswith(temp_dir))
            self.assertTrue(first["output_path"].startswith(temp_dir))


class UploadPollingTests(unittest.TestCase):
    def test_wait_for_uploaded_file_ready_times_out(self):
        def always_processing(_name):
            return SimpleNamespace(state="PROCESSING")

        with self.assertRaises(TimeoutError):
            editor.wait_for_uploaded_file_ready(
                always_processing,
                "file-123",
                timeout_seconds=0.01,
                poll_interval_seconds=0,
            )

    def test_wait_for_uploaded_file_ready_returns_when_active(self):
        states = iter(
            [
                SimpleNamespace(state="PROCESSING"),
                SimpleNamespace(state="ACTIVE"),
            ]
        )

        def next_state(_name):
            return next(states)

        info = editor.wait_for_uploaded_file_ready(
            next_state,
            "file-123",
            timeout_seconds=1,
            poll_interval_seconds=0,
        )

        self.assertEqual(info.state, "ACTIVE")


if __name__ == "__main__":
    unittest.main()
