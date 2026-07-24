"""Telegram handlers for creators, engagement, inactivity, POP, and reports."""

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from html import escape

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, TypeHandler, filters

import database as db
from engagement import classify, contains_promotional_spam
from permissions import can_manage_sensitive, can_mutate, can_read, can_view_audit, has_permission, role_for
from pop_policy import format_lateness, label as pop_label, posted_time, submission_timing
from pop_reliability import classify_pop_candidate
from routing import send_routed
from briefing import daily_admin_brief_job
from constants import MIN_AUDIO_PARTICIPATION_SECONDS
from telegram_io import retry_telegram


def config(ctx):
    return ctx.bot_data["config"]


async def require_admin(update, ctx):
    user_id = update.effective_user.id if update.effective_user else None
    if can_read(user_id, config(ctx)):
        return True
    await update.effective_message.reply_text("Sorry, this command is for admins only.")
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


def _pop_observed_at(update, message, timezone):
    """Return the original Telegram source time, never delayed processing/edit time."""
    moment = getattr(message, "date", None)
    return moment.astimezone(timezone).isoformat() if moment else datetime.now(timezone).isoformat()


def _update_type(update):
    return "edited_message" if getattr(update,"edited_message",None) is not None else "message"


async def record_update_observation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Count each replayable Telegram update once without consuming or rerouting it."""
    message=getattr(update,"edited_message",None) or getattr(update,"message",None)
    source_at=_pop_observed_at(update,message,config(ctx).timezone) if message else None
    kind=_update_type(update) if message else "callback_query" if getattr(update,"callback_query",None) else "other"
    db.claim_processed_update(getattr(update,"update_id",None),kind,source_at)


async def pop_report_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_permission(update, ctx, "view_creator_reports"): return
    cfg=config(ctx);now=datetime.now(cfg.timezone)
    rows=db.pop_status_report(now,getattr(cfg,"pop_due_weekday",3),getattr(cfg,"pop_cutoff_time","23:59"),getattr(cfg,"timezone_name","America/New_York"))
    lines = ["Thursday POP Report"] + [f"{r['display_name']}: {pop_label(r['effective_status'])}" for r in rows]
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


def participation_enabled(config, chat_id, thread_id):
    """Return whether a message is in a configured participation location."""
    configured_chat = getattr(config, "participation_chat_id", None) or getattr(config, "girls_chat_id", None)
    if configured_chat is None or chat_id != configured_chat:
        return False
    topics = frozenset(getattr(config, "participation_topic_ids", frozenset()) or ())
    legacy_topic = getattr(config, "girls_thread_id", None)
    if getattr(config,"participation_chat_id",None) is None and legacy_topic is not None:
        topics = topics | {legacy_topic}
    # An empty topic list intentionally means General only, never every forum topic.
    return thread_id in topics if topics else thread_id is None


def _participation_location(config):
    """Return the exact configured chat and topics used by the eligibility rule."""
    chat_id = getattr(config, "participation_chat_id", None) or getattr(config, "girls_chat_id", None)
    topics = set(getattr(config, "participation_topic_ids", frozenset()) or ())
    legacy_topic = getattr(config, "girls_thread_id", None)
    if getattr(config, "participation_chat_id", None) is None and legacy_topic is not None:
        topics.add(legacy_topic)
    return chat_id, sorted(topics)


def _record_creator_participation_diagnostic(config, creator, message, reason):
    """Persist an approved creator's last outcome without retaining message text."""
    configured_chat, configured_topics = _participation_location(config)
    payload = {
        "observed_at": datetime.now(config.timezone).isoformat(),
        "observed_chat_id": message.chat_id,
        "observed_thread_id": message.message_thread_id,
        "configured_chat_id": configured_chat,
        "configured_thread_ids": configured_topics,
        "chat_matches": message.chat_id == configured_chat,
        "topic_matches": participation_enabled(config, message.chat_id, message.message_thread_id),
        "reason": reason,
    }
    db.set_system_state(f"participation:last_creator:{creator['telegram_id']}", json.dumps(payload, separators=(",", ":")))


