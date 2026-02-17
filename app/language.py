from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.services import language_grammar


async def start_grammar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await language_grammar.start_grammar(update, context)


async def handle_grammar_topic_click(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    return await language_grammar.handle_grammar_topic_click(update, context, text)
