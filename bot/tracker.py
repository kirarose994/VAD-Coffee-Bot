"""Telegram handlers for creators, engagement, inactivity, POP, and reports."""

from datetime import date, datetime, time, timedelta, timezone
from html import escape

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

import database as db
from engagement import classify
from permissions import can_manage_sensitive, can_mutate, can_read, can_view_audit, role_for


def config(ctx):
    return ctx.bot_data["config"]


async def require_admin(update, ctx):
    user_id = update.effective_user.id if update.effective_user else None
    if can_read(user_id, config(ctx)):
        return True
    await update.effective_message.reply_text("Sorry, this command is for admins and lead admins only.")
    return False


async def require_operational_admin(update, ctx):
    user_id = update.effective_user.id if update.effective_user else None
    if can_mutate(user_id, config(ctx)):
        return True
    await update.effective_message.reply_text("Sorry, this command is for operational admins only.")
    return False


async def require_owner(update, ctx):
    user_id = update.effective_user.id if update.effective_user else None
    if can_manage_sensitive(user_id, config(ctx)):
        return True
    await update.effective_message.reply_text("Sorry, this command is for owners only.")
    return False


def parse_target(ctx):
    try:
        return int(ctx.args[0])
    except (IndexError, ValueError):
        return None


async def register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.register_creator(user.id, user.username, user.full_name)
    await update.message.reply_text("Registration submitted for admin approval.")


async def approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_operational_admin(update, ctx): return
    target = parse_target(ctx)
    if not target or not db.set_status(target, "active", update.effective_user.id):
        return await update.message.reply_text("Usage: /creator_approve TELEGRAM_ID (registered creator required)")
    await update.message.reply_text(f"Creator {target} approved.")


async def deactivate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_operational_admin(update, ctx): return
    target = parse_target(ctx)
    if not target or not db.set_status(target, "inactive", update.effective_user.id):
        return await update.message.reply_text("Usage: /creator_deactivate TELEGRAM_ID")
    await update.message.reply_text(f"Creator {target} deactivated.")


async def reject_creator(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_operational_admin(update, ctx): return
    target = parse_target(ctx)
    if not target or not db.set_status(target, "rejected", update.effective_user.id):
        return await update.message.reply_text("Usage: /creator_reject TELEGRAM_ID")
    await update.message.reply_text(f"Creator {target} rejected.")


async def delete_creator(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_operational_admin(update, ctx): return
    target = parse_target(ctx)
    if not target or not db.delete_creator(target, update.effective_user.id):
        return await update.message.reply_text("Usage: /creator_delete TELEGRAM_ID")
    await update.message.reply_text(f"Creator {target} and related tracker records deleted.")


async def vacation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    target = user.id
    raw = ctx.args[0] if ctx.args else ""
    if len(ctx.args) >= 2:
        if not await require_operational_admin(update, ctx): return
        target, raw = parse_target(ctx), ctx.args[1]
    try:
        until = date.fromisoformat(raw).isoformat()
    except (ValueError, TypeError):
        return await update.message.reply_text("Usage: /vacation YYYY-MM-DD or admin: /vacation ID YYYY-MM-DD")
    if not db.set_vacation(target, until, user.id):
        return await update.message.reply_text("Creator is not registered.")
    await update.message.reply_text(f"Vacation mode active through {until} Eastern Time.")


async def vacation_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args:
        if not await require_operational_admin(update, ctx): return
        target = parse_target(ctx)
    else:
        target = update.effective_user.id
    if not db.set_vacation(target, None, update.effective_user.id):
        return await update.message.reply_text("Creator is not registered.")
    await update.message.reply_text("Vacation mode disabled.")


async def creator_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, ctx): return
    rows = db.list_creators()
    lines = ["Creator report"] + [f"{r['display_name']} ({r['telegram_id']}): {r['status']}; last meaningful: {r['last_meaningful_at'] or 'never'}; vacation: {r['vacation_until'] or 'off'}" for r in rows]
    if not rows:
        lines.append("No creators are registered yet.")
    await update.message.reply_text("\n".join(lines)[:4000])


def week_key(now):
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


async def pop_report_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, ctx): return
    key = ctx.args[0] if ctx.args else week_key(datetime.now(config(ctx).timezone))
    rows = db.pop_report(key)
    lines = [f"POP report {key}"] + [f"{r['display_name']} ({r['telegram_id']}): {r['status'] or 'missing'}" + (f" [submission {r['id']}]" if r['id'] else "") for r in rows]
    await update.message.reply_text("\n".join(lines)[:4000])


async def pop_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE, status):
    if not await require_operational_admin(update, ctx): return
    try: submission_id = int(ctx.args[0])
    except (IndexError, ValueError): return await update.message.reply_text(f"Usage: /pop_{status} SUBMISSION_ID [note]")
    note = " ".join(ctx.args[1:])
    if not db.review_pop(submission_id, status, update.effective_user.id, note):
        return await update.message.reply_text("Pending submission not found.")
    await update.message.reply_text(f"POP submission {submission_id} {status}.")


async def pop_approve(update, ctx): return await pop_review(update, ctx, "approved")
async def pop_reject(update, ctx): return await pop_review(update, ctx, "rejected")


async def history_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    if not can_view_audit(user_id, config(ctx)):
        await update.effective_message.reply_text("Sorry, the private audit log is for owners only.")
        return
    rows = db.history()
    lines = ["Admin history"] + [f"{r['created_at']} actor={r['actor_id']} target={r['target_id']} {r['action']} {r['details'] or ''}" for r in rows]
    await update.message.reply_text("\n".join(lines)[:4000])