def _record_pop_location_diagnostic(config,message,reason):
    """Persist numeric location matches without retaining proof text or URLs."""
    configured_chat=getattr(config,"pop_chat_id",None) or getattr(config,"girls_chat_id",None)
    configured_thread=getattr(config,"pop_thread_id",None)
    payload={"observed_at":datetime.now(config.timezone).isoformat(),
        "observed_chat_id":message.chat_id,"observed_thread_id":message.message_thread_id,
        "configured_chat_id":configured_chat,"configured_thread_id":configured_thread,
        "chat_matches":message.chat_id==configured_chat,
        "topic_matches":message.chat_id==configured_chat and message.message_thread_id==configured_thread,
        "reason":reason}
    db.set_system_state("pop:last_observation",json.dumps(payload,separators=(",",":")))


def _audio_details(message):
    """Return Telegram's stable audio identity, duration, and participation type."""
    media = message.voice or getattr(message, "audio", None)
    if not media:
        return None
    kind = "voice_message" if message.voice else "audio_message"
    stable_id = getattr(media, "file_unique_id", None) or getattr(media, "file_id", None)
    digest = hashlib.sha256(f"{kind}:{stable_id}".encode()).hexdigest() if stable_id else None
    return kind, int(getattr(media, "duration", 0) or 0), digest


