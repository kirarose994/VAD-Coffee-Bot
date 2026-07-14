"""Role-aware, nonce-protected application navigation."""

import secrets
from datetime import datetime

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


def home_markup(ctx, user_id):
    nonce = _nonce(ctx)
    cfg = ctx.bot_data["config"]
    role = role_for(user_id, cfg)
    rows = [[_button("👤 Creator", nonce, "creator")]]
    if role >= Role.ADMIN:
        rows.append([_button("👑 Admin", nonce, "admin")])
    if role is Role.OWNER:
        rows.append([_button("🔐 Owner", nonce, "owner")])
    rows.extend([
        [_button("📊 Reports", nonce, "reports"), _button("📅 Calendar", nonce, "calendar")],
        [_button("📖 Resources", nonce, "resources"), _button("🆘 Support", nonce, "support")],
        [_button("❌ Cancel", nonce, "cancel")],
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
        f"Participation: {participation}\n"
        f"POP this week: {pop.replace('_', ' ').title()}\n"
        f"Standing: {_standing(warning)}\n"
        f"Away Notice: {away}\n"
        f"Availability: {creator['availability'].title()}"
    )


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    text = (
        f"Welcome to VAD Operations, {update.effective_user.first_name}! 💛\n\n"
        "This bot is here to help you stay informed, submit what you need, and keep "
        "community participation tracking consistent and fair.\n\n"
        "Away Notices are simply a way to tell the team when you need time away. An approved "
        "notice pauses participation and POP expectations for the covered dates—no private "
        "medical details are needed.\n\nChoose an area below."
    )
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
        return await _show(query, "VAD Operations Bot\n\nHere to help keep your VAD participation clear, supported, and fair. 💛", home_markup(ctx, user_id))
    if action == "cancel":
        ctx.user_data.clear()
        return await _show(query, "Action cancelled.", home_markup(ctx, user_id))
    if action == "creator":
        return await _show(query, "Creator Dashboard\n\n" + creator_card(user_id, cfg), menu_markup(ctx, [
            ("📝 Register", "register"), ("🟢 Mark Available", "available"),
            ("🔴 Mark Unavailable", "unavailable"), ("🌴 Vacation Away Notice", "vacation_help"),
            ("🤒 Sick-Day Away Notice", "sick_help"), ("📸 Submit Thursday POP", "pop_help"),
            ("📈 My Activity", "my_activity"), ("⚠️ My Status", "my_status"),
            ("💛 My Warnings", "my_warnings"), ("📜 My Timeline", "timeline_0"),
            ("💬 Contact Admin", "contact"),
        ]))
    if action == "admin":
        if role < Role.ADMIN:
            return await _show(query, "Admin access is required.", home_markup(ctx, user_id))
        actions = [
            ("✅ Pending Approvals", "registration_queue"), ("📝 Registration Queue", "registration_queue"),
            ("🌴 Vacation Requests", "vacation_queue"), ("🤒 Sick-Day Requests", "sick_queue"),
            ("📸 POP Review Queue", "pop_queue"), ("⚠️ Inactivity Alerts", "reports"),
            ("👥 Creator Management", "creator_report"), ("🔎 Creator Search", "search_help"),
            ("📊 Creator Reports", "creator_report"), ("📅 Absence Calendar", "calendar"),
            ("💛 Warnings & Strikes", "warnings_help"), ("💬 Message Templates", "templates_help"),
            ("📨 Announcements", "announce_help"), ("📜 Recent Admin Actions", "audit"),
        ]
        return await _show(query, "Admin Dashboard", menu_markup(ctx, actions))
    if action == "owner":
        if role is not Role.OWNER:
            return await _show(query, "Owner access is required.", home_markup(ctx, user_id))
        return await _show(query, "Owner Dashboard", menu_markup(ctx, [
            ("🔒 Full Audit Log", "audit"), ("🗑 Deleted and Archived Records", "deleted"),
            ("👥 Roles and Permissions", "roles"), ("🧑‍⚖️ Admin Action History", "audit"),
            ("📝 Registration History", "audit"), ("🌴 Vacation History", "audit"),
            ("🤒 Sick-Day History", "audit"), ("📸 POP History", "audit"),
            ("⚠️ Warning History", "audit"), ("📈 Analytics", "reports"),
            ("⚙️ System Settings", "settings"), ("💾 Export and Backup", "export_help"),
            ("♻️ Restore Records", "restore_help"), ("🩺 System Health", "health"),
        ]))
    if action == "register":
        db.register_creator(user_id, update.effective_user.username, update.effective_user.full_name)
        return await _show(query, "Registration submitted for administrator review.", menu_markup(ctx, [], "creator"))
    if action in {"available", "unavailable"}:
        if not db.set_availability(user_id, action, user_id, "creator self-service"):
            text = "Register first before changing availability."
        else:
            text = f"Availability changed to {action}."
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
            "templates_help": "Use /template_list, then /template_preview TEMPLATE_KEY TELEGRAM_ID [reason]. Every message is previewed and confirmed before delivery.",
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
