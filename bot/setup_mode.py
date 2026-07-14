"""Temporary, explicitly gated commands for collecting Telegram numeric IDs."""

from telegram import ChatMember, Update
from telegram.ext import CommandHandler, ContextTypes

DISABLED_MESSAGE = "Temporary setup mode is disabled."
GROUP_ADMIN_MESSAGE = "Sorry, this setup command is available only to administrators of this group."


def setup_enabled(ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(ctx.bot_data["config"].setup_mode)


async def require_setup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    if setup_enabled(ctx):
        return True
    await update.effective_message.reply_text(DISABLED_MESSAGE)
    return False


async def require_current_group_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    chat, user = update.effective_chat, update.effective_user
    if not chat or chat.type not in ("group", "supergroup") or not user:
        await update.effective_message.reply_text(GROUP_ADMIN_MESSAGE)
        return False
    member = await ctx.bot.get_chat_member(chat.id, user.id)
    if member.status not in (ChatMember.ADMINISTRATOR, ChatMember.OWNER):
        await update.effective_message.reply_text(GROUP_ADMIN_MESSAGE)
        return False
    return True


async def myid_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_setup(update, ctx):
        return
    user = update.effective_user
    if user:
        await update.effective_message.reply_text(f"Your Telegram user ID is: {user.id}")


async def chatid_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_setup(update, ctx) or not await require_current_group_admin(update, ctx):
        return
    await update.effective_message.reply_text(f"This Telegram chat ID is: {update.effective_chat.id}")


async def threadid_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_setup(update, ctx) or not await require_current_group_admin(update, ctx):
        return
    message = update.effective_message
    if not message.is_topic_message or message.message_thread_id is None:
        await message.reply_text("Run /threadid inside the forum topic whose ID you need.")
        return
    await message.reply_text(f"This forum topic thread ID is: {message.message_thread_id}")


def register_setup_handlers(app) -> None:
    app.add_handler(CommandHandler("myid", myid_command))
    app.add_handler(CommandHandler("chatid", chatid_command))
    app.add_handler(CommandHandler("threadid", threadid_command))
