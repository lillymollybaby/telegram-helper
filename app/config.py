from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv(override=True)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "reminder.db")

DEFAULT_BUFFER_MIN = int(os.getenv("DEFAULT_BUFFER_MIN", "15"))
DEFAULT_REMIND_BEFORE_MIN = int(os.getenv("DEFAULT_REMIND_BEFORE_MIN", "30"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
ROUTING_PROVIDER = os.getenv("ROUTING_PROVIDER", "auto").strip().lower()
DGIS_API_KEY = os.getenv("DGIS_API_KEY", "").strip()
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "").strip()
YANDEX_ROUTING_API_KEY = os.getenv("YANDEX_ROUTING_API_KEY", "").strip()
YANDEX_DISTANCE_MATRIX_API_KEY = os.getenv("YANDEX_DISTANCE_MATRIX_API_KEY", "").strip()

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
OPENSUBTITLES_API_KEY = os.getenv("OPENSUBTITLES_API_KEY", "").strip()
LETTERBOXD_POLL_SECONDS = int(os.getenv("LETTERBOXD_POLL_SECONDS", "20"))
SCRIPT_DB_ROOT = os.getenv("SCRIPT_DB_ROOT", "").strip()
AUTO_DELETE_TRIGGER_MESSAGES = os.getenv("AUTO_DELETE_TRIGGER_MESSAGES", "1").strip().lower() in ("1", "true", "yes", "on")
AUTO_DELETE_DELAY_SEC = int(os.getenv("AUTO_DELETE_DELAY_SEC", "2"))
AUTO_DELETE_ALL_MESSAGES = os.getenv("AUTO_DELETE_ALL_MESSAGES", "1").strip().lower() in ("1", "true", "yes", "on")
AUTO_DELETE_ALL_DELAY_SEC = int(os.getenv("AUTO_DELETE_ALL_DELAY_SEC", "20"))

FOOD_DEFAULT_TIMEZONE = os.getenv("FOOD_DEFAULT_TIMEZONE", "Asia/Bishkek").strip()
FOOD_DINNER_HOUR = int(os.getenv("FOOD_DINNER_HOUR", "19"))
FOOD_REMINDER_INTERVAL_SEC = int(os.getenv("FOOD_REMINDER_INTERVAL_SEC", "300"))
FOOD_CALORIE_TARGET_DEFAULT = int(os.getenv("FOOD_CALORIE_TARGET_DEFAULT", "2000"))
GRAMMAR_A1A2_PDF = os.getenv("GRAMMAR_A1A2_PDF", "").strip()
GRAMMAR_B1B2_PDF = os.getenv("GRAMMAR_B1B2_PDF", "").strip()

BTN_LANGUAGE = "Language Learning"
BTN_MOVIES = "Movie"
BTN_PLANNER = "Personal Planning"
BTN_FOOD = "Food"
BTN_PROFILE = "Мой профиль"

BTN_MOVIES_BIND = "Link Letterboxd Account"
BTN_MOVIES_UNBIND = "Unlink Letterboxd Account"
BTN_MOVIES_CHECK = "Logged Movies"
BTN_MOVIES_CHECK_WISHLIST = "Wishlist"
BTN_MOVIES_ENGLISH = "Learn Words (Movie-related vocabulary)"
BTN_MOVIES_CREW = "Learn Crew (Actors, Directors, etc.)"
BTN_MOVIES_STATUS = "Account Status"
BTN_MOVIES_IMDB_LINK = "Link IMDb Account"
BTN_MOVIES_IMDB_UNLINK = "Unlink IMDb Account"
BTN_MOVIES_IMDB_MOVIES = "Movies"

BTN_MY_PLANS = "My Plans"
BTN_ACTIVE_PLANS = "Active Plans"
BTN_ALL_PLANS = "All Plans"

BTN_LANG_ENGLISH = "English"
BTN_LANG_FRENCH = "French"
BTN_LANG_GERMAN = "German"
BTN_LEVEL_A = "A1/A2"
BTN_LEVEL_B = "B1/B2"
BTN_LEVEL_C = "C1/C2"
BTN_SKILL_VOCAB = "Vocabulary"
BTN_SKILL_GRAMMAR = "Grammar"

BTN_EXAM_IELTS = "IELTS/TOEFL Preparation"
BTN_EXAM_IELTS_LISTEN = "Listening"
BTN_EXAM_IELTS_WRITE = "Writing"
BTN_EXAM_IELTS_READ = "Reading"
BTN_EXAM_DELF = "DELF/DALF Preparation"
BTN_EXAM_DELF_WRITE = "Production ecrite (Written Production)"
BTN_EXAM_DELF_READ = "Comprehension ecrite (Reading Comprehension)"
BTN_EXAM_DELF_LISTEN = "Comprehension orale (Listening Comprehension)"
BTN_EXAM_GOETHE = "Goethe-Zertifikat"
BTN_EXAM_GOETHE_H = "Horen"
BTN_EXAM_GOETHE_S = "Schreiben"
BTN_EXAM_GOETHE_L = "Lesen"

BTN_FOOD_DIARY = "Дневник и Анализ"
BTN_FOOD_COACH = "Советник / AI Coach"
BTN_FOOD_PROFILE = "Настройки профиля"

BTN_FOOD_ADD_MEAL = "Добавить прием пищи"
BTN_FOOD_DAY_SUMMARY = "Итоги дня"
BTN_FOOD_HISTORY = "История"

BTN_FOOD_DINNER = "Что съесть на ужин?"
BTN_FOOD_COMPOSITION = "Разбор состава"
BTN_FOOD_ASK_AI = "Вопрос к ИИ"

BTN_FOOD_PARAMS = "Мои параметры"
BTN_FOOD_GOAL = "Цель"
BTN_FOOD_REMINDERS = "Напоминания"

BTN_PROFILE_OVERVIEW = "Показать профиль"
BTN_PROFILE_EDIT = "Изменить профиль"
BTN_PROFILE_SLEEP = "Режим сна"
BTN_PROFILE_RESET = "Сбросить анкету"
BTN_PROFILE_START = "Начать настройку"
BTN_PROFILE_EDIT_NAME = "Изменить имя"
BTN_PROFILE_EDIT_HOME = "Изменить дом"
BTN_PROFILE_EDIT_WORK = "Изменить работу/учебу"
BTN_PROFILE_EDIT_BODY = "Изменить рост/вес"
BTN_PROFILE_EDIT_GOAL = "Изменить цель"
BTN_PROFILE_EDIT_SLEEP = "Изменить сон"
BTN_PROFILE_EDIT_WATER = "Настроить воду"

BTN_SLEEP_YES = "Да"
BTN_SLEEP_NO = "Нет"
BTN_SLEEP_LATER = "Напомнить позже"

BTN_WATER_YES = "Да, выпил"
BTN_WATER_NO = "Нет"

BTN_BACK_MOVIES = "Назад"
BTN_HOME_MENU = "Главное меню"

BTN_PLAN_USE_HOME = "Домашний адрес"
BTN_PLAN_SET_START = "Указать адрес"
BTN_PLAN_SHARE_GEO = "Текущий адрес (гео)"
BTN_PLAN_USE_DETECTED_DEST = "Использовать место из сообщения"
BTN_PLAN_USE_DETECTED_TIME = "Использовать время из сообщения"
