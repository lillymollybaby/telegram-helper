from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app import cleanup, config, language
from app.keyboards import language_exam_keyboard, language_language_keyboard, language_level_keyboard
from app.services.navigation_common import send_nav_message, set_screen


async def handle_language_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    text = (update.effective_message.text or "").strip()

    if text in {config.BTN_LANG_ENGLISH, config.BTN_LANG_FRENCH, config.BTN_LANG_GERMAN}:
        await cleanup.cleanup_trigger_message(update, context)
        context.user_data["lang_selected"] = text
        set_screen(context, "lang_language")
        await send_nav_message(update, context, text, language_language_keyboard(text))
        return True

    if text in {config.BTN_LEVEL_A, config.BTN_LEVEL_B, config.BTN_LEVEL_C}:
        await cleanup.cleanup_trigger_message(update, context)
        context.user_data["lang_level"] = text
        context.user_data.pop("grammar_topics", None)
        context.user_data.pop("grammar_pdf_path", None)
        set_screen(context, "lang_level")
        await send_nav_message(update, context, text, language_level_keyboard())
        return True

    if await language.handle_grammar_topic_click(update, context, text):
        await cleanup.cleanup_trigger_message(update, context)
        return True

    if text in {config.BTN_SKILL_VOCAB, config.BTN_SKILL_GRAMMAR}:
        await cleanup.cleanup_trigger_message(update, context)
        if text == config.BTN_SKILL_GRAMMAR:
            await language.start_grammar(update, context)
        else:
            lang = context.user_data.get("lang_selected", "Language")
            level = context.user_data.get("lang_level", "")
            await update.effective_message.reply_text(
                f"{lang} / {level} / {text}\nSection is ready for content.",
                reply_markup=language_level_keyboard(),
            )
        return True

    if text in {config.BTN_EXAM_IELTS, config.BTN_EXAM_DELF, config.BTN_EXAM_GOETHE}:
        await cleanup.cleanup_trigger_message(update, context)
        set_screen(context, "lang_exam")
        context.user_data["lang_exam"] = text
        await send_nav_message(update, context, text, language_exam_keyboard(text))
        return True

    if text in {
        config.BTN_EXAM_IELTS_LISTEN,
        config.BTN_EXAM_IELTS_WRITE,
        config.BTN_EXAM_IELTS_READ,
        config.BTN_EXAM_DELF_WRITE,
        config.BTN_EXAM_DELF_READ,
        config.BTN_EXAM_DELF_LISTEN,
        config.BTN_EXAM_GOETHE_H,
        config.BTN_EXAM_GOETHE_S,
        config.BTN_EXAM_GOETHE_L,
    }:
        await cleanup.cleanup_trigger_message(update, context)
        exam = context.user_data.get("lang_exam", "Exam")
        await update.effective_message.reply_text(
            f"{exam} / {text}\nSection is ready for content.",
            reply_markup=language_exam_keyboard(exam),
        )
        return True

    return False

