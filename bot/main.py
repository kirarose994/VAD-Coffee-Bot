"""
VAD Coffee Date Bot — entry point.

Run:
    python main.py

Required environment variable:
    TELEGRAM_BOT_TOKEN — your bot token from @BotFather
"""

import logging
import sys
import os

# Allow imports from this directory regardless of working directory
sys.path.insert(0, os.path.dirname(__file__))

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config import Config
from handlers.start import start_handler, help_handler
from handlers.profile import profile_handler
from handlers.match import match_handler
from handlers.register import build_register_conversation
from handlers.error import error_handler


def setup_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        level=getattr(logging, level, logging.INFO),
        stream=sys.stdout,
    )
    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def build_app(config: Config) -> Application:
    """Build and configure the Telegram Application."""
    app = Application.builder().token(config.token).build()

    # Conversation handler (must be added before plain command handlers
    # so it intercepts messages during an active conversation)
    app.add_handler(build_register_conversation())

    # Standalone command handlers
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("profile", profile_handler))
    app.add_handler(CommandHandler("match", match_handler))

    # Global error handler
    app.add_error_handler(error_handler)

    return app


def main() -> None:
    config = Config.from_env()
    setup_logging(config.log_level)

    logger = logging.getLogger(__name__)
    logger.info("Starting VAD Coffee Date Bot…")

    app = build_app(config)

    logger.info("Bot is running. Press Ctrl-C to stop.")
    app.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
