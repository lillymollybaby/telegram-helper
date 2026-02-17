from __future__ import annotations

from telegram.ext import ContextTypes

PLAN_DRAFT_KEY = "plan_draft"


def plan_draft(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault(
        PLAN_DRAFT_KEY,
        {
            "title": None,
            "destination": None,
            "event_dt": None,
            "detected_destination": None,
            "detected_event_dt": None,
            "origin_address": None,
            "awaiting": None,
        },
    )


def clear_plan_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(PLAN_DRAFT_KEY, None)


def cancel_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_plan_draft(context)
