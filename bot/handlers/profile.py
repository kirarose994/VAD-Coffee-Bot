"""
/profile command handler — displays the user's saved coffee date profile.
"""

import logging
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from utils.formatting import format_profile_summary

logger = logging.getLogger(__name__)


async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /profile command."""
    user = update.effective_user
    if user is None:
        return

    # Profiles are stored in bot_data keyed by user_id
    profiles: dict = context.bot_data.get("profiles", {})
    profile = profiles.get(user.id)

    if not profile:
        await update.message.reply_html(
            "You don't have a profile yet! Use /register to create one. ☕",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    logger.info("User %s viewed their profile", user.full_name)
    await update.message.reply_html(
        format_profile_summary(profile),
        reply_markup=ReplyKeyboardRemove(),
    )
