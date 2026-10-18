import json
import tempfile
import unittest
from pathlib import Path

from glow_settings import DEFAULT_TOL, read_glow_settings, write_glow_settings


class TestGlowSettings(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.file = Path(self.dir.name) / "settings" / "settings.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_missing_defaults(self):
        self.assertEqual(read_glow_settings(self.file), (None, DEFAULT_TOL))

    def test_saved_preset_restored(self):
        write_glow_settings((230, 90, 31), 55, self.file)
        self.assertEqual(read_glow_settings(self.file), ((230, 90, 31), 55))
        self.assertEqual(json.loads(self.file.read_text())["glow_rgb"], [230, 90, 31])

    def test_f7_removes_saved_preset_but_keeps_tolerance(self):
        write_glow_settings((230, 90, 31), 55, self.file)
        write_glow_settings(None, 55, self.file)
        self.assertEqual(read_glow_settings(self.file), (None, 55))

    def test_tolerance_persists(self):
        write_glow_settings((210, 75, 45), 45, self.file)
        write_glow_settings((210, 75, 45), 50, self.file)
        self.assertEqual(read_glow_settings(self.file), ((210, 75, 45), 50))

    def test_invalid_json_uses_defaults(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text("{not json", encoding="utf-8")
        self.assertEqual(read_glow_settings(self.file), (None, DEFAULT_TOL))

    def test_invalid_values_use_defaults(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text(json.dumps({"glow_rgb": [255, True, -1],
                                         "glow_tolerance": 999}), encoding="utf-8")
        self.assertEqual(read_glow_settings(self.file), (None, DEFAULT_TOL))

    def test_invalid_tolerance_rejected(self):
        with self.assertRaises(ValueError):
            write_glow_settings((230, 90, 31), 200, self.file)

    def test_save_error_does_not_override_existing_preset(self):
        write_glow_settings((230, 90, 31), 55, self.file)
        with self.assertRaises(ValueError):
            write_glow_settings((1, 2, 3), -10, self.file)
        self.assertEqual(read_glow_settings(self.file), ((230, 90, 31), 55))


if __name__ == "__main__":
    unittest.main()
