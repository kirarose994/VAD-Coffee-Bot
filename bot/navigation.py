"""Role-aware, nonce-protected application navigation."""

import io
import json
import secrets
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

import database as db
from config import RESOURCE_DEFAULTS
from permissions import Role, has_permission, role_for
from pop_policy import current_period, label as pop_label
from presentation import audit_entry, friendly_timestamp, timeline_entry
from runtime_config import persist_setting


def _nonce(ctx):
    value = secrets.token_urlsafe(6)
    ctx.user_data["menu_nonce"] = value
    return value


def _button(label, nonce, action):
    return InlineKeyboardButton(label, callback_data=f"op:{nonce}:{action}")


def _nav(nonce, back="home"):
    """Passive screens need Home and Back; Cancel belongs to active workflows only."""
    return [_button("🏠 Home", nonce, "home"), _button("◀️ Back", nonce, back)]


def grid_markup(ctx, rows, back="home"):
    nonce = _nonce(ctx)
    keyboard = [[_button(label,nonce,action) for label,action in row] for row in rows if row]
    keyboard.append(_nav(nonce,back))
    return InlineKeyboardMarkup(keyboard)


def home_markup(ctx, user_id):
    nonce = _nonce(ctx)
    cfg = ctx.bot_data["config"]
    role = role_for(user_id, cfg)
    creator = db.get_creator(user_id)
    member = db.get_member(user_id)
    rows = []
    if creator:
        rows.append([_button("👤 My Creator Hub", nonce, "creator")])
    elif member and member["member_type"] == "creator":
        rows.append([_button("👤 Registration Status",nonce,"registration_status")])
    elif not member:
        rows.append([_button("✨ I'm a Creator / Seller", nonce, "join_creator")])
        if role is Role.NONE:
            rows.append([_button("🛍️ I'm a Buyer", nonce, "join_buyer")])
    elif role is Role.NONE:
        rows.append([_button("🛍️ Buyer Home", nonce, "buyer")])
    if role >= Role.ADMIN:
        rows.append([_button("🛡️ Admin Tools", nonce, "admin")])
    if role is Role.OWNER:
        rows.append([_button("🔐 Owner Dashboard", nonce, "owner")])
    rows.extend([
        [_button("📚 Help Center", nonce, "resources"), _button("💬 Get Help", nonce, "support")],
    ])
    return InlineKeyboardMarkup(rows)


def menu_markup(ctx, actions, back="home"):
    nonce = _nonce(ctx)
    rows = [[_button(label, nonce, action)] for label, action in actions]
    rows.append(_nav(nonce, back))
    return InlineKeyboardMarkup(rows)


def confirmation_markup(ctx, confirm_action, back="setup"):
    """Confirmation controls for a state-changing workflow."""
    nonce = _nonce(ctx)
    return InlineKeyboardMarkup([
        [_button("✅ Confirm",nonce,confirm_action),_button("❌ Cancel",nonce,"cancel")],
        [_button("◀️ Back",nonce,back)],
    ])


def _week_key(now):
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _standing(summary):
    if summary["strikes"] >= 3:
        return "🔴 Owner review required"
    if summary["strikes"]:
        return f"🟠 {summary['strikes']} strike{'s' if summary['strikes'] != 1 else ''} documented"
    if summary["warnings"] >= 2:
        return f"🟠 {summary['warnings']} warnings"
    if summary["warnings"] == 1:
        return "💛 1 warning"
    return "💚 Good standing"


AVAILABILITY_LABELS = {
    "available": "🟢 Available",
    "unavailable": "⚪ Unavailable",
    "vacation": "🌴 On vacation",
    "sick": "🤒 Not feeling well",
}

def _pop_args(cfg):
    return (getattr(cfg,"pop_due_weekday",3),getattr(cfg,"pop_cutoff_time","23:59"),getattr(cfg,"timezone_name","America/New_York"))


def _metrics(cfg):
    now = datetime.now(cfg.timezone)
    period = current_period(now,*_pop_args(cfg))
    metrics = db.dashboard_metrics(period.week_key)
    pop = db.pop_status_counts(now,*_pop_args(cfg))
    metrics["pending_pop"] = pop["awaiting_review"]
    metrics["missing_pop"] = pop["missing"]
    return metrics


def _friendly_time(value, cfg):
    if not value:
        return "No participation recorded yet"
    try:
        moment = datetime.fromisoformat(value).astimezone(cfg.timezone)
        return f"{moment.strftime('%b')} {moment.day} at {moment.strftime('%I').lstrip('0')}:{moment.strftime('%M %p')}"
    except (ValueError, TypeError):
        return "Not available"


def creator_card(user_id, cfg):
    creator = db.get_creator(user_id)
    if not creator:
        return "You are not registered yet. Tap Register to get started."
    warning = db.warning_summary(user_id)
    pop = db.creator_current_pop_status(user_id,datetime.now(cfg.timezone),*_pop_args(cfg)) if creator["status"] == "active" else "not_due"
    absence = db.latest_absence(user_id)
    away = "None" if not absence else f"{absence['start_date']}–{absence['end_date']} · {absence['status'].title()}"
    participation = "Active" if creator["status"] == "active" else creator["status"].title()
    timing = ""
    next_step = ""
    anchor = creator["last_meaningful_at"] or creator["approved_at"] or creator["registered_at"]
    if creator["status"] == "active" and anchor and creator["availability"] not in {"vacation","sick"}:
        try:
            elapsed = (datetime.now(cfg.timezone) - datetime.fromisoformat(anchor).astimezone(cfg.timezone)).total_seconds() / 3600
            warning_hours, alert_hours = getattr(cfg,"warning_hours",48), getattr(cfg,"alert_hours",72)
            if elapsed >= alert_hours:
                participation = "🔴 Admin follow-up required"
                next_step = "\n➡️ The three-day limit was reached; the admin team has been notified."
            elif elapsed >= warning_hours:
                participation = "🟠 Participation reminder"
                timing = f"\n⏱ Admin follow-up in about {max(0, int(alert_hours-elapsed))}h"
                next_step = "\n➡️ Join a meaningful conversation or record an Away Notice."
            else:
                timing = f"\n⏱ Friendly reminder in about {max(0, int(warning_hours-elapsed))}h"
        except (TypeError,ValueError):
            pass
    return (
        "📋 Today’s Status\n"
        f"🤝 Participation: {participation}\n"
        f"📸 Thursday POP: {pop_label(pop)}\n"
        f"{_standing(warning)}\n"
        f"💙 Away Notice: {away}\n"
        f"{AVAILABILITY_LABELS.get(creator['availability'], '⚪ Unavailable')}\n"
        f"🕒 Last meaningful participation: {_friendly_time(creator['last_meaningful_at'], cfg)}"
        f"{timing}{next_step}"
    )


def admin_card(cfg):
    metrics = _metrics(cfg)
    pending = metrics["pending_registrations"] + metrics["pending_vacations"] + metrics["pending_sick"] + metrics["pending_pop"]
    return (
        f"🚨 Admin queue: {pending + metrics.get('participation_flags', 0) + metrics.get('failed_notifications', 0)}\n"
        f"📝 New creators: {metrics['pending_registrations']}\n"
        f"💙 Away Notices: {metrics['pending_vacations'] + metrics['pending_sick']}\n"
        f"📸 POP reviews: {metrics['pending_pop']}\n"
        f"🟠 Participation flags: {metrics.get('participation_flags', 0)}\n"
        f"⚠️ Failed notifications: {metrics.get('failed_notifications', 0)}"
    )


def owner_card(cfg):
    metrics = _metrics(cfg)
    attention_total = metrics.get("needs_attention", 0)
    return (
        f"🚨 Needs attention: {attention_total}\n"
        f"👥 Active creators: {metrics['active_creators']}\n"
        f"💙 Away now: {metrics['away_now']}\n"
        f"📸 POP reviews: {metrics['pending_pop']}\n"
        f"🟠 Participation alerts: {metrics.get('participation_flags', 0)}\n"
        f"⚠️ Warnings / strikes: {metrics['active_warnings']} / {metrics['active_strikes']}\n"
        f"🗃️ Archived records: {metrics['deleted_records']}\n"
        f"🔐 Audit events today: {metrics.get('audit_today', 0)}\n"
        + ("🟢 System healthy" if metrics.get("failed_notifications", 0) == 0 else "🟠 Notification delivery needs review")
    )


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    returning = bool(ctx.user_data.get("welcome_seen"))
    ctx.user_data.clear()
    ctx.user_data["welcome_seen"] = True
    role = role_for(update.effective_user.id, ctx.bot_data["config"])
    creator = db.get_creator(update.effective_user.id)
    member = db.get_member(update.effective_user.id)
    text = f"Welcome back, {update.effective_user.first_name}! 💛" if returning else (
        f"Welcome, {update.effective_user.first_name}! 💛\n\n"
        "Your VAD Community Hub is here to help keep participation, Thursday POP, Away Notices, and personal updates together.\n\n"
        "Away Notices simply keep tracking fair while you take time away. No private details are required."
    )
    if creator:
        text += "\n\nToday\n" + creator_card(update.effective_user.id,ctx.bot_data["config"])
    elif role >= Role.ADMIN:
        text += "\n\nChoose the tools you need below."
    elif member and member["member_type"] == "buyer":
        text += "\n\nBuyer Home keeps community help and support easy to find."
    elif member:
        text += "\n\nOpen Registration Status to review how your creator profile is recorded."
    else:
        text += "\n\nChoose the community view that fits you."
    markup = home_markup(ctx, update.effective_user.id)
    await update.effective_message.reply_text(text, reply_markup=markup)


