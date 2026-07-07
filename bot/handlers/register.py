"""
/register ConversationHandler — collects a user's coffee date profile
through a multi-step conversation.
"""

import logging
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import (
    STATE_ASKING_NAME,
    STATE_ASKING_AVAILABILITY,
    STATE_ASKING_LOCATION,
    STATE_ASKING_INTERESTS,
    STATE_CONFIRMING,
    CB_CONFIRM_YES,
    CB_CONFIRM_NO,
    CB_CANCEL,
    AVAILABILITY_OPTIONS,
    INTEREST_OPTIONS,
)
from utils.keyboards import availability_keyboard, interests_keyboard, confirm_keyboard
from utils.formatting import format_profile_summary

logger = logging.getLogger(__name__)

# ── helpers ──────────────────────────────────────────────────────────────────


def _draft(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Return (and lazily initialise) the draft profile in user_data."""
    if "draft" not in context.user_data:
        context.user_data["draft"] = {
            "name": "",
            "availability": [],
            "location": "",
            "interests": [],
        }
    return context.user_data["draft"]


def _clear_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("draft", None)


# ── entry point ───────────────────────────────────────────────────────────────


async def register_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the registration conversation."""
    _clear_draft(context)
    user = update.effective_user
    logger.info("User %s started registration", user.full_name if user else "unknown")

    await update.message.reply_html(
        "☕ <b>Let's set up your Coffee Date profile!</b>\n\n"
        "Step 1 of 4 — What's your name? (or a nickname you'd like to use)",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_ASKING_NAME


# ── step 1: name ─────────────────────────────────────────────────────────────


async def got_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Please enter a non-empty name.")
        return STATE_ASKING_NAME

    _draft(context)["name"] = name
    logger.debug("Draft name set to %r", name)

    await update.message.reply_html(
        f"Nice to meet you, <b>{name}</b>! ☕\n\n"
        "Step 2 of 4 — <b>When are you generally available?</b>\n"
        "Select all slots that work for you, then tap <b>✅ Done selecting</b>.",
        reply_markup=availability_keyboard(),
    )
    return STATE_ASKING_AVAILABILITY


# ── step 2: availability ──────────────────────────────────────────────────────


async def got_availability(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if text == "❌ Cancel":
        return await _cancel_from_message(update, context)

    if text == "✅ Done selecting":
        draft = _draft(context)
        if not draft["availability"]:
            await update.message.reply_text(
                "Please select at least one availability slot first.",
                reply_markup=availability_keyboard(),
            )
            return STATE_ASKING_AVAILABILITY

        await update.message.reply_html(
            "Great choices! ✅\n\n"
            "Step 3 of 4 — <b>What's your location or neighbourhood?</b>\n"
            "(e.g. 'Downtown NYC', 'East London', 'remote/online')",
            reply_markup=ReplyKeyboardRemove(),
        )
        return STATE_ASKING_LOCATION

    if text in AVAILABILITY_OPTIONS:
        draft = _draft(context)
        slots: list = draft["availability"]
        if text in slots:
            slots.remove(text)
            await update.message.reply_text(
                f"Removed: {text}\nCurrent selection: {', '.join(slots) or '(none)'}",
                reply_markup=availability_keyboard(),
            )
        else:
            slots.append(text)
            await update.message.reply_text(
                f"Added: {text}\nCurrent selection: {', '.join(slots)}",
                reply_markup=availability_keyboard(),
            )
        return STATE_ASKING_AVAILABILITY

    await update.message.reply_text(
        "Please use the keyboard buttons to select your availability.",
        reply_markup=availability_keyboard(),
    )
    return STATE_ASKING_AVAILABILITY


# ── step 3: location ──────────────────────────────────────────────────────────


async def got_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    location = update.message.text.strip()
    if not location:
        await update.message.reply_text("Please enter your location or neighbourhood.")
        return STATE_ASKING_LOCATION

    _draft(context)["location"] = location

    await update.message.reply_html(
        "📍 Got it!\n\n"
        "Step 4 of 4 — <b>What are your interests?</b>\n"
        "Select all that apply, then tap <b>✅ Done selecting</b>.",
        reply_markup=interests_keyboard(),
    )
    return STATE_ASKING_INTERESTS


# ── step 4: interests ─────────────────────────────────────────────────────────


async def got_interests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if text == "❌ Cancel":
        return await _cancel_from_message(update, context)

    if text == "✅ Done selecting":
        draft = _draft(context)
        if not draft["interests"]:
            await update.message.reply_text(
                "Please select at least one interest.",
                reply_markup=interests_keyboard(),
            )
            return STATE_ASKING_INTERESTS

        summary = format_profile_summary(draft)
        await update.message.reply_html(
            f"{summary}\n\n<b>Does everything look good?</b>",
            reply_markup=confirm_keyboard(),
        )
        return STATE_CONFIRMING

    if text in INTEREST_OPTIONS:
        draft = _draft(context)
        chosen: list = draft["interests"]
        if text in chosen:
            chosen.remove(text)
            await update.message.reply_text(
                f"Removed: {text}\nSelected: {', '.join(chosen) or '(none)'}",
                reply_markup=interests_keyboard(),
            )
        else:
            chosen.append(text)
            await update.message.reply_text(
                f"Added: {text}\nSelected: {', '.join(chosen)}",
                reply_markup=interests_keyboard(),
            )
        return STATE_ASKING_INTERESTS

    await update.message.reply_text(
        "Please use the keyboard buttons to select your interests.",
        reply_markup=interests_keyboard(),
    )
    return STATE_ASKING_INTERESTS


# ── step 5: confirmation ──────────────────────────────────────────────────────


async def confirm_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    draft = _draft(context)

    # Persist to bot_data
    if "profiles" not in context.bot_data:
        context.bot_data["profiles"] = {}
    context.bot_data["profiles"][user.id] = dict(draft)
    _clear_draft(context)

    logger.info("User %s (%d) completed registration", user.full_name, user.id)

    await query.edit_message_text(
        "☕ <b>You're all set!</b>\n\n"
        "Your coffee date profile has been saved.\n"
        "Use /match to find your next coffee partner, or /profile to review your info.",
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def confirm_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Restart from the beginning so the user can re-enter everything."""
    query = update.callback_query
    await query.answer()

    _clear_draft(context)
    await query.edit_message_text(
        "No problem! Let's start over. Use /register whenever you're ready.",
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def confirm_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _clear_draft(context)

    await query.edit_message_text("Registration cancelled. Come back when you're ready! ☕")
    return ConversationHandler.END


# ── cancel command ────────────────────────────────────────────────────────────


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_draft(context)
    await update.message.reply_html(
        "Registration cancelled. Use /register to start again whenever you like. ☕",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def _cancel_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_draft(context)
    await update.message.reply_html(
        "Registration cancelled. Use /register to start again. ☕",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# ── conversation handler factory ──────────────────────────────────────────────


def build_register_conversation() -> ConversationHandler:
    """Return the fully configured ConversationHandler for registration."""
    # per_message=False (explicit): we track conversation per user+chat, not per
    # message. The confirmation inline keyboard belongs to a single bot message
    # and is never duplicated, so routing callbacks per-message is unnecessary.
    return ConversationHandler(
        entry_points=[CommandHandler("register", register_entry)],
        per_message=False,
        states={
            STATE_ASKING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_name),
            ],
            STATE_ASKING_AVAILABILITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_availability),
            ],
            STATE_ASKING_LOCATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_location),
            ],
            STATE_ASKING_INTERESTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_interests),
            ],
            STATE_CONFIRMING: [
                CallbackQueryHandler(confirm_yes, pattern=f"^{CB_CONFIRM_YES}$"),
                CallbackQueryHandler(confirm_no, pattern=f"^{CB_CONFIRM_NO}$"),
                CallbackQueryHandler(confirm_cancel, pattern=f"^{CB_CANCEL}$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
        allow_reentry=True,
        name="register_conversation",
    )
