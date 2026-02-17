from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app import config, db


class TaskDbSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._old_db_path = config.DB_PATH
        self._tmp_dir = tempfile.TemporaryDirectory()
        config.DB_PATH = str(Path(self._tmp_dir.name) / "test.db")
        db.init_db()

    def tearDown(self) -> None:
        config.DB_PATH = self._old_db_path
        self._tmp_dir.cleanup()

    def test_create_and_delete_task(self) -> None:
        event_time = datetime.now() + timedelta(hours=2)
        remind_time = event_time - timedelta(minutes=30)
        task_id = db.save_task(
            user_id=7,
            text="Проверка",
            destination="Бишкек, Киевская, 165",
            event_time=event_time,
            remind_time=remind_time,
            leave_time=None,
            taxi_order_time=None,
        )
        self.assertGreater(task_id, 0)
        tasks = db.list_tasks_for_user(7)
        self.assertEqual(len(tasks), 1)
        self.assertTrue(db.delete_task(7, task_id))
        self.assertEqual(len(db.list_tasks_for_user(7)), 0)

    def test_delete_last_task(self) -> None:
        base = datetime.now() + timedelta(hours=1)
        first = db.save_task(8, "A", None, base, base - timedelta(minutes=10), None, None)
        second = db.save_task(8, "B", None, base + timedelta(hours=1), base + timedelta(minutes=40), None, None)
        self.assertTrue(first < second)
        deleted = db.delete_last_task(8)
        self.assertEqual(deleted, second)
        remain = db.list_tasks_for_user(8)
        self.assertEqual(len(remain), 1)
        self.assertEqual(remain[0].id, first)


if __name__ == "__main__":
    unittest.main()

