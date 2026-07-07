"""
Keyboard helpers for VAD Coffee Date Bot.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from config import (
    AVAILABILITY_OPTIONS,
    INTEREST_OPTIONS,
    CB_CONFIRM_YES,
    CB_CONFIRM_NO,
    CB_CANCEL,
)


def availability_keyboard() -> ReplyKeyboardMarkup:
    """Reply keyboard for selecting availability slots."""
    buttons = [[KeyboardButton(opt)] for opt in AVAILABILITY_OPTIONS]
    buttons.append([KeyboardButton("✅ Done selecting")])
    buttons.append([KeyboardButton("❌ Cancel")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=False)


def interests_keyboard() -> ReplyKeyboardMarkup:
    """Reply keyboard for selecting interests (two per row)."""
    opts = INTEREST_OPTIONS
    rows = [opts[i : i + 2] for i in range(0, len(opts), 2)]
    buttons = [[KeyboardButton(opt) for opt in row] for row in rows]
    buttons.append([KeyboardButton("✅ Done selecting")])
    buttons.append([KeyboardButton("❌ Cancel")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=False)


def confirm_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard for confirming registration."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data=CB_CONFIRM_YES),
            InlineKeyboardButton("✏️ Edit", callback_data=CB_CONFIRM_NO),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL)],
    ])


def remove_keyboard() -> ReplyKeyboardMarkup:
    """Placeholder to remove the reply keyboard."""
    from telegram import ReplyKeyboardRemove  # noqa: F401
    return None  # type: ignore[return-value]
