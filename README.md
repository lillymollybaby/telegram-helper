# TG Reminder Bot

## Структура
- `bot.py` — точка входа и роутер сообщений.
- `app/config.py` — все env-переменные и текст кнопок.
- `app/keyboards.py` — клавиатуры Telegram.
- `app/db.py` — SQLite-модели и CRUD.
- `app/planner.py` — планы/напоминания/маршруты.
- `app/movies.py` — Letterboxd RSS/wishlist, TMDB, кнопки по фильмам.

## Запуск
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python bot.py
```

## Деплой на Render (Background Worker)
1. Загрузите проект в GitHub (без `.env` и без `reminder.db`).
2. В Render: `New` -> `Background Worker`.
3. Подключите репозиторий.
4. Либо используйте `render.yaml` (автоконфиг), либо вручную:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`
5. Заполните переменные окружения из `.env.example` в панели Render.
6. Нажмите `Deploy`.

Примечание:
- `SQLite` (`reminder.db`) на free-плане Render может сбрасываться после redeploy/restart.
- Для постоянного хранения лучше перейти на внешний Postgres/Supabase.

## Основные env
- `BOT_TOKEN`
- `GEMINI_API_KEY`
- `TMDB_API_KEY`
- `GOOGLE_MAPS_API_KEY`
- `DGIS_API_KEY`
- `ROUTING_PROVIDER=auto|google|dgis|yandex|yandex_matrix`
- `YANDEX_API_KEY`
- `YANDEX_ROUTING_API_KEY`
- `YANDEX_DISTANCE_MATRIX_API_KEY`
- `LETTERBOXD_POLL_SECONDS` (например `20`)
- `SCRIPT_DB_ROOT` (путь к `Movie-Script-Database` корню)
- `AUTO_DELETE_TRIGGER_MESSAGES=1` (авто-удалять служебные сообщения-вызовы)
- `AUTO_DELETE_DELAY_SEC=2` (через сколько секунд удалять вызов)
- `FOOD_DEFAULT_TIMEZONE=Asia/Bishkek`
- `FOOD_DINNER_HOUR=19`
- `FOOD_REMINDER_INTERVAL_SEC=300`
- `FOOD_CALORIE_TARGET_DEFAULT=2000`

## Поведение
- Кнопка `Планировщик`: задачи и напоминания.
- Кнопка `Фильмы`: привязка Letterboxd, проверка логов и wishlist.
- При новом фильме: реакция + inline-кнопки `Актеры и режиссер` / `Факты` / `English`.
- Wishlist `403` (Cloudflare) обрабатывается fallback-ом через HTML-страницу.
- English-слова стараются браться из диалогов фильма: сначала `parsed/dialogue`, если нет - из `unprocessed/imsdb`.
- Если Gemini временно недоступен или уперся в лимит, слова генерируются локальным fallback из диалогов + встроенного словаря.
- Ветка `Food`:
  - `Добавить прием пищи`: текст или фото, оценка ккал/БЖУ, сохранение даты/времени.
  - `Итоги дня` и `История`: суммарные показатели и список приемов.
  - Авто-напоминание за час до ужина с учетом того, что уже съедено.
