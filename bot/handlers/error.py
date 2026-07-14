"""Safe structured error handling for the VAD Operations Bot."""

import logging
import uuid

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import database as db

logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error,BadRequest) and "message is not modified" in str(context.error).casefold():
        logger.info("Ignored harmless duplicate callback edit")
        return
    reference = uuid.uuid4().hex[:12]
    logger.exception("Unhandled bot error reference=%s", reference, exc_info=context.error)
    actor_id = None
    if isinstance(update, Update) and update.effective_user:
        actor_id = update.effective_user.id
    try:
        db.record_audit(actor_id,"system_error","system",result="error",
            reason="An unhandled bot operation failed",error_reference=f"ERR-{reference[:8].upper()}")
    except Exception:
        logger.exception("Could not persist error reference=%s", reference)
    cfg = getattr(context,"bot_data",{}).get("config") if getattr(context,"bot_data",None) else None
    if cfg:
        notice=f"⚠️ System issue\nReference: ERR-{reference[:8].upper()}\nAn owner review is recommended."
        destinations=list(cfg.owner_user_ids)
        for owner_id in destinations:
            try: await context.bot.send_message(owner_id,notice)
            except Exception: logger.warning("Could not notify owner of error reference=%s",reference)
        if cfg.admin_chat_id and getattr(cfg,"health_thread_id",None):
            try: await context.bot.send_message(cfg.admin_chat_id,notice,message_thread_id=cfg.health_thread_id)
            except Exception: logger.warning("Could not notify health topic reference=%s",reference)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            f"Something went wrong. Please return Home and try again. Error reference: ERR-{reference[:8].upper()}"
        )
