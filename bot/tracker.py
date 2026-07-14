"""Telegram handlers for creators, engagement, inactivity, POP, and reports."""

from datetime import date, datetime, time, timedelta, timezone
from html import escape

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

import database as db
from engagement import classify
from permissions import can_manage_sensitive, can_mutate, can_read, can_view_audit, has_permission, role_for


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


async def require_permission(update, ctx, permission):
    user_id = update.effective_user.id if update.effective_user else None
    if has_permission(user_id, config(ctx), permission):
        return True
    await update.effective_message.reply_text("You do not have permission for this operational action.")
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
    await update.message.reply_text("You’re registered! Your profile is waiting for a quick community review. 💛")


async def approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_permission(update, ctx, "review_registrations"): return
    target = parse_target(ctx)
    if not target or not db.set_status(target, "active", update.effective_user.id):
        return await update.message.reply_text("Usage: /creator_approve TELEGRAM_ID (registered creator required)")
    await update.message.reply_text(f"Creator {target} is approved and ready to participate.")


async def deactivate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_permission(update, ctx, "manage_creators"): return
    target = parse_target(ctx)
    if not target or not db.set_status(target, "inactive", update.effective_user.id):
        return await update.message.reply_text("Usage: /creator_deactivate TELEGRAM_ID")
    await update.message.reply_text(f"Creator {target} is now inactive. Their history is preserved.")


async def reject_creator(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_permission(update, ctx, "review_registrations"): return
    target = parse_target(ctx)
    if not target or not db.set_status(target, "rejected", update.effective_user.id):
        return await update.message.reply_text("Usage: /creator_reject TELEGRAM_ID")
    await update.message.reply_text(f"Registration for creator {target} was not approved. The decision is recorded.")


async def delete_creator(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_permission(update, ctx, "manage_creators"): return
    target = parse_target(ctx)
    if not target or not db.delete_creator(target, update.effective_user.id):
        return await update.message.reply_text("Usage: /creator_delete TELEGRAM_ID")
    await update.message.reply_text(f"Creator {target} archived with history preserved.")


async def vacation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    target = user.id
    raw = ctx.args[0] if ctx.args else ""
    if len(ctx.args) >= 2:
        if not await require_permission(update, ctx, "review_vacations"): return
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
        if not await require_permission(update, ctx, "review_vacations"): return
        target = parse_target(ctx)
    else:
        target = update.effective_user.id
    if not db.set_vacation(target, None, update.effective_user.id):
        return await update.message.reply_text("Creator is not registered.")
    await update.message.reply_text("Vacation mode disabled.")


async def creator_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_permission(update, ctx, "view_creator_reports"): return
    rows = db.list_creators()
    lines = ["Creator report"] + [f"{r['display_name']} ({r['telegram_id']}): {r['status']}; last meaningful: {r['last_meaningful_at'] or 'never'}; vacation: {r['vacation_until'] or 'off'}" for r in rows]
    if not rows:
        lines.append("No creators are registered yet.")
    await update.message.reply_text("\n".join(lines)[:4000])


def week_key(now):
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


async def pop_report_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_permission(update, ctx, "view_creator_reports"): return
    key = ctx.args[0] if ctx.args else week_key(datetime.now(config(ctx).timezone))
    rows = db.pop_report(key)
    lines = [f"POP report {key}"] + [f"{r['display_name']} ({r['telegram_id']}): {r['status'] or 'missing'}" + (f" [submission {r['id']}]" if r['id'] else "") for r in rows]
    await update.message.reply_text("\n".join(lines)[:4000])


async def pop_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE, status):
    if not await require_permission(update, ctx, "review_pop"): return
    try: submission_id = int(ctx.args[0])
    except (IndexError, ValueError): return await update.message.reply_text(f"Usage: /pop_{status} SUBMISSION_ID [note]")
    note = " ".join(ctx.args[1:])
    submission = db.get_pop_submission(submission_id)
    if not db.review_pop(submission_id, status, update.effective_user.id, note):
        return await update.message.reply_text("Pending submission not found.")
    if submission:
        try:
            await ctx.bot.send_message(submission["telegram_id"], f"Your Thursday POP submission was {status.replace('_', ' ')}." + (f" Note: {note}" if note else ""))
        except Exception:
            pass
    await update.message.reply_text(f"POP submission {submission_id} {status}.")


async def pop_approve(update, ctx): return await pop_review(update, ctx, "approved")
async def pop_reject(update, ctx): return await pop_review(update, ctx, "rejected")
async def pop_resubmit(update, ctx): return await pop_review(update, ctx, "resubmission_requested")


async def history_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    if not can_view_audit(user_id, config(ctx)):
        await update.effective_message.reply_text("Sorry, the private audit log is for owners only.")
        return
    rows = db.history()
    lines = ["Owner audit log"] + [f"{r['occurred_at']} actor={r['actor_id']} target={r['target_telegram_id']} {r['action']} {r['new_value'] or ''}" for r in rows]
    await update.message.reply_text("\n".join(lines)[:4000])


async def reset_history_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update, ctx): return
    await update.message.reply_text("The audit log is append-only and cannot be altered or erased.")


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
    if not await require_permission(update, ctx, "change_settings"): return
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
    if db.approved_absence_on(user.id, local_now.date()):
        return
    if creator["vacation_until"] and date.fromisoformat(creator["vacation_until"]) >= local_now.date():
        return
    thread_id = msg.message_thread_id
    media = bool(msg.photo or msg.sticker or msg.animation or msg.video or msg.voice or msg.document)
    pop_caption = (msg.caption or "").casefold() if media else ""
    if media and "pop" in pop_caption and cfg.pop_thread_id and thread_id == cfg.pop_thread_id and local_now.weekday() == 3:
        proof_type = "photo" if msg.photo else "document" if msg.document else "media"
        if db.submit_pop(user.id, week_key(local_now), msg.message_id, msg.chat_id, thread_id, proof_type):
            await msg.reply_text("Thursday POP received! 📸 It’s now waiting for review.")
            if cfg.admin_chat_id:
                try:
                    await ctx.bot.send_message(cfg.admin_chat_id,
                        f"📸 POP awaiting review\n{escape(user.full_name)} submitted Thursday POP.",
                        message_thread_id=cfg.reports_thread_id)
                    db.record_audit(None,"pop_notification_delivered","notification",target_telegram_id=user.id)
                except Exception:
                    db.record_audit(None,"pop_notification_delivery_failed","notification",target_telegram_id=user.id,result="error")
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
    db.sync_absence_availability(local_date)
    for creator in db.due_creators():
        absence = db.approved_absence_on(creator["telegram_id"], local_date)
        if absence or (creator["vacation_until"] and date.fromisoformat(creator["vacation_until"]) >= local_date):
            continue
        anchor = creator["last_meaningful_at"] or creator["approved_at"] or creator["registered_at"]
        started = datetime.fromisoformat(anchor)
        recent = db.calendar_absences("1900-01-01", local_date.isoformat())
        creator_absences = [r for r in recent if r["telegram_id"] == creator["telegram_id"]]
        if creator_absences:
            last_end = max(date.fromisoformat(r["end_date"]) for r in creator_absences)
            grace_start = datetime.combine(last_end + timedelta(days=1), time.min, cfg.timezone)
            if grace_start > started:
                started = grace_start
        hours = (now - started.astimezone(timezone.utc)).total_seconds() / 3600
        if hours >= cfg.alert_hours and db.claim_notification(creator["telegram_id"], anchor, "alert"):
            if cfg.admin_chat_id:
                try:
                    await ctx.bot.send_message(cfg.admin_chat_id,
                        f"🔴 Admin follow-up required\n{escape(creator['display_name'])} has reached the three-day community participation limit.",
                        message_thread_id=cfg.reports_thread_id)
                    db.record_audit(None,"alert_delivered","notification",target_telegram_id=creator["telegram_id"])
                except Exception:
                    db.record_audit(None,"alert_delivery_failed","notification",target_telegram_id=creator["telegram_id"],result="error")
        elif hours >= cfg.warning_hours and db.claim_notification(creator["telegram_id"], anchor, "warning"):
            try:
                await ctx.bot.send_message(creator["telegram_id"],
                    "🟠 Participation reminder\n\nIt has been two days since your last meaningful participation. "
                    "Another day without participation will notify the admin team. Taking time away? You can record an Away Notice.")
                db.record_audit(None,"warning_delivered","notification",target_telegram_id=creator["telegram_id"])
            except Exception:
                db.record_audit(None,"warning_delivery_failed","notification",target_telegram_id=creator["telegram_id"],result="error")


