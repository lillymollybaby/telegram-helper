from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import config, db
from app.services import food_analysis, food_service
from tests.test_fakes import FakeContext, FakeUpdate


class FoodFlowSmokeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._old_db_path = config.DB_PATH
        self._tmp_dir = tempfile.TemporaryDirectory()
        config.DB_PATH = str(Path(self._tmp_dir.name) / "test.db")
        db.init_db()

    def tearDown(self) -> None:
        config.DB_PATH = self._old_db_path
        self._tmp_dir.cleanup()

    async def test_food_text_flow_saves_meal(self) -> None:
        update = FakeUpdate(user_id=100, text="гречка и курица")
        context = FakeContext()
        context.user_data[food_analysis.STATE_WAIT_MEAL] = True

        fake_analysis = {
            "meal_name": "гречка и курица",
            "calories_kcal": 520,
            "protein_g": 31.0,
            "fat_g": 12.0,
            "carbs_g": 67.0,
            "fiber_g": 4.0,
            "advice": ["Добавьте овощи."],
        }
        with patch("app.services.food_analysis.analyze_meal_text", new=AsyncMock(return_value=fake_analysis)):
            handled = await food_service.handle_text_input(update, context)

        self.assertTrue(handled)
        rows = db.list_food_meals(100)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["meal_text"], "гречка и курица")

    async def test_food_photo_flow_saves_meal(self) -> None:
        photo = [SimpleNamespace(file_id="ph1")]
        update = FakeUpdate(user_id=101, caption="обед", photo=photo)
        context = FakeContext()
        context.user_data[food_analysis.STATE_WAIT_MEAL] = True
        context.bot.files["ph1"] = b"image-bytes"

        fake_analysis = {
            "meal_name": "обед",
            "calories_kcal": 600,
            "protein_g": 25.0,
            "fat_g": 20.0,
            "carbs_g": 70.0,
            "fiber_g": 5.0,
            "advice": [],
        }
        with patch("app.services.food_analysis.analyze_meal_photo", new=AsyncMock(return_value=fake_analysis)):
            handled = await food_service.handle_photo_input(update, context)

        self.assertTrue(handled)
        rows = db.list_food_meals(101)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "photo")


if __name__ == "__main__":
    unittest.main()

