"""Role-aware, nonce-protected application navigation."""

import secrets
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

import database as db
from config import RESOURCE_DEFAULTS
from permissions import Role, has_permission, role_for


def _nonce(ctx):
    value = secrets.token_urlsafe(6)
    ctx.user_data["menu_nonce"] = value
    return value


def _button(label, nonce, action):
    return InlineKeyboardButton(label, callback_data=f"op:{nonce}:{action}")


def _nav(nonce, back="home"):
    return [_button("🏠 Home", nonce, "home"), _button("◀️ Back", nonce, back), _button("❌ Cancel", nonce, "cancel")]


def grid_markup(ctx, rows, back="home"):
    nonce = _nonce(ctx)
    keyboard = [[_button(label,nonce,action) for label,action in row] for row in rows if row]
    keyboard.append(_nav(nonce,back))
    return InlineKeyboardMarkup(keyboard)


def home_markup(ctx, user_id):
    nonce = _nonce(ctx)
    cfg = ctx.bot_data["config"]
    role = role_for(user_id, cfg)
    rows = [[_button("👤 My Dashboard", nonce, "creator")]]
    if role >= Role.ADMIN:
        rows.append([_button("👑 Admin Dashboard", nonce, "admin")])
    if role is Role.OWNER:
        rows.append([_button("🔐 Owner Dashboard", nonce, "owner")])
    rows.extend([
        [_button("📖 Resources", nonce, "resources"), _button("🆘 Support", nonce, "support")],
    ])
    return InlineKeyboardMarkup(rows)


def menu_markup(ctx, actions, back="home"):
    nonce = _nonce(ctx)
    rows = [[_button(label, nonce, action)] for label, action in actions]
    rows.append(_nav(nonce, back))
    return InlineKeyboardMarkup(rows)


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


def creator_card(user_id, cfg):
    creator = db.get_creator(user_id)
    if not creator:
        return "You are not registered yet. Tap Register to get started."
    warning = db.warning_summary(user_id)
    pop = db.creator_pop_status(user_id, _week_key(datetime.now(cfg.timezone))) if creator["status"] == "active" else "awaiting approval"
    absence = db.latest_absence(user_id)
    away = "None on file" if not absence else f"{absence['absence_type'].title()} {absence['start_date']}–{absence['end_date']} ({absence['status']})"
    participation = "Active" if creator["status"] == "active" else creator["status"].title()
    return (
        f"🤝 Participation · {participation}\n"
        f"📸 Thursday POP · {pop.replace('_', ' ').title()}\n"
        f"💛 Community standing · {_standing(warning)}\n"
        f"🌴 Away Notice · {away}\n"
        f"🟢 Availability · {creator['availability'].title()}"
    )


def admin_card(cfg):
    metrics = db.dashboard_metrics(_week_key(datetime.now(cfg.timezone)))
    pending = metrics["pending_registrations"] + metrics["pending_vacations"] + metrics["pending_sick"] + metrics["pending_pop"]
    return (
        f"📥 Reviews waiting · {pending}\n"
        f"📝 Registrations · {metrics['pending_registrations']}\n"
        f"🌴 Away Notices · {metrics['pending_vacations'] + metrics['pending_sick']}\n"
        f"📸 POP reviews · {metrics['pending_pop']}\n"
        f"⚠️ Missing POP · {metrics['missing_pop']}"
    )


