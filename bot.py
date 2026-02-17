from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, MessageHandler, filters

from app import config, db, food, movies, planner, profile
from app.services import navigation_service


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def build_app() -> Application:
    if not config.BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в .env")

    db.init_db()
    application = Application.builder().token(config.BOT_TOKEN).build()

    planner.register_handlers(application)
    movies.register_handlers(application)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, navigation_service.text_router))
    application.add_handler(MessageHandler(filters.PHOTO, navigation_service.photo_router))
    application.add_handler(MessageHandler(filters.LOCATION, navigation_service.location_router))

    async def post_init(app: Application) -> None:
        await planner.load_pending_jobs(app)
        app.job_queue.run_repeating(
            movies.poll_letterboxd_job,
            interval=max(10, config.LETTERBOXD_POLL_SECONDS),
            first=5,
            name="letterboxd_polling",
        )
        food.schedule_jobs(app)
        profile.schedule_jobs(app)

    application.post_init = post_init
    return application


def main() -> None:
    planner.ensure_event_loop()
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
