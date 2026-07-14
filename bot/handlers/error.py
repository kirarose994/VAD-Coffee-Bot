"""Safe structured error handling for the VAD Operations Bot."""

import logging
import uuid

from telegram import Update
from telegram.ext import ContextTypes

import database as db

logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference = uuid.uuid4().hex[:12]
    logger.exception("Unhandled bot error reference=%s", reference, exc_info=context.error)
    actor_id = None
    if isinstance(update, Update) and update.effective_user:
        actor_id = update.effective_user.id
    try:
        db.record_audit(actor_id,"system_error","system",result="error",reason=reference)
    except Exception:
        logger.exception("Could not persist error reference=%s", reference)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            f"Something went wrong. Please try again or use /start. Error reference: {reference}"
        )