async def observe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg, user, cfg = update.effective_message, update.effective_user, config(ctx)
    if not msg or not user:
        return
    # Owner-guided test messages are evaluated without touching real engagement totals.
    state=db.system_state();code=state.get("readiness:test_code",{}).get("value","");mode=state.get("readiness:test_mode",{}).get("value","")
    prefix=f"VAD-SAFE-{code}:{mode}:" if code and mode else ""
    if prefix and (msg.text or "").startswith(prefix):
        creator=db.get_creator(user.id);in_location=participation_enabled(cfg,msg.chat_id,msg.message_thread_id)
        body=(msg.text or "")[len(prefix):].strip()
        decision=classify("hi" if mode=="ignored" else body,media=False,
            is_repeat=lambda digest,since:False,min_words=getattr(cfg,"meaningful_min_words",3),
            min_characters=getattr(cfg,"meaningful_min_characters",12),repeat_window_days=getattr(cfg,"repeat_window_days",7))
        passed=bool(creator and creator["status"]=="active" and (
            (mode=="meaningful" and in_location and decision.accepted) or
            (mode=="ignored" and in_location and not decision.accepted) or
            (mode=="wrong_topic" and msg.chat_id==getattr(cfg,"participation_chat_id",None) and not in_location) or
            (mode=="wrong_group" and msg.chat_id!=getattr(cfg,"participation_chat_id",None) and not in_location)))
        if passed:
            db.set_system_state(f"readiness:{mode}_test",datetime.now(cfg.timezone).isoformat())
            db.record_audit(user.id,"safe_readiness_test_passed","readiness_test",new_value={"mode":mode,"chat":msg.chat_id,"thread":msg.message_thread_id})
            await msg.reply_text("🟢 Safe test passed. Real participation totals were not changed.")
        else:
            await msg.reply_text("⚪ Safe test detected, but the location or test creator was not eligible. No operational data changed.")
        return
    if isinstance(msg.chat_id,int) and msg.chat_id<0:
        db.set_system_state("last_group_message_chat_id",msg.chat_id)
        db.set_system_state("last_group_message_thread_id",msg.message_thread_id if msg.message_thread_id is not None else "general:none")
        db.set_system_state("last_group_message_detected",datetime.now(cfg.timezone).isoformat())
    in_participation_chat = msg.chat_id == (getattr(cfg,"participation_chat_id",None) or getattr(cfg,"girls_chat_id",None))
    if in_participation_chat:
        detected_at=datetime.now(cfg.timezone).isoformat()
        db.set_system_state("last_participation_message_detected",detected_at)
        db.set_system_state("last_participation_chat_id",msg.chat_id)
        db.set_system_state("last_participation_thread_id",msg.message_thread_id if msg.message_thread_id is not None else "general:none")
    creator = db.get_creator(user.id)
    audio_details = _audio_details(msg)
    if not creator or creator["status"] != "active":
        if audio_details:
            _record_creator_participation_diagnostic(cfg,creator or {"telegram_id":user.id},msg,"creator_not_approved")
        if in_participation_chat and participation_enabled(cfg,msg.chat_id,msg.message_thread_id):
            db.record_audit(None,"engagement_ignored","participation_event",target_telegram_id=user.id,new_value={"reason":"unregistered_user"})
        return
    local_now = datetime.now(cfg.timezone)
    # An approved Away Notice pauses participation expectations, but it does not
    # prevent a creator from receiving credit when they choose to participate.
    active_away_notice = bool(db.approved_absence_on(user.id, local_now.date()))
    if creator["vacation_until"] and date.fromisoformat(creator["vacation_until"]) >= local_now.date():
        _record_creator_participation_diagnostic(cfg,creator,msg,"legacy_vacation_active")
        return
    thread_id = msg.message_thread_id
    media = bool(msg.photo or msg.sticker or msg.animation or msg.video or msg.voice or getattr(msg,"audio",None) or msg.document)
    pop_chat_id = getattr(cfg,"pop_chat_id",None) or getattr(cfg,"girls_chat_id",None)
    in_pop_topic=bool(pop_chat_id==msg.chat_id and cfg.pop_thread_id and thread_id==cfg.pop_thread_id)
    _record_pop_location_diagnostic(cfg,msg,"configured_topic" if in_pop_topic else "outside_configured_topic")
    if in_pop_topic:
        source_at=_pop_observed_at(update,msg,cfg.timezone);observed_at=local_now.isoformat()
        update_id=getattr(update,"update_id",None)
        _,recovered=db.claim_processed_update(update_id,_update_type(update),source_at)
        decision=classify_pop_candidate(msg)
        period_week,timing=submission_timing(datetime.fromisoformat(source_at),
            getattr(cfg,"pop_due_weekday",3),getattr(cfg,"pop_cutoff_time","23:59"),
            getattr(cfg,"timezone_name","America/New_York"))
        db.set_system_state("pop:last_topic_update",observed_at)
        db.set_system_state("pop:last_observed_chat_id",msg.chat_id)
        db.set_system_state("pop:last_observed_thread_id",thread_id)
        if (decision.proof_type or decision.needs_review) and timing!="not_yet_due":
            proof_type=decision.proof_type or "ambiguous_text"
            needs_review=decision.reason if decision.needs_review else None
            related=db.recent_pop_evidence(user.id,msg.chat_id,thread_id,source_at)
            relationship="supporting" if related else "primary"
            result=db.record_pop_evidence(user.id,period_week,msg.message_id,msg.chat_id,thread_id,
                proof_type,timing,source_message_at=source_at,observed_at=observed_at,
                update_id=update_id,recovered_after_outage=recovered,
                needs_review_reason=needs_review,relationship=relationship)
            if decision.proof_type:db.set_system_state("pop:last_valid_proof",observed_at)
            if decision.proof_type and timing=="late":
                late=db.claim_late_pop_alert(result["submission_id"])
                if late:
                    source=datetime.fromisoformat(late["source_message_at"])
                    await send_routed(ctx.bot,cfg,"pop_review",
                        "🟠 POP Submitted During Grace Period\n\n"
                        f"Creator: {escape(late['display_name'])}\n"
                        f"Submitted: {posted_time(source,cfg.timezone_name)}\n"
                        f"Week: {late['week_key']}\n\n"
                        f"Delay: {format_lateness(source,cfg.pop_due_weekday,cfg.pop_cutoff_time,cfg.timezone_name)}\n"
                        "Status: Accepted\n\n"
                        "This submission was received during the Friday grace period and was recorded successfully.\n\n"
                        "Grace period: POP is due Thursday at 11:59 PM Eastern. Submissions received through Friday at 11:59 PM Eastern are late but accepted and receive credit.\n\n"
                        "Preservation requirement: The submitted POP should remain available for at least 24 hours from the original posting time.\n\n"
                        "Action for admins: None required. This notice is informational only. No warning or strike was created automatically.",
                        target_telegram_id=late["telegram_id"],related_submission_id=late["id"],
                        payload_summary=f"Late POP heads-up for submission {late['id']}")
            if result["created"]:
                qualifier=" and needs review" if needs_review else ""
                recovery=" after the bot reconnected" if recovered else ""
                await msg.reply_text(f"📸 Your Weekly POP was recorded{recovery}{qualifier}. Your original posting time was used.")
            _record_creator_participation_diagnostic(cfg,creator,msg,"pop_workflow_message")
            return
        # POP-topic conversation must never spill into participation tracking.
        _record_creator_participation_diagnostic(cfg,creator,msg,
            "pop_candidate_needs_context" if decision.needs_review else "pop_unqualified_message")
        return
    if not participation_enabled(cfg,msg.chat_id,thread_id):
        configured_chat,_configured_topics=_participation_location(cfg)
        reason="wrong_chat" if msg.chat_id != configured_chat else "wrong_topic"
        _record_creator_participation_diagnostic(cfg,creator,msg,reason)
        if in_participation_chat:
            db.record_audit(None,"engagement_ignored","participation_event",target_telegram_id=user.id,new_value={"reason":"wrong_topic"})
        return
    if audio_details:
        event_type,duration,digest=audio_details
        if duration < MIN_AUDIO_PARTICIPATION_SECONDS:
            decision_reason="audio_too_short"
        elif contains_promotional_spam(msg.caption or ""):
            decision_reason="promotional_spam"
        elif not digest:
            decision_reason="audio_missing_file_identity"
        else:
            since=(datetime.now(timezone.utc)-timedelta(days=int(getattr(cfg,"repeat_window_days",7)))).isoformat()
            decision_reason="duplicate_audio" if db.recent_hash_exists(user.id,digest,since) else event_type
        accepted=decision_reason in {"voice_message","audio_message"}
        stored=db.record_engagement(user.id,msg.message_id,msg.chat_id,thread_id,digest,
            "accepted" if accepted else "rejected",decision_reason,event_type=event_type)
        if stored and accepted:
            source_at=_pop_observed_at(update,msg,cfg.timezone)
            _,recovered=db.claim_processed_update(getattr(update,"update_id",None),_update_type(update),source_at)
            if recovered:db.count_recovered_event("participation")
            diagnostic_reason=(f"accepted_{event_type}_during_away_notice"
                if active_away_notice else f"accepted_{event_type}")
            _record_creator_participation_diagnostic(cfg,creator,msg,diagnostic_reason)
            counted_at=datetime.now(cfg.timezone).isoformat()
            db.set_system_state("last_meaningful_participation_counted",counted_at)
            db.set_system_state("readiness:meaningful_test",counted_at)
        elif stored:
            _record_creator_participation_diagnostic(cfg,creator,msg,decision_reason)
            db.set_system_state("readiness:ignored_test",datetime.now(cfg.timezone).isoformat())
        else:
            _record_creator_participation_diagnostic(cfg,creator,msg,"duplicate_telegram_update")
        return
    decision = classify(msg.text, media=media,
        is_repeat=lambda digest, since: db.recent_hash_exists(user.id, digest, since),
        min_words=getattr(cfg,"meaningful_min_words",3),
        min_characters=getattr(cfg,"meaningful_min_characters",12),
        repeat_window_days=getattr(cfg,"repeat_window_days",7))
    stored=db.record_engagement(user.id,msg.message_id,msg.chat_id,thread_id,decision.digest or None,
                         "accepted" if decision.accepted else "rejected",decision.reason)
    if stored and decision.accepted:
        source_at=_pop_observed_at(update,msg,cfg.timezone)
        _,recovered=db.claim_processed_update(getattr(update,"update_id",None),_update_type(update),source_at)
        if recovered:db.count_recovered_event("participation")
        diagnostic_reason = "accepted_during_away_notice" if active_away_notice else "accepted"
        _record_creator_participation_diagnostic(cfg,creator,msg,diagnostic_reason)
        counted_at=datetime.now(cfg.timezone).isoformat()
        db.set_system_state("last_meaningful_participation_counted",counted_at)
        # A real accepted event is stronger evidence than the isolated safe test.
        db.set_system_state("readiness:meaningful_test",counted_at)
    elif stored:
        _record_creator_participation_diagnostic(cfg,creator,msg,decision.reason)
        db.set_system_state("readiness:ignored_test",datetime.now(cfg.timezone).isoformat())
    else:
        _record_creator_participation_diagnostic(cfg,creator,msg,"duplicate_telegram_update")


