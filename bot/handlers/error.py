"""Safe structured error handling for the VAD Operations Bot."""

import logging
import re
import traceback
import uuid

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import database as db
from telegram_io import is_transient_network_error, retry_telegram

logger = logging.getLogger(__name__)


def safe_error_details(error):
    """Capture owner-useful diagnostics while redacting token-shaped values."""
    error_type=type(error).__name__ if error else "UnknownError"
    message=str(error) if error else "No exception message was available."
    stack="".join(traceback.format_exception(type(error),error,error.__traceback__)) if error else "Traceback unavailable."
    token_pattern=r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b"
    redact=lambda value: re.sub(token_pattern,"[REDACTED TELEGRAM TOKEN]",value)
    return {"exception_type":error_type,"message":redact(message)[:2000],"traceback":redact(stack)[-12000:]}


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error,BadRequest) and "message is not modified" in str(context.error).casefold():
        logger.info("Ignored harmless duplicate callback edit")
        return
    reference = uuid.uuid4().hex[:8].upper()
    logger.exception("Unhandled bot error reference=%s", reference, exc_info=context.error)
    actor_id = None
    if isinstance(update, Update) and update.effective_user:
        actor_id = update.effective_user.id
    try:
        details=safe_error_details(context.error)
        transient=is_transient_network_error(context.error)
        job=getattr(context,"job",None);source=getattr(job,"name",None) or ("telegram_polling" if update is None else "telegram_handler")
        fingerprint="transient_network:telegram" if transient else f"non_network:{reference}"
        details["source"]=source
        incident,created=db.record_system_incident(fingerprint,f"ERR-{reference}",
            "transient_network" if transient else "application_error",source,details)
        reference=incident["error_reference"].removeprefix("ERR-")
        if created:
            audit_details={**details,"incident_id":incident["id"]}
            db.record_audit(actor_id,"system_error","system",target_record_id=incident["id"],result="error",
                reason="Transient Telegram/network read failure" if transient else "An unhandled bot operation failed",
                new_value=audit_details,error_reference=incident["error_reference"])
    except Exception:
        logger.exception("Could not persist error reference=%s", reference)
        transient=False;created=True
    cfg = getattr(context,"bot_data",{}).get("config") if getattr(context,"bot_data",None) else None
    if cfg and created:
        notice=(f"⚠️ {'Temporary Telegram connection issue' if transient else 'System issue'}\n"
            f"Reference: ERR-{reference}\nOccurrences are grouped until communication recovers.\nAn owner review is recommended.")
        destinations=list(cfg.owner_user_ids)
        for owner_id in destinations:
            try: await retry_telegram(lambda owner_id=owner_id: context.bot.send_message(owner_id,notice),attempts=2)
            except Exception: logger.warning("Could not notify owner of error reference=%s",reference)
        if cfg.admin_chat_id and getattr(cfg,"health_thread_id",None):
            try: await retry_telegram(lambda: context.bot.send_message(cfg.admin_chat_id,notice,message_thread_id=cfg.health_thread_id),attempts=2)
            except Exception: logger.warning("Could not notify health topic reference=%s",reference)
    if not transient and isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            f"Something went wrong. Please return Home and try again. Error reference: ERR-{reference}"
        )
