"""
Global error handler for VAD Coffee Date Bot.
"""

import logging
import traceback
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and notify the user that something went wrong."""
    logger.error(
        "Exception while handling an update:\n%s",
        "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__)),
    )

    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ Oops — something went wrong on my end. Please try again in a moment."
        )