async def inactivity_job(ctx: ContextTypes.DEFAULT_TYPE):
    cfg = config(ctx)
    now = datetime.now(timezone.utc)
    local_date = now.astimezone(cfg.timezone).date()
    db.sync_absence_availability(local_date)
    db.set_system_state("last_scheduled_check",datetime.now(cfg.timezone).isoformat())
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
        if hours >= cfg.alert_hours:
            if db.claim_notification(creator["telegram_id"], anchor, "alert"):
                full_creator=db.get_creator(creator["telegram_id"])
                username=f"@{full_creator['username']}" if full_creator and full_creator["username"] else "No username"
                try:
                    await ctx.bot.send_message(creator["telegram_id"],
                        "💙 Just checking in again\n\nWe still haven’t seen recent meaningful participation from you.\n\n"
                        "Staying involved helps maintain momentum in the chat and keeps the community active and interesting "
                        "for creators and clients alike.\n\nIf you’re taking some time away, please use the Away Notice option "
                        "so the bot can pause reminders and protect your standing.")
                    db.record_audit(None,"three_day_checkin_delivered","notification",target_telegram_id=creator["telegram_id"])
                except Exception:
                    db.record_audit(None,"three_day_checkin_delivery_failed","notification",target_telegram_id=creator["telegram_id"],result="error")
                await send_routed(ctx.bot,cfg,"participation_alert",
                    f"🔴 Friendly Admin follow-up\n{escape(creator['display_name'])} · {username}\nTelegram ID: {creator['telegram_id']}\n"
                    "Creator has reached the three-day participation threshold and may need a friendly check-in.\n"
                    f"Last meaningful participation: {anchor}\nElapsed: {hours:.1f} hours\nAway Notice: None active\nOpen Admin Home → Participation Alerts.",
                    target_telegram_id=creator["telegram_id"])
                db.set_system_state("last_admin_notification",datetime.now(cfg.timezone).isoformat())
            # Never fall back to a two-day reminder after the three-day cycle was
            # already claimed on an earlier scheduler run.
            continue
        if hours >= cfg.warning_hours and db.claim_notification(creator["telegram_id"], anchor, "warning"):
            try:
                await ctx.bot.send_message(creator["telegram_id"],
                    "💛 Friendly check-in\n\nWe haven’t seen a meaningful message from you in a couple of days.\n\n"
                    "Regular conversation helps keep the community lively, welcoming, and engaging for everyone, "
                    "including the clients who enjoy getting to know the creators.\n\nThere’s no pressure if life is busy. "
                    "If you’ll be away for a while, you can submit an Away Notice and participation expectations will pause during that time.")
                db.record_audit(None,"warning_delivered","notification",target_telegram_id=creator["telegram_id"])
            except Exception:
                db.record_audit(None,"warning_delivery_failed","notification",target_telegram_id=creator["telegram_id"],result="error")
            await send_routed(ctx.bot,cfg,"participation_flag",
                f"🟠 Two-day participation flag\n{escape(creator['display_name'])}\nTelegram ID: {creator['telegram_id']}\n"
                f"Last meaningful participation: {anchor}\nElapsed: {hours:.1f} hours\nAway Notice: None active.",
                target_telegram_id=creator["telegram_id"])
    # Missing POP becomes time-sensitive only after the centralized ET deadline.
    pop_rows = (db.pop_status_report(datetime.now(cfg.timezone),cfg.pop_due_weekday,cfg.pop_cutoff_time,cfg.timezone_name)
                if hasattr(cfg,"pop_due_weekday") else ())
    for row in pop_rows:
        if row["effective_status"] == "missing" and db.claim_notification(row["telegram_id"],row["week_key"],"pop_exception"):
            await send_routed(ctx.bot,cfg,"pop_review",
                f"🔴 Thursday POP needs attention\n{escape(row['display_name'])}\nThe deadline passed without POP or an applicable excusal.",
                target_telegram_id=row["telegram_id"])