async def daily_owner_summary_job(ctx: ContextTypes.DEFAULT_TYPE):
    """Optional and disabled by default; delivery is deduplicated per owner and Eastern date."""
    cfg = config(ctx)
    if not cfg.daily_owner_summary_enabled:
        return
    now = datetime.now(cfg.timezone)
    key = week_key(now)
    metrics = db.dashboard_metrics(key)
    attention = db.needs_attention_counts(key)
    body = (
        "📊 VAD Daily Summary\n\n"
        f"🚨 Needs attention: {attention['total']}\n"
        f"👥 Active creators: {metrics['active_creators']}\n"
        f"💙 Away now: {metrics['away_now']}\n"
        f"📸 POP awaiting review: {metrics['pending_pop']}\n"
        f"🟠 Participation alerts: {metrics['participation_flags']}\n"
        f"⚠️ Warnings / strikes: {metrics['active_warnings']} / {metrics['active_strikes']}\n"
        + ("🟢 System healthy" if metrics["failed_notifications"] == 0 else "🟠 Delivery failures need review")
    )
    for owner_id in cfg.owner_user_ids:
        cycle = f"owner-summary:{now.date().isoformat()}"
        if not db.claim_owner_summary(owner_id, cycle):
            continue
        try:
            await ctx.bot.send_message(owner_id, body)
            db.record_audit(None,"owner_summary_delivered","notification",target_telegram_id=owner_id)
        except Exception:
            db.record_audit(None,"owner_summary_delivery_failed","notification",target_telegram_id=owner_id,result="error")


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
    app.add_handler(CommandHandler("pop_resubmit", pop_resubmit))
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
    cfg = app.bot_data.get("config")
    if cfg and getattr(cfg, "daily_owner_summary_enabled", False):
        try:
            hour, minute = map(int, getattr(cfg,"daily_owner_summary_time","09:00").split(":", 1))
            app.job_queue.run_daily(daily_owner_summary_job, time=time(hour,minute,tzinfo=cfg.timezone), name="daily-owner-summary")
        except (ValueError, TypeError):
            pass
