"""
VAD Coffee Lounge Bot — entry point.

Required:
    TELEGRAM_BOT_TOKEN   — bot token from @BotFather (Replit Secret)

Optional:
    ADMIN_CHAT_ID        — group chat ID where orders are forwarded
    LOG_LEVEL            — default INFO
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


async def groupid_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the current chat's ID — useful for setting ADMIN_CHAT_ID."""
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


def setup_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        level=getattr(logging, level, logging.INFO),
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main() -> None:
    config = Config.from_env()
    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)
    logger.info("Starting VAD Coffee Lounge Bot…")

    app = Application.builder().token(config.token).build()

    if config.admin_chat_id:
        app.bot_data["admin_chat_id"] = config.admin_chat_id
        logger.info("Admin chat connected: %s", config.admin_chat_id)
    else:
        logger.warning("ADMIN_CHAT_ID not set — orders will not be forwarded to an admin group")

    app.add_handler(build_order_conversation())
    app.add_handler(CommandHandler("groupid", groupid_command))
    app.add_error_handler(error_handler)

    logger.info("Bot is running. Press Ctrl-C to stop.")
    app.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
