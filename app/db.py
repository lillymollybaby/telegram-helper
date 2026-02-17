from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from app import config


@dataclass
class Task:
    id: int
    user_id: int
    text: str
    destination: Optional[str]
    event_time: datetime
    remind_time: datetime
    leave_time: Optional[datetime]
    taxi_order_time: Optional[datetime]
    status: str


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            home_address TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            destination TEXT,
            event_time TEXT NOT NULL,
            remind_time TEXT NOT NULL,
            leave_time TEXT,
            taxi_order_time TEXT,
            status TEXT NOT NULL DEFAULT 'scheduled'
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS letterboxd_subscriptions (
            user_id INTEGER PRIMARY KEY,
            rss_url TEXT NOT NULL,
            watchlist_rss_url TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_guid TEXT,
            last_watchlist_guid TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS letterboxd_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            guid TEXT NOT NULL,
            film_title TEXT NOT NULL,
            entry_title TEXT,
            entry_link TEXT,
            published_at TEXT,
            summary TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, guid)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS english_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            film_title TEXT NOT NULL,
            word TEXT NOT NULL,
            translation TEXT NOT NULL,
            example TEXT,
            next_review_at TEXT NOT NULL,
            interval_hours INTEGER NOT NULL DEFAULT 6,
            success_count INTEGER NOT NULL DEFAULT 0,
            fail_count INTEGER NOT NULL DEFAULT 0,
            last_result TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, film_title, word)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS subtitle_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title_key TEXT NOT NULL,
            year INTEGER,
            lines_json TEXT NOT NULL,
            source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(title_key, year)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS food_profiles (
            user_id INTEGER PRIMARY KEY,
            params_json TEXT,
            goal TEXT,
            timezone TEXT NOT NULL DEFAULT 'Asia/Bishkek',
            dinner_hour INTEGER NOT NULL DEFAULT 19,
            dinner_enabled INTEGER NOT NULL DEFAULT 1,
            last_dinner_nudge_date TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS food_meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            meal_text TEXT,
            meal_time TEXT NOT NULL,
            source TEXT,
            image_file_id TEXT,
            calories REAL,
            protein REAL,
            fat REAL,
            carbs REAL,
            fiber REAL,
            analysis_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            birth_date TEXT,
            age INTEGER,
            city TEXT,
            timezone TEXT NOT NULL DEFAULT 'Asia/Bishkek',
            home_address TEXT,
            work_address TEXT,
            height_cm REAL,
            weight_kg REAL,
            activity_level TEXT,
            goal TEXT,
            target_weight_kg REAL,
            dietary_restrictions TEXT,
            meals_per_day INTEGER,
            water_goal_ml INTEGER,
            sleep_time TEXT,
            wake_time TEXT,
            sleep_remind_before_min INTEGER NOT NULL DEFAULT 10,
            wake_remind_before_min INTEGER NOT NULL DEFAULT 10,
            reminders_enabled INTEGER NOT NULL DEFAULT 1,
            quiet_hours_start TEXT,
            quiet_hours_end TEXT,
            onboarding_completed INTEGER NOT NULL DEFAULT 0,
            last_sleep_nudge_date TEXT,
            last_wake_nudge_date TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS water_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount_ml INTEGER NOT NULL,
            logged_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def from_iso(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def set_home_address(user_id: int, address: str) -> None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (user_id, home_address)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET home_address = excluded.home_address
        """,
        (user_id, address),
    )
    conn.commit()
    conn.close()


def get_home_address(user_id: int) -> Optional[str]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT home_address FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["home_address"] if row and row["home_address"] else None


def save_task(
    user_id: int,
    text: str,
    destination: Optional[str],
    event_time: datetime,
    remind_time: datetime,
    leave_time: Optional[datetime],
    taxi_order_time: Optional[datetime],
) -> int:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO tasks (user_id, text, destination, event_time, remind_time, leave_time, taxi_order_time, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'scheduled')
        """,
        (user_id, text, destination, iso(event_time), iso(remind_time), iso(leave_time), iso(taxi_order_time)),
    )
    conn.commit()
    task_id = int(cur.lastrowid)
    conn.close()
    return task_id


def list_tasks_for_user(user_id: int) -> list[Task]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM tasks
        WHERE user_id = ? AND status = 'scheduled'
        ORDER BY event_time ASC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()

    return [
        Task(
            id=r["id"],
            user_id=r["user_id"],
            text=r["text"],
            destination=r["destination"],
            event_time=datetime.fromisoformat(r["event_time"]),
            remind_time=datetime.fromisoformat(r["remind_time"]),
            leave_time=from_iso(r["leave_time"]),
            taxi_order_time=from_iso(r["taxi_order_time"]),
            status=r["status"],
        )
        for r in rows
    ]


def delete_task(user_id: int, task_id: int) -> bool:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def delete_last_task(user_id: int) -> Optional[int]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM tasks
        WHERE user_id = ? AND status = 'scheduled'
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    task_id = int(row["id"])
    cur.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
    conn.commit()
    conn.close()
    return task_id


def mark_task_sent(task_id: int) -> None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET status = 'sent' WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()


def list_pending_tasks() -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE status = 'scheduled'")
    rows = cur.fetchall()
    conn.close()
    return rows


def get_letterboxd_subscription(user_id: int) -> Optional[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM letterboxd_subscriptions WHERE user_id = ? AND enabled = 1", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def set_letterboxd_subscription(user_id: int, rss_url: str, watchlist_rss_url: Optional[str]) -> None:
    now_iso = datetime.now().isoformat()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO letterboxd_subscriptions (user_id, rss_url, watchlist_rss_url, enabled, last_guid, last_watchlist_guid, created_at, updated_at)
        VALUES (?, ?, ?, 1, NULL, NULL, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            rss_url = excluded.rss_url,
            watchlist_rss_url = excluded.watchlist_rss_url,
            enabled = 1,
            updated_at = excluded.updated_at
        """,
        (user_id, rss_url, watchlist_rss_url, now_iso, now_iso),
    )
    conn.commit()
    conn.close()


def disable_letterboxd_subscription(user_id: int) -> bool:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE letterboxd_subscriptions SET enabled = 0, updated_at = ? WHERE user_id = ? AND enabled = 1",
        (datetime.now().isoformat(), user_id),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def update_letterboxd_last_guid(user_id: int, last_guid: str) -> None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE letterboxd_subscriptions SET last_guid = ?, updated_at = ? WHERE user_id = ?",
        (last_guid, datetime.now().isoformat(), user_id),
    )
    conn.commit()
    conn.close()


def update_letterboxd_last_watchlist_guid(user_id: int, last_guid: str) -> None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE letterboxd_subscriptions SET last_watchlist_guid = ?, updated_at = ? WHERE user_id = ?",
        (last_guid, datetime.now().isoformat(), user_id),
    )
    conn.commit()
    conn.close()


def list_letterboxd_subscriptions() -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM letterboxd_subscriptions WHERE enabled = 1")
    rows = cur.fetchall()
    conn.close()
    return rows


def save_letterboxd_entry_if_new(
    user_id: int,
    guid: str,
    film_title: str,
    entry_title: str,
    entry_link: Optional[str],
    published_at: Optional[str],
    summary: Optional[str],
) -> Optional[int]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO letterboxd_entries
        (user_id, guid, film_title, entry_title, entry_link, published_at, summary, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, guid, film_title, entry_title, entry_link, published_at, summary, datetime.now().isoformat()),
    )
    inserted = cur.rowcount > 0
    entry_id = int(cur.lastrowid) if inserted else None
    conn.commit()
    conn.close()
    return entry_id


def get_letterboxd_entry(entry_id: int, user_id: int) -> Optional[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM letterboxd_entries WHERE id = ? AND user_id = ?", (entry_id, user_id))
    row = cur.fetchone()
    conn.close()
    return row


def get_latest_film_title_for_user(user_id: int) -> Optional[str]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT film_title
        FROM letterboxd_entries
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row["film_title"] if row else None


def save_english_words(user_id: int, film_title: str, words: list[dict]) -> int:
    now = datetime.now()
    now_iso = now.isoformat()
    inserted = 0
    conn = db_connect()
    cur = conn.cursor()
    for w in words:
        word = str(w.get("word", "")).strip()
        translation = str(w.get("translation", "")).strip()
        example = str(w.get("example", "")).strip() or None
        if not word or not translation:
            continue
        cur.execute(
            """
            INSERT OR IGNORE INTO english_words
            (user_id, film_title, word, translation, example, next_review_at, interval_hours, success_count, fail_count, last_result, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 6, 0, 0, NULL, ?, ?)
            """,
            (user_id, film_title, word, translation, example, now_iso, now_iso, now_iso),
        )
        if cur.rowcount > 0:
            inserted += 1
    conn.commit()
    conn.close()
    return inserted


def get_due_english_word(user_id: int) -> Optional[sqlite3.Row]:
    now_iso = datetime.now().isoformat()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM english_words
        WHERE user_id = ? AND next_review_at <= ?
        ORDER BY fail_count DESC, next_review_at ASC, id ASC
        LIMIT 1
        """,
        (user_id, now_iso),
    )
    row = cur.fetchone()
    conn.close()
    return row


def get_any_english_word(user_id: int) -> Optional[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM english_words
        WHERE user_id = ?
        ORDER BY fail_count DESC, next_review_at ASC, id ASC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def get_english_word(word_id: int, user_id: int) -> Optional[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM english_words WHERE id = ? AND user_id = ?", (word_id, user_id))
    row = cur.fetchone()
    conn.close()
    return row


def update_english_word_review(word_id: int, user_id: int, result: str) -> None:
    row = get_english_word(word_id, user_id)
    if not row:
        return
    now = datetime.now()
    interval = int(row["interval_hours"] or 6)
    success = int(row["success_count"] or 0)
    fail = int(row["fail_count"] or 0)

    if result in {"learned", "correct"}:
        interval = min(max(6, interval * 2), 24 * 30)
        success += 1
        next_dt = now + timedelta(hours=interval)
    elif result == "hard":
        interval = max(2, interval // 2)
        fail += 1
        next_dt = now + timedelta(hours=2)
    else:
        # failed / wrong translation -> show often
        interval = 1
        fail += 1
        next_dt = now + timedelta(minutes=30)

    conn = db_connect()
    cur = conn.cursor()
    cur.execute( 
        """
        UPDATE english_words
        SET interval_hours = ?, success_count = ?, fail_count = ?, last_result = ?, next_review_at = ?, updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (interval, success, fail, result, next_dt.isoformat(), now.isoformat(), word_id, user_id),
    )
    conn.commit()
    conn.close()


def get_subtitle_cache(title_key: str, year: Optional[int]) -> Optional[list[str]]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT lines_json
        FROM subtitle_cache
        WHERE title_key = ? AND year IS ?
        LIMIT 1
        """,
        (title_key, year),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    try:
        data = json.loads(row["lines_json"])
        if isinstance(data, list):
            return [str(x) for x in data if str(x).strip()]
    except Exception:
        return None
    return None


def save_subtitle_cache(title_key: str, year: Optional[int], lines: list[str], source: Optional[str] = None) -> None:
    if not lines:
        return
    now_iso = datetime.now().isoformat()
    payload = json.dumps(lines, ensure_ascii=False)
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO subtitle_cache (title_key, year, lines_json, source, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(title_key, year) DO UPDATE SET
            lines_json = excluded.lines_json,
            source = COALESCE(excluded.source, subtitle_cache.source),
            updated_at = excluded.updated_at
        """,
        (title_key, year, payload, source, now_iso, now_iso),
    )
    conn.commit()
    conn.close()


def ensure_food_profile(user_id: int) -> None:
    now_iso = datetime.now().isoformat()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO food_profiles (user_id, params_json, goal, timezone, dinner_hour, dinner_enabled, last_dinner_nudge_date, created_at, updated_at)
        VALUES (?, NULL, NULL, ?, ?, 1, NULL, ?, ?)
        ON CONFLICT(user_id) DO NOTHING
        """,
        (user_id, config.FOOD_DEFAULT_TIMEZONE, config.FOOD_DINNER_HOUR, now_iso, now_iso),
    )
    conn.commit()
    conn.close()


def get_food_profile(user_id: int) -> sqlite3.Row:
    ensure_food_profile(user_id)
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM food_profiles WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def update_food_params(user_id: int, params: dict) -> None:
    ensure_food_profile(user_id)
    now_iso = datetime.now().isoformat()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE food_profiles
        SET params_json = ?, updated_at = ?
        WHERE user_id = ?
        """,
        (json.dumps(params, ensure_ascii=False), now_iso, user_id),
    )
    conn.commit()
    conn.close()


def update_food_goal(user_id: int, goal: str) -> None:
    ensure_food_profile(user_id)
    now_iso = datetime.now().isoformat()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE food_profiles
        SET goal = ?, updated_at = ?
        WHERE user_id = ?
        """,
        (goal, now_iso, user_id),
    )
    conn.commit()
    conn.close()


def update_food_reminder(user_id: int, dinner_hour: int, timezone_value: Optional[str] = None, enabled: bool = True) -> None:
    ensure_food_profile(user_id)
    now_iso = datetime.now().isoformat()
    tz = timezone_value or config.FOOD_DEFAULT_TIMEZONE
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE food_profiles
        SET dinner_hour = ?, timezone = ?, dinner_enabled = ?, updated_at = ?
        WHERE user_id = ?
        """,
        (int(dinner_hour), tz, 1 if enabled else 0, now_iso, user_id),
    )
    conn.commit()
    conn.close()


def save_food_meal(
    user_id: int,
    meal_text: str,
    meal_time: datetime,
    calories: Optional[float],
    protein: Optional[float],
    fat: Optional[float],
    carbs: Optional[float],
    fiber: Optional[float],
    analysis: Optional[dict],
    image_file_id: Optional[str] = None,
    source: str = "text",
) -> int:
    ensure_food_profile(user_id)
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO food_meals
        (user_id, meal_text, meal_time, source, image_file_id, calories, protein, fat, carbs, fiber, analysis_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            meal_text,
            meal_time.isoformat(),
            source,
            image_file_id,
            calories,
            protein,
            fat,
            carbs,
            fiber,
            json.dumps(analysis or {}, ensure_ascii=False),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    mid = int(cur.lastrowid)
    conn.close()
    return mid


def list_food_meals(user_id: int, limit: int = 20) -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM food_meals
        WHERE user_id = ?
        ORDER BY meal_time DESC, id DESC
        LIMIT ?
        """,
        (user_id, int(limit)),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def list_food_meals_for_date(user_id: int, date_iso: str) -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM food_meals
        WHERE user_id = ? AND substr(meal_time, 1, 10) = ?
        ORDER BY meal_time ASC, id ASC
        """,
        (user_id, date_iso),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_food_daily_totals(user_id: int, date_iso: str) -> dict:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COUNT(*) AS meals_count,
            COALESCE(SUM(calories), 0) AS calories,
            COALESCE(SUM(protein), 0) AS protein,
            COALESCE(SUM(fat), 0) AS fat,
            COALESCE(SUM(carbs), 0) AS carbs,
            COALESCE(SUM(fiber), 0) AS fiber
        FROM food_meals
        WHERE user_id = ? AND substr(meal_time, 1, 10) = ?
        """,
        (user_id, date_iso),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {"meals_count": 0, "calories": 0, "protein": 0, "fat": 0, "carbs": 0, "fiber": 0}


def list_food_profiles_for_reminders() -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM food_profiles WHERE dinner_enabled = 1")
    rows = cur.fetchall()
    conn.close()
    return rows


def mark_food_nudge_sent(user_id: int, date_iso: str) -> None:
    ensure_food_profile(user_id)
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE food_profiles SET last_dinner_nudge_date = ?, updated_at = ? WHERE user_id = ?",
        (date_iso, datetime.now().isoformat(), user_id),
    )
    conn.commit()
    conn.close()


def ensure_user_profile(user_id: int) -> None:
    now_iso = datetime.now().isoformat()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_profiles
        (user_id, timezone, sleep_remind_before_min, wake_remind_before_min, reminders_enabled, onboarding_completed, created_at, updated_at)
        VALUES (?, ?, 10, 10, 1, 0, ?, ?)
        ON CONFLICT(user_id) DO NOTHING
        """,
        (user_id, config.FOOD_DEFAULT_TIMEZONE, now_iso, now_iso),
    )
    conn.commit()
    conn.close()


def get_user_profile(user_id: int) -> sqlite3.Row:
    ensure_user_profile(user_id)
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def update_user_profile(user_id: int, **fields) -> None:
    ensure_user_profile(user_id)
    if not fields:
        return
    allowed = {
        "full_name",
        "birth_date",
        "age",
        "city",
        "timezone",
        "home_address",
        "work_address",
        "height_cm",
        "weight_kg",
        "activity_level",
        "goal",
        "target_weight_kg",
        "dietary_restrictions",
        "meals_per_day",
        "water_goal_ml",
        "sleep_time",
        "wake_time",
        "sleep_remind_before_min",
        "wake_remind_before_min",
        "reminders_enabled",
        "quiet_hours_start",
        "quiet_hours_end",
        "onboarding_completed",
        "last_sleep_nudge_date",
        "last_wake_nudge_date",
    }
    parts = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            parts.append(f"{k} = ?")
            vals.append(v)
    if not parts:
        return
    parts.append("updated_at = ?")
    vals.append(datetime.now().isoformat())
    vals.append(user_id)
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(f"UPDATE user_profiles SET {', '.join(parts)} WHERE user_id = ?", vals)
    conn.commit()
    conn.close()


def is_onboarding_completed(user_id: int) -> bool:
    row = get_user_profile(user_id)
    return bool(row and int(row["onboarding_completed"] or 0) == 1)


def reset_onboarding(user_id: int) -> None:
    update_user_profile(user_id, onboarding_completed=0)


def list_profiles_for_sleep_reminders() -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM user_profiles
        WHERE reminders_enabled = 1
          AND sleep_time IS NOT NULL
          AND wake_time IS NOT NULL
        """
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def list_profiles_for_water_reminders() -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM user_profiles
        WHERE reminders_enabled = 1
          AND water_goal_ml IS NOT NULL
          AND water_goal_ml > 0
        """
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def save_water_intake(user_id: int, amount_ml: int, logged_at: Optional[datetime] = None) -> int:
    ts = logged_at or datetime.now()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO water_logs (user_id, amount_ml, logged_at, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, int(amount_ml), ts.isoformat(), datetime.now().isoformat()),
    )
    conn.commit()
    wid = int(cur.lastrowid)
    conn.close()
    return wid


def get_water_daily_total(user_id: int, date_iso: str) -> int:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(SUM(amount_ml), 0) AS total_ml
        FROM water_logs
        WHERE user_id = ? AND substr(logged_at, 1, 10) = ?
        """,
        (user_id, date_iso),
    )
    row = cur.fetchone()
    conn.close()
    return int((row["total_ml"] if row else 0) or 0)
