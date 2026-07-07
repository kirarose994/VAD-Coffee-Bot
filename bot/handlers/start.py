"""
/start and /help command handlers.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from utils.formatting import format_welcome, format_help

logger = logging.getLogger(__name__)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    user = update.effective_user
    if user is None:
        return

    logger.info("User %s (%d) started the bot", user.full_name, user.id)

    await update.message.reply_html(format_welcome(user.first_name))


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    user = update.effective_user
    logger.info("User %s requested help", user.full_name if user else "unknown")

    await update.message.reply_html(format_help())
