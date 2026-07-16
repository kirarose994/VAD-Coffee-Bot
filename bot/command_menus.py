"""Scoped Telegram command menus and privacy-safe command entry points."""

import logging
from datetime import datetime

from telegram import (BotCommand, BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats,
    InlineKeyboardButton, InlineKeyboardMarkup, Update)
from telegram.ext import CommandHandler, ContextTypes

import database as db
from permissions import Role, has_permission, role_for

LOGGER=logging.getLogger(__name__)

PRIVATE_COMMANDS=(
    ("start","Open your VAD home"),("status","View your creator status"),
    ("pop","Open Thursday POP"),("away","Submit or review time away"),
    ("timeline","View your activity history"),("directory","Open the creator directory"),
    ("calendar","View the VAD calendar"),("support","Contact VAD Support"),
    ("help","Learn how to use the bot"),
)
GROUP_COMMANDS=(
    ("start","Open the VAD Operations Bot"),("help","View bot help"),
    ("status","Check your private creator status"),("pop","Open your private Thursday POP tools"),
    ("away","Open your private time-away tools"),
)
ADMIN_COMMANDS=GROUP_COMMANDS+(
    ("admin","Open Admin Home privately"),("inbox","Open Operations Inbox privately"),
    ("participation","Open Participation Summary privately"),("whosaway","Open Who’s Away privately"),
)


def _commands(rows):return [BotCommand(command,description) for command,description in rows]


def _record_scope_state(key,value):
    """Command-menu observability must never make startup fatal."""
    try:db.set_system_state(key,value)
    except Exception as exc:LOGGER.warning("Could not store Telegram command-scope state: %s",type(exc).__name__)


async def register_command_scopes(app):
    """Register each scope once at startup; failures are observable but never fatal."""
    scopes=(("private",BotCommandScopeAllPrivateChats(),PRIVATE_COMMANDS),
        ("group",BotCommandScopeAllGroupChats(),GROUP_COMMANDS),
        ("admin",BotCommandScopeAllChatAdministrators(),ADMIN_COMMANDS))
    for name,scope,commands in scopes:
        try:
            await app.bot.set_my_commands(_commands(commands),scope=scope)
            _record_scope_state(f"command_scope:{name}","ready")
        except Exception as exc:  # Telegram transport/error diagnostics handle details separately.
            LOGGER.warning("Could not register Telegram %s command scope: %s",name,type(exc).__name__)
            _record_scope_state(f"command_scope:{name}",f"failed:{type(exc).__name__}")
        finally:_record_scope_state(f"command_scope_checked:{name}",datetime.now(app.bot_data["config"].timezone).isoformat())


def command_scope_status(path=None):
    state=db.system_state(path)
    return {name:state.get(f"command_scope:{name}",{}).get("value","not_verified")
        for name in ("private","group","admin")}


def _private_url(ctx):
    username=(ctx.bot_data.get("bot_username") or "").lstrip("@")
    return f"https://t.me/{username}" if username else None


async def group_private_redirect(update,ctx,label="Open the VAD Operations Bot privately"):
    """Never render personal or operational details in a group."""
    url=_private_url(ctx);markup=(InlineKeyboardMarkup([[InlineKeyboardButton("Open Privately",url=url)]]) if url else None)
    text=f"{label}. Your private information will not be shown in this group."
    if not url:text+=" Open a private chat with the bot from its profile."
    await update.effective_message.reply_text(text,reply_markup=markup)


def _is_private(update):return getattr(getattr(update,"effective_chat",None),"type",None)=="private"


async def scoped_command(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    command=(update.effective_message.text or "").split()[0].split("@",1)[0].lstrip("/").casefold()
    cfg=ctx.bot_data["config"];user_id=update.effective_user.id;role=role_for(user_id,cfg)
    admin_requirements={"admin":None,"inbox":None,"participation":"view_creator_reports","whosaway":None}
    if command in admin_requirements:
        permission=admin_requirements[command]
        if role < Role.ADMIN or (permission and not has_permission(user_id,cfg,permission)):
            return await update.effective_message.reply_text("This Admin tool is not available to your account.")
    if not _is_private(update):
        return await group_private_redirect(update,ctx)
    from navigation import creator_card,home_markup,menu_markup
    creator=db.get_creator(user_id)
    if command=="status":
        text=("📋 My Creator Status\n\n"+creator_card(user_id,cfg) if creator else
            "Creator status is available after registration. Open your VAD home to register or review your registration.")
        markup=home_markup(ctx,user_id)
    elif command=="pop":text,markup="📸 Thursday POP\n\nOpen your private POP status and posting guidance.",menu_markup(ctx,[("📸 Open Thursday POP","pop_help")])
    elif command=="away":text,markup="💙 Time Away\n\nSubmit an Away Notice or review your existing notices privately.",menu_markup(ctx,[("💙 Let Us Know You’ll Be Away","away_help"),("📋 My Away Notices","my_away_notices")])
    elif command=="timeline":text,markup="📜 My Activity History\n\nOpen your private creator timeline.",menu_markup(ctx,[("📜 View My Activity History","timeline_0")])
    elif command=="support":text,markup="💬 VAD Support\n\nAsk the Admin team for help through a private guided message.",menu_markup(ctx,[("💬 Contact VAD Support","contact")])
    elif command=="help":text,markup="📚 Help Center\n\nLearn how participation, POP, Away Notices, and support work.",menu_markup(ctx,[("📚 Open Help Center","resources")])
    elif command=="directory":
        if role < Role.ADMIN or not has_permission(user_id,cfg,"view_creator_reports"):
            return await update.effective_message.reply_text("The creator directory is available only to authorized Admins and Owners.",reply_markup=home_markup(ctx,user_id))
        text,markup="👥 Creator Directory\n\nFind a creator and review the information you are authorized to see.",menu_markup(ctx,[("👥 Open Creator Directory","creator_report")])
    elif command=="calendar":
        if role < Role.ADMIN:return await update.effective_message.reply_text("The community calendar is available only to Admins and Owners.",reply_markup=home_markup(ctx,user_id))
        text,markup="📅 VAD Calendar\n\nOpen the private operational calendar.",menu_markup(ctx,[("📅 Open VAD Calendar","calendar")])
    else:
        actions={"admin":("🛡️ Open Admin Home","admin"),"inbox":("📥 Open Operations Inbox","admin_queue"),
            "participation":("📊 Open Participation Summary","participation_summary"),"whosaway":("📅 Open Who’s Away","whos_away")}
        label,action=actions[command];text=f"{label}\n\nThis operational screen is available only in your private chat."
        markup=menu_markup(ctx,[(label,action)])
    await update.effective_message.reply_text(text,reply_markup=markup)


def register_scoped_command_handlers(app):
    app.add_handler(CommandHandler([name for name,_ in PRIVATE_COMMANDS if name!="start"]+
        ["admin","inbox","participation","whosaway"],scoped_command))
