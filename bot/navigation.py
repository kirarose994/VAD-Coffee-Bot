"""Role-aware, nonce-protected application navigation."""

import io
import json
import secrets
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

import database as db
from config import RESOURCE_DEFAULTS
from permissions import Membership, Role, has_permission, role_for, roles_for
from pop_policy import current_period, label as pop_label
from presentation import audit_entry, friendly_timestamp, system_error_detail, timeline_entry
from runtime_config import persist_setting
from routing import ROUTES, routing_summary, send_routed
from readiness import readiness_items, status_icon, system_check_summary
from community_snapshot import PARTICIPATION_POLICY, build_snapshot, section_lines
from briefing import deliver_daily_brief


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
    memberships=roles_for(user_id,cfg,has_creator_profile=bool(creator))
    member = db.get_member(user_id)
    rows = []
    if Membership.OWNER in memberships:
        rows.append([_button("👑 Owner Home",nonce,"owner")])
    if Membership.ADMIN in memberships:
        rows.append([_button("🛡️ Admin Home",nonce,"admin")])
    if Membership.CREATOR in memberships:
        rows.append([_button("💛 My VAD Home", nonce, "creator")])
    elif member and member["member_type"] == "creator":
        rows.append([_button("👤 Registration Status",nonce,"registration_status")])
    elif not member:
        rows.append([_button("✨ I'm a Creator / Seller", nonce, "join_creator")])
        if role is Role.NONE:
            rows.append([_button("🛍️ I'm a Buyer", nonce, "join_buyer")])
    elif role is Role.NONE:
        rows.append([_button("🛍️ Buyer Home", nonce, "buyer")])
    rows.append([_button("📚 Help Center", nonce, "resources")])
    if role is Role.NONE: rows.append([_button("💬 Contact an Admin",nonce,"support")])
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
                next_step = "\n➡️ Three full days passed without meaningful participation; the Admin team has been notified for follow-up."
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

def _snapshot_sections(user_id,cfg):
    if role_for(user_id,cfg) is Role.OWNER:return ["creators","participation","pop","away","support","accountability","system"]
    allowed=[]
    if has_permission(user_id,cfg,"view_creator_reports"):allowed += ["creators","participation"]
    if has_permission(user_id,cfg,"review_pop"):allowed.append("pop")
    if has_permission(user_id,cfg,"review_vacations") or has_permission(user_id,cfg,"review_sick_days"):allowed.append("away")
    if has_permission(user_id,cfg,"manage_support"):allowed.append("support")
    if has_permission(user_id,cfg,"adjust_warnings"):allowed.append("accountability")
    if has_permission(user_id,cfg,"view_system_health"):allowed.append("system")
    return allowed

