from __future__ import annotations

from telegram import KeyboardButton, ReplyKeyboardMarkup

from app import config


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[config.BTN_LANGUAGE, config.BTN_MOVIES], [config.BTN_PLANNER, config.BTN_FOOD], [config.BTN_PROFILE]],
        resize_keyboard=True,
    )


def movies_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [config.BTN_MOVIES_BIND, config.BTN_MOVIES_UNBIND],
            [config.BTN_MOVIES_CHECK, config.BTN_MOVIES_CHECK_WISHLIST],
            [config.BTN_MOVIES_CREW],
            [config.BTN_MOVIES_ENGLISH],
            [config.BTN_MOVIES_IMDB_LINK, config.BTN_MOVIES_IMDB_UNLINK],
            [config.BTN_MOVIES_IMDB_MOVIES],
            [config.BTN_BACK_MOVIES, config.BTN_HOME_MENU],
        ],
        resize_keyboard=True,
    )


def planning_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[config.BTN_MY_PLANS], [config.BTN_BACK_MOVIES, config.BTN_HOME_MENU]],
        resize_keyboard=True,
    )


def planner_origin_keyboard(has_home: bool) -> ReplyKeyboardMarkup:
    rows = []
    if has_home:
        rows.append([config.BTN_PLAN_USE_HOME])
    rows.append([config.BTN_PLAN_SET_START, KeyboardButton(config.BTN_PLAN_SHARE_GEO, request_location=True)])
    rows.append([config.BTN_BACK_MOVIES, config.BTN_HOME_MENU])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def my_plans_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[config.BTN_ACTIVE_PLANS, config.BTN_ALL_PLANS], [config.BTN_BACK_MOVIES, config.BTN_HOME_MENU]],
        resize_keyboard=True,
    )


def language_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[config.BTN_LANG_ENGLISH, config.BTN_LANG_FRENCH], [config.BTN_LANG_GERMAN], [config.BTN_BACK_MOVIES, config.BTN_HOME_MENU]],
        resize_keyboard=True,
    )


def language_language_keyboard(lang: str) -> ReplyKeyboardMarkup:
    rows = [[config.BTN_LEVEL_A, config.BTN_LEVEL_B], [config.BTN_LEVEL_C]]
    if lang == config.BTN_LANG_ENGLISH:
        rows.append([config.BTN_EXAM_IELTS])
    elif lang == config.BTN_LANG_FRENCH:
        rows.append([config.BTN_EXAM_DELF])
    elif lang == config.BTN_LANG_GERMAN:
        rows.append([config.BTN_EXAM_GOETHE])
    rows.append([config.BTN_BACK_MOVIES, config.BTN_HOME_MENU])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def language_level_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[config.BTN_SKILL_VOCAB, config.BTN_SKILL_GRAMMAR], [config.BTN_BACK_MOVIES, config.BTN_HOME_MENU]],
        resize_keyboard=True,
    )


def language_exam_keyboard(exam: str) -> ReplyKeyboardMarkup:
    if exam == config.BTN_EXAM_IELTS:
        rows = [[config.BTN_EXAM_IELTS_LISTEN, config.BTN_EXAM_IELTS_WRITE], [config.BTN_EXAM_IELTS_READ]]
    elif exam == config.BTN_EXAM_DELF:
        rows = [[config.BTN_EXAM_DELF_WRITE], [config.BTN_EXAM_DELF_READ], [config.BTN_EXAM_DELF_LISTEN]]
    else:
        rows = [[config.BTN_EXAM_GOETHE_H, config.BTN_EXAM_GOETHE_S], [config.BTN_EXAM_GOETHE_L]]
    rows.append([config.BTN_BACK_MOVIES, config.BTN_HOME_MENU])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def food_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [config.BTN_FOOD_DIARY],
            [config.BTN_FOOD_COACH],
            [config.BTN_FOOD_PROFILE],
            [config.BTN_BACK_MOVIES, config.BTN_HOME_MENU],
        ],
        resize_keyboard=True,
    )


def food_diary_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [config.BTN_FOOD_ADD_MEAL],
            [config.BTN_FOOD_DAY_SUMMARY],
            [config.BTN_FOOD_HISTORY],
            [config.BTN_BACK_MOVIES, config.BTN_HOME_MENU],
        ],
        resize_keyboard=True,
    )


def food_coach_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [config.BTN_FOOD_DINNER],
            [config.BTN_FOOD_COMPOSITION],
            [config.BTN_FOOD_ASK_AI],
            [config.BTN_BACK_MOVIES, config.BTN_HOME_MENU],
        ],
        resize_keyboard=True,
    )


def food_profile_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [config.BTN_FOOD_PARAMS],
            [config.BTN_FOOD_GOAL],
            [config.BTN_FOOD_REMINDERS],
            [config.BTN_BACK_MOVIES, config.BTN_HOME_MENU],
        ],
        resize_keyboard=True,
    )


def profile_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [config.BTN_PROFILE_OVERVIEW, config.BTN_PROFILE_EDIT],
            [config.BTN_PROFILE_SLEEP],
            [config.BTN_PROFILE_RESET],
            [config.BTN_BACK_MOVIES, config.BTN_HOME_MENU],
        ],
        resize_keyboard=True,
    )


def sleep_check_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[config.BTN_SLEEP_YES, config.BTN_SLEEP_NO], [config.BTN_SLEEP_LATER], [config.BTN_HOME_MENU]],
        resize_keyboard=True,
    )


def profile_edit_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [config.BTN_PROFILE_EDIT_NAME, config.BTN_PROFILE_EDIT_HOME],
            [config.BTN_PROFILE_EDIT_WORK, config.BTN_PROFILE_EDIT_BODY],
            [config.BTN_PROFILE_EDIT_GOAL, config.BTN_PROFILE_EDIT_SLEEP],
            [config.BTN_PROFILE_EDIT_WATER],
            [config.BTN_PROFILE_START],
            [config.BTN_BACK_MOVIES, config.BTN_HOME_MENU],
        ],
        resize_keyboard=True,
    )


def yes_no_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[config.BTN_SLEEP_YES, config.BTN_SLEEP_NO], [config.BTN_HOME_MENU]], resize_keyboard=True)


def water_check_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[config.BTN_WATER_YES, config.BTN_WATER_NO], [config.BTN_HOME_MENU]], resize_keyboard=True)
