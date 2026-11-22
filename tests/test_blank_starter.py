"""Tests for the empty starter state."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from bot import config
from bot.bot import Bot

class _Screen:
    def screenshot(self):
        return np.zeros((900, 1600, 3), dtype=np.uint8)

class BlankStarterTest(unittest.TestCase):
    def test_buttons_file_with_only_meta_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "buttons.json"
            path.write_text('{"_meta": {"base_resolution": [1600, 900]}}',
                            encoding="utf-8")
            with mock.patch.object(config, "BUTTONS_FILE", path):
                buttons, meta = config.read_buttons_file()
        self.assertEqual(buttons, {})
        self.assertEqual(tuple(meta.get("base_resolution", ())), (1600, 900))

    def test_bot_fits_a_screen_with_no_buttons(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("bot.bot.read_buttons_file",
                            return_value=({}, {"base_resolution": [1600, 900]})), \
                 mock.patch("bot.bot.TEMPLATES_DIR", Path(tmp)):
                bot = Bot(_Screen(), autofit=True, log=lambda _m: None)
                info = bot.fit_to_screen()
        self.assertEqual(info["source"], "native")
        self.assertEqual(info["scale"], 1.0)
        self.assertEqual((bot.screen_w, bot.screen_h), (1600, 900))
