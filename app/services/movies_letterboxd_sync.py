from __future__ import annotations

from html import escape
from typing import Optional

from telegram.constants import ParseMode
from telegram.ext import Application, ContextTypes

from app import db
from app.services import letterboxd_feed, movies_ui


async def process_letterboxd_for_user(
    application: Application,
    user_id: int,
    rss_url: str,
    last_guid: Optional[str],
    silent_if_no_new: bool = True,
) -> tuple[int, Optional[str], Optional[str]]:
    items, err = await letterboxd_feed.fetch_letterboxd_items(rss_url)
    if err:
        return 0, err, None
    newest = items[0]["guid"] if items else None
    if not last_guid:
        if newest:
            db.update_letterboxd_last_guid(user_id, newest)
        if not silent_if_no_new:
            return 0, None, "Синхронизировал текущие логи. Покажу только новые после привязки."
        return 0, None, None
    new_items = []
    for i in items:
        if last_guid and i["guid"] == last_guid:
            break
        new_items.append(i)
    new_count = 0
    for i in reversed(new_items):
        entry_id = db.save_letterboxd_entry_if_new(
            user_id=user_id,
            guid=i["guid"],
            film_title=i["film_title"],
            entry_title=i["entry_title"],
            entry_link=i["link"],
            published_at=i["published"],
            summary=i["summary"],
        )
        if not entry_id:
            continue
        new_count += 1
        lines = [f"Вижу, вы посмотрели <b>{escape(i['film_title'])}</b> 👀", "Хочешь разбор по фильму? Выбери кнопку ниже."]
        if i.get("link"):
            lines.insert(1, f"<a href=\"{escape(i['link'])}\">Открыть запись в Letterboxd</a>")
        await application.bot.send_message(
            chat_id=user_id,
            text="\n".join(lines),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=movies_ui.movie_action_keyboard(entry_id),
        )
    if newest:
        db.update_letterboxd_last_guid(user_id, newest)
    if new_count == 0 and not silent_if_no_new:
        return 0, None, "Пока без новых логов."
    return new_count, None, None


async def process_letterboxd_watchlist_for_user(
    application: Application,
    user_id: int,
    rss_url: str,
    last_guid: Optional[str],
    silent_if_no_new: bool = True,
) -> tuple[int, Optional[str], Optional[str]]:
    items, err = await letterboxd_feed.fetch_watchlist_items(rss_url)
    if err:
        return 0, err, None
    newest = items[0]["guid"] if items else None
    if not last_guid:
        if newest:
            db.update_letterboxd_last_watchlist_guid(user_id, newest)
        if not silent_if_no_new:
            return 0, None, "Синхронизировал текущий wishlist. Покажу только новые после привязки."
        return 0, None, None
    new_items = []
    for i in items:
        if last_guid and i["guid"] == last_guid:
            break
        new_items.append(i)
    new_count = 0
    for i in reversed(new_items):
        entry_id = db.save_letterboxd_entry_if_new(
            user_id=user_id,
            guid=f"wishlist:{i['guid']}",
            film_title=i["film_title"],
            entry_title=i["entry_title"],
            entry_link=i["link"],
            published_at=i["published"],
            summary=i["summary"],
        )
        if not entry_id:
            continue
        new_count += 1
        lines = [
            f"✨ Вижу, вы добавили в wishlist: <b>{escape(i['film_title'])}</b>",
            "Давайте подготовимся: изучим актеров и пару слов к фильму?",
        ]
        if i.get("link"):
            lines.insert(1, f"<a href=\"{escape(i['link'])}\">Открыть в Letterboxd</a>")
        await application.bot.send_message(
            chat_id=user_id,
            text="\n".join(lines),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=movies_ui.movie_action_keyboard(entry_id),
        )
    if newest:
        db.update_letterboxd_last_watchlist_guid(user_id, newest)
    if new_count == 0 and not silent_if_no_new:
        return 0, None, "Пока без новых фильмов в wishlist."
    return new_count, None, None


async def bind_letterboxd_rss_for_user(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    rss_url: str,
) -> tuple[bool, str]:
    items, err = await letterboxd_feed.fetch_letterboxd_items(rss_url)
    if err:
        return False, f"Не смог прочитать RSS: {err}"
    watchlist_rss = letterboxd_feed.derive_watchlist_rss_url(rss_url)
    db.set_letterboxd_subscription(user_id, rss_url, watchlist_rss)
    if items:
        db.update_letterboxd_last_guid(user_id, items[0]["guid"])
    if watchlist_rss:
        wl_items, _ = await letterboxd_feed.fetch_watchlist_items(watchlist_rss)
        if wl_items:
            db.update_letterboxd_last_watchlist_guid(user_id, wl_items[0]["guid"])
    return True, "Letterboxd привязан. Буду отслеживать новые логи и wishlist."
