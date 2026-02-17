from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import config, db
from app.services import profile_service
from tests.test_fakes import FakeContext, FakeUpdate


class ProfileOnboardingSmokeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._old_db_path = config.DB_PATH
        self._tmp_dir = tempfile.TemporaryDirectory()
        config.DB_PATH = str(Path(self._tmp_dir.name) / "test.db")
        db.init_db()

    def tearDown(self) -> None:
        config.DB_PATH = self._old_db_path
        self._tmp_dir.cleanup()

    async def test_onboarding_start_and_first_step(self) -> None:
        update = FakeUpdate(user_id=200, text="/start")
        context = FakeContext()

        started = await profile_service.start_onboarding(update, context, force=True)
        self.assertTrue(started)
        self.assertTrue(context.user_data.get(profile_service.PROFILE_STATE_KEY, {}).get("onboarding_active"))

        answer_update = FakeUpdate(user_id=200, text="Илья")
        answer_update.effective_message.replies = []
        answer_update.message = answer_update.effective_message
        answer_handled = await profile_service.handle_text(answer_update, context)
        self.assertTrue(answer_handled)

        state = context.user_data.get(profile_service.PROFILE_STATE_KEY, {})
        self.assertEqual(state.get("step"), 1)
        profile = db.get_user_profile(200)
        self.assertEqual(profile["full_name"], "Илья")


if __name__ == "__main__":
    unittest.main()