POP_THURSDAY_REMINDER_TIME = time(10, 0)
POP_FRIDAY_REMINDER_TIME = time(12, 0)
POP_FRIDAY_REMINDER_TEXT = (
    "Hi! Life gets busy, and it looks like we haven’t recorded your Weekly POP yet. "
    "You can still submit it in the POP topic. Please remember to leave your post up for "
    "the required time."
)


async def pop_reminder_job(ctx: ContextTypes.DEFAULT_TYPE):
    """Send one gentle POP reminder per creator/week without changing POP state."""
    cfg = config(ctx)
    now = datetime.now(cfg.timezone)
    local_time = now.timetz().replace(tzinfo=None)
    if now.weekday() == 3 and local_time >= POP_THURSDAY_REMINDER_TIME:
        eligible_statuses = {"due_today"}
        notification_kind = "pop_thursday_reminder"
        body = ("Hi! This is a friendly reminder to submit your Weekly POP in the POP topic today. "
                "If an approved Away Notice applies, you are already excused.")
    elif now.weekday() == 4 and local_time >= POP_FRIDAY_REMINDER_TIME:
        eligible_statuses = {"missing"}
        notification_kind = "pop_friday_reminder"
        body = POP_FRIDAY_REMINDER_TEXT
    else:
        return
    rows = db.pop_status_report(now, cfg.pop_due_weekday, cfg.pop_cutoff_time, cfg.timezone_name)
    for row in rows:
        if row["effective_status"] not in eligible_statuses:
            continue
        if not db.claim_notification(row["telegram_id"], row["week_key"], notification_kind):
            continue
        try:
            await ctx.bot.send_message(row["telegram_id"], body)
            db.record_audit(None, f"{notification_kind}_delivered", "notification",
                target_telegram_id=row["telegram_id"])
        except Exception:
            db.record_audit(None, f"{notification_kind}_delivery_failed", "notification",
                target_telegram_id=row["telegram_id"], result="error")


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