async def reset_history_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update, ctx): return
    deleted = db.reset_history(update.effective_user.id)
    await update.message.reply_text(f"Audit history reset. {deleted} earlier entries removed; this reset was audited.")


SETTING_FIELDS = {
    "warning_hours": "warning_hours", "alert_hours": "alert_hours",
    "girls_chat_id": "girls_chat_id", "girls_thread_id": "girls_thread_id",
    "pop_thread_id": "pop_thread_id", "reports_thread_id": "reports_thread_id",
}


async def settings_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, ctx): return
    cfg = config(ctx)
    lines = [f"Role: {role_for(update.effective_user.id, cfg).name.lower()}"]
    lines.extend(f"{key}={getattr(cfg, field)}" for key, field in SETTING_FIELDS.items())
    await update.message.reply_text("\n".join(lines))


async def setting_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_operational_admin(update, ctx): return
    if len(ctx.args) != 2 or ctx.args[0] not in SETTING_FIELDS:
        return await update.message.reply_text("Usage: /setting_set KEY INTEGER_OR_NONE")
    key, raw = ctx.args
    try:
        value = None if raw.casefold() == "none" else int(raw)
    except ValueError:
        return await update.message.reply_text("Setting values must be an integer or 'none'.")
    cfg, field = config(ctx), SETTING_FIELDS[key]
    old_value = getattr(cfg, field)
    setattr(cfg, field, value)
    db.audit_setting_change(update.effective_user.id, key, old_value, value)
    await update.message.reply_text(f"{key} changed from {old_value} to {value}. Replit Secrets remain the restart source of truth.")


async def observe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg, user, cfg = update.effective_message, update.effective_user, config(ctx)
    if not msg or not user or not cfg.girls_chat_id or update.effective_chat.id != cfg.girls_chat_id:
        return
    creator = db.get_creator(user.id)
    if not creator or creator["status"] != "active":
        return
    local_now = datetime.now(cfg.timezone)
    if creator["vacation_until"] and date.fromisoformat(creator["vacation_until"]) >= local_now.date():
        return
    thread_id = msg.message_thread_id
    media = bool(msg.photo or msg.sticker or msg.animation or msg.video or msg.voice or msg.document)
    if media and cfg.pop_thread_id and thread_id == cfg.pop_thread_id and local_now.weekday() == 3:
        proof_type = "photo" if msg.photo else "document" if msg.document else "media"
        if db.submit_pop(user.id, week_key(local_now), msg.message_id, msg.chat_id, thread_id, proof_type):
            await msg.reply_text("POP proof received and pending admin approval.")
        return
    if cfg.girls_thread_id is not None and thread_id != cfg.girls_thread_id:
        return
    decision = classify(msg.text, media=media,
        is_repeat=lambda digest, since: db.recent_hash_exists(user.id, digest, since))
    db.record_engagement(user.id, msg.message_id, msg.chat_id, thread_id, decision.digest or None,
                         "accepted" if decision.accepted else "rejected", decision.reason)


async def inactivity_job(ctx: ContextTypes.DEFAULT_TYPE):
    cfg = config(ctx)
    now = datetime.now(timezone.utc)
    local_date = now.astimezone(cfg.timezone).date()
    for creator in db.due_creators():
        if creator["vacation_until"] and date.fromisoformat(creator["vacation_until"]) >= local_date:
            continue
        anchor = creator["last_meaningful_at"] or creator["approved_at"] or creator["registered_at"]
        started = datetime.fromisoformat(anchor)
        hours = (now - started.astimezone(timezone.utc)).total_seconds() / 3600
        if hours >= cfg.alert_hours and db.claim_notification(creator["telegram_id"], anchor, "alert"):
            if cfg.admin_chat_id:
                await ctx.bot.send_message(cfg.admin_chat_id,
                    f"3-day inactivity alert: {escape(creator['display_name'])} ({creator['telegram_id']})",
                    message_thread_id=cfg.reports_thread_id)
        elif hours >= cfg.warning_hours and db.claim_notification(creator["telegram_id"], anchor, "warning"):
            try:
                await ctx.bot.send_message(creator["telegram_id"], "Friendly reminder: no meaningful girls-group engagement has been recorded for two days.")
            except Exception:
                pass


def register_handlers(app):
    app.add_handler(CommandHandler("creator_register", register))
    app.add_handler(CommandHandler("creator_approve", approve))
    app.add_handler(CommandHandler("creator_deactivate", deactivate))
    app.add_handler(CommandHandler("creator_reject", reject_creator))
    app.add_handler(CommandHandler("creator_delete", delete_creator))
    app.add_handler(CommandHandler("vacation", vacation))
    app.add_handler(CommandHandler("vacation_off", vacation_off))
    app.add_handler(CommandHandler("creator_report", creator_report))
    app.add_handler(CommandHandler("pop_report", pop_report_command))
    app.add_handler(CommandHandler("pop_approve", pop_approve))
    app.add_handler(CommandHandler("pop_reject", pop_reject))
    app.add_handler(CommandHandler("admin_history", history_command))
    app.add_handler(CommandHandler("history_reset", reset_history_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("setting_set", setting_set))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, observe), group=10)
    pop_media = (
        filters.PHOTO | filters.Sticker.ALL | filters.ANIMATION |
        filters.VIDEO | filters.VOICE | filters.Document.ALL
    )
    app.add_handler(MessageHandler(pop_media, observe), group=10)
    app.job_queue.run_repeating(inactivity_job, interval=1800, first=60, name="inactivity-monitor")
