from __future__ import annotations

from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def movie_action_keyboard(entry_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Актеры и режиссер", callback_data=f"mv:people:{entry_id}"),
                InlineKeyboardButton("Факты", callback_data=f"mv:facts:{entry_id}"),
            ],
            [InlineKeyboardButton("English", callback_data=f"mv:en:{entry_id}")],
            [InlineKeyboardButton("Главное меню", callback_data=f"mv:home:{entry_id}")],
        ]
    )


def movie_back_keyboard(entry_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Назад", callback_data=f"mv:menu:{entry_id}")],
            [InlineKeyboardButton("Главное меню", callback_data=f"mv:home:{entry_id}")],
        ]
    )


def words_keyboard(entry_id: int, page: int = 0, total_pages: int = 1) -> InlineKeyboardMarkup:
    """Keyboard for word list navigation."""
    buttons = []
    
    # Navigation buttons if multiple pages
    if total_pages > 1:
        prev_page = page - 1 if page > 0 else total_pages - 1
        next_page = (page + 1) % total_pages
        buttons.append([
            InlineKeyboardButton("⬅️ Назад", callback_data=f"mv:words:{entry_id}:{prev_page}"),
            InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data=f"mv:words:{entry_id}:{page}"),
            InlineKeyboardButton("Вперед ➡️", callback_data=f"mv:words:{entry_id}:{next_page}"),
        ])
    
    # Back buttons
    buttons.append([InlineKeyboardButton("Назад к фильму", callback_data=f"mv:menu:{entry_id}")])
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data=f"mv:home:{entry_id}")])
    
    return InlineKeyboardMarkup(buttons)


def people_carousel_keyboard(entry_id: int, idx: int, total: int) -> InlineKeyboardMarkup:
    if total <= 1:
        return movie_back_keyboard(entry_id)
    prev_idx = (idx - 1) % total
    next_idx = (idx + 1) % total
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅️", callback_data=f"mvp:{entry_id}:{prev_idx}"),
                InlineKeyboardButton(f"{idx + 1}/{total}", callback_data=f"mvp:{entry_id}:{idx}"),
                InlineKeyboardButton("➡️", callback_data=f"mvp:{entry_id}:{next_idx}"),
            ],
            [InlineKeyboardButton("Назад", callback_data=f"mv:menu:{entry_id}")],
            [InlineKeyboardButton("Главное меню", callback_data=f"mv:home:{entry_id}")],
        ]
    )


def english_word_keyboard(word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Показать перевод", callback_data=f"eng:show:{word_id}"),
                InlineKeyboardButton("❌ Не выучил", callback_data=f"eng:hard:{word_id}"),
            ],
            [
                InlineKeyboardButton("✅ Выучил", callback_data=f"eng:learned:{word_id}"),
                InlineKeyboardButton("➡️ Следующее", callback_data=f"eng:next:{word_id}"),
            ],
            [
                InlineKeyboardButton("Назад", callback_data="eng:menu:0"),
                InlineKeyboardButton("Главное меню", callback_data="eng:home:0"),
            ],
        ]
    )


def english_word_card_text(row: dict, reveal: bool = False) -> str:
    film = row.get("film_title", "Фильм")
    word = row.get("word", "")
    translation = row.get("translation", "")
    example = row.get("example") or ""
    lines = [
        f"📘 <b>English по фильму {escape(film)}</b>",
        "",
        f"<b>Word:</b> {escape(word)}",
    ]
    if reveal:
        lines.append(f"<b>Перевод:</b> {escape(translation)}")
    else:
        lines.append("<b>Перевод:</b> ❓ (введи в чат или нажми 'Показать перевод')")
    if example:
        lines.append("")
        lines.append(f"<b>Example:</b> {escape(example)}")
    return "\n".join(lines)


def build_english_text(film_title: str, lesson: dict) -> str:
    lines = [f"🇬🇧 <b>English по фильму {escape(film_title)}</b>"]
    for w in lesson.get("words", [])[:5]:
        lines.append(f"• {escape(str(w))}")
    for p in lesson.get("phrases", [])[:2]:
        lines.append(f"• {escape(str(p))}")
    if len(lines) == 1:
        lines.append("Пока нет данных.")
    return "\n".join(lines)
