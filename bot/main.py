#!/usr/bin/env python3
"""VAD Operations Bot entry point."""

import logging
import os
import re
import socket
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import Config
from database import (DATABASE_PATH, acquire_process_lease, begin_recovery_run,
    heartbeat_process_lease, initialize_database, release_process_lease,
    set_system_state, synchronize_role_memberships)
from handlers.error import error_handler
from navigation import register_navigation
from operations import register_operations
from permissions import can_manage_sensitive
from runtime_config import apply_persisted_settings
from readiness import critical_fingerprint
from tracker import register_handlers
from telegram_io import retry_telegram
from command_menus import register_command_scopes, register_scoped_command_handlers


APPLICATION_NAME = "VAD Operations Bot"
POLLER_LEASE_NAME = "telegram_bot_api_poller"
POLLER_LEASE_TTL_SECONDS = 90
POLLER_LEASE_HEARTBEAT_SECONDS = 30


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


def _safe_identifier(value: str | None, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._:-]+", "-", (value or "").strip())[:80]
    return cleaned or fallback


def startup_source() -> str:
    """Return a short non-secret host/source label without dumping environment data."""
    if os.environ.get("REPLIT_DEPLOYMENT"):
        return "replit-deployment:" + _safe_identifier(os.environ.get("REPL_ID"))
    if os.environ.get("REPL_ID"):
        return "replit-workspace:" + _safe_identifier(os.environ.get("REPL_ID"))
    return "host:" + _safe_identifier(socket.gethostname())


def commit_identifier() -> str:
    for key in ("REPLIT_GIT_COMMIT", "GIT_COMMIT", "SOURCE_COMMIT"):
        if os.environ.get(key):
            return _safe_identifier(os.environ[key])
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True, text=True, timeout=2, check=True,
        )
        return _safe_identifier(result.stdout)
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def log_startup_identity(logger, instance_id, source, lease_acquired,
                         polling_started_at=None) -> None:
    logger.info(
        "startup_identity application=%s commit=%s instance_id=%s database=sqlite:%s "
        "lease_acquired=%s polling_start_et=%s source=%s",
        APPLICATION_NAME, commit_identifier(), instance_id, DATABASE_PATH.resolve(),
        str(bool(lease_acquired)).lower(), polling_started_at or "not-started", source,
    )


async def poller_lease_heartbeat_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Keep the poller lease alive; stop polling immediately if ownership is lost."""
    if ctx.application.bot_data.get("poller_lease_lost"):
        return
    instance_id = ctx.application.bot_data["process_instance_id"]
    try:
        owned = heartbeat_process_lease(
            POLLER_LEASE_NAME, instance_id, POLLER_LEASE_TTL_SECONDS,
        )
    except Exception as exc:
        logging.getLogger(__name__).critical(
            "Singleton lease heartbeat could not be verified; stopping polling (%s)",
            type(exc).__name__,
        )
        owned = False
    if not owned:
        ctx.application.bot_data["poller_lease_lost"] = True
        logging.getLogger(__name__).critical(
            "Singleton lease ownership was lost; stopping Telegram polling"
        )
        ctx.application.stop_running()


async def polling_liveness_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Restart safely if scheduler jobs outlive Telegram's polling updater."""
    if not getattr(ctx.application,"running",True):
        return
    updater = getattr(ctx.application,"updater",None)
    if updater is not None and getattr(updater,"running",False):
        return
    logging.getLogger(__name__).critical(
        "Telegram polling liveness failed; updater is inactive while the workflow is running. "
        "Stopping to release the singleton lease for automatic recovery"
    )
    ctx.application.stop_running()


def register_application_handlers(app: Application) -> None:
    register_navigation(app)
    register_scoped_command_handlers(app)
    register_operations(app)
    register_handlers(app)
    app.add_handler(CommandHandler("groupid", groupid_command))
    app.add_handler(CommandHandler("topicid", topicid_command))
    app.add_error_handler(error_handler)


