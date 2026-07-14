#!/usr/bin/env python3
"""
VAD Coffee Lounge Bot — entry point.

Required:
    TELEGRAM_BOT_TOKEN        — bot token from @BotFather (Replit Secret)

Optional:
    ADMIN_CHAT_ID             — supergroup chat ID where order receipts are forwarded
    COFFEE_ORDERS_THREAD_ID   — message_thread_id of the Coffee Orders topic inside that supergroup
    LOG_LEVEL                 — default INFO
"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import Config
from order import build_order_conversation
from handlers.error import error_handler
from database import initialize_database
from tracker import register_handlers
from permissions import can_mutate
from setup_mode import register_setup_handlers


async def groupid_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the current chat's ID — useful for setting ADMIN_CHAT_ID."""
    if not can_mutate(update.effective_user.id if update.effective_user else None, ctx.bot_data["config"]):
        await update.effective_message.reply_text("Sorry, this command is for operational admins only.")
        return
    chat = update.effective_chat
    if chat.type in ("group", "supergroup", "channel"):
        await update.message.reply_html(
            f"✨ This group's chat ID is:\n<code>{chat.id}</code>\n\n"
            "Set <b>ADMIN_CHAT_ID</b> to this value in Replit Secrets to connect the admin group."
        )
    else:
        await update.message.reply_text(
            "Add me to a group first, then use /groupid there to get the chat ID. ☕"
        )


async def topicid_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the topic's message_thread_id — useful for setting COFFEE_ORDERS_THREAD_ID."""
    if not can_mutate(update.effective_user.id if update.effective_user else None, ctx.bot_data["config"]):
        await update.effective_message.reply_text("Sorry, this command is for operational admins only.")
        return
    msg = update.message
    if msg and msg.is_topic_message:
        await msg.reply_html(
            f"✨ This topic's thread ID is:\n<code>{msg.message_thread_id}</code>\n\n"
            "Set <b>COFFEE_ORDERS_THREAD_ID</b> to this value in Replit Secrets, "
            "then restart the bot to route order receipts here."
        )
    elif update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
        await msg.reply_text(
            "Use /topicid inside a specific topic thread to get its ID. ☕"
        )
    else:
        await msg.reply_text(
            "Add me to a supergroup and run /topicid inside the target topic thread. ☕"
        )


def setup_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        level=getattr(logging, level, logging.INFO),
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def register_application_handlers(app: Application) -> None:
    """Register specific slash commands before the Coffee conversation router."""
    register_handlers(app)
    register_setup_handlers(app)
    app.add_handler(CommandHandler("groupid", groupid_command))
    app.add_handler(CommandHandler("topicid", topicid_command))
    app.add_handler(build_order_conversation())
    app.add_error_handler(error_handler)


def main() -> None:
    config = Config.from_env()
    initialize_database()
    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)
    logger.info("Starting VAD Coffee Lounge Bot…")

    app = Application.builder().token(config.token).build()
    app.bot_data["config"] = config

    if config.admin_chat_id:
        app.bot_data["admin_chat_id"] = config.admin_chat_id
        logger.info("Admin chat connected: %s", config.admin_chat_id)
    else:
        logger.warning("ADMIN_CHAT_ID not set — orders will not be forwarded to an admin group")

    if config.coffee_orders_thread_id:
        app.bot_data["coffee_orders_thread_id"] = config.coffee_orders_thread_id
        logger.info("Coffee Orders topic thread ID: %s", config.coffee_orders_thread_id)
    else:
        logger.warning("COFFEE_ORDERS_THREAD_ID not set — receipts will post to the group root")

    register_application_handlers(app)

    logger.info("Bot is running. Press Ctrl-C to stop.")
    app.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