def owner_card(cfg):
    metrics = db.dashboard_metrics(_week_key(datetime.now(cfg.timezone)))
    return (
        f"👥 Active creators · {metrics['active_creators']}\n"
        f"📥 Pending actions · {metrics['pending_registrations'] + metrics['pending_vacations'] + metrics['pending_sick'] + metrics['pending_pop']}\n"
        f"🌴 Away now · {metrics['away_now']}\n"
        f"💛 Warnings / strikes · {metrics['active_warnings']} / {metrics['active_strikes']}\n"
        f"🗃 Archived records · {metrics['deleted_records']}\n"
        f"🔒 Audit events · {metrics['audit_events']}\n"
        "🩺 System · Ready"
    )


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    text = (
        f"Welcome, {update.effective_user.first_name}! 💛\n\n"
        "This space is here to help you check VAD participation, submit Thursday POP, or share an Away Notice.\n\n"
        "Away Notices keep tracking fair when you need time away—no private details needed."
    )
    if db.get_creator(update.effective_user.id):
        text += "\n\nToday\n" + creator_card(update.effective_user.id,ctx.bot_data["config"])
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
    if action == "creator":
        creator = db.get_creator(user_id)
        if not creator:
            return await _show(query,"Your VAD Dashboard\n\nYou are not registered yet. Registration takes one tap and sends your profile for review.",
                grid_markup(ctx,[[ ("📝 Register","register") ],[("📖 Resources","resources"),("💬 Get Help","contact")]]))
        return await _show(query, "Your VAD Dashboard\n\n" + creator_card(user_id, cfg), grid_markup(ctx, [
            [("🟢 Available","available"),("⚪ Unavailable","unavailable")],
            [("🌴 Vacation Notice","vacation_help"),("🤒 Sick-Day Notice","sick_help")],
            [("📸 POP Help","pop_help"),("💛 Standing","my_warnings")],
            [("📜 Timeline","timeline_0"),("💬 Get Help","contact")],
        ]))
    if action == "admin":
        if role < Role.ADMIN:
            return await _show(query, "Admin access is required.", home_markup(ctx, user_id))
        rows = []
        if has_permission(user_id,cfg,"review_registrations"): rows.append([("📝 Registrations","registration_queue")])
        away = []
        if has_permission(user_id,cfg,"review_vacations"): away.append(("🌴 Vacation","vacation_queue"))
        if has_permission(user_id,cfg,"review_sick_days"): away.append(("🤒 Sick Day","sick_queue"))
        if away: rows.append(away)
        if has_permission(user_id,cfg,"review_pop"): rows.append([("📸 POP Reviews","pop_queue")])
        if has_permission(user_id,cfg,"view_creator_reports"): rows.append([("👥 Creator Directory","creator_report"),("📅 Calendar","calendar")])
        tools = []
        if has_permission(user_id,cfg,"adjust_warnings"): tools.append(("💛 Standing","warnings_help"))
        if has_permission(user_id,cfg,"send_announcements"): tools.append(("💬 Messages","templates_help"))
        if tools: rows.append(tools)
        return await _show(query, "Admin Dashboard\n\n" + admin_card(cfg), grid_markup(ctx,rows))
    if action == "owner":
        if role is not Role.OWNER:
            return await _show(query, "Owner access is required.", home_markup(ctx, user_id))
        return await _show(query, "Owner Dashboard\n\n" + owner_card(cfg), grid_markup(ctx,[
            [("🔒 Audit","audit"),("🗃 Archive","deleted")],
            [("👥 Access","roles"),("⚙️ Settings","settings")],
            [("📈 Reports","reports"),("🩺 Health","health")],
            [("💾 Export","export_help"),("♻️ Restore","restore_help")],
        ]))
    if action == "register":
        db.register_creator(user_id, update.effective_user.username, update.effective_user.full_name)
        return await _show(query, "You’re registered! 💛\n\nYour profile is waiting for a quick community review. We’ll update your dashboard when it’s ready.", menu_markup(ctx, [], "creator"))
    if action in {"available", "unavailable"}:
        if not db.set_availability(user_id, action, user_id, "creator self-service"):
            text = "Please register before updating availability."
        else:
            text = f"You’re now marked {action}."
        return await _show(query, text, menu_markup(ctx, [], "creator"))
    if action in {"vacation_help", "sick_help"}:
        command = "vacation_request" if action.startswith("vacation") else "sick_request"
        return await _show(query, f"Send /{command} YYYY-MM-DD YYYY-MM-DD followed by an optional note. You will confirm before submission.", menu_markup(ctx, [], "creator"))
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
        lines = ["My Timeline"] + [f"{r['occurred_at']}\n{r['action'].replace('_', ' ').title()}" for r in rows]
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
        return await _show(query, "Send /contact_admin followed by your message. Do not include sensitive medical information.", menu_markup(ctx, [], "creator" if action == "contact" else "home"))
    if action == "resources":
        return await _show(query, "Resources", menu_markup(ctx, [(title, f"resource_{key}") for key, (title, _) in RESOURCE_DEFAULTS.items()]))
    if action.startswith("resource_"):
        key = action.removeprefix("resource_")
        title, body = RESOURCE_DEFAULTS.get(key, ("Resource", "Resource not found."))
        return await _show(query, f"{title}\n\n{body}", menu_markup(ctx, [], "resources"))
    if action == "audit":
        if role is not Role.OWNER:
            return await _show(query, "The complete audit log and administrator identities are owner-only.", menu_markup(ctx, [], "admin"))
        rows = db.history(20)
        text = "Full Audit Log\n" + ("\n".join(f"#{r['id']} {r['occurred_at']} actor={r['actor_id']} {r['action']}" for r in rows) or "No events.")
        return await _show(query, text[:3900], menu_markup(ctx, [], "owner"))
    if action == "deleted":
        if role is not Role.OWNER:
            return await _show(query, "Deleted records are owner-only.", home_markup(ctx, user_id))
        rows = db.deleted_records()
        text = "Deleted creator records\n" + ("\n".join(f"{r['telegram_id']} {r['display_name']} — {r['deleted_at']}" for r in rows) or "None.")
        return await _show(query, text, menu_markup(ctx, [], "owner"))
    if action == "registration_queue" and has_permission(user_id,cfg,"review_registrations"):
        rows = [r for r in db.list_creators() if r["status"] == "pending"]
        text = "Registration Reviews\n\n" + ("\n\n".join(f"{r['display_name']} · {r['telegram_id']}\nApprove: /creator_approve {r['telegram_id']}" for r in rows[:10]) or "All caught up! No registrations are waiting. ✨")
        return await _show(query,text[:3900],menu_markup(ctx,[],"admin"))
    if action in {"vacation_queue","sick_queue"}:
        absence_type = "vacation" if action == "vacation_queue" else "sick"
        permission = "review_vacations" if absence_type == "vacation" else "review_sick_days"
        if not has_permission(user_id,cfg,permission):
            return await _show(query,"This review area isn’t included in your access.",menu_markup(ctx,[],"admin"))
        rows = db.list_absence_requests("pending",absence_type)
        text = f"{absence_type.title()} Away Notices\n\n" + ("\n\n".join(f"#{r['id']} · {r['display_name']}\n{r['start_date']} → {r['end_date']}\nReview: /absence_queue {absence_type}" for r in rows[:10]) or "All caught up! No Away Notices are waiting. ✨")
        return await _show(query,text[:3900],menu_markup(ctx,[],"admin"))
    if action == "pop_queue" and has_permission(user_id,cfg,"review_pop"):
        key = _week_key(datetime.now(cfg.timezone))
        rows = db.pop_report(key)
        pending = [r for r in rows if r["status"] == "pending"]
        missing = [r for r in rows if not r["status"]]
        lines = [f"Thursday POP · {key}",f"Waiting for review · {len(pending)}",f"Not submitted · {len(missing)}"]
        lines += [f"\n{r['display_name']} · Submission #{r['id']}\nReview with /pop_approve, /pop_reject, or /pop_resubmit" for r in pending[:8]]
        if not pending: lines.append("\nNo POP reviews are waiting. ✨")
        return await _show(query,"\n".join(lines)[:3900],menu_markup(ctx,[],"admin"))
    if action == "creator_report" and has_permission(user_id,cfg,"view_creator_reports"):
        rows = db.list_creators()
        lines = ["Creator Directory"] + [f"{r['display_name']} · {r['availability'].title()}\nParticipation: {r['status'].title()} · ID {r['telegram_id']}" for r in rows[:15]]
        if not rows: lines.append("No creator profiles yet.")
        lines.append("\nSearch: /creator_search name or Telegram ID")
        return await _show(query,"\n\n".join(lines)[:3900],menu_markup(ctx,[],"admin"))
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
        text = "Message Templates\n\n" + "\n".join(f"• {r['title']} · {r['template_key']}" for r in rows) + "\n\nPreview: /template_preview KEY TELEGRAM_ID"
        return await _show(query,text[:3900],menu_markup(ctx,[],"admin"))
    if action == "health" and role is Role.OWNER:
        return await _show(query,"System Health\n\n🟢 Database ready\n🟢 Handler routing ready\n🟢 Scheduled checks configured\n🔒 Secrets are never displayed",menu_markup(ctx,[],"owner"))
    if action == "settings" and role is Role.OWNER:
        return await _show(query,"System Settings\n\nParticipation reminder · 48 hours\nParticipation alert · 72 hours\nTime zone · America/New_York\n\nUse /settings for configured routing IDs.",menu_markup(ctx,[],"owner"))
    if action == "roles" and role is Role.OWNER:
        return await _show(query,f"Access Overview\n\nOwners · {len(cfg.owner_user_ids)}\nLead admins · {len(cfg.lead_admin_user_ids)}\nAdmins · {len(cfg.admin_user_ids)}\n\nUse /role_set or /permission_set for changes.",menu_markup(ctx,[],"owner"))
    permission_actions = {
        "registration_queue":"review_registrations", "vacation_queue":"review_vacations",
        "sick_queue":"review_sick_days", "pop_queue":"review_pop",
        "creator_report":"view_creator_reports", "search_help":"view_creator_reports",
        "warnings_help":"adjust_warnings", "templates_help":"send_announcements",
        "announce_help":"send_announcements",
    }
    if action in permission_actions and not has_permission(user_id,cfg,permission_actions[action]):
        return await _show(query,"This tool isn’t included in your access.",menu_markup(ctx,[],"admin"))
    if action in {"roles","settings","export_help","restore_help","health"} and role is not Role.OWNER:
        return await _show(query,"This tool is available only in the Owner dashboard.",home_markup(ctx,user_id))
    if action in {"reports", "creator_report", "calendar", "registration_queue", "vacation_queue", "sick_queue", "pop_queue", "search_help", "warnings_help", "templates_help", "announce_help", "roles", "settings", "export_help", "restore_help", "health"}:
        if action not in {"reports", "calendar"} and role < Role.ADMIN:
            return await _show(query, "Administrator access is required.", home_markup(ctx, user_id))
        descriptions = {
            "reports": "Use the dashboard report buttons or /creator_report and /pop_report.",
            "creator_report": "Use /creator_report for the current operational creator report.",
            "calendar": "Use /absence_calendar for Today, This Week, Next 30 Days, Away Now, and Upcoming Absences.",
            "registration_queue": "Use /registration_queue to review pending registrations.",
            "vacation_queue": "Use /absence_queue vacation to review vacation requests.",
            "sick_queue": "Use /absence_queue sick to review sick-day requests.",
            "pop_queue": "Use /pop_report to review pending POP submissions.",
            "search_help": "Use /creator_search TELEGRAM_ID or username.",
            "warnings_help": "Use /warning_add TELEGRAM_ID warning|strike reason. Creators acknowledge with /warning_ack WARNING_ID. Authorized admins may use /warning_remove WARNING_ID reason.",
            "templates_help": "Use /template_list, then /template_preview TEMPLATE_KEY TELEGRAM_ID [reason]. Broadcast to an audience with /announce AUDIENCE message. Every message is previewed before delivery.",
            "announce_help": "Use /announce AUDIENCE message to preview an authorized announcement.",
            "roles": "Owner-protected role assignments come from secure environment configuration.",
            "settings": "Use /settings. Sensitive history remains in the owner audit log.",
            "export_help": "Use /export_records. Full exports are owner-only and audited.",
            "restore_help": "Use /creator_restore TELEGRAM_ID reason. Restoration is owner-only and audited.",
            "health": "Use /system_health. Security and system health are owner-only.",
        }
        back = "owner" if role is Role.OWNER and action in {"roles","settings","export_help","restore_help","health"} else "admin"
        return await _show(query, descriptions[action], menu_markup(ctx, [], back))
    return await _show(query, "Unknown or unavailable action.", home_markup(ctx, user_id))


def register_navigation(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback, pattern=r"^op:"))