async def pop_preservation_job(ctx: ContextTypes.DEFAULT_TYPE):
    """Audit inconclusive preservation checks without treating them as removal evidence."""
    cfg=config(ctx);now=datetime.now(cfg.timezone)
    for row in db.pop_preservation_due(now):
        db.mark_pop_preservation_unavailable(row["id"],now.isoformat())


async def telegram_recovery_job(ctx: ContextTypes.DEFAULT_TYPE):
    """Maintain polling incidents without making a competing Telegram probe."""
    db.resolve_quiet_polling_incidents()
    cfg=config(ctx)
    for incident in db.polling_incidents_due_escalation():
        if not db.claim_polling_escalation(incident["id"]):continue
        db.record_audit(None,"system_error","system",target_record_id=incident["id"],result="error",
            reason="Sustained Telegram polling read failures",new_value={"incident_id":incident["id"],
            "operation":"get_updates","occurrence_count":incident["occurrence_count"]},
            error_reference=incident["error_reference"])
        notice=(f"⚠️ Temporary Telegram connection issue\nReference: {incident['error_reference']}\n"
            "Repeated getUpdates read failures need review. Occurrences remain grouped until polling is stable.")
        for owner_id in cfg.owner_user_ids:
            try:await retry_telegram(lambda owner_id=owner_id:ctx.bot.send_message(owner_id,notice),attempts=2)
            except Exception:pass
        if cfg.admin_chat_id and getattr(cfg,"health_thread_id",None):
            try:await retry_telegram(lambda:ctx.bot.send_message(cfg.admin_chat_id,notice,
                message_thread_id=cfg.health_thread_id),attempts=2)
            except Exception:pass


