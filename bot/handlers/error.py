"""
Global error handler for VAD Coffee Lounge Bot.
"""

import logging
import traceback
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(
        "Unhandled exception:\n%s",
        "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__)),
    )
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ Something went wrong. Please try again or type /start to restart."
        )