def snapshot_text(user_id,cfg):
    snap=build_snapshot(cfg);headings={"creators":"CREATORS","participation":"PARTICIPATION","pop":"THURSDAY POP",
        "away":"AWAY NOTICES","support":"SUPPORT","accountability":"ACCOUNTABILITY","system":"SYSTEM HEALTH"}
    blocks=[]
    for section in _snapshot_sections(user_id,cfg):
        blocks.append(headings[section]+"\n"+"\n".join(f"{label}: {value}" for label,value in section_lines(snap,section)))
    return "📊 Community Snapshot\n\nSee current creator activity, outstanding tasks, and bot status at a glance.\n\n"+"\n\n".join(blocks)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if getattr(getattr(update,"effective_chat",None),"type","private")=="private":
        db.record_bot_user(update.effective_user.id,getattr(update.effective_user,"username",None),
            getattr(update.effective_user,"full_name",None) or getattr(update.effective_user,"first_name","Telegram User"))
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
        if outcome == "created":
            await send_routed(ctx.bot,cfg,"registration",
                f"📝 New creator\n{update.effective_user.full_name} is ready for review.",target_telegram_id=user_id)
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
        return await _show(query, "💛 My VAD Home\n\nPrivately check your participation, POP, Away Notices, reminders, and personal history.\n\n" + creator_card(user_id, cfg), grid_markup(ctx, [
            [("🟢 Available","available"),("⚪ Unavailable","unavailable")],
            [("💙 Let Us Know You’ll Be Away","away_help")],
            [("🤝 My Participation","my_status"),("📸 My Thursday POP","pop_help")],
            [("💛 View My Community Standing","my_warnings")],
            [("💙 My Away Notices","my_away_notices"),("📜 View My Activity History","timeline_0")],
            [("📨 My Support Requests","my_support"),("💬 Contact an Admin","contact")],
            [("📚 Help Center","resources")],
        ]))
    if action == "admin":
        if role < Role.ADMIN:
            return await _show(query, "Admin access is required.", home_markup(ctx, user_id))
        rows = [[("📊 Community Snapshot","community_snapshot")],[ ("🚨 Admin Queue","admin_queue")]]
        if has_permission(user_id,cfg,"review_registrations"): rows.append([("📝 Review New Creators","registration_queue")])
        if has_permission(user_id,cfg,"review_vacations") or has_permission(user_id,cfg,"review_sick_days"):
            rows.append([("💙 Away Notices","away_queue")])
        if has_permission(user_id,cfg,"review_pop"): rows.append([("📸 POP Reviews","pop_queue")])
        if has_permission(user_id,cfg,"view_creator_reports"): rows.append([("👥 Active Creators","creator_report"),("📅 Community Calendar","calendar")])
        tools = []
        if has_permission(user_id,cfg,"adjust_warnings"): tools.append(("💛 Creator Standing","warnings_help"))
        if has_permission(user_id,cfg,"send_announcements"): tools.append(("💬 Message Center","templates_help"))
        if tools: rows.append(tools)
        if has_permission(user_id,cfg,"manage_support"):rows.append([("📨 Support Requests","support_queue")])
        rows.append([("📚 Help Center","resources")])
        return await _show(query, "🛡️ Admin Home\n\nYou are signed in as an Admin. Review requests, alerts, and tools assigned to your role.\n\n" + admin_card(cfg), grid_markup(ctx,rows))
    if action == "owner":
        if role is not Role.OWNER:
            return await _show(query, "Owner access is required.", home_markup(ctx, user_id))
        return await _show(query, "👑 Owner Home\n\nYou are signed in as an Owner. Review anything needing attention, manage community operations, and access protected Owner tools.\n\n" + owner_card(cfg), grid_markup(ctx,[
            [("🚨 Needs Attention","needs_attention")],
            [("📊 Community Snapshot","community_snapshot")],
            [("📋 My Status","my_account_status"),("📸 My POP","pop_help")],
            [("💙 My Away Notices","my_away_notices"),("📜 My Timeline","timeline_0")],
            [("👥 Creator Directory","creator_report"),("📸 Review POP Submissions","pop_queue")],
            [("💙 Review Away Notices","away_queue"),("🟠 Participation Alerts","participation_queue")],
            [("⚠️ Warnings and Strikes","warnings_help"),("💬 Message Center","templates_help")],
            [("📨 Support Requests","support_queue"),("📅 Calendar","calendar")],
            [("📊 Reports","reports")],
            [("📍 Telegram Locations","telegram_locations"),("📈 Participation Monitor","participation_monitor")],
            [("✅ Setup & Readiness","readiness"),("🧪 Test Center","test_center")],
            [("🧭 Complete Initial Setup","setup_wizard"),("👥 People & Roles","roles")],
            [("🧾 Participation Event Log","participation_events"),("🔐 Audit Log","audit")],
            [("🗃️ Archive","deleted"),("♻️ Restore","restore_help")],
            [("🧭 Setup","setup"),("🩺 Health","health")],
            [("💾 Export","export_help"),("📚 Help Center","resources")],
        ]))
    if action == "community_snapshot":
        if role < Role.ADMIN:return await _show(query,"Community Snapshot is available only to authorized Admins and Owners.",home_markup(ctx,user_id))
        sections=_snapshot_sections(user_id,cfg)
        if not sections:return await _show(query,"Your Admin role does not include community-wide reports.",home_markup(ctx,user_id))
        snap=build_snapshot(cfg);buttons=[]
        if "creators" in sections:
            buttons += [(f"👥 {len(snap['creators']['active'])} Active Creators","snapshot_list_creators_active"),
                (f"📝 {len(snap['creators']['pending'])} Pending Registrations","registration_queue")]
        if "participation" in sections:
            buttons += [(f"🟡 {len(snap['participation']['approaching'])} Approaching Reminder","snapshot_list_participation_approaching"),
                (f"🔴 {len(snap['participation']['follow_up'])} Three-Day Follow-Up","snapshot_list_participation_follow_up")]
        if "pop" in sections:
            buttons += [(f"📸 {len(snap['pop']['submitted'])+len(snap['pop']['awaiting_review'])} POP Received","snapshot_list_pop_received"),
                (f"🔴 {len(snap['pop']['missing'])} POP Exceptions","snapshot_list_pop_missing")]
        if "away" in sections:buttons.append((f"💙 {len(snap['away']['pending'])} Away Notices Waiting","away_queue"))
        if "support" in sections:buttons.append((f"📨 {len(snap['support']['open'])} Open Support Requests","support_queue"))
        if "accountability" in sections:buttons.append(("⚠️ Warning & Strike Details","warnings_help"))
        if "system" in sections:buttons.append(("🩺 System Health","health"))
        buttons.append(("ℹ️ Participation Policy","snapshot_policy"))
        return await _show(query,snapshot_text(user_id,cfg),menu_markup(ctx,buttons,"owner" if role is Role.OWNER else "admin"))
    if action.startswith("snapshot_list_"):
        if role < Role.ADMIN:return await _show(query,"Admin access is required.",home_markup(ctx,user_id))
        key=action.removeprefix("snapshot_list_");section=key.split("_",1)[0]
        if section not in _snapshot_sections(user_id,cfg):return await _show(query,"That snapshot section is not included in your permissions.",home_markup(ctx,user_id))
        snap=build_snapshot(cfg)
        mapping={"creators_active":snap["creators"]["active"],"participation_approaching":snap["participation"]["approaching"],
            "participation_follow_up":snap["participation"]["follow_up"],"pop_received":snap["pop"]["submitted"]+snap["pop"]["awaiting_review"],
            "pop_missing":snap["pop"]["missing"]}
        rows=mapping.get(key,[]);lines=[]
        for row in rows:
            name=row.get("display_name","Creator");hours=row.get("inactive_hours")
            lines.append(f"• {name}"+(f" · {hours:.1f} hours" if hours is not None else ""))
        title=key.replace("_"," ").title()
        return await _show(query,f"📊 {title}\n\n"+("\n".join(lines) if lines else "✅ No matching items."),menu_markup(ctx,[],"community_snapshot"))
    if action == "snapshot_policy":
        if role < Role.ADMIN:return await _show(query,"Admin access is required.",home_markup(ctx,user_id))
        return await _show(query,"🤝 Meaningful Participation\n\n"+PARTICIPATION_POLICY+"\n\nMeaningful participation means genuine conversation that helps keep the community active and engaging. Simple check-ins, greetings, emoji, stickers, context-free media, links, duplicates, promotions, commands, and filler do not count.",menu_markup(ctx,[],"community_snapshot"))
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
        if outcome == "created":
            await send_routed(ctx.bot,cfg,"registration",
                f"📝 New registration\n{update.effective_user.full_name} is waiting for review.",target_telegram_id=user_id)
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
        if has_permission(user_id,cfg,"manage_support"):
            permitted.append(("📨 Support requests",counts.get("support_requests",0),"support_queue"))
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
    if action == "my_account_status":
        return await _show(query,"📋 My Status\n\nReview your own creator status and current community information.\n\n"+
            (creator_card(user_id,cfg) if db.get_creator(user_id) else "No creator profile is registered for this Owner account."),menu_markup(ctx,[],"owner"))
    if action == "my_away_notices":
        if not db.get_creator(user_id): return await _show(query,"No creator profile is registered for this account.",menu_markup(ctx,[],"home"))
        rows=db.creator_absences(user_id)
        text="💙 My Away Notices\n\nReview only the time-away notices connected to your account.\n\n"+(
            "\n".join(f"{r['start_date']}–{r['end_date']} · {r['status'].title()}" for r in rows[:10]) if rows else "No Away Notices yet.")
        return await _show(query,text,menu_markup(ctx,[],"creator" if role is Role.NONE else "owner"))
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
        back = "creator" if db.get_creator(user_id) else "buyer" if db.get_member(user_id) else "home"
        return await _show(query,"💬 Contact an Admin\n\nChoose what we can help you with today.",menu_markup(ctx,[
            ("General Question","support_category_general"),("Thursday POP","support_category_pop"),
            ("Away Notice","support_category_away"),("Participation","support_category_participation"),
            ("Account or Verification","support_category_account"),("Report an Issue","support_category_issue"),
            ("Something Else","support_category_other")],back))
    if action.startswith("support_category_"):
        if not db.get_creator(user_id):
            return await _show(query,"Tracked support requests are available after creator registration.",menu_markup(ctx,[],"home"))
        category=action.removeprefix("support_category_").replace("_"," ").title()
        ctx.user_data["support_category"]=category;ctx.user_data["guided_input"]="support_message"
        return await _show(query,"💬 New Support Request\n\nType your message. You’ll preview and confirm it before sending.",menu_markup(ctx,[],"creator"))
    if action == "my_support":
        if not db.get_creator(user_id):
            return await _show(query,"Register as a creator to view support requests.",home_markup(ctx,user_id))
        rows=db.support_requests_for(user_id)
        text="📨 My Support Requests\n\nTrack your questions, Admin replies, and current status.\n\n"+(
            "\n\n".join(f"#{r['id']} · {r['category']}\n{r['status'].title()} · {friendly_timestamp(r['created_at'],timezone_name=cfg.timezone_name)}"+
                (f"\n💬 Latest reply: {db.support_messages_for(r['id'],user_id)[-1]['body']}" if db.support_messages_for(r['id'],user_id) else "") for r in rows[:10])
            if rows else "No support requests yet.")
        return await _show(query,text,menu_markup(ctx,[],"creator"))
    if action == "support_queue":
        if not has_permission(user_id,cfg,"manage_support"):
            return await _show(query,"Support Requests isn’t included in your access.",home_markup(ctx,user_id))
        rows=db.support_queue();buttons=[[(f"#{r['id']} · {r['display_name']}",f"support_select_{r['id']}")] for r in rows[:20]]
        return await _show(query,"📨 Support Requests\n\nReview creator questions and track them until resolved.",grid_markup(ctx,buttons,"admin"))
    if action.startswith("support_select_"):
        if not has_permission(user_id,cfg,"manage_support"): return await _show(query,"Support access is required.",home_markup(ctx,user_id))
        request_id=int(action.removeprefix("support_select_"));row=next((r for r in db.support_queue() if r["id"]==request_id),None)
        if not row:return await _show(query,"That request is no longer open.",menu_markup(ctx,[],"support_queue"))
        username=f"@{row['username']}" if row["username"] else "No username"
        text=(f"📨 Support Request #{request_id}\n\nCreator: {row['display_name']}\nUsername: {username}\n"
            f"Telegram ID: {row['telegram_id']}\nCategory: {row['category']}\nStatus: {row['status'].title()}\n\n{row['message']}")
        return await _show(query,text,menu_markup(ctx,[("Assign to Me",f"support_action_assign_{request_id}"),("Reply",f"support_reply_{request_id}"),
            ("Open Creator Profile",f"creator_select_{row['telegram_id']}"),("Add Private Note",f"notes_member_{row['telegram_id']}"),
            ("Escalate to Owner",f"support_action_escalate_{request_id}"),("Mark Resolved",f"support_action_resolve_{request_id}")],"support_queue"))
    if action.startswith("support_reply_"):
        if not has_permission(user_id,cfg,"manage_support"):return await _show(query,"Support access is required.",home_markup(ctx,user_id))
        ctx.user_data["support_reply_id"]=int(action.removeprefix("support_reply_"));ctx.user_data["guided_input"]="support_reply"
        return await _show(query,"💬 Reply to Support Request\n\nType your reply. It will be recorded before delivery.",menu_markup(ctx,[],"support_queue"))
    if action.startswith("support_action_"):
        if not has_permission(user_id,cfg,"manage_support"): return await _show(query,"Support access is required.",home_markup(ctx,user_id))
        raw=action.removeprefix("support_action_");kind,request_raw=raw.rsplit("_",1)
        request_id=int(request_raw);request=db.get_support_request(request_id)
        changed=db.update_support_request(request_id,kind,user_id)
        if changed and kind=="escalate" and request:
            await send_routed(ctx.bot,cfg,"owner_review",
                f"🚨 Support request escalated\nRequest #{request_id} requires Owner attention.",
                target_telegram_id=request["telegram_id"],related_request_id=request_id)
        if changed and kind=="resolve" and request:
            try: await ctx.bot.send_message(request["telegram_id"],f"✅ Support request #{request_id} has been resolved. You can still view its history in My Support Requests.")
            except Exception:
                db.record_delivery_failure("SUP-"+secrets.token_hex(4).upper(),"support_resolution",request["telegram_id"],None,f"Support request #{request_id}")
        return await _show(query,"✅ Support request updated and audited." if changed else "That request was already resolved.",menu_markup(ctx,[],"support_queue"))
    if action == "resources":
        help_actions = [("⭐ Getting Started","resource_about"),("📜 Community Rules","resource_rules"),
            ("📈 Participation Guide","resource_engagement"),("📸 Thursday POP Guide","resource_pop"),
            ("💙 Away Notice Guide","resource_vacation"),("❓ Frequently Asked Questions","resource_faq"),
            ("💬 Contact Admin","contact")]
        if role >= Role.ADMIN:
            help_actions.extend([("🛡️ Review New Creators","resource_admin_registrations"),("🛡️ Review POP","resource_admin_pop"),
                ("🛡️ Review Away Notices","resource_admin_away"),("🛡️ Participation Alerts","resource_admin_alerts"),
                ("🛡️ Support Requests","resource_admin_support")])
        if role is Role.OWNER:
            help_actions.extend([("👑 Telegram Locations","resource_owner_locations"),("👑 Participation Monitor","resource_owner_monitor"),
                ("👑 Audit and Recovery","resource_owner_audit")])
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
        if selected == "errors":
            actions = [(f"View {row['error_reference'] or 'Error'}",f"system_error_{row['id']}_0") for row in rows] + actions
        return await _show(query, text[:3900], menu_markup(ctx, actions, "owner"))
    if action.startswith("system_error_"):
        if role is not Role.OWNER:
            return await _show(query,"System error details are owner-only.",home_markup(ctx,user_id))
        raw=action.removeprefix("system_error_");audit_raw,page_raw=raw.rsplit("_",1);audit_id,page=int(audit_raw),max(0,int(page_raw));row=db.get_audit_event(audit_id)
        if not row or row["action"]!="system_error":
            return await _show(query,"That system error record is unavailable.",menu_markup(ctx,[],"audit_filter_errors"))
        details=json.loads(row["new_value"]) if row["new_value"] else {};incident=db.get_system_incident(details.get("incident_id")) if isinstance(details,dict) and details.get("incident_id") else None
        detail=system_error_detail(row,getattr(cfg,"timezone_name","America/New_York"),incident);size=3400;pages=[detail[i:i+size] for i in range(0,len(detail),size)] or [detail]
        page=min(page,len(pages)-1);actions=[]
        if page:actions.append(("◀️ Previous Trace Page",f"system_error_{audit_id}_{page-1}"))
        if page+1<len(pages):actions.append(("Next Trace Page ▶️",f"system_error_{audit_id}_{page+1}"))
        suffix=f"\n\nTrace page {page+1} of {len(pages)}" if len(pages)>1 else ""
        return await _show(query,pages[page]+suffix,menu_markup(ctx,actions,"audit_filter_errors"))
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
        await send_routed(ctx.bot,cfg,"moderation",f"⚠️ {draft['type'].title()} recorded\nMember: {creator['display_name']}",target_telegram_id=draft["target"])
        summary=db.warning_summary(draft["target"])
        if summary["strikes"]>=3:
            cycle=f"three-strike:{warning_id}"
            if db.claim_notification(draft["target"],cycle,"owner_review"):
                await send_routed(ctx.bot,cfg,"owner_review",
                    f"🔴 Three strikes — Owner Review Required\nMember: {creator['display_name']}\nNo automatic removal has occurred.",
                    target_telegram_id=draft["target"])
        return await _show(query,f"✅ {draft['type'].title()} #{warning_id} {result}. The full action is audited.",menu_markup(ctx,[],"warnings_help"))
    if action == "readiness":
        if role is not Role.OWNER:return await _show(query,"Setup & Readiness is owner-only.",home_markup(ctx,user_id))
        items=readiness_items(cfg);lines=[f"{status_icon(i['state'])} · {i['label']}" for i in items]
        buttons=[(i["label"][:55],f"readiness_item_{i['key']}") for i in items if i["state"]!="ready"]
        buttons=[("🩺 Run Full System Check","full_system_check"),("🧭 Complete Initial Setup","setup_wizard"),("🧪 Test Center","test_center")]+buttons
        return await _show(query,"✅ Setup & Readiness\n\nCheck whether every part of the VAD Operations Bot is configured and working before relying on it.\n\n"+"\n".join(lines),menu_markup(ctx,buttons,"owner"))
    if action.startswith("readiness_item_"):
        if role is not Role.OWNER:return await _show(query,"Readiness details are owner-only.",home_markup(ctx,user_id))
        key=action.removeprefix("readiness_item_");item=next((i for i in readiness_items(cfg) if i["key"]==key),None)
        if not item:return await _show(query,"That readiness check is unavailable.",menu_markup(ctx,[],"readiness"))
        return await _show(query,f"{status_icon(item['state'])} · {item['label']}\n\n{item['detail']}\n\nNo secret values are displayed.",
            menu_markup(ctx,[("Open the Correct Setup Screen",item["action"]),("How to Fix This","readiness_help")],"readiness"))
    if action == "readiness_help":
        if role is not Role.OWNER:return await _show(query,"Owner access is required.",home_markup(ctx,user_id))
        return await _show(query,"How to Fix an Incomplete Item\n\nOpen the suggested screen, verify the Telegram location or setting, review the detected values, and confirm only when they match. Then return to Setup & Readiness and run the Full System Check again.",menu_markup(ctx,[],"readiness"))
    if action == "readiness_token_help":
        if role is not Role.OWNER:return await _show(query,"Owner access is required.",home_markup(ctx,user_id))
        return await _show(query,"Bot Token Setup\n\nIn Replit, open Tools → Secrets, add or update TELEGRAM_BOT_TOKEN, then restart the bot. Never paste the token into Telegram or GitHub. Return here and run the Full System Check.",menu_markup(ctx,[],"readiness"))
    if action == "backup_help":
        if role is not Role.OWNER:return await _show(query,"Backup information is owner-only.",home_markup(ctx,user_id))
        state=db.system_state();last=state.get("last_database_backup")
        text="💾 Backup Basics\n\nBot code is stored in GitHub, but creator history and operational records are stored in the database. Both are needed for a full recovery.\n\nStop the bot before copying vad_tracker.db and its WAL/SHM companions to private storage. The bot reports a backup only after an Owner records that it was completed; it never assumes Replit created one.\n\nLast known backup: "+(friendly_timestamp(last["value"],timezone_name=cfg.timezone_name) if last else "None recorded")
        return await _show(query,text,menu_markup(ctx,[("Record Manual Backup Completed","backup_confirm")],"readiness"))
    if action == "backup_confirm":
        if role is not Role.OWNER:return await _show(query,"Backup tracking is owner-only.",home_markup(ctx,user_id))
        return await _show(query,"Confirm Manual Backup\n\nOnly confirm after the bot was stopped and the database plus WAL/SHM files were copied to private storage. This records the time; it does not create a backup.",confirmation_markup(ctx,"backup_recorded","backup_help"))
    if action == "backup_recorded":
        if role is not Role.OWNER:return await _show(query,"Backup tracking is owner-only.",home_markup(ctx,user_id))
        now=datetime.now(cfg.timezone).isoformat();db.set_system_state("last_database_backup",now);db.record_audit(user_id,"manual_backup_recorded","system",new_value={"recorded_at":now})
        return await _show(query,"🟢 Manual backup time recorded and audited. The bot did not create or inspect the backup file.",menu_markup(ctx,[],"readiness"))
    if action == "full_system_check":
        if role is not Role.OWNER:return await _show(query,"The Full System Check is owner-only.",home_markup(ctx,user_id))
        checks,counts=system_check_summary(cfg)
        telegram_ok=False;chat_problems=[]
        try:
            await ctx.bot.get_me();telegram_ok=True
            for label,chat_id in (("Main group",getattr(cfg,"participation_chat_id",None)),("Sellers group",getattr(cfg,"creator_group_id",None)),("Admin group",getattr(cfg,"admin_chat_id",None))):
                if chat_id:
                    try:
                        await ctx.bot.get_chat(chat_id);member=await ctx.bot.get_chat_member(chat_id,ctx.bot.id)
                        if str(getattr(member,"status","member")) in {"left","kicked"}:chat_problems.append(label)
                    except Exception:chat_problems.append(label)
        except Exception:pass
        if telegram_ok:counts["ready"]+=1
        else:counts["problem"]+=1
        counts["problem"]+=len(chat_problems)
        db.set_system_state("last_full_system_check",datetime.now(cfg.timezone).isoformat())
        incomplete=[i for i in checks if i["state"]!="ready"]
        text=(f"System Check Complete\n\n🟢 {counts['ready']} checks passed\n🟡 {counts['setup']+counts['unverified']} items still need setup or verification\n"
            f"🔴 {counts['problem']} critical problems\n\nTelegram connection: {'Ready' if telegram_ok else 'Problem detected'}")
        if chat_problems:text+="\nChat access needs review: "+", ".join(chat_problems)
        if incomplete:text+="\n\nNeeds Setup or Verification:\n"+"\n".join(f"• {i['label']}" for i in incomplete)
        buttons=[(i["label"][:55],i["action"]) for i in incomplete]
        return await _show(query,text,menu_markup(ctx,buttons,"readiness"))
    if action == "test_center":
        if role is not Role.OWNER:return await _show(query,"Test Center is owner-only.",home_markup(ctx,user_id))
        return await _show(query,"🧪 Test Center\n\nRun safe tests before using the bot with the full community. Test records are labeled and never change real participation, POP, warnings, strikes, or reports.",menu_markup(ctx,[
            ("Test Main Participation Location","test_main"),("Test Meaningful Participation","test_meaningful"),("Test Ignored Message","test_ignored"),
            ("Test Wrong Topic","test_wrong_topic"),("Test Other Group","test_wrong_group"),("Test Registration Routing","test_route_registration"),("Test Away Notice Routing","test_route_away_notice"),
            ("Test POP Routing","test_route_pop_review"),("Test Participation Alert Routing","test_route_participation_alert"),
            ("Test Support Request Routing","test_route_support"),("Test Admin Reply","test_admin_reply"),("Test Failed-Delivery Handling","test_failed_delivery"),
            ("Test Creator Privacy","test_privacy"),("Test Admin Permissions","test_admin_permissions"),("Test Owner Permissions","test_owner_permissions")],"owner"))
    if action in {"test_main","test_meaningful","test_ignored","test_wrong_topic","test_wrong_group"}:
        if role is not Role.OWNER:return await _show(query,"Test Center is owner-only.",home_markup(ctx,user_id))
        code=secrets.token_hex(3).upper();mode={"test_main":"meaningful","test_meaningful":"meaningful","test_ignored":"ignored","test_wrong_topic":"wrong_topic","test_wrong_group":"wrong_group"}[action]
        db.set_system_state("readiness:test_code",code);db.set_system_state("readiness:test_mode",mode)
        sentence=f"VAD-SAFE-{code}:{mode}: I am checking that thoughtful community participation is detected correctly."
        where="configured Main Group participation topic" if mode not in {"wrong_topic","wrong_group"} else "a different Main Group topic that must not count" if mode=="wrong_topic" else "a different group that must not count"
        expected="detected and counted as a test only" if mode=="meaningful" else "detected and ignored without changing participation"
        return await _show(query,f"Safe {mode.replace('_',' ').title()} Test\n\n1. From an approved test creator, open the {where}.\n2. Send the exact test message below.\n3. Return here and tap Check Result.\n\n{sentence}\n\nExpected: {expected}. No real participation or report totals change. Test state is replaced automatically by the next test.",menu_markup(ctx,[
            ("📋 Show Test Message","test_copy"),("Check Result",f"test_check_{mode}"),("Cancel Test","test_cancel")],"test_center"))
    if action == "test_copy":
        state=db.system_state();code=state.get("readiness:test_code",{}).get("value");mode=state.get("readiness:test_mode",{}).get("value")
        return await _show(query,f"Press and hold to copy this test message:\n\nVAD-SAFE-{code}:{mode}: I am checking that thoughtful community participation is detected correctly.",menu_markup(ctx,[],"test_center"))
    if action.startswith("test_check_"):
        mode=action.removeprefix("test_check_");row=db.system_state().get(f"readiness:{mode}_test")
        text="🟢 Test passed. The result was isolated from real operational totals." if row else "⚪ No passing result yet. Confirm the location, sender approval, and exact test message, then try again."
        return await _show(query,text,menu_markup(ctx,[],"test_center"))
    if action == "test_cancel":
        db.set_system_state("readiness:test_code","");db.set_system_state("readiness:test_mode","")
        return await _show(query,"Test cancelled. No operational records were changed.",menu_markup(ctx,[],"test_center"))
    if action.startswith("test_route_"):
        if role is not Role.OWNER:return await _show(query,"Test Center is owner-only.",home_markup(ctx,user_id))
        event=action.removeprefix("test_route_");ok,ref=await send_routed(ctx.bot,cfg,event,f"🧪 SAFE ROUTING TEST\n\nEvent: {event.replace('_',' ').title()}\nNo creator record or operational status was changed.",payload_summary="Owner safe routing test")
        key={"away_notice":"away_route","support":"support_route"}.get(event,event+"_route")
        if ok:db.set_system_state(f"readiness:{key}_test",datetime.now(cfg.timezone).isoformat())
        return await _show(query,"🟢 Test card delivered to the configured destination. No real creator data changed." if ok else f"🔴 Delivery was not completed. No data was lost. Review the destination and try again. Reference: {ref}",menu_markup(ctx,[],"test_center"))
    if action in {"test_failed_delivery","test_privacy","test_admin_permissions","test_owner_permissions","test_admin_reply"}:
        if role is not Role.OWNER:return await _show(query,"Test Center is owner-only.",home_markup(ctx,user_id))
        explanations={
            "test_failed_delivery":"Automated tests confirm failures are stored with safe references and surfaced to Owners; this check does not intentionally break a live route.",
            "test_privacy":"Automated checks confirm an unregistered or different Telegram ID cannot receive another creator’s record.",
            "test_admin_permissions":"Automated checks confirm Admin callbacks recheck permissions and cannot open Owner tools.",
            "test_owner_permissions":"Your current session passed the server-side Owner check. Owner access still comes only from configured numeric IDs.",}
        explanations["test_admin_reply"]="Support reply storage, creator-only visibility, delivery failure preservation, and resolution are covered by safe automated tests. No creator message was sent."
        return await _show(query,"🟢 Safe Verification\n\n"+explanations[action]+"\n\nNo operational data changed.",menu_markup(ctx,[],"test_center"))
    if action == "setup_wizard" or action.startswith("wizard_"):
        if role is not Role.OWNER:return await _show(query,"Initial Setup is owner-only.",home_markup(ctx,user_id))
        if action.startswith("wizard_step_"):step=max(1,min(8,int(action.removeprefix("wizard_step_"))));db.set_system_state(f"setup_wizard:{user_id}",step)
        else:
            saved=db.system_state().get(f"setup_wizard:{user_id}",{}).get("value","1")
            try:step=int(saved)
            except ValueError:step=1
        steps=[("Owners","Confirm Kira now and add Alex’s immutable numeric ID when available.","roles"),
            ("Main Participation Group","Verify the Main VAD group.","location_main"),("Participation Topic","Verify General safely; never guess its topic ID.","location_participation"),
            ("Sellers Group and POP Topic","Verify the Sellers group and POP topic.","telegram_locations"),("Admin Group and Topics","Verify each private operational destination.","telegram_locations"),
            ("Reminder and POP Times","Review Eastern Time reminders and Thursday cutoff.","settings"),("Test Registration","Send a labeled safe registration routing card.","test_route_registration"),
            ("Final Readiness Check","Run the complete non-destructive system check.","full_system_check")]
        title,detail,target=steps[step-1];actions=[("Open This Step",target)]
        if step<8:actions.append(("Save & Continue",f"wizard_step_{step+1}"))
        return await _show(query,f"🧭 Complete Initial Setup\n\nStep {step} of 8 — {title}\n\n{detail}\n\nYour progress is saved automatically and resumes here after restart.",menu_markup(ctx,actions,"owner"))
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
    if action == "telegram_locations":
        if role is not Role.OWNER:return await _show(query,"Telegram Locations is owner-only.",home_markup(ctx,user_id))
        return await _show(query,"📍 Telegram Locations\n\nConfigure where participation is counted and where operational notifications are delivered.",menu_markup(ctx,[
            ("Verify Main Group","location_main"),("Verify Participation Topic","location_participation"),
            ("Verify Sellers Group","location_sellers"),("Verify POP Topic","location_pop"),
            ("Verify POP Review Topic","location_pop_review"),
            ("Verify Admin Group","location_admin"),("Verify Reports Topic","location_reports"),
            ("Verify Away Notice Topic","location_away"),("Verify Registration Topic","location_registration"),
            ("Verify Moderation Topic","location_moderation"),("Verify Support Topic","location_support"),
            ("Verify Health Topic","location_health"),("View Routing Summary","routing_summary")],"owner"))
    if action.startswith("location_"):
        if role is not Role.OWNER:return await _show(query,"Telegram Locations is owner-only.",home_markup(ctx,user_id))
        purpose=action.removeprefix("location_");chat=getattr(query.message,"chat",None) or update.effective_chat
        chat_id=getattr(chat,"id",None);thread_id=getattr(query.message,"message_thread_id",None)
        topic_purposes={"participation","pop","pop_review","reports","away","registration","moderation","support","health"}
        value=thread_id if purpose in topic_purposes else chat_id
        current={"main":getattr(cfg,"participation_chat_id",None),"sellers":getattr(cfg,"creator_group_id",None),
            "admin":getattr(cfg,"admin_chat_id",None),"participation":sorted(getattr(cfg,"participation_topic_ids",frozenset())),
            "pop":getattr(cfg,"pop_thread_id",None),"reports":getattr(cfg,"reports_thread_id",None),
            "pop_review":getattr(cfg,"pop_review_thread_id",None),
            "away":getattr(cfg,"away_thread_id",None),"registration":getattr(cfg,"registration_thread_id",None),
            "moderation":getattr(cfg,"moderation_thread_id",None),"support":getattr(cfg,"support_thread_id",None),
            "health":getattr(cfg,"health_thread_id",None)}.get(purpose)
        match=((value in current) if current else value is None) if purpose=="participation" and isinstance(current,list) else value==current
        title=getattr(chat,"title",None) or "Private chat";forum=bool(getattr(chat,"is_forum",False))
        recommendation=("Use General (no topic ID) for participation" if purpose=="participation" and value is None else
            "Open this tool inside the intended forum topic." if value is None else f"Use {value} for {purpose.replace('_',' ')}")
        key={"main":"participation_chat","sellers":"creator_group","admin":"admin_chat","participation":"participation_topic",
            "pop":"pop_topic","pop_review":"pop_review_topic","reports":"reports_topic","away":"away_topic","registration":"registration_topic",
            "moderation":"moderation_topic","support":"support_topic","health":"health_topic"}.get(purpose)
        bot_permissions="Unable to verify; check that the bot is present"
        privacy_status="Not checked"
        bot=getattr(ctx,"bot",None)
        if bot and hasattr(bot,"get_me"):
            try:
                identity=await bot.get_me();can_read=bool(getattr(identity,"can_read_all_group_messages",False))
                privacy_status="Disabled — ordinary messages available" if can_read else "Enabled — make the bot an Admin or disable privacy with BotFather"
            except Exception:pass
        if chat_id and bot and hasattr(bot,"get_chat_member") and getattr(chat,"type",None) in {"group","supergroup","channel"}:
            try:
                member=await bot.get_chat_member(chat_id,bot.id)
                allowed=[name.replace("can_","").replace("_"," ").title() for name in
                    ("can_send_messages","can_post_messages","can_manage_topics","can_delete_messages") if getattr(member,name,False)]
                bot_permissions=str(getattr(member,"status","member")).title()+(f" · {', '.join(allowed)}" if allowed else "")
            except Exception:
                pass
        text=(f"📍 Verify {purpose.replace('_',' ').title()}\n\nConfirm this Telegram location before saving it.\n\n"
            f"Chat title: {title}\nChat type: {getattr(chat,'type','unknown')}\nChat ID: {chat_id}\nForum enabled: {'Yes' if forum else 'No'}\n"
            f"Topic title: {'General' if thread_id is None else 'Current topic (title unavailable)'}\nTopic ID: {thread_id or 'None'}\n"
            f"Bot membership and permissions: {bot_permissions}\nTelegram privacy mode: {privacy_status}\nCurrent configured destination: {current if current is not None else 'Not configured'}\n"
            f"Participation enabled here: {'Yes' if purpose == 'participation' and match else 'No'}\nMatch: {'Yes' if match else 'No'}\nRecommended correction: {recommendation}")
        actions=([("Use General for Participation","setup_prepare_participation_general")] if purpose=="participation" and value is None else
            [] if value is None else [("Use This Location",f"setup_prepare_{key}")])
        return await _show(query,text,menu_markup(ctx,actions,"telegram_locations"))
    if action == "routing_summary":
        if role is not Role.OWNER:return await _show(query,"Routing Summary is owner-only.",home_markup(ctx,user_id))
        state=db.system_state();failures=db.open_delivery_failures();lines=[];actions=[]
        for event,chat,thread in routing_summary(cfg):
            success=state.get(f"last_route_success:{event}");failure=next((r for r in failures if r["event_type"]==event),None)
            lines.append(f"{event.replace('_',' ').title()}\nSource: operational workflow\nDestination: {'Configured' if chat and thread is not None else 'Needs setup'}\n"
                f"Verification: {'Verified by delivery' if success else 'Not yet verified'}\nLast success: {friendly_timestamp(success['value'],timezone_name=cfg.timezone_name) if success else 'None recorded'}\n"
                f"Last failure: {failure['error_reference'] if failure else 'None open'}")
            actions.append((f"Test {event.replace('_',' ').title()}",f"test_route_{event}"))
        return await _show(query,"📍 Routing Summary\n\nReview each private operational route, its most recent result, and a safe test.\n\n"+"\n\n".join(lines),menu_markup(ctx,actions,"telegram_locations"))
    if action == "participation_monitor":
        if role is not Role.OWNER:return await _show(query,"Participation Monitor is owner-only.",home_markup(ctx,user_id))
        monitor=db.participation_monitor();cats=", ".join(f"{r['reason']}: {r['count']}" for r in monitor["ignored_categories"]) or "None"
        state=db.system_state();privacy=state.get("telegram_can_read_all_group_messages",{}).get("value")
        access="Yes" if privacy=="true" or monitor["last_detected"] else "No — disable privacy mode or make the bot an Admin"
        observed_chat=state.get("last_group_message_chat_id",{}).get("value","None yet")
        observed_topic=state.get("last_group_message_thread_id",{}).get("value","None yet")
        configured_chat=cfg.participation_chat_id or cfg.girls_chat_id
        configured_topics=sorted(cfg.participation_topic_ids) if cfg.participation_topic_ids else []
        expected_topics=", ".join(map(str,configured_topics)) if configured_topics else "General (no thread ID)"
        topic_source="Owner Setup (database override)" if "config:participation_topic_ids" in state else "Startup configuration"
        reports_overlap=bool(configured_topics and getattr(cfg,"reports_thread_id",None) in configured_topics)
        chat_match="Not yet observed" if observed_chat=="None yet" else ("Yes" if str(observed_chat)==str(configured_chat) else "No")
        observed_topic_value=None if observed_topic=="general:none" else observed_topic
        topic_match="Not yet observed" if observed_topic=="None yet" else ("Yes" if ((not configured_topics and observed_topic_value is None) or str(observed_topic_value) in {str(v) for v in configured_topics}) else "No")
        reason_labels={"accepted":"Counted as meaningful participation","wrong_chat":"Rejected: wrong chat","wrong_topic":"Rejected: wrong topic",
            "accepted_voice_message":"Counted: qualifying voice message","accepted_audio_message":"Counted: qualifying audio message",
            "creator_not_approved":"Rejected: creator not approved","audio_too_short":"Ignored: audio too short",
            "duplicate_audio":"Ignored: duplicate audio","audio_missing_file_identity":"Ignored: audio identity unavailable",
            "active_away_notice":"Not counted: active Away Notice","legacy_vacation_active":"Not counted: active legacy vacation",
            "pop_workflow_message":"Not counted: POP workflow message","duplicate_telegram_update":"Ignored: duplicate Telegram update",
            "greeting_only":"Ignored: greeting only","emoji_only":"Ignored: emoji only","too_short":"Ignored: too short",
            "promotional_spam":"Ignored: promotional content","link_only":"Ignored: link only","repeated_text":"Ignored: repeated text",
            "non_text":"Ignored: no meaningful text","command":"Ignored: bot command"}
        creator_lines=[]
        for item in db.creator_participation_diagnostics():
            creator=item["creator"];diag=item["diagnostic"]
            if not diag:
                creator_lines.append(f"{creator['display_name']} — No message from this creator has reached the participation observer.")
                continue
            reason=reason_labels.get(diag.get("reason"),f"Ignored: {str(diag.get('reason','unknown')).replace('_',' ')}")
            creator_lines.append(f"{creator['display_name']} — {reason}\nObserved chat/topic: {diag.get('observed_chat_id')} / {diag.get('observed_thread_id') if diag.get('observed_thread_id') is not None else 'General (none)'}\n"
                f"Configured chat/topics: {diag.get('configured_chat_id')} / {', '.join(map(str,diag.get('configured_thread_ids') or [])) or 'General (none)'}\n"
                f"Observed: {friendly_timestamp(diag.get('observed_at'),timezone_name=cfg.timezone_name)}")
        last=lambda row: friendly_timestamp(row["created_at"],timezone_name=cfg.timezone_name) if row else "None yet"
        text=("📈 Participation Monitor\n\nThis page confirms whether participation tracking is seeing and correctly processing messages in the approved VAD participation area.\n\n"
            f"Configured chat ID: {configured_chat or 'Not configured'}\nConfigured topic IDs: {expected_topics}\nConfiguration source: {topic_source}\n"
            f"Admin reports topic mistakenly reused: {'Yes' if reports_overlap else 'No'}\n"
            f"Connected: {'Yes' if cfg.participation_chat_id else 'No'}\nCan read ordinary messages: {access}\nLast message detected: {last(monitor['last_detected'])}\n"
            f"Last observed chat ID: {observed_chat}\nLast observed topic ID: {observed_topic}\nChat matches: {chat_match}\nTopic matches: {topic_match}\n"
            f"Last meaningful participation: {last(monitor['last_counted'])}\nApproved sellers tracked: {monitor['tracked']}\n"
            f"Ignored today: {monitor['ignored_today']}\nIgnored categories: {cats}\nProcessing failures: {monitor['failures']}\n\n"
            "Last approved-creator outcomes\n"+("\n\n".join(creator_lines) or "No approved creators are currently tracked."))
        monitor_actions=[("🧾 Participation Event Log","participation_events")]
        if observed_topic=="general:none" and configured_topics:
            text += "\n\nRecommended correction\nGeneral is receiving creator messages, but numbered topic IDs are configured. Replace the participation topic list with General-only after confirming General is the intended area."
            monitor_actions.insert(0,("Use General for Participation","setup_prepare_participation_general"))
        return await _show(query,text,menu_markup(ctx,monitor_actions,"owner"))
    if action == "participation_events":
        if role is not Role.OWNER:return await _show(query,"Participation Event Log is owner-only.",home_markup(ctx,user_id))
        rows=db.participation_events();lines=[f"{'✅ Counted' if r['decision']=='accepted' else '⚪ Ignored'} · {r['display_name'] or 'Unregistered user'} · {r['reason']}\n{friendly_timestamp(r['created_at'],timezone_name=cfg.timezone_name)}" for r in rows]
        return await _show(query,"🧾 Participation Event Log\n\nReview concise processing outcomes without storing full message text.\n\n"+("\n\n".join(lines) or "No participation events yet."),menu_markup(ctx,[],"participation_monitor"))
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
        if is_forum and action == "verify_topic" and thread_id is None and topics: problems.append("General is observed, but a numbered participation topic is configured")
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
        elif action == "verify_topic" and thread_id is None:
            actions = [("Use General for Participation","setup_prepare_participation_general")]
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
            "participation_general":"general",
            "pop_topic":getattr(query.message,"message_thread_id",None),
            "pop_review_topic":getattr(query.message,"message_thread_id",None),
            "reports_topic":getattr(query.message,"message_thread_id",None),
            "away_topic":getattr(query.message,"message_thread_id",None),
            "registration_topic":getattr(query.message,"message_thread_id",None),
            "moderation_topic":getattr(query.message,"message_thread_id",None),
            "support_topic":getattr(query.message,"message_thread_id",None),
            "health_topic":getattr(query.message,"message_thread_id",None),
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
            "admin_chat":"admin_chat_id","buyer_group":"buyer_group_id","pop_topic":"pop_thread_id",
            "pop_review_topic":"pop_review_thread_id",
            "reports_topic":"reports_thread_id","away_topic":"away_thread_id","registration_topic":"registration_thread_id",
            "moderation_topic":"moderation_thread_id","support_topic":"support_thread_id","health_topic":"health_thread_id"}
        if pending["key"] == "participation_general":
            persist_setting(cfg,"participation_topic_ids",frozenset(),user_id)
        elif pending["key"] == "participation_topic":
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
            ("📸 POP Deadline","settings_pop"),("📊 Daily Admin Brief","daily_brief_settings")],"setup"))
    if action == "daily_brief_settings":
        if role is not Role.OWNER:return await _show(query,"Daily Admin Brief settings are owner-only.",home_markup(ctx,user_id))
        destination="Configured" if cfg.daily_brief_chat_id else "Needs setup"
        text=("📊 Daily Admin Brief\n\nSend one concise operations brief to the configured Admin destination.\n\n"
            f"Enabled: {'Yes' if cfg.daily_brief_enabled else 'No'}\nTime: {cfg.daily_brief_time} ET\nDestination: {destination}\n"
            f"System Health: {'Included' if cfg.daily_brief_include_health else 'Hidden'}\n"
            f"Zero-count sections: {'Included' if cfg.daily_brief_include_zero else 'Hidden'}\n"
            f"Weekends: {'Yes' if cfg.daily_brief_weekends else 'No'}")
        return await _show(query,text,menu_markup(ctx,[("Enable / Disable","brief_toggle"),("8:00 AM ET","brief_time_08:00"),
            ("9:00 AM ET","brief_time_09:00"),("10:00 AM ET","brief_time_10:00"),("Use This Chat","brief_use_chat"),
            ("Use This Topic","brief_use_topic"),("Include / Hide System Health","brief_health"),
            ("Show / Hide Zero Items","brief_zero"),("Weekends On / Off","brief_weekends"),("Verify Destination","brief_verify"),
            ("🧪 Send Test Brief","brief_test")],"settings"))
    if action in {"brief_toggle","brief_health","brief_zero","brief_weekends"} or action.startswith("brief_time_"):
        if role is not Role.OWNER:return await _show(query,"Daily Admin Brief settings are owner-only.",home_markup(ctx,user_id))
        if action=="brief_toggle":attr="daily_brief_enabled";new=not cfg.daily_brief_enabled
        elif action=="brief_health":attr="daily_brief_include_health";new=not cfg.daily_brief_include_health
        elif action=="brief_zero":attr="daily_brief_include_zero";new=not cfg.daily_brief_include_zero
        elif action=="brief_weekends":attr="daily_brief_weekends";new=not cfg.daily_brief_weekends
        else:attr="daily_brief_time";new=action.removeprefix("brief_time_")
        persist_setting(cfg,attr,new,user_id)
        return await _show(query,"✅ Daily Brief setting updated and audited.",menu_markup(ctx,[],"daily_brief_settings"))
    if action in {"brief_use_chat","brief_use_topic"}:
        if role is not Role.OWNER:return await _show(query,"Daily Admin Brief settings are owner-only.",home_markup(ctx,user_id))
        value=query.message.chat_id if action=="brief_use_chat" else query.message.message_thread_id
        if value is None:return await _show(query,"This message is not inside a forum topic.",menu_markup(ctx,[],"daily_brief_settings"))
        attr="daily_brief_chat_id" if action=="brief_use_chat" else "daily_brief_thread_id"
        ctx.user_data["brief_destination_draft"]={"attr":attr,"value":value}
        return await _show(query,"Confirm Daily Brief destination\n\nThis changes where protected Admin summaries are delivered. The change is reversible and will be audited.",confirmation_markup(ctx,"brief_confirm_destination","daily_brief_settings"))
    if action == "brief_confirm_destination":
        if role is not Role.OWNER:return await _show(query,"Daily Admin Brief settings are owner-only.",home_markup(ctx,user_id))
        draft=ctx.user_data.pop("brief_destination_draft",None)
        if not draft:return await _show(query,"That destination change expired. Nothing was changed.",menu_markup(ctx,[],"daily_brief_settings"))
        persist_setting(cfg,draft["attr"],draft["value"],user_id)
        return await _show(query,"✅ Daily Brief destination updated and audited.",menu_markup(ctx,[],"daily_brief_settings"))
    if action == "brief_verify":
        if role is not Role.OWNER:return await _show(query,"Destination verification is owner-only.",home_markup(ctx,user_id))
        status="🟢 Configured" if cfg.daily_brief_chat_id else "🟡 Needs setup"
        return await _show(query,f"📍 Daily Brief Destination\n\n{status}\nChat and topic identifiers stay protected in Owner settings.",menu_markup(ctx,[],"daily_brief_settings"))
    if action == "brief_test":
        if role is not Role.OWNER:return await _show(query,"Test Brief is owner-only.",home_markup(ctx,user_id))
        ok,ref=await deliver_daily_brief(ctx.bot,cfg,test=True)
        message="✅ Test Brief delivered. No operational records or alerts were changed." if ok else f"⚠️ Test delivery failed. No operational records were changed. Check the destination and try again. Reference: {ref}"
        return await _show(query,message,menu_markup(ctx,[],"daily_brief_settings"))
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
        return await _show(query,f"👥 People & Roles\n\nRoles are additive: Admins include Creator access, and Owners include both Admin and Creator access.\n\n👑 Owners: {len(cfg.owner_user_ids)}\n🛡️ Lead Admins: {len(cfg.lead_admin_user_ids)}\n👥 Admins: {len(cfg.admin_user_ids)}",
            menu_markup(ctx,[("👑 Owners","access_owners"),("🛡️ Lead Admins","access_leads"),("👥 Admins","access_admins"),
                ("➕ Add Admin","access_add"),("✏️ Edit Admin Permissions","access_edit"),("➖ Remove Admin","access_remove"),
                ("⏳ Pending Bot Users","pending_bot_users"),("📝 Creator Registrations","registration_queue"),("🔄 Dual-Role Members","dual_roles"),
                ("📜 Role History","audit_filter_roles"),("📋 Copy Admin Instructions","copy_admin_instructions"),
                ("📋 Copy Creator Invite Instructions","copy_creator_instructions"),("📋 Copy Alex Owner Instructions","copy_alex_instructions")],"owner"))
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
        assigned=set(cfg.owner_user_ids)|set(cfg.admin_user_ids)|set(cfg.lead_admin_user_ids)
        creators=[r for r in db.list_creators() if r["telegram_id"] not in assigned and r["status"]=="active"]
        pending=db.pending_bot_users(cfg.owner_user_ids,cfg.admin_user_ids,cfg.lead_admin_user_ids)
        candidates={r["telegram_id"]:r["display_name"] for r in pending}
        candidates.update({r["telegram_id"]:r["display_name"] for r in creators})
        buttons=[(name[:45],f"access_candidate_{target}") for target,name in list(candidates.items())[:20]]
        return await _show(query,"➕ Add Admin\n\nSelect an approved creator or someone who has privately opened the bot. Admin access attaches to the same Telegram identity and never creates a duplicate creator record.\n\n"+("No eligible accounts are waiting." if not candidates else "Choose a known user:"),menu_markup(ctx,buttons,"roles"))
    if action.startswith("access_candidate_"):
        if role is not Role.OWNER:return await _show(query,"People & Roles is owner-only.",home_markup(ctx,user_id))
        target=int(action.removeprefix("access_candidate_"));creator=db.get_creator(target)
        pending=next((r for r in db.pending_bot_users(cfg.owner_user_ids,cfg.admin_user_ids,cfg.lead_admin_user_ids) if r["telegram_id"]==target),None)
        if not creator and not pending:return await _show(query,"That account is no longer eligible for assignment.",menu_markup(ctx,[],"roles"))
        name=creator["display_name"] if creator else pending["display_name"]
        return await _show(query,f"{name}\n\nChoose an additive role. The existing Telegram identity and creator history will be preserved.",menu_markup(ctx,[
            ("Make Admin",f"access_confirm_admin_{target}"),("Make Lead Admin",f"access_confirm_lead_{target}"),("Make Owner",f"access_confirm_owner_{target}")],"roles"))
    if action == "pending_bot_users":
        if role is not Role.OWNER:return await _show(query,"People & Roles is owner-only.",home_markup(ctx,user_id))
        rows=db.pending_bot_users(cfg.owner_user_ids,cfg.admin_user_ids,cfg.lead_admin_user_ids)
        buttons=[(r["display_name"][:45],f"pending_user_{r['telegram_id']}") for r in rows[:20]]
        return await _show(query,"⏳ Pending Bot Users\n\nThese people privately started the bot but have not been assigned a role or registered as a community member. No role is inferred automatically.",menu_markup(ctx,buttons,"roles"))
    if action.startswith("pending_user_"):
        if role is not Role.OWNER:return await _show(query,"People & Roles is owner-only.",home_markup(ctx,user_id))
        target=int(action.removeprefix("pending_user_"));rows=db.pending_bot_users(cfg.owner_user_ids,cfg.admin_user_ids,cfg.lead_admin_user_ids)
        row=next((r for r in rows if r["telegram_id"]==target),None)
        if not row:return await _show(query,"That user is no longer unassigned.",menu_markup(ctx,[],"roles"))
        return await _show(query,f"{row['display_name']}\n\nChoose an explicit next step. Nothing changes until you confirm.",menu_markup(ctx,[
            ("Make Admin",f"access_confirm_admin_{target}"),("Make Lead Admin",f"access_confirm_lead_{target}"),("Make Owner",f"access_confirm_owner_{target}"),
            ("Invite to Register as Creator",f"invite_creator_{target}"),("Leave Unassigned","roles")],"pending_bot_users"))
    if action.startswith("invite_creator_"):
        if role is not Role.OWNER:return await _show(query,"People & Roles is owner-only.",home_markup(ctx,user_id))
        target=int(action.removeprefix("invite_creator_"))
        try:
            await ctx.bot.send_message(target,"You’re invited to register as a VAD creator. Open this private chat, tap Start, then tap Register as Creator. Admin access is not included.")
            db.record_audit(user_id,"creator_registration_invite_sent","bot_user",target,target)
            text="✅ Creator registration instructions were delivered privately. No role was assigned."
        except Exception:
            text="The invitation was not delivered. No role was assigned. Ask the person to open the bot privately and tap Start, then try again."
        return await _show(query,text,menu_markup(ctx,[],"roles"))
    if action == "dual_roles":
        if role is not Role.OWNER:return await _show(query,"People & Roles is owner-only.",home_markup(ctx,user_id))
        ids=set(cfg.admin_user_ids)|set(cfg.lead_admin_user_ids);rows=[db.get_creator(i) for i in ids];rows=[r for r in rows if r]
        return await _show(query,"🔄 Multi-Role Members\n\nEvery Admin includes Creator access. Every Owner includes Admin and Creator access. Each person still has only one creator profile.\n\n"+("\n".join(r["display_name"] for r in rows) or "No multi-role members."),menu_markup(ctx,[],"roles"))
    if action in {"copy_creator_instructions","copy_admin_instructions","copy_alex_instructions"}:
        if role is not Role.OWNER:return await _show(query,"Owner access is required.",home_markup(ctx,user_id))
        texts={
            "copy_creator_instructions":"📋 Creator Registration Instructions\n\n1. Open the VAD Operations Bot privately.\n2. Tap Start.\n3. Tap Register as Creator.\n4. Complete the registration.\n5. Wait for approval.\n6. After approval, the bot recognizes participation through your Telegram account automatically.\n\nYou do not need to find or send your numeric Telegram ID.",
            "copy_admin_instructions":"📋 Admin Setup Instructions\n\n1. Open the VAD Operations Bot privately.\n2. Tap Start once.\n3. Tell Kira or Alex this is complete.\n4. Kira or Alex assigns your Admin role and permissions through People & Roles.\n5. Admin access automatically includes one Creator profile and never duplicates your identity.",
            "copy_alex_instructions":"📋 Alex Owner Setup Instructions\n\n1. Alex opens the bot privately and taps Start.\n2. The bot captures her immutable Telegram identity.\n3. Kira verifies Alex’s account and assigns Owner through People & Roles, or adds her numeric ID to secure bootstrap configuration.\n4. Alex opens the bot again and confirms Owner, Admin, and My VAD Home are available.\n\nThe bot never displays the bot token or existing Secret values."}
        return await _show(query,texts[action]+"\n\nPress and hold this message to copy it.",menu_markup(ctx,[],"roles"))
    if action in {"access_edit","access_remove"}:
        if role is not Role.OWNER: return await _show(query,"Access management is owner-only.",home_markup(ctx,user_id))
        ids = sorted(set(cfg.admin_user_ids)|set(cfg.lead_admin_user_ids)|set(cfg.owner_user_ids))
        buttons = [[((db.get_creator(i)["display_name"] if db.get_creator(i) else f"Admin •••{str(i)[-4:]}")[:40],f"access_member_{i}")] for i in ids]
        return await _show(query,"Select an administrator.",grid_markup(ctx,buttons,"roles"))
    if action.startswith("access_member_"):
        if role is not Role.OWNER: return await _show(query,"Access management is owner-only.",home_markup(ctx,user_id))
        target = int(action.removeprefix("access_member_"))
        return await _show(query,"Choose the change to review.",menu_markup(ctx,[("👥 Make Admin",f"access_confirm_admin_{target}"),
            ("🛡️ Make Lead Admin",f"access_confirm_lead_{target}"),("👑 Make Owner",f"access_confirm_owner_{target}"),
            ("➖ Remove Highest Role",f"access_confirm_none_{target}")],"roles"))
    if action.startswith("access_confirm_"):
        if role is not Role.OWNER: return await _show(query,"Access management is owner-only.",home_markup(ctx,user_id))
        _,_,new_role,target_raw = action.split("_",3); target = int(target_raw)
        previous = role_for(target,cfg).name.lower(); admins,leads,owners=set(cfg.admin_user_ids),set(cfg.lead_admin_user_ids),set(cfg.owner_user_ids)
        admins.discard(target); leads.discard(target)
        if new_role == "none" and target in owners:
            if target == user_id:return await _show(query,"You cannot remove your own Owner access.",menu_markup(ctx,[],"roles"))
            if len(owners) <= 1:return await _show(query,"At least one Owner must remain configured.",menu_markup(ctx,[],"roles"))
            owners.discard(target);admins.add(target)
        if new_role == "admin": admins.add(target)
        if new_role == "lead": leads.add(target)
        if new_role == "owner":owners.add(target)
        cfg.admin_user_ids,cfg.lead_admin_user_ids,cfg.owner_user_ids=frozenset(admins),frozenset(leads),frozenset(owners)
        persist_setting(cfg,"admin_user_ids",cfg.admin_user_ids,user_id)
        persist_setting(cfg,"lead_admin_user_ids",cfg.lead_admin_user_ids,user_id)
        persist_setting(cfg,"owner_user_ids",cfg.owner_user_ids,user_id)
        db.record_audit(user_id,"role_changed","admin_role",target,target,previous,new_role)
        return await _show(query,"✅ Access changed, persisted, and audited. The account retains one creator profile.",menu_markup(ctx,[],"roles"))
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

async def brief_callback(update: Update,ctx: ContextTypes.DEFAULT_TYPE):
    """Safely open brief destinations without editing a shared Admin-topic message."""
    query=update.callback_query;user_id=update.effective_user.id;cfg=ctx.bot_data["config"]
    if role_for(user_id,cfg)<Role.ADMIN:
        return await query.answer("This Admin information is not available to your account.",show_alert=True)
    await query.answer("Opening privately…")
    action=(query.data or "").removeprefix("brief:")
    if action=="snapshot":text=snapshot_text(user_id,cfg)
    elif action=="attention":text="🚨 Needs Attention\n\nOpen your private Admin or Owner Home and choose Needs Attention / Admin Queue."
    else:
        if role_for(user_id,cfg) is not Role.OWNER and not has_permission(user_id,cfg,"view_system_health"):
            text="System Health is not included in your assigned permissions."
        else:text="🩺 System Health\n\nOpen your private Owner Home and choose Health to run protected diagnostics."
    await ctx.bot.send_message(user_id,text)


def register_navigation(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback, pattern=r"^op:"))
    app.add_handler(CallbackQueryHandler(brief_callback, pattern=r"^brief:"))
