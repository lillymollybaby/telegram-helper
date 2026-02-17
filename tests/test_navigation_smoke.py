from __future__ import annotations

import unittest

from app import config
from app.services import navigation_service
from tests.test_fakes import FakeContext, FakeUpdate


class NavigationSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_home_button_opens_main_menu(self) -> None:
        update = FakeUpdate(text=config.BTN_HOME_MENU)
        context = FakeContext()
        context.user_data["screen"] = "food_diary"

        handled = await navigation_service.handle_navigation(update, context)

        self.assertTrue(handled)
        self.assertEqual(context.user_data.get("screen"), "main")
        self.assertTrue(update.effective_message.replies)
        self.assertIn("Main Menu", update.effective_message.replies[-1]["text"])


if __name__ == "__main__":
    unittest.main()

