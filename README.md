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
- `GRAMMAR_A1A2_PDF` (путь к PDF-учебнику Grammar для A1/A2)
- `GRAMMAR_B1B2_PDF` (путь к PDF-учебнику Grammar для B1/B2)

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

## Grammar Data
- Для `English + A1/A2 + Grammar` и `English + B1/B2 + Grammar` бот умеет брать темы прямо из PDF (оглавление) и отправлять фрагмент страницы по выбранной теме.
- Укажите путь к книгам в `.env`: `GRAMMAR_A1A2_PDF=...`, `GRAMMAR_B1B2_PDF=...`.
- Grammar-темы читаются из JSON:
  - `app/language/grammar_data/en/a1.json ... c2.json`
  - `app/language/grammar_data/fr/a1.json ... c2.json`
  - `app/language/grammar_data/de/a1.json ... c2.json`
- Формат темы:
```json
{
  "topics": [
    {
      "title": "Present Simple",
      "rule": "Use base verb for habits and facts.",
      "examples": [
        "I work every day.",
        "She likes coffee."
      ]
    }
  ]
}
```