async def startup_readiness_notice(app: Application) -> None:
    """Privately notify Owners once per distinct critical setup state."""
    try:
        identity=await retry_telegram(lambda: app.bot.get_me(),attempts=2)
        app.bot_data["bot_username"]=getattr(identity,"username",None)
        set_system_state("telegram_can_read_all_group_messages",
            "true" if bool(getattr(identity,"can_read_all_group_messages",False)) else "false")
        set_system_state("telegram_bot_identity_checked_at",datetime.now(ZoneInfo("America/New_York")).isoformat())
    except Exception:
        # The transient-network incident system owns connectivity failures.
        pass
    await register_command_scopes(app)
    cfg=app.bot_data["config"];fingerprint,incomplete=critical_fingerprint(cfg)
    if not incomplete:return
    from database import system_state
    state=system_state()
    labels={"owners":"Owner configuration","token":"Bot connection","main":"Main participation group",
        "participation_topic":"General participation topic","privacy":"Telegram privacy mode blocks ordinary messages",
        "admin":"Admin group","reports":"Participation-alert topic","health":"Health topic"}
    body="⚠️ Setup Incomplete\n\nThe bot started safely, but these items still need attention:\n"+"\n".join(f"• {labels.get(key,key)}" for key in incomplete)+"\n\nOpen Owner Home → Setup & Readiness."
    for owner_id in cfg.owner_user_ids:
        marker=f"startup_readiness_notice:{owner_id}:{fingerprint}"
        if marker in state:continue
        try:
            await app.bot.send_message(owner_id,body)
            set_system_state(marker,datetime.now(ZoneInfo("America/New_York")).isoformat())
        except Exception:pass


def main() -> int:
    config = Config.from_env()
    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)
    initialize_database()
    instance_id = uuid.uuid4().hex
    source = startup_source()
    try:
        acquired = acquire_process_lease(
            POLLER_LEASE_NAME, instance_id, POLLER_LEASE_TTL_SECONDS, source,
        )
    except Exception as exc:
        log_startup_identity(logger,instance_id,source,False)
        logger.critical(
            "Singleton lease verification failed; Telegram polling will not start (%s)",
            type(exc).__name__,
        )
        return 2
    if not acquired:
        log_startup_identity(logger,instance_id,source,False)
        logger.error(
            "Another live VAD Operations Bot process owns the polling lease; "
            "this process will exit without contacting Telegram"
        )
        return 2

    polling_started_at = datetime.now(ZoneInfo("America/New_York")).isoformat()
    log_startup_identity(logger,instance_id,source,True,polling_started_at)
    logger.info("Telegram polling lease claimed instance_id=%s",instance_id)
    try:
        recovery_run_id=begin_recovery_run(polling_started_at)
        apply_persisted_settings(config)
        synchronize_role_memberships(config)
        set_system_state("last_restart", polling_started_at)
        app = Application.builder().token(config.token).post_init(startup_readiness_notice).build()
        app.bot_data["config"] = config
        app.bot_data["recovery_run_id"] = recovery_run_id
        app.bot_data["process_instance_id"] = instance_id
        register_application_handlers(app)
        app.job_queue.run_repeating(
            poller_lease_heartbeat_job,
            interval=POLLER_LEASE_HEARTBEAT_SECONDS,
            first=POLLER_LEASE_HEARTBEAT_SECONDS,
            name="bot-api-poller-singleton-heartbeat",
        )
        app.job_queue.run_repeating(
            polling_liveness_job,
            interval=POLLER_LEASE_HEARTBEAT_SECONDS,
            first=POLLER_LEASE_HEARTBEAT_SECONDS,
            name="bot-api-poller-liveness",
        )
        # Verify ownership again immediately before the first Telegram request.
        if not heartbeat_process_lease(
            POLLER_LEASE_NAME, instance_id, POLLER_LEASE_TTL_SECONDS,
        ):
            logger.critical("Singleton lease was lost before polling; startup aborted")
            return 2
        logger.info("Telegram polling starting instance_id=%s allowed_updates=message,edited_message,callback_query",instance_id)
        # The pending queue is the only safe short-outage recovery source. Never
        # discard it and never run a second getUpdates consumer.
        app.run_polling(allowed_updates=["message", "edited_message", "callback_query"], drop_pending_updates=False)
        return 0
    except Exception as exc:
        logger.exception("Bot startup or polling stopped with %s",type(exc).__name__)
        raise
    finally:
        try:
            released = release_process_lease(POLLER_LEASE_NAME,instance_id)
            logger.info("Singleton polling lease released=%s instance_id=%s",released,instance_id)
        except Exception as exc:
            logger.error("Singleton lease release failed; it will expire safely (%s)",type(exc).__name__)


if __name__ == "__main__":
    raise SystemExit(main())
