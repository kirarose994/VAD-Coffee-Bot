#!/usr/bin/env python3
"""VAD Operations Bot entry point."""

import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import Config
from database import initialize_database, set_system_state
from handlers.error import error_handler
from navigation import register_navigation
from operations import register_operations
from permissions import can_manage_sensitive
from runtime_config import apply_persisted_settings
from readiness import critical_fingerprint
from tracker import register_handlers


async def groupid_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not can_manage_sensitive(update.effective_user.id if update.effective_user else None, ctx.bot_data["config"]):
        return await update.effective_message.reply_text("Sorry, chat verification is owner-only.")
    chat = update.effective_chat
    if chat.type in ("group", "supergroup", "channel"):
        await update.effective_message.reply_text(f"This group's chat ID is: {chat.id}")
    else:
        await update.effective_message.reply_text("Run /groupid in the target group.")


async def topicid_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not can_manage_sensitive(update.effective_user.id if update.effective_user else None, ctx.bot_data["config"]):
        return await update.effective_message.reply_text("Sorry, topic verification is owner-only.")
    msg = update.effective_message
    if msg and msg.is_topic_message:
        await msg.reply_text(f"This topic's thread ID is: {msg.message_thread_id}")
    else:
        await msg.reply_text("Run /topicid inside the target forum topic.")


def setup_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        level=getattr(logging, level, logging.INFO), stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def register_application_handlers(app: Application) -> None:
    register_navigation(app)
    register_operations(app)
    register_handlers(app)
    app.add_handler(CommandHandler("groupid", groupid_command))
    app.add_handler(CommandHandler("topicid", topicid_command))
    app.add_error_handler(error_handler)


async def startup_readiness_notice(app: Application) -> None:
    """Privately notify Owners once per distinct critical setup state."""
    cfg=app.bot_data["config"];fingerprint,incomplete=critical_fingerprint(cfg)
    if not incomplete:return
    from database import system_state
    state=system_state()
    labels={"owners":"Owner configuration","token":"Bot connection","main":"Main participation group",
        "participation_topic":"General participation topic","admin":"Admin group","reports":"Participation-alert topic","health":"Health topic"}
    body="⚠️ Setup Incomplete\n\nThe bot started safely, but these items still need attention:\n"+"\n".join(f"• {labels.get(key,key)}" for key in incomplete)+"\n\nOpen Owner Home → Setup & Readiness."
    for owner_id in cfg.owner_user_ids:
        marker=f"startup_readiness_notice:{owner_id}:{fingerprint}"
        if marker in state:continue
        try:
            await app.bot.send_message(owner_id,body)
            set_system_state(marker,datetime.now(ZoneInfo("America/New_York")).isoformat())
        except Exception:pass


def main() -> None:
    config = Config.from_env()
    initialize_database()
    apply_persisted_settings(config)
    set_system_state("last_restart", datetime.now(ZoneInfo("America/New_York")).isoformat())
    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)
    logger.info("Starting VAD Operations Bot")
    app = Application.builder().token(config.token).post_init(startup_readiness_notice).build()
    app.bot_data["config"] = config
    register_application_handlers(app)
    logger.info("Bot is running. Press Ctrl-C to stop.")
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