def _recovery_stamp(value,cfg):
    if not value:return "Unknown"
    moment=datetime.fromisoformat(value).astimezone(cfg.timezone)
    return f"{moment.strftime('%A')} {moment.strftime('%I').lstrip('0')}:{moment.strftime('%M %p')} ET"


async def startup_recovery_job(ctx: ContextTypes.DEFAULT_TYPE):
    """Finalize one pending-update catch-up and privately summarize it to Owners."""
    cfg=config(ctx);run_id=ctx.bot_data.get("recovery_run_id")
    if not run_id:return
    run=db.finalize_recovery_run(run_id,datetime.now(cfg.timezone).isoformat())
    if not run:return
    db.set_system_state("pop:last_reconciliation",run["completed_at"])
    db.set_system_state("pop:last_recovery_confidence",run["confidence"])
    if not db.claim_recovery_summary(run_id):return
    body=("♻️ Recovery Summary\n\n"
        f"Offline: {_recovery_stamp(run['previous_heartbeat_at'],cfg)} – {_recovery_stamp(run['started_at'],cfg)}\n"
        f"Telegram updates recovered: {run['updates_recovered']}\n"
        f"POP submissions recovered: {run['pop_recovered']}\n"
        f"Participation events recovered: {run['participation_recovered']}\n"
        f"Away Notice updates recovered: {run['away_recovered']}\n\n"
        f"POP on time: {run['pop_on_time']}\nPOP late: {run['pop_late']}\n"
        f"POP needs review: {run['pop_needs_review']}\n"
        f"Recovery confidence: {run['confidence'].title()}")
    if run["unresolved_gap"]:
        body += "\n\nAn unrecoverable gap may remain. Telegram does not provide arbitrary group-history retrieval."
    for owner_id in cfg.owner_user_ids:
        if not db.claim_owner_summary(owner_id,f"recovery:{run_id}"):continue
        try:await ctx.bot.send_message(owner_id,body)
        except Exception:
            db.record_audit(None,"recovery_summary_delivery_failed","recovery_run",
                target_record_id=run_id,target_telegram_id=owner_id,result="error")


async def runtime_heartbeat_job(ctx: ContextTypes.DEFAULT_TYPE):
    db.record_runtime_heartbeat()


def register_handlers(app):
    app.add_handler(TypeHandler(Update,record_update_observation),group=-100)
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
        filters.VIDEO | filters.VOICE | filters.AUDIO | filters.Document.ALL
    )
    app.add_handler(MessageHandler(pop_media, observe), group=10)
    app.job_queue.run_once(startup_recovery_job,when=105,name="startup-pop-recovery")
    app.job_queue.run_repeating(runtime_heartbeat_job,interval=30,first=15,name="runtime-heartbeat")
    app.job_queue.run_repeating(inactivity_job, interval=1800, first=150, name="inactivity-monitor")
    app.job_queue.run_repeating(pop_reminder_job, interval=900, first=180, name="pop-reminder-monitor")
    app.job_queue.run_repeating(pop_preservation_job,interval=900,first=180,name="pop-preservation-monitor")
    # A repeating check allows Owner settings to take effect without rescheduling jobs.
    app.job_queue.run_repeating(daily_admin_brief_job, interval=900, first=180, name="daily-admin-brief")
    app.job_queue.run_repeating(telegram_recovery_job,interval=60,first=60,name="telegram-polling-incident-maintenance")
    cfg = app.bot_data.get("config")
    if cfg and getattr(cfg, "daily_owner_summary_enabled", False):
        try:
            hour, minute = map(int, getattr(cfg,"daily_owner_summary_time","09:00").split(":", 1))
            app.job_queue.run_daily(daily_owner_summary_job, time=time(hour,minute,tzinfo=cfg.timezone), name="daily-owner-summary")
        except (ValueError, TypeError):
            pass