async def _show(query, text, markup):
    await query.edit_message_text(text, reply_markup=markup)


async def callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = (query.data or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "op" or parts[1] != ctx.user_data.get("menu_nonce"):
        await query.answer("This button expired or was already used.", show_alert=True)
        return await _show(query, "That action expired. Choose from your current home menu.", home_markup(ctx, update.effective_user.id))
    await query.answer()
    action = parts[2]
    user_id = update.effective_user.id
    cfg = ctx.bot_data["config"]
    role = role_for(user_id, cfg)
    if action == "home":
        text = "VAD Operations\n\nHere to keep your participation clear, supported, and fair. 💛"
        if db.get_creator(user_id): text += "\n\nToday\n" + creator_card(user_id,cfg)
        return await _show(query,text,home_markup(ctx,user_id))
    if action == "cancel":
        ctx.user_data.clear()
        return await _show(query, "Action cancelled.", home_markup(ctx, user_id))
    if action == "join_creator":
        member = db.get_member(user_id)
        if member and member["member_type"] == "buyer":
            return await _show(query,"That community view is already set.",home_markup(ctx,user_id))
        outcome = db.register_creator(user_id,update.effective_user.username,update.effective_user.full_name)
        if outcome == "archived":
            return await _show(query,"Your earlier creator record is archived. An owner can review and restore it from the Archive.",home_markup(ctx,user_id))
        if outcome == "active":
            return await _show(query,"Your creator profile is already approved and active.",home_markup(ctx,user_id))
        if outcome in {"inactive","rejected"}:
            return await _show(query,f"Your creator profile is currently {outcome}. Contact an owner if you need another review.",home_markup(ctx,user_id))
        if getattr(cfg,"admin_chat_id",None) and outcome == "created":
            try:
                await ctx.bot.send_message(cfg.admin_chat_id,
                    f"📝 New creator\n{update.effective_user.full_name} is ready for review.",
                    message_thread_id=getattr(cfg,"registration_thread_id",None) or getattr(cfg,"reports_thread_id",None))
            except Exception:
                db.record_audit(None,"registration_notification_delivery_failed","notification",target_telegram_id=user_id,result="error")
        return await _show(query,"Welcome! 💛\n\nYour creator profile is ready for community review.",home_markup(ctx,user_id))
    if action == "registration_status":
        status = db.creator_identity_status(user_id)
        labels = {"not_registered":"Not registered","pending":"Waiting for review","active":"Approved and active",
            "inactive":"Inactive","rejected":"Not approved","archived":"Archived"}
        details = [f"Status: {labels.get(status['state'],status['state'].title())}",
            f"Visible in creator lists: {'Yes' if status['directory_visible'] else 'No'}"]
        if status.get("identity_consistent") is False:
            details.append("Identity check: Needs owner review")
        explanation = "See exactly how your creator registration is recorded."
        return await _show(query,"👤 Registration Status\n\n"+explanation+"\n\n"+"\n".join(details),menu_markup(ctx,[],"home"))
    if action == "join_buyer":
        if role is not Role.NONE or db.get_creator(user_id):
            return await _show(query,"That community view is already set.",home_markup(ctx,user_id))
        db.register_member(user_id,update.effective_user.username,update.effective_user.full_name,"buyer")
        return await _show(query,"Welcome to the buyer community. 💛\n\nUse Buyer Home for help and community information.",home_markup(ctx,user_id))
    if action == "buyer":
        member = db.get_member(user_id)
        if role is not Role.NONE or not member or member["member_type"] != "buyer":
            return await _show(query,"Buyer Home is available to registered buyers.",home_markup(ctx,user_id))
        return await _show(query,"🛍️ Buyer Home\n\nFind community information or ask the admin team for help.",grid_markup(ctx,[
            [("📜 Community Rules","resource_rules")],[("💬 Contact Admin","contact")],[("📚 Help Center","resources")]
        ]))
    if action == "creator":
        creator = db.get_creator(user_id)
        if not creator:
            return await _show(query,"Creator access is not available for this account.",home_markup(ctx,user_id))
        return await _show(query, "👤 My Creator Hub\n\nSee your participation, POP, time away, and community standing.\n\n" + creator_card(user_id, cfg), grid_markup(ctx, [
            [("🟢 Available","available"),("⚪ Unavailable","unavailable")],
            [("💙 Let Us Know You’ll Be Away","away_help")],
            [("📸 POP Help","pop_help"),("💛 My Standing","my_warnings")],
            [("📜 Timeline","timeline_0"),("💬 Get Help","contact")],
        ]))
    if action == "admin":
        if role < Role.ADMIN:
            return await _show(query, "Admin access is required.", home_markup(ctx, user_id))
        rows = [[("🚨 Admin Queue","admin_queue")]]
        if has_permission(user_id,cfg,"review_registrations"): rows.append([("📝 Review New Creators","registration_queue")])
        if has_permission(user_id,cfg,"review_vacations") or has_permission(user_id,cfg,"review_sick_days"):
            rows.append([("💙 Away Notices","away_queue")])
        if has_permission(user_id,cfg,"review_pop"): rows.append([("📸 POP Reviews","pop_queue")])
        if has_permission(user_id,cfg,"view_creator_reports"): rows.append([("👥 Active Creators","creator_report"),("📅 Community Calendar","calendar")])
        tools = []
        if has_permission(user_id,cfg,"adjust_warnings"): tools.append(("💛 Creator Standing","warnings_help"))
        if has_permission(user_id,cfg,"send_announcements"): tools.append(("💬 Message Center","templates_help"))
        if tools: rows.append(tools)
        return await _show(query, "🛡️ Admin Tools\n\nReview community items assigned to your role.\n\n" + admin_card(cfg), grid_markup(ctx,rows))
    if action == "owner":
        if role is not Role.OWNER:
            return await _show(query, "Owner access is required.", home_markup(ctx, user_id))
        return await _show(query, "👑 Owner Dashboard\n\n" + owner_card(cfg), grid_markup(ctx,[
            [("🚨 Needs Attention","needs_attention")],
            [("📊 Reports","reports"),("👥 Access","roles")],
            [("🔐 Audit","audit"),("🗃️ Archive","deleted")],
            [("♻️ Restore","restore_help")],
            [("🧭 Setup","setup"),("🩺 Health","health")],
            [("💾 Export","export_help")],
        ]))
    if action == "register":
        member = db.get_member(user_id)
        if member and member["member_type"] == "buyer":
            return await _show(query,"This account is already set up for the buyer community. Contact an owner if that needs to change.",home_markup(ctx,user_id))
        outcome = db.register_creator(user_id, update.effective_user.username, update.effective_user.full_name)
        if outcome == "archived":
            return await _show(query,"Your previous creator record is archived. Please contact an owner.",home_markup(ctx,user_id))
        if outcome == "active":
            return await _show(query,"Your creator profile is already approved and active.",home_markup(ctx,user_id))
        if outcome in {"inactive","rejected"}:
            return await _show(query,f"Your creator profile is currently {outcome}. Contact an owner if you need another review.",home_markup(ctx,user_id))
        if getattr(cfg,"admin_chat_id",None) and outcome == "created":
            try:
                await ctx.bot.send_message(cfg.admin_chat_id,
                    f"📝 New registration\n{update.effective_user.full_name} is waiting for review.",
                    message_thread_id=getattr(cfg,"registration_thread_id",None) or getattr(cfg,"reports_thread_id",None))
                db.record_audit(None,"registration_notification_delivered","notification",target_telegram_id=user_id)
            except Exception:
                db.record_audit(None,"registration_notification_delivery_failed","notification",target_telegram_id=user_id,result="error")
        return await _show(query, "You’re registered! 💛\n\nYour profile is waiting for a quick community review. We’ll update your dashboard when it’s ready.", menu_markup(ctx, [], "creator"))
    if action in {"needs_attention", "admin_queue"}:
        if action == "needs_attention" and role is not Role.OWNER:
            return await _show(query, "Needs Attention is available only to owners.", home_markup(ctx,user_id))
        if action == "admin_queue" and role < Role.ADMIN:
            return await _show(query, "Admin access is required.", home_markup(ctx,user_id))
        now = datetime.now(cfg.timezone)
        period = current_period(now,*_pop_args(cfg))
        counts = db.needs_attention_counts(period.week_key,now=now,due_weekday=_pop_args(cfg)[0],cutoff_time=_pop_args(cfg)[1],timezone_name=_pop_args(cfg)[2])
        permitted = []
        if has_permission(user_id,cfg,"review_registrations"):
            permitted.append(("📝 New creators",counts["registrations"],"registration_queue"))
        if has_permission(user_id,cfg,"review_vacations") or has_permission(user_id,cfg,"review_sick_days"):
            permitted.append(("💙 Away Notices",counts["away_notices"],"away_queue"))
        if has_permission(user_id,cfg,"review_pop"):
            permitted.append(("📸 POP reviews",counts["pop_reviews"],"pop_queue"))
        if has_permission(user_id,cfg,"view_creator_reports"):
            permitted.extend([
                ("🟡 Near two days",counts["near_two_days"],"participation_queue"),
                ("🔴 Three-day alerts",counts["three_day_alerts"],"participation_queue"),
                ("🔴 Missing POP",counts.get("missing_pop",0),"pop_queue"),
            ])
        if has_permission(user_id,cfg,"adjust_warnings"):
            permitted.extend([
                ("⚠️ Unacknowledged",counts["unacknowledged_warnings"],"warnings_help"),
                ("🔴 Owner review",counts["owner_reviews"],"warnings_help"),
            ])
        if role is Role.OWNER:
            permitted.extend([
                ("📭 Failed notifications",counts["failed_notifications"],"health"),
                ("🗃️ Recent archive changes",counts["recent_archive_changes"],"deleted"),
            ])
        active = [item for item in permitted if item[1]]
        title = "🚨 Needs Attention" if action == "needs_attention" else "🚨 Admin Queue"
        if not active:
            text = title + "\n\n✅ Nothing needs your attention right now."
        else:
            text = title + "\n\n" + "\n".join(f"{label}: {count}" for label,count,_ in active)
        buttons = [[(f"{label} · {count}",target)] for label,count,target in active]
        return await _show(query,text,grid_markup(ctx,buttons,"owner" if role is Role.OWNER else "admin"))
    if action == "away_queue":
        if not (has_permission(user_id,cfg,"review_vacations") or has_permission(user_id,cfg,"review_sick_days")):
            return await _show(query,"This review area isn’t included in your access.",home_markup(ctx,user_id))
        rows = db.list_absence_requests("pending")
        text = "💙 Away Notices\n\n" + ("\n\n".join(
            f"#{r['id']} · {r['display_name']}\n{r['start_date']} → {r['end_date']}\n💙 Acknowledge with /absence_queue"
            for r in rows[:10]) or "💙 No Away Notices need review.")
        return await _show(query,text[:3900],menu_markup(ctx,[],"admin"))
    if action == "participation_queue":
        if not has_permission(user_id,cfg,"view_creator_reports"):
            return await _show(query,"Participation reports aren’t included in your access.",home_markup(ctx,user_id))
        rows = db.participation_attention(cfg.warning_hours,cfg.alert_hours)
        lines = ["🟠 Participation Attention"] + [
            f"{('🔴' if r['hours'] >= cfg.alert_hours else '🟠')} {r['display_name']} · {int(r['hours'])}h"
            for r in rows[:20]
        ]
        if not rows: lines.append("✅ No participation follow-up is needed.")
        return await _show(query,"\n\n".join(lines),menu_markup(ctx,[],"admin"))
    if action in {"available", "unavailable"}:
        if not db.set_availability(user_id, action, user_id, "creator self-service"):
            text = "Please register before updating availability."
        else:
            text = f"You’re now marked {action}."
        return await _show(query, text, menu_markup(ctx, [], "creator"))
    if action == "away_help":
        return await _show(query, "💙 Let Us Know You’ll Be Away\n\nChoose the category that fits best. Private details are never required.", menu_markup(ctx, [
            ("🌴 Vacation or trip","away_category_vacation_trip"),("🤒 Not feeling well","away_category_not_feeling_well"),
            ("🧠 Mental health or personal day","away_category_personal_day"),("🚨 Emergency","away_category_emergency"),
            ("💙 Other time away","away_category_other")], "creator"))
    if action.startswith("away_category_"):
        if not db.get_creator(user_id): return await _show(query,"Away Notices become available after registration.",menu_markup(ctx,[],"creator"))
        ctx.user_data["away_category"]=action.removeprefix("away_category_");ctx.user_data["guided_input"]="away_dates"
        return await _show(query,"🗓️ Choose Dates\n\nType the start date and end date as YYYY-MM-DD YYYY-MM-DD. You may add an optional short note after the dates.\n\nExample: 2026-08-01 2026-08-03 Family trip",menu_markup(ctx,[],"away_help"))
    if action in {"vacation_help", "sick_help"}:
        return await _show(query,"Choose Let Us Know You’ll Be Away to start the guided Away Notice workflow.",menu_markup(ctx,[("💙 Start Away Notice","away_help")],"creator"))
    if action == "pop_help":
        return await _show(query, "Submit meaningful POP proof in the configured girls-group Thursday POP topic. Images elsewhere are ignored.", menu_markup(ctx, [], "creator"))
    if action in {"my_activity", "my_status"}:
        text = creator_card(user_id, cfg)
        return await _show(query, text, menu_markup(ctx, [], "creator"))
    if action == "my_warnings":
        rows = db.list_warnings(user_id)
        summary = db.warning_summary(user_id)
        lines = [f"My Standing: {_standing(summary)}"] + [f"#{r['id']} {r['warning_type'].title()} — {r['status']}\n{r['reason']}" for r in rows]
        actions = [(f"Acknowledge #{r['id']}",f"ackwarning_{r['id']}") for r in rows if r["status"] == "active"]
        return await _show(query, "\n\n".join(lines)[:3900], menu_markup(ctx, actions, "creator"))
    if action.startswith("ackwarning_"):
        try: warning_id = int(action.split("_",1)[1])
        except ValueError: warning_id = 0
        warning = db.get_warning(warning_id)
        if not warning or warning["telegram_id"] != user_id:
            return await _show(query,"That warning is unavailable.",menu_markup(ctx,[],"creator"))
        if not db.acknowledge_warning(warning_id,user_id):
            text = "That warning was already acknowledged or removed."
        else:
            text = "Warning acknowledged. Thank you—your timeline has been updated. 💛"
        return await _show(query,text,menu_markup(ctx,[],"creator"))
    if action.startswith("timeline_"):
        try: page = max(0, int(action.split("_", 1)[1]))
        except ValueError: page = 0
        rows = db.creator_timeline(user_id, 8, page * 8)
        lines = ["📜 My Timeline"] + [timeline_entry(r,getattr(cfg,"timezone_name","America/New_York")) for r in rows]
        actions = []
        if page: actions.append(("⬅️ Newer", f"timeline_{page - 1}"))
        if len(rows) == 8: actions.append(("Older ➡️", f"timeline_{page + 1}"))
        return await _show(query, "\n\n".join(lines) if rows else "My Timeline\n\nNo activity yet.", menu_markup(ctx, actions, "creator"))
    if action == "reports" and role < Role.ADMIN:
        creator = db.get_creator(user_id)
        text = "Register to view your personal report." if not creator else (
            f"My Report\nApproval: {creator['status']}\nAvailability: {creator['availability']}\n"
            f"Last meaningful engagement: {creator['last_meaningful_at'] or 'none'}"
        )
        return await _show(query, text, menu_markup(ctx, [], "home"))
    if action == "calendar" and role < Role.ADMIN:
        rows = db.creator_absences(user_id)
        text = "My Absence Calendar\n" + ("\n".join(f"{r['start_date']}–{r['end_date']} {r['absence_type']} ({r['status']})" for r in rows) or "No absence requests.")
        return await _show(query, text[:3900], menu_markup(ctx, [], "home"))
    if action in {"contact", "support"}:
        ctx.user_data["guided_input"] = "contact_admin"
        back = "creator" if db.get_creator(user_id) else "buyer" if db.get_member(user_id) else "home"
        return await _show(query, "💬 Contact Admin\n\nWhat do you need help with? Send one message below. Please do not include private medical details.\n\nYou’ll preview it before anything is sent.", menu_markup(ctx, [], back))
    if action == "resources":
        help_actions = [("⭐ Getting Started","resource_about"),("📜 Community Rules","resource_rules"),
            ("📈 Participation Guide","resource_engagement"),("📸 Thursday POP Guide","resource_pop"),
            ("💙 Away Notice Guide","resource_vacation"),("❓ Frequently Asked Questions","resource_faq"),
            ("💬 Contact Admin","contact")]
        return await _show(query, "📚 Help Center\n\nChoose a topic below.", menu_markup(ctx, help_actions))
    if action.startswith("resource_"):
        key = action.removeprefix("resource_")
        title, body = RESOURCE_DEFAULTS.get(key, ("Resource", "Resource not found."))
        return await _show(query, f"{title}\n\n{body}", menu_markup(ctx, [], "resources"))
    if action == "audit" or action.startswith("audit_filter_"):
        if role is not Role.OWNER:
            return await _show(query, "The complete audit log and administrator identities are owner-only.", menu_markup(ctx, [], "admin"))
        rows = list(db.history(100))
        selected = action.removeprefix("audit_filter_") if action.startswith("audit_filter_") else "today"
        today = datetime.now(cfg.timezone).date()
        filters = {
            "today": lambda r: datetime.fromisoformat(r["occurred_at"]).astimezone(cfg.timezone).date()==today,
            "admins": lambda r: r["actor_role"] in {"admin","lead_admin","owner"},
            "creators": lambda r: r["actor_role"] == "creator",
            "errors": lambda r: r["result"] == "error",
            "deletions": lambda r: "deleted" in r["action"],
            "restorations": lambda r: "restored" in r["action"],
            "warnings": lambda r: "warning" in r["action"] or "strike" in r["action"],
            "roles": lambda r: "role" in r["action"] or "permission" in r["action"],
            "exports": lambda r: "export" in r["action"],
        }
        rows = [row for row in rows if filters.get(selected,filters["today"])(row)][:12]
        def resolve(actor_id):
            creator = db.get_creator(actor_id)
            return creator["display_name"] if creator else None
        text = "🔐 Owner Audit\n\n" + ("\n\n".join(audit_entry(r,resolve,getattr(cfg,"timezone_name","America/New_York")) for r in rows) or "✅ No audit records match this filter.")
        actions = [("Today","audit_filter_today"),("Admin actions","audit_filter_admins"),("Creator actions","audit_filter_creators"),
            ("System errors","audit_filter_errors"),("Deletions","audit_filter_deletions"),("Restorations","audit_filter_restorations"),
            ("Warnings & strikes","audit_filter_warnings"),("Role changes","audit_filter_roles"),("Exports","audit_filter_exports")]
        return await _show(query, text[:3900], menu_markup(ctx, actions, "owner"))
    if action == "deleted":
        if role is not Role.OWNER:
            return await _show(query, "Deleted records are owner-only.", home_markup(ctx, user_id))
        rows = db.deleted_records()
        text = "Deleted creator records\n" + ("\n".join(f"{r['telegram_id']} {r['display_name']} — {r['deleted_at']}" for r in rows) or "None.")
        return await _show(query, text, menu_markup(ctx, [], "owner"))
    if action == "registration_queue" and has_permission(user_id,cfg,"review_registrations"):
        rows = [r for r in db.list_creators() if r["status"] == "pending"]
        buttons = [[(r["display_name"][:40],f"registration_select_{r['telegram_id']}")] for r in rows[:20]]
        text = "📝 Registration Reviews\n\n" + ("Select a creator to review." if rows else "✅ No registrations are waiting.\nYou’re all caught up.")
        return await _show(query,text,grid_markup(ctx,buttons,"admin"))
    if action.startswith("registration_select_"):
        if not has_permission(user_id,cfg,"review_registrations"):
            return await _show(query,"Registration review isn’t included in your access.",home_markup(ctx,user_id))
        target = int(action.removeprefix("registration_select_"))
        creator = db.get_creator(target)
        if not creator or creator["status"] != "pending": return await _show(query,"This registration is no longer pending.",menu_markup(ctx,[],"registration_queue"))
        return await _show(query,f"📝 Review Registration\n\n{creator['display_name']}\n@{creator['username'] or 'no username'}\n\nWhat would you like to record?",
            menu_markup(ctx,[("✅ Approve",f"registration_confirm_approve_{target}"),("🚫 Decline",f"registration_confirm_reject_{target}")],"registration_queue"))
    if action.startswith("registration_confirm_"):
        if not has_permission(user_id,cfg,"review_registrations"):
            return await _show(query,"Registration review isn’t included in your access.",home_markup(ctx,user_id))
        parts = action.split("_")
        decision,target = parts[2],int(parts[3])
        status = "active" if decision == "approve" else "rejected"
        if not db.set_status(target,status,user_id): text = "This registration was already handled."
        else: text = "✅ Creator approved." if status == "active" else "Registration declined and recorded."
        return await _show(query,text,menu_markup(ctx,[],"registration_queue"))
    if action in {"vacation_queue","sick_queue"}:
        absence_type = "vacation" if action == "vacation_queue" else "sick"
        permission = "review_vacations" if absence_type == "vacation" else "review_sick_days"
        if not has_permission(user_id,cfg,permission):
            return await _show(query,"This review area isn’t included in your access.",menu_markup(ctx,[],"admin"))
        rows = db.list_absence_requests("pending",absence_type)
        text = f"{absence_type.title()} Away Notices\n\n" + ("\n\n".join(f"#{r['id']} · {r['display_name']}\n{r['start_date']} → {r['end_date']}\nReview: /absence_queue {absence_type}" for r in rows[:10]) or "All caught up! No Away Notices are waiting. ✨")
        return await _show(query,text[:3900],menu_markup(ctx,[],"admin"))
    if action == "pop_queue" and has_permission(user_id,cfg,"review_pop"):
        now = datetime.now(cfg.timezone)
        period = current_period(now,*_pop_args(cfg))
        rows = db.pop_status_report(now,*_pop_args(cfg))
        pending = [r for r in rows if r["effective_status"] == "awaiting_review"]
        missing = [r for r in rows if r["effective_status"] == "missing"]
        due = f"{period.due_at.strftime('%A, %b')} {period.due_at.day} at {period.due_at.strftime('%I').lstrip('0')}:{period.due_at.strftime('%M %p')} ET"
        lines = ["📸 Thursday POP Review",f"Due: {due}",f"Waiting for review: {len(pending)}",f"Missing after deadline: {len(missing)}"]
        lines += [f"\n{r['display_name']} · Awaiting review" for r in pending[:8]]
        if not pending: lines.append("\n📸 No POP reviews are waiting.\nYou’re all caught up.")
        buttons=[(r["display_name"][:40],f"pop_select_{r['id']}") for r in pending[:20]]
        return await _show(query,"\n".join(lines)[:3900],menu_markup(ctx,buttons,"admin"))
    if action.startswith("pop_select_"):
        if not has_permission(user_id,cfg,"review_pop"): return await _show(query,"POP review isn’t included in your access.",home_markup(ctx,user_id))
        submission_id=int(action.removeprefix("pop_select_"));submission=db.get_pop_submission(submission_id)
        if not submission or submission["status"]!="pending": return await _show(query,"That POP submission is no longer pending.",menu_markup(ctx,[],"pop_queue"))
        creator=db.get_creator(submission["telegram_id"])
        return await _show(query,f"📸 Review POP\n\n{creator['display_name']}\nSubmitted: {friendly_timestamp(submission['submitted_at'],timezone_name=getattr(cfg,'timezone_name','America/New_York'))}\n\nChoose a decision.",
            menu_markup(ctx,[("✅ Approve",f"pop_decide_approved_{submission_id}"),("🔴 Reject",f"pop_decide_rejected_{submission_id}"),("🟡 Request Resubmission",f"pop_decide_resubmission_requested_{submission_id}")],"pop_queue"))
    if action.startswith("pop_decide_"):
        if not has_permission(user_id,cfg,"review_pop"): return await _show(query,"POP review isn’t included in your access.",home_markup(ctx,user_id))
        raw=action.removeprefix("pop_decide_");status,submission_raw=raw.rsplit("_",1);submission_id=int(submission_raw)
        changed=db.review_pop(submission_id,status,user_id,"Guided review")
        return await _show(query,"✅ POP decision recorded and audited." if changed else "That submission was already reviewed.",menu_markup(ctx,[],"pop_queue"))
    if action == "creator_report" and has_permission(user_id,cfg,"view_creator_reports"):
        actions = [("🔎 Search by Name","creator_search_name"),("🆔 Search by Telegram ID","creator_search_id"),
            ("📋 Browse All Creators","creator_list_all"),("🟢 Available","creator_list_available"),
            ("⚪ Unavailable","creator_list_unavailable"),("💙 Away","creator_list_away"),
            ("🟠 Needs Attention","creator_list_attention")]
        return await _show(query,"👥 Active Creators\n\nFind a creator and open the tools available to your role.",menu_markup(ctx,actions,"admin"))
    if action in {"creator_search_name","creator_search_id"}:
        if not has_permission(user_id,cfg,"view_creator_reports"):
            return await _show(query,"Creator search isn’t included in your access.",home_markup(ctx,user_id))
        ctx.user_data["guided_input"] = action
        prompt = "Type the creator’s display name or username." if action.endswith("name") else "Type the creator’s numeric Telegram ID."
        return await _show(query,"🔎 Creator Search\n\n"+prompt+"\n\nYou can cancel or go back without searching.",menu_markup(ctx,[],"creator_report"))
    if action.startswith("creator_list_"):
        if not has_permission(user_id,cfg,"view_creator_reports"):
            return await _show(query,"Active Creators isn’t included in your access.",home_markup(ctx,user_id))
        selected = action.removeprefix("creator_list_")
        rows = list(db.list_creators())
        if selected == "available": rows = [r for r in rows if r["availability"] == "available"]
        if selected == "unavailable": rows = [r for r in rows if r["availability"] == "unavailable"]
        if selected == "away": rows = [r for r in rows if r["availability"] in {"vacation","sick"}]
        if selected == "attention": rows = [r for r in rows if sum(db.warning_summary(r["telegram_id"]).values()) or r["status"] != "active"]
        buttons = [[(r["display_name"][:40],f"creator_select_{r['telegram_id']}")] for r in rows[:20]]
        text = "👥 Active Creators\n\n" + (f"Select a creator below. Showing {len(rows)} result(s)." if rows else "No creators match this filter.")
        return await _show(query,text,grid_markup(ctx,buttons,"creator_report"))
    if action.startswith("creator_select_"):
        if not has_permission(user_id,cfg,"view_creator_reports"):
            return await _show(query,"Creator records aren’t included in your access.",home_markup(ctx,user_id))
        try: target = int(action.removeprefix("creator_select_"))
        except ValueError: target = 0
        creator = db.get_creator(target)
        if not creator: return await _show(query,"That creator profile is unavailable.",menu_markup(ctx,[],"creator_report"))
        pop = db.creator_current_pop_status(target,datetime.now(cfg.timezone),*_pop_args(cfg))
        warning = db.warning_summary(target)
        username = f"@{creator['username']}" if creator["username"] else "No username"
        text = (f"👤 {creator['display_name']}\n{username}\n\n{AVAILABILITY_LABELS.get(creator['availability'],'⚪ Unavailable')}\n"
            f"🤝 Participation: {creator['status'].title()}\n🕒 Last meaningful: {_friendly_time(creator['last_meaningful_at'],cfg)}\n"
            f"📸 POP: {pop_label(pop)}\n💛 Warnings: {warning['warnings']} · Strikes: {warning['strikes']}")
        actions = [("📊 Overview",f"creator_select_{target}"),("📜 Timeline",f"creator_admin_timeline_{target}_0"),
            ("📸 POP History","pop_queue"),("💙 Away Notices","calendar"),("⚠️ Creator Standing","warnings_help")]
        if has_permission(user_id,cfg,"add_admin_notes"): actions.append(("📝 Private Notes",f"notes_member_{target}"))
        if has_permission(user_id,cfg,"send_announcements"): actions.append(("💬 Send Message",f"template_member_{target}"))
        if has_permission(user_id,cfg,"manage_creators"): actions.extend([("✏️ Edit",f"creator_edit_{target}"),("🗃️ Archive",f"archive_creator_{target}")])
        actions.append(("ℹ️ Member Details",f"creator_details_{target}"))
        return await _show(query,text,menu_markup(ctx,actions,"creator_report"))
    if action.startswith("creator_details_"):
        if not has_permission(user_id,cfg,"view_creator_reports"):
            return await _show(query,"Member details aren’t included in your access.",home_markup(ctx,user_id))
        target = int(action.removeprefix("creator_details_"))
        creator = db.get_creator(target)
        return await _show(query,f"ℹ️ Member Details\n\nTelegram ID: {target}\nRegistered: {friendly_timestamp(creator['registered_at'],timezone_name=getattr(cfg,'timezone_name','America/New_York'))}",menu_markup(ctx,[],f"creator_select_{target}"))
    if action.startswith("creator_admin_timeline_"):
        if not has_permission(user_id,cfg,"view_creator_reports"):
            return await _show(query,"Creator timelines aren’t included in your access.",home_markup(ctx,user_id))
        raw=action.removeprefix("creator_admin_timeline_"); target_raw,page_raw=raw.rsplit("_",1);target,page=int(target_raw),max(0,int(page_raw))
        rows=db.creator_timeline(target,8,page*8);creator=db.get_creator(target)
        lines=[f"📜 {creator['display_name']} · Timeline"]+[timeline_entry(r,getattr(cfg,"timezone_name","America/New_York")) for r in rows]
        buttons=[]
        if page: buttons.append(("⬅️ Newer",f"creator_admin_timeline_{target}_{page-1}"))
        if len(rows)==8: buttons.append(("Older ➡️",f"creator_admin_timeline_{target}_{page+1}"))
        return await _show(query,"\n\n".join(lines) if rows else "No timeline activity yet.",menu_markup(ctx,buttons,f"creator_select_{target}"))
    if action.startswith("notes_member_"):
        if not has_permission(user_id,cfg,"add_admin_notes"): return await _show(query,"Private notes aren’t included in your access.",home_markup(ctx,user_id))
        target=int(action.removeprefix("notes_member_"));notes=db.list_admin_notes(target)
        ctx.user_data["admin_note_target"]=target;ctx.user_data["guided_input"]="admin_note"
        text="📝 Private Notes\n\n"+("\n\n".join(f"• {n['note']}\n{friendly_timestamp(n['created_at'],timezone_name=getattr(cfg,'timezone_name','America/New_York'))}" for n in notes[:8]) if notes else "No private notes yet.")
        return await _show(query,text+"\n\nWrite a new note below, or go Back without adding one.",menu_markup(ctx,[],f"creator_select_{target}"))
    if action.startswith("creator_edit_") and action.removeprefix("creator_edit_").isdigit():
        if not has_permission(user_id,cfg,"manage_creators"): return await _show(query,"Creator editing isn’t included in your access.",home_markup(ctx,user_id))
        target=int(action.removeprefix("creator_edit_"))
        return await _show(query,"✏️ Correct Creator Record\n\nChoose the field to correct. Every change preserves the previous value and is audited.",menu_markup(ctx,[
            ("🟢 Mark Available",f"creator_edit_avail_available_{target}"),("⚪ Mark Unavailable",f"creator_edit_avail_unavailable_{target}"),
            ("✅ Activate",f"creator_edit_status_active_{target}"),("⏸ Deactivate",f"creator_edit_status_inactive_{target}")],f"creator_select_{target}"))
    if action.startswith("creator_edit_avail_") or action.startswith("creator_edit_status_"):
        if not has_permission(user_id,cfg,"manage_creators"): return await _show(query,"Creator editing isn’t included in your access.",home_markup(ctx,user_id))
        if action.startswith("creator_edit_avail_"):
            raw=action.removeprefix("creator_edit_avail_");value,target_raw=raw.rsplit("_",1);changed=db.set_availability(int(target_raw),value,user_id,"Guided admin correction")
        else:
            raw=action.removeprefix("creator_edit_status_");value,target_raw=raw.rsplit("_",1);changed=db.set_status(int(target_raw),value,user_id)
        return await _show(query,"✅ Record corrected and audited." if changed else "No change was recorded.",menu_markup(ctx,[],f"creator_select_{target_raw}"))
    if action.startswith("archive_creator_"):
        if not has_permission(user_id,cfg,"manage_creators"): return await _show(query,"Archiving isn’t included in your access.",home_markup(ctx,user_id))
        target=int(action.removeprefix("archive_creator_"));creator=db.get_creator(target)
        return await _show(query,f"🗃️ Archive {creator['display_name']}?\n\nThe profile will leave active lists but remain recoverable. Audit and history are preserved.",menu_markup(ctx,[("🗃️ Confirm Archive",f"archive_confirm_{target}")],f"creator_select_{target}"))
    if action.startswith("archive_confirm_"):
        if not has_permission(user_id,cfg,"manage_creators"): return await _show(query,"Archiving isn’t included in your access.",home_markup(ctx,user_id))
        target=int(action.removeprefix("archive_confirm_"));changed=db.delete_creator(target,user_id)
        return await _show(query,"✅ Creator archived. The record can be restored by an owner." if changed else "That record was already archived.",menu_markup(ctx,[],"creator_report"))
    if action == "calendar" and role >= Role.ADMIN:
        today = datetime.now(cfg.timezone).date()
        rows = db.calendar_absences(today.isoformat(),(today + timedelta(days=30)).isoformat())
        lines = ["Away Calendar · Next 30 Days"] + [f"{r['start_date']} → {r['end_date']}\n{r['display_name']} · {r['absence_type'].title()}" for r in rows[:15]]
        if not rows: lines.append("No approved Away Notices in the next 30 days.")
        return await _show(query,"\n\n".join(lines)[:3900],menu_markup(ctx,[],"admin"))
    if action == "reports" and role >= Role.ADMIN:
        text = ("Community Overview\n\n" + owner_card(cfg)) if role is Role.OWNER else ("Operations Overview\n\n" + admin_card(cfg))
        return await _show(query,text,menu_markup(ctx,[],"owner" if role is Role.OWNER else "admin"))
    if action == "templates_help" and has_permission(user_id,cfg,"send_announcements"):
        rows = db.message_templates()
        buttons=[(r["title"][:40],f"template_select_{r['template_key']}") for r in rows]
        buttons.append(("✍️ Custom Message","template_custom"))
        return await _show(query,"💬 Message Center\n\nChoose a message template.",menu_markup(ctx,buttons,"admin"))
    if action.startswith("template_select_"):
        if not has_permission(user_id,cfg,"send_announcements"): return await _show(query,"Messaging isn’t included in your access.",home_markup(ctx,user_id))
        key=action.removeprefix("template_select_"); template=db.message_template(key)
        if not template: return await _show(query,"That template is unavailable.",menu_markup(ctx,[],"templates_help"))
        creators=list(db.list_creators()); buttons=[[(r["display_name"][:40],f"template_preview_{key}_{r['telegram_id']}")] for r in creators[:20]]
        return await _show(query,f"{template['title']}\n\nChoose a recipient.",grid_markup(ctx,buttons,"templates_help"))
    if action == "template_custom":
        if not has_permission(user_id,cfg,"send_announcements"): return await _show(query,"Messaging isn’t included in your access.",home_markup(ctx,user_id))
        ctx.user_data["guided_input"]="template_custom"
        return await _show(query,"✍️ Custom Message\n\nWrite the message below. You will choose a recipient and preview it before sending.",menu_markup(ctx,[],"templates_help"))
    if action.startswith("template_custom_member_"):
        if not has_permission(user_id,cfg,"send_announcements"): return await _show(query,"Messaging isn’t included in your access.",home_markup(ctx,user_id))
        target=int(action.removeprefix("template_custom_member_")); body=ctx.user_data.get("custom_template_body")
        if not body: return await _show(query,"That custom-message draft expired.",menu_markup(ctx,[],"templates_help"))
        ctx.user_data["guided_template"]={"key":"custom","target":target,"body":body}
        return await _show(query,"💬 Message Preview\n\n"+body,menu_markup(ctx,[("✅ Confirm & Send","template_send")],"templates_help"))
    if action.startswith("template_preview_"):
        if not has_permission(user_id,cfg,"send_announcements"): return await _show(query,"Messaging isn’t included in your access.",home_markup(ctx,user_id))
        raw=action.removeprefix("template_preview_"); key,target_raw=raw.rsplit("_",1); target=int(target_raw)
        template,creator=db.message_template(key),db.get_creator(target)
        if not template or not creator: return await _show(query,"Template or recipient unavailable.",menu_markup(ctx,[],"templates_help"))
        body=template["body"].replace("{name}",creator["display_name"]).replace("{reason}","Please contact an admin if you have questions.")
        ctx.user_data["guided_template"]={"key":key,"target":target,"body":body}
        return await _show(query,"💬 Message Preview\n\n"+body,menu_markup(ctx,[("✅ Confirm & Send","template_send")],"templates_help"))
    if action == "template_send":
        if not has_permission(user_id,cfg,"send_announcements"): return await _show(query,"Messaging isn’t included in your access.",home_markup(ctx,user_id))
        draft=ctx.user_data.pop("guided_template",None)
        if not draft: return await _show(query,"That preview expired. Nothing was sent.",menu_markup(ctx,[],"templates_help"))
        try:
            await ctx.bot.send_message(draft["target"],draft["body"]); result="success"; text="✅ Message delivered and audited."
        except Exception:
            result="error"; text="The message could not be delivered. The failure is in Needs Attention."
        db.record_audit(user_id,"template_message_sent" if result=="success" else "template_message_delivery_failed","message_template",
            target_telegram_id=draft["target"],new_value={"template":draft["key"],"length":len(draft["body"])},result=result)
        return await _show(query,text,menu_markup(ctx,[],"templates_help"))
    if action == "warnings_help" and has_permission(user_id,cfg,"adjust_warnings"):
        creators=list(db.list_creators()); buttons=[[(r["display_name"][:40],f"warning_member_{r['telegram_id']}")] for r in creators[:20]]
        return await _show(query,"⚠️ Warning & Strike Management\n\nSelect a member.",grid_markup(ctx,buttons,"admin"))
    if action.startswith("warning_member_"):
        if not has_permission(user_id,cfg,"adjust_warnings"): return await _show(query,"Creator Standing isn’t included in your access.",home_markup(ctx,user_id))
        target=int(action.removeprefix("warning_member_")); creator=db.get_creator(target)
        return await _show(query,f"⚠️ {creator['display_name']}\n\nChoose the record type.",menu_markup(ctx,[("💛 Warning",f"warning_type_warning_{target}"),("🔴 Strike",f"warning_type_strike_{target}")],"warnings_help"))
    if action.startswith("warning_type_"):
        if not has_permission(user_id,cfg,"adjust_warnings"): return await _show(query,"Creator Standing isn’t included in your access.",home_markup(ctx,user_id))
        raw=action.removeprefix("warning_type_"); kind,target_raw=raw.split("_",1); target=int(target_raw)
        ctx.user_data["warning_draft"]={"type":kind,"target":target}
        return await _show(query,"Choose a reason or write a custom reason.",menu_markup(ctx,[("Participation follow-up","warning_reason_participation"),
            ("Community-rule concern","warning_reason_rules"),("✍️ Custom reason","warning_reason_custom")],f"warning_member_{target}"))
    if action.startswith("warning_reason_"):
        if not has_permission(user_id,cfg,"adjust_warnings"): return await _show(query,"Creator Standing isn’t included in your access.",home_markup(ctx,user_id))
        draft=ctx.user_data.get("warning_draft")
        if not draft: return await _show(query,"That workflow expired.",menu_markup(ctx,[],"warnings_help"))
        choice=action.removeprefix("warning_reason_")
        if choice=="custom":
            ctx.user_data["guided_input"]="warning_reason"
            return await _show(query,"Write the reason below. You will preview and confirm it before sending.",menu_markup(ctx,[],"warnings_help"))
        draft["reason"]="Participation follow-up" if choice=="participation" else "Community-rule concern"
        creator=db.get_creator(draft["target"]); template=db.message_template(draft["type"])
        body=template["body"].replace("{name}",creator["display_name"]).replace("{reason}",draft["reason"])
        return await _show(query,f"⚠️ Preview\n\nType: {draft['type'].title()}\nReason: {draft['reason']}\n\n{body}",menu_markup(ctx,[("✅ Confirm, Record & Send","warning_send")],"warnings_help"))
    if action == "warning_send":
        if not has_permission(user_id,cfg,"adjust_warnings"): return await _show(query,"Creator Standing isn’t included in your access.",home_markup(ctx,user_id))
        draft=ctx.user_data.pop("warning_draft",None)
        if not draft or not draft.get("reason"): return await _show(query,"That warning preview expired.",menu_markup(ctx,[],"warnings_help"))
        warning_id=db.add_warning(draft["target"],draft["type"],draft["reason"],user_id,template_key=draft["type"])
        creator,template=db.get_creator(draft["target"]),db.message_template(draft["type"])
        body=template["body"].replace("{name}",creator["display_name"]).replace("{reason}",draft["reason"])
        try: await ctx.bot.send_message(draft["target"],body); result="delivered"
        except Exception: db.record_audit(user_id,"warning_delivery_failed","creator_warning",warning_id,draft["target"],result="error"); result="recorded; delivery failed"
        if cfg.admin_chat_id:
            try: await ctx.bot.send_message(cfg.admin_chat_id,f"⚠️ {draft['type'].title()} recorded\nMember: {creator['display_name']}",message_thread_id=getattr(cfg,"moderation_thread_id",None) or cfg.reports_thread_id)
            except Exception: db.record_audit(user_id,"moderation_notification_delivery_failed","creator_warning",warning_id,draft["target"],result="error")
        return await _show(query,f"✅ {draft['type'].title()} #{warning_id} {result}. The full action is audited.",menu_markup(ctx,[],"warnings_help"))
    if action == "health" and role is Role.OWNER:
        state=db.system_state(); zone=getattr(cfg,"timezone_name","America/New_York")
        def when(key):
            return friendly_timestamp(state[key]["updated_at"],timezone_name=zone) if key in state else "Not recorded yet"
        failed=db.needs_attention_counts(current_period(datetime.now(cfg.timezone),*_pop_args(cfg)).week_key,
            now=datetime.now(cfg.timezone),due_weekday=_pop_args(cfg)[0],cutoff_time=_pop_args(cfg)[1],timezone_name=_pop_args(cfg)[2])["failed_notifications"]
        text=("🩺 System Health\n\n🟢 Bot online\n🟢 Telegram connected\n🟢 Database ready\n🟢 Handler routing ready\n"
            f"🟢 Scheduler running\nLast check: {when('last_scheduled_check')}\n"
            f"{'🟢' if not failed else '🟠'} Admin notifications: {failed} unresolved failure(s)\n"
            f"Last success: {when('last_admin_notification')}\n🟢 Database schema current: {db.schema_version()}\n"
            f"Last restart: {when('last_restart')}\nDatabase backup: Not tracked by the bot\n\n🔒 Secret values are never displayed.")
        return await _show(query,text,menu_markup(ctx,[("🔄 Refresh","health"),("⚠️ Review Errors","audit_filter_errors")],"owner"))
    if action == "setup":
        if role is not Role.OWNER:
            return await _show(query,"Setup is available only to owners.",home_markup(ctx,user_id))
        return await _show(query,"🧭 Setup\n\nReview where the bot works and adjust owner-protected community settings.",menu_markup(ctx,[
            ("💬 Participation Chat","setup_participation_chat"),("🧵 Participation Topics","setup_participation_topics"),
            ("📸 POP Group","setup_pop_group"),("🧵 POP Topic","setup_pop_topic"),
            ("🛡️ Admin Group","setup_admin_group"),("👤 Seller Group","setup_creator_group"),
            ("🛍️ Buyer Group","setup_buyer_group"),("🌎 Time Zone","setup_timezone"),
            ("⏰ Reminder Times","settings"),
            ("🤝 Meaningful Participation","setup_meaningful"),
            ("👤 My Registration Status","registration_status"),
            ("✅ Verify Current Chat","verify_chat"),("✅ Verify Current Topic","verify_topic"),
        ],"owner"))
    if action in {"setup_participation_chat","setup_participation_topics","setup_pop_group","setup_pop_topic",
                  "setup_admin_group","setup_creator_group","setup_buyer_group","setup_timezone","setup_meaningful"}:
        if role is not Role.OWNER:
            return await _show(query,"Setup is available only to owners.",home_markup(ctx,user_id))
        topics = sorted(getattr(cfg,"participation_topic_ids",frozenset()) or ())
        values = {
            "setup_participation_chat": ("💬 Participation Chat","This is the only group where participation can count.",getattr(cfg,"participation_chat_id",None) or getattr(cfg,"girls_chat_id",None)),
            "setup_participation_topics": ("🧵 Participation Topics","Only these topics count. Multiple topics are supported.",", ".join(map(str,topics)) if topics else "General only"),
            "setup_pop_group": ("📸 POP Group","Thursday proof is accepted only in this group.",getattr(cfg,"pop_chat_id",None) or getattr(cfg,"girls_chat_id",None)),
            "setup_pop_topic": ("🧵 POP Topic","Thursday proof is accepted only in this topic.",getattr(cfg,"pop_thread_id",None)),
            "setup_admin_group": ("🛡️ Admin Group","Private reviews and operational notices are routed here.",getattr(cfg,"admin_chat_id",None)),
            "setup_creator_group": ("👤 Seller Group","This is the configured creator/seller community group.",getattr(cfg,"creator_group_id",None) or getattr(cfg,"girls_chat_id",None)),
            "setup_buyer_group": ("🛍️ Buyer Group","This is the configured buyer community group.",getattr(cfg,"buyer_group_id",None)),
            "setup_timezone": ("🌎 Time Zone","POP deadlines and reminders use this daylight-saving-aware time zone.",getattr(cfg,"timezone_name","America/New_York")),
            "setup_meaningful": ("🤝 Meaningful Participation","These rules reject filler and repeated messages before participation is counted.",
                f"Minimum {getattr(cfg,'meaningful_min_words',3)} words · {getattr(cfg,'meaningful_min_characters',12)} characters · {getattr(cfg,'repeat_window_days',7)}-day repeat window"),
        }
        title, explanation, value = values.get(action,("Setup","Review this owner-protected setting.",None))
        text = f"{title}\n\n{explanation}\n\nCurrent setting: {value if value is not None else 'Not configured'}"
        actions=[("✅ Verify Current Chat","verify_chat"),("✅ Verify Current Topic","verify_topic")]
        if action == "setup_meaningful":
            actions=[("3-word minimum","setting_words_3"),("4-word minimum","setting_words_4"),
                ("12-character minimum","setting_chars_12"),("20-character minimum","setting_chars_20"),
                ("7-day repeat window","setting_repeat_7"),("14-day repeat window","setting_repeat_14")]
        elif action == "setup_timezone":
            actions=[("America / New York","setting_timezone_eastern")]
        return await _show(query,text,menu_markup(ctx,actions,"setup"))
    if action in {"verify_chat","verify_topic"}:
        if role is not Role.OWNER:
            return await _show(query,"Chat and topic verification is owner-only.",home_markup(ctx,user_id))
        chat = getattr(query.message,"chat",None) or update.effective_chat
        message = query.message
        chat_id = getattr(chat,"id",None)
        title = getattr(chat,"title",None) or getattr(chat,"full_name",None) or "Private chat"
        thread_id = getattr(message,"message_thread_id",None)
        is_forum = bool(getattr(chat,"is_forum",False))
        participation_chat = getattr(cfg,"participation_chat_id",None) or getattr(cfg,"girls_chat_id",None)
        topics = frozenset(getattr(cfg,"participation_topic_ids",frozenset()) or ())
        participation_on = chat_id == participation_chat and (thread_id in topics if topics else thread_id is None)
        configured = []
        if chat_id == participation_chat: configured.append("Participation chat")
        if chat_id == (getattr(cfg,"pop_chat_id",None) or getattr(cfg,"girls_chat_id",None)): configured.append("POP group")
        if chat_id == getattr(cfg,"admin_chat_id",None): configured.append("Admin group")
        if chat_id == getattr(cfg,"creator_group_id",None): configured.append("Seller group")
        if chat_id == getattr(cfg,"buyer_group_id",None): configured.append("Buyer group")
        topic_created = getattr(message,"forum_topic_created",None)
        topic_name = "General" if thread_id is None else getattr(topic_created,"name",None) or "Current forum topic (title unavailable from this message)"
        bot_permissions = "Could not be checked from this chat"
        bot = getattr(ctx,"bot",None)
        if chat_id and bot and hasattr(bot,"get_chat_member") and getattr(chat,"type",None) in {"group","supergroup","channel"}:
            try:
                member = await bot.get_chat_member(chat_id,bot.id)
                allowed = [name.replace("can_","").replace("_"," ").title() for name in
                    ("can_send_messages","can_post_messages","can_manage_topics","can_delete_messages") if getattr(member,name,False)]
                bot_permissions = f"{str(getattr(member,'status','member')).title()}" + (f" · {', '.join(allowed)}" if allowed else "")
            except Exception:
                bot_permissions = "Unable to verify; check that the bot is present"
        problems = []
        if participation_chat is None: problems.append("Participation Group is not configured")
        if getattr(cfg,"pop_chat_id",None) is None: problems.append("POP Group is not configured")
        if getattr(cfg,"pop_thread_id",None) is None: problems.append("POP Topic is not configured")
        if is_forum and action == "verify_topic" and thread_id is None: problems.append("Run this inside the intended forum topic")
        text = (f"✅ {'Current Topic' if action == 'verify_topic' else 'Current Chat'}\n\n"
            "Confirm that this is the place you intended to configure.\n\n"
            f"Chat name: {title}\nChat ID: {chat_id}\nForum: {'Yes' if is_forum else 'No'}\n"
            f"Topic name: {topic_name}\nTopic ID: {thread_id if thread_id is not None else 'None'}\n"
            f"Current configuration: {', '.join(configured) if configured else 'No matching destination'}\n"
            f"Participation enabled here: {'Yes' if participation_on else 'No'}\n"
            f"Bot permissions: {bot_permissions}\n"
            f"Configuration problems: {'; '.join(problems) if problems else 'None detected'}")
        actions = []
        if action == "verify_chat" and chat_id is not None:
            actions = [("Use as Participation Group","setup_prepare_participation_chat"),
                ("Use as Seller Group","setup_prepare_creator_group"),("Use as POP Group","setup_prepare_pop_chat"),
                ("Use as Admin Group","setup_prepare_admin_chat"),("Use as Buyer Group","setup_prepare_buyer_group")]
        elif thread_id is not None:
            actions = [("Add Participation Topic","setup_prepare_participation_topic"),("Use as POP Topic","setup_prepare_pop_topic")]
        return await _show(query,text,menu_markup(ctx,actions,"setup"))
    if action.startswith("setup_prepare_"):
        if role is not Role.OWNER:
            return await _show(query,"Setup is available only to owners.",home_markup(ctx,user_id))
        key = action.removeprefix("setup_prepare_")
        chat = getattr(query.message,"chat",None) or update.effective_chat
        values = {
            "participation_chat": getattr(chat,"id",None),"creator_group":getattr(chat,"id",None),
            "pop_chat":getattr(chat,"id",None),"admin_chat":getattr(chat,"id",None),
            "buyer_group":getattr(chat,"id",None),"participation_topic":getattr(query.message,"message_thread_id",None),
            "pop_topic":getattr(query.message,"message_thread_id",None),
        }
        value = values.get(key)
        if value is None:
            return await _show(query,"This chat or topic could not be detected. Open Setup from the intended location and try again.",menu_markup(ctx,[],"setup"))
        ctx.user_data["setup_pending"]={"key":key,"value":value}
        label=key.replace("_"," ").title()
        return await _show(query,f"Confirm Setup Change\n\n{label} will be set to {value}. The change is persistent, reversible, and audited.",
            confirmation_markup(ctx,"setup_confirm_change","setup"))
    if action == "setup_confirm_change":
        if role is not Role.OWNER:
            return await _show(query,"Setup is available only to owners.",home_markup(ctx,user_id))
        pending=ctx.user_data.pop("setup_pending",None)
        if not pending:
            return await _show(query,"That setup change expired. No settings were changed.",menu_markup(ctx,[],"setup"))
        mapping={"participation_chat":"participation_chat_id","creator_group":"creator_group_id","pop_chat":"pop_chat_id",
            "admin_chat":"admin_chat_id","buyer_group":"buyer_group_id","pop_topic":"pop_thread_id"}
        if pending["key"] == "participation_topic":
            new_topics=set(getattr(cfg,"participation_topic_ids",frozenset()));new_topics.add(int(pending["value"]))
            persist_setting(cfg,"participation_topic_ids",frozenset(new_topics),user_id)
        else:
            persist_setting(cfg,mapping[pending["key"]],int(pending["value"]),user_id)
        return await _show(query,"✅ Setup updated and audited. This setting will remain active after restart.",menu_markup(ctx,[],"setup"))
    if action == "settings" and role is Role.OWNER:
        period = current_period(datetime.now(cfg.timezone),*_pop_args(cfg))
        text = ("⚙️ System Settings\n\n"
            f"🟡 Participation reminder: {cfg.warning_hours} hours\n"
            f"🔴 Three-day alert: {cfg.alert_hours} hours\n"
            f"📸 POP due: {period.due_at.strftime('%A')} at {period.due_at.strftime('%I').lstrip('0')}:{period.due_at.strftime('%M %p')} ET\n"
            f"🌎 Time zone: {getattr(cfg,'timezone_name','America/New_York')}\n"
            f"📊 Daily summary: {'Enabled' if getattr(cfg,'daily_owner_summary_enabled',False) else 'Disabled'}\n"
            f"📨 Admin routing: {'Configured' if cfg.admin_chat_id else 'Needs setup'}\n"
            "🤖 Bot version: 1.1\n🗄️ Database schema: 4")
        return await _show(query,text,menu_markup(ctx,[("🟡 Reminder Times","settings_warning"),("🔴 Follow-up Time","settings_alert"),
            ("📸 POP Deadline","settings_pop"),("📊 Daily Summary","settings_summary")],"setup"))
    if action in {"settings_warning","settings_alert","settings_pop","settings_summary"}:
        if role is not Role.OWNER: return await _show(query,"Settings are owner-only.",home_markup(ctx,user_id))
        choices = {
            "settings_warning":[("36 hours","setting_warning_36"),("48 hours","setting_warning_48")],
            "settings_alert":[("72 hours","setting_alert_72"),("96 hours","setting_alert_96")],
            "settings_pop":[("Thursday 6 PM","setting_pop_18:00"),("Thursday 11:59 PM","setting_pop_23:59")],
            "settings_summary":[("Enable","setting_summary_on"),("Disable","setting_summary_off")],
        }
        return await _show(query,"Choose a new value. The change affects this running process and will be audited.",menu_markup(ctx,choices[action],"settings"))
    if action.startswith("setting_"):
        if role is not Role.OWNER: return await _show(query,"Settings are owner-only.",home_markup(ctx,user_id))
        _,key,value = action.split("_",2)
        attrs = {"warning":"warning_hours","alert":"alert_hours","pop":"pop_cutoff_time","summary":"daily_owner_summary_enabled",
            "words":"meaningful_min_words","chars":"meaningful_min_characters","repeat":"repeat_window_days","timezone":"timezone_name"}
        attr = attrs.get(key)
        if not attr: return await _show(query,"That setting is unavailable.",menu_markup(ctx,[],"settings"))
        old = getattr(cfg,attr)
        if key == "summary": new = value == "on"
        elif key in {"warning","alert","words","chars","repeat"}: new = int(value)
        elif key == "timezone": new = "America/New_York"
        else: new = value
        if key == "summary":
            setattr(cfg,attr,new);db.audit_setting_change(user_id,attr,old,new)
        else:
            persist_setting(cfg,attr,new,user_id)
        back="setup_meaningful" if key in {"words","chars","repeat"} else "setup_timezone" if key == "timezone" else "settings"
        return await _show(query,"✅ Setting updated and audited. This setting will remain active after restart.",menu_markup(ctx,[],back))
    if action == "roles" and role is Role.OWNER:
        return await _show(query,f"👥 Access Management\n\n👑 Owners: {len(cfg.owner_user_ids)}\n🛡️ Lead Admins: {len(cfg.lead_admin_user_ids)}\n👥 Admins: {len(cfg.admin_user_ids)}",
            menu_markup(ctx,[("👑 Owners","access_owners"),("🛡️ Lead Admins","access_leads"),("👥 Admins","access_admins"),
                ("➕ Add Admin","access_add"),("✏️ Edit Permissions","access_edit"),("➖ Remove Admin","access_remove"),("📜 Role History","audit_filter_roles")],"owner"))
    if action in {"access_owners","access_leads","access_admins"}:
        if role is not Role.OWNER: return await _show(query,"Access management is owner-only.",home_markup(ctx,user_id))
        ids = cfg.owner_user_ids if action.endswith("owners") else cfg.lead_admin_user_ids if action.endswith("leads") else cfg.admin_user_ids
        names = []
        for member_id in ids:
            member = db.get_creator(member_id)
            names.append(member["display_name"] if member else f"Configured account ending in {str(member_id)[-4:]}")
        return await _show(query,"\n".join(names) or "No accounts are configured in this role.",menu_markup(ctx,[],"roles"))
    if action == "access_add":
        if role is not Role.OWNER: return await _show(query,"Access management is owner-only.",home_markup(ctx,user_id))
        ctx.user_data["guided_input"] = "access_add"
        return await _show(query,"➕ Add Admin\n\nEnter the person’s numeric Telegram ID. You will choose a role and confirm before access changes.",menu_markup(ctx,[],"roles"))
    if action in {"access_edit","access_remove"}:
        if role is not Role.OWNER: return await _show(query,"Access management is owner-only.",home_markup(ctx,user_id))
        ids = sorted(set(cfg.admin_user_ids)|set(cfg.lead_admin_user_ids))
        buttons = [[((db.get_creator(i)["display_name"] if db.get_creator(i) else f"Admin •••{str(i)[-4:]}")[:40],f"access_member_{i}")] for i in ids]
        return await _show(query,"Select an administrator.",grid_markup(ctx,buttons,"roles"))
    if action.startswith("access_member_"):
        if role is not Role.OWNER: return await _show(query,"Access management is owner-only.",home_markup(ctx,user_id))
        target = int(action.removeprefix("access_member_"))
        return await _show(query,"Choose the change to review.",menu_markup(ctx,[("👥 Make Admin",f"access_confirm_admin_{target}"),
            ("🛡️ Make Lead Admin",f"access_confirm_lead_{target}"),("➖ Remove Admin",f"access_confirm_none_{target}")],"roles"))
    if action.startswith("access_confirm_"):
        if role is not Role.OWNER: return await _show(query,"Access management is owner-only.",home_markup(ctx,user_id))
        _,_,new_role,target_raw = action.split("_",3); target = int(target_raw)
        if target in cfg.owner_user_ids: return await _show(query,"Owner access is protected by secure configuration.",menu_markup(ctx,[],"roles"))
        previous = role_for(target,cfg).name.lower(); admins,leads=set(cfg.admin_user_ids),set(cfg.lead_admin_user_ids)
        admins.discard(target); leads.discard(target)
        if new_role == "admin": admins.add(target)
        if new_role == "lead": leads.add(target)
        cfg.admin_user_ids,cfg.lead_admin_user_ids=frozenset(admins),frozenset(leads)
        db.record_audit(user_id,"role_changed","admin_role",target,target,previous,new_role)
        return await _show(query,"✅ Access changed and audited. Update secure persistent configuration before restart.",menu_markup(ctx,[],"roles"))
    if action == "export_help" and role is Role.OWNER:
        return await _show(query,"💾 Export Records\n\nChoose an export. You will confirm before a private file is created.",menu_markup(ctx,[
            ("📄 Creator List","export_confirm_creators"),("📄 Audit Log","export_confirm_audit"),("📄 Warning & Strike History","export_confirm_warnings"),
            ("📄 Away Notice History","export_confirm_absences"),("📄 POP History","export_confirm_pop"),("📦 Full Owner Export","export_confirm_full")],"owner"))
    if action.startswith("export_confirm_"):
        if role is not Role.OWNER: return await _show(query,"Exports are owner-only.",home_markup(ctx,user_id))
        kind = action.removeprefix("export_confirm_")
        return await _show(query,f"Confirm {kind.replace('_',' ').title()} export?\n\nA private file will be sent to you. This action is audited.",menu_markup(ctx,[("✅ Create Export",f"export_send_{kind}")],"export_help"))
    if action.startswith("export_send_"):
        if role is not Role.OWNER: return await _show(query,"Exports are owner-only.",home_markup(ctx,user_id))
        kind = action.removeprefix("export_send_"); snapshot=db.export_snapshot()
        mapping={"creators":"creators","audit":"audit","warnings":"warnings","absences":"absences","pop":"pop"}
        payload=snapshot if kind=="full" else {kind:snapshot.get(mapping.get(kind,kind),[])}
        data=json.dumps(payload,indent=2,default=str).encode(); stream=io.BytesIO(data); stream.name=f"vad-{kind}-export.json"
        await ctx.bot.send_document(user_id,stream,caption="Private owner export. Store it securely.")
        db.record_audit(user_id,"records_exported","system",new_value={"kind":kind,"bytes":len(data)})
        return await _show(query,"✅ Export delivered privately and audited.",menu_markup(ctx,[],"owner"))
    if action == "restore_help" and role is Role.OWNER:
        rows=db.deleted_records(); buttons=[[(r["display_name"][:40],f"restore_select_{r['telegram_id']}")] for r in rows[:20]]
        return await _show(query,"♻️ Restore Records\n\n"+("Select an archived record." if rows else "🔐 No archived records match this filter."),grid_markup(ctx,buttons,"owner"))
    if action.startswith("restore_select_"):
        if role is not Role.OWNER: return await _show(query,"Restoration is owner-only.",home_markup(ctx,user_id))
        target=int(action.removeprefix("restore_select_")); row=next((r for r in db.deleted_records() if r["telegram_id"]==target),None)
        if not row: return await _show(query,"That archived record is unavailable.",menu_markup(ctx,[],"restore_help"))
        text=f"🗃️ {row['display_name']}\nDeleted: {friendly_timestamp(row['deleted_at'],timezone_name=getattr(cfg,'timezone_name','America/New_York'))}\nReason: {row['deletion_reason'] or 'Not provided'}\n\nRestoration is reversible and will be audited."
        return await _show(query,text,menu_markup(ctx,[("♻️ Restore",f"restore_confirm_{target}")],"restore_help"))
    if action.startswith("restore_confirm_"):
        if role is not Role.OWNER: return await _show(query,"Restoration is owner-only.",home_markup(ctx,user_id))
        target=int(action.removeprefix("restore_confirm_")); restored=db.restore_creator(target,user_id,"Guided owner restoration")
        return await _show(query,"✅ Record restored and audited." if restored else "That record was already restored.",menu_markup(ctx,[],"restore_help"))
    permission_actions = {
        "registration_queue":"review_registrations", "vacation_queue":"review_vacations",
        "sick_queue":"review_sick_days", "pop_queue":"review_pop",
        "creator_report":"view_creator_reports", "search_help":"view_creator_reports",
        "warnings_help":"adjust_warnings", "templates_help":"send_announcements",
        "announce_help":"send_announcements",
    }
    if action in permission_actions and not has_permission(user_id,cfg,permission_actions[action]):
        return await _show(query,"This tool isn’t included in your access.",menu_markup(ctx,[],"admin"))
    if action in {"roles","setup","settings","export_help","restore_help","health","verify_chat","verify_topic"} and role is not Role.OWNER:
        return await _show(query,"This tool is available only in the Owner dashboard.",home_markup(ctx,user_id))
    if action in {"reports", "creator_report", "calendar", "registration_queue", "vacation_queue", "sick_queue", "pop_queue", "search_help", "warnings_help", "templates_help", "announce_help", "roles", "settings", "export_help", "restore_help", "health"}:
        if action not in {"reports", "calendar"} and role < Role.ADMIN:
            return await _show(query, "Administrator access is required.", home_markup(ctx, user_id))
        descriptions = {
            "reports": "Choose a report from the dashboard.",
            "creator_report": "Choose Search, Browse, or a creator filter.",
            "calendar": "Choose a calendar view.",
            "registration_queue": "Select a pending registration to review it.",
            "vacation_queue": "Choose Away Notices to review requests.",
            "sick_queue": "Choose Away Notices to review requests.",
            "pop_queue": "Select a pending POP submission to review it.",
            "search_help": "Choose Search by Name or Search by Telegram ID.",
            "warnings_help": "Select a member to begin a guided warning or strike workflow.",
            "templates_help": "Choose a template, recipient, preview, and confirm.",
            "announce_help": "Choose an audience, preview the message, and confirm.",
            "roles": "Owner-protected role assignments come from secure environment configuration.",
            "settings": "Choose the setting you want to review or change.",
            "export_help": "Choose an export type. Every export requires confirmation and is audited.",
            "restore_help": "Browse archived records, review deletion details, and confirm restoration.",
            "health": "Review live system checks and safe diagnostics.",
        }
        back = "owner" if role is Role.OWNER and action in {"roles","export_help","restore_help","health"} else "setup" if action == "settings" else "admin"
        return await _show(query, descriptions[action], menu_markup(ctx, [], back))
    return await _show(query, "Unknown or unavailable action.", home_markup(ctx, user_id))


def register_navigation(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback, pattern=r"^op:"))
