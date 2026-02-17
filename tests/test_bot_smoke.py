from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import bot
from app import config


class BotSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._old_token = config.BOT_TOKEN
        self._old_db_path = config.DB_PATH
        self._tmp_dir = tempfile.TemporaryDirectory()
        config.DB_PATH = str(Path(self._tmp_dir.name) / "test.db")

    def tearDown(self) -> None:
        config.BOT_TOKEN = self._old_token
        config.DB_PATH = self._old_db_path
        self._tmp_dir.cleanup()

    def test_build_app_requires_token(self) -> None:
        config.BOT_TOKEN = ""
        with self.assertRaises(RuntimeError):
            bot.build_app()

    def test_build_app_success(self) -> None:
        config.BOT_TOKEN = "123456:TEST_TOKEN"
        app = bot.build_app()
        self.assertIsNotNone(app)
        self.assertIsNotNone(app.post_init)


if __name__ == "__main__":
    unittest.main()

