"""Operational workflows for absences, notes, announcements, and owner tools."""

import io
import json
import secrets
import time
from datetime import date, datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import database as db
from permissions import Role, has_permission, role_for
from runtime_config import persist_setting
from routing import send_routed


def _clean(text, limit=1000):
    return " ".join((text or "").replace("<", "").replace(">", "").split())[:limit]


def _render_template(body, name, reason=""):
    return body.replace("{name}",name).replace("{reason}",reason)


def _token(ctx, key):
    token = secrets.token_urlsafe(8)
    ctx.user_data[key] = token
    return token


async def absence_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE, absence_type, category=None):
    creator = db.get_creator(update.effective_user.id)
    if not creator or creator["status"] != "active":
        return await update.effective_message.reply_text("Away Notices become available once your creator profile is approved. 💛")
    if len(ctx.args) < 2:
        return await update.effective_message.reply_text(f"Send /{absence_type}_request START_DATE END_DATE [optional note]\nExample: /{absence_type}_request 2026-08-01 2026-08-03 Family plans")
    try:
        start, end = date.fromisoformat(ctx.args[0]), date.fromisoformat(ctx.args[1])
        if end < start or (end - start).days > 366:
            raise ValueError
    except ValueError:
        return await update.effective_message.reply_text("Those dates don’t look quite right. Use YYYY-MM-DD, with the end date on or after the start date.")
    note = _clean(" ".join(ctx.args[2:]))
    token = _token(ctx, "absence_nonce")
    category = category or ("vacation_trip" if absence_type == "vacation" else "not_feeling_well")
    labels = {"vacation_trip":"🌴 Vacation or trip","not_feeling_well":"🤒 Not feeling well",
              "personal_day":"🧠 Mental health or personal day","emergency":"🚨 Emergency","other":"💙 Other time away"}
    ctx.user_data["absence_draft"] = {"type": absence_type, "category":category, "start": start.isoformat(), "end": end.isoformat(), "note": note}
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data=f"absence:{token}:confirm"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"absence:{token}:cancel"),
    ]])
    await update.effective_message.reply_text(
        f"Confirm Away Notice\n\n{labels.get(category,'💙 Time away')}\nDates · {start} → {end}\nNote · {note or 'No note'}",
        reply_markup=keyboard,
    )


async def vacation_request(update, ctx): return await absence_request(update, ctx, "vacation")
async def sick_request(update, ctx): return await absence_request(update, ctx, "sick")
async def personal_day_request(update, ctx): return await absence_request(update, ctx, "sick", "personal_day")
async def emergency_away_request(update, ctx): return await absence_request(update, ctx, "sick", "emergency")
async def other_away_request(update, ctx): return await absence_request(update, ctx, "vacation", "other")


async def absence_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[1] != ctx.user_data.pop("absence_nonce", None):
        await query.answer("This confirmation expired or was already used.", show_alert=True)
        return await query.edit_message_text("This confirmation expired. Nothing was submitted. Use /start to return home.")
    draft = ctx.user_data.pop("absence_draft", None)
    if parts[2] != "confirm" or not draft:
        await query.answer()
        return await query.edit_message_text("Away Notice cancelled. Nothing was submitted.")
    request_id = db.create_absence_request(update.effective_user.id, draft["type"], draft["start"], draft["end"], draft["note"], category=draft["category"])
    await query.answer("Submitted")
    await query.edit_message_text(f"Away Notice #{request_id} sent for review. 💛\n\nYou’ll receive an update here when it’s reviewed. Use /start to return home.")
    cfg = ctx.bot_data["config"]
    await send_routed(ctx.bot,cfg,"away_notice",
        f"💙 Away Notice awaiting review\nCreator: {update.effective_user.full_name}\n"
        f"Dates: {draft['start']} to {draft['end']}\nCategory: {draft['category'].replace('_',' ').title()}\n"
        f"Note: {draft['note'] or 'None'}\nOpen Admin Home → Away Notices.",
        target_telegram_id=update.effective_user.id,related_request_id=request_id)


async def absence_queue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id, cfg = update.effective_user.id, ctx.bot_data["config"]
    requested_type = ctx.args[0] if ctx.args and ctx.args[0] in {"vacation", "sick"} else None
    permission = "review_sick_days" if requested_type == "sick" else "review_vacations"
    if not has_permission(user_id, cfg, permission):
        return await update.effective_message.reply_text("You do not have permission to review these requests.")
    rows = db.list_absence_requests("pending", requested_type)
    if not rows:
        return await update.effective_message.reply_text("All caught up! No Away Notices are waiting. ✨")
    for row in rows[:20]:
        token = _token(ctx, f"review_nonce_{row['id']}")
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Record as excused", callback_data=f"review:{token}:{row['id']}:approved"),
            InlineKeyboardButton("🚫 Mark invalid", callback_data=f"review:{token}:{row['id']}:denied"),
        ],[
            InlineKeyboardButton("💬 Ask for clarification", callback_data=f"review:{token}:{row['id']}:clarification"),
        ]])
        await update.effective_message.reply_text(
            f"#{row['id']} {row['display_name']} — {row['absence_type']}\n{row['start_date']} to {row['end_date']}\nNote: {row['note'] or 'none'}\nSubmitted: {row['submitted_at']}",
            reply_markup=buttons)


async def review_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = (query.data or "").split(":")
    if len(parts) != 4:
        return await query.answer("Invalid action.", show_alert=True)
    _, token, raw_id, decision = parts
    try: request_id = int(raw_id)
    except ValueError: return await query.answer("Invalid request.", show_alert=True)
    if token != ctx.user_data.pop(f"review_nonce_{request_id}", None):
        await query.answer("This review button expired or was already used.", show_alert=True)
        return await query.edit_message_text("Review not recorded. Refresh the queue.")
    cfg, user_id = ctx.bot_data["config"], update.effective_user.id
    if not (has_permission(user_id, cfg, "review_vacations") or has_permission(user_id, cfg, "review_sick_days")):
        return await query.answer("You are not authorized.", show_alert=True)
    confirm = _token(ctx, "review_confirm_nonce")
    ctx.user_data["review_draft"] = (request_id, decision)
    await query.answer()
    await query.edit_message_text(f"Confirm {decision} for request #{request_id}?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Record Decision", callback_data=f"reviewconfirm:{confirm}:yes"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"reviewconfirm:{confirm}:no"),
        ]]))


async def review_confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[1] != ctx.user_data.pop("review_confirm_nonce", None):
        await query.answer("This confirmation expired or was already used.", show_alert=True)
        return await query.edit_message_text("This review expired. No decision was saved; refresh the queue and try again.")
    draft = ctx.user_data.pop("review_draft", None)
    if parts[2] != "yes" or not draft:
        await query.answer()
        return await query.edit_message_text("Review cancelled.")
    request_id, decision = draft
    request_row = db.get_absence_request(request_id)
    if not db.review_absence(request_id, decision, update.effective_user.id):
        await query.answer("Already reviewed or unavailable.", show_alert=True)
        return await query.edit_message_text("No change was recorded.")
    await query.answer("Recorded")
    friendly = {"approved":"approved","denied":"not approved","clarification":"waiting for clarification"}[decision]
    await query.edit_message_text(f"Away Notice #{request_id} is now {friendly}. The update was saved to its history.")
    if request_row:
        try:
            await ctx.bot.send_message(request_row["telegram_id"],
                f"Your {request_row['absence_type']} request #{request_id} was {decision}.")
        except Exception:
            pass


async def absence_calendar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if role_for(update.effective_user.id, ctx.bot_data["config"]) < Role.ADMIN:
        return await update.effective_message.reply_text("The operational calendar is for administrators.")
    today = datetime.now(ctx.bot_data["config"].timezone).date()
    view = (ctx.args[0].casefold() if ctx.args else "week")
    days = 0 if view == "today" else 30 if view in {"30", "month"} else 7
    rows = db.calendar_absences(today.isoformat(), (today + timedelta(days=days)).isoformat())
    lines = [f"Absence calendar: {view}"] + [f"{r['start_date']}–{r['end_date']} {r['display_name']} ({r['absence_type']})" for r in rows]
    await update.effective_message.reply_text("\n".join(lines)[:3900])


async def add_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not has_permission(update.effective_user.id, ctx.bot_data["config"], "add_admin_notes"):
        return await update.effective_message.reply_text("Private notes aren’t included in your access.")
    if len(ctx.args) < 2:
        return await update.effective_message.reply_text("Usage: /admin_note TELEGRAM_ID note")
    try: target = int(ctx.args[0])
    except ValueError: return await update.effective_message.reply_text("Telegram ID must be numeric.")
    note = _clean(" ".join(ctx.args[1:]), 2000)
    note_id = db.add_admin_note(target, note, update.effective_user.id)
    await update.effective_message.reply_text(f"Private note #{note_id} saved to the creator timeline.")


async def view_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not has_permission(update.effective_user.id, ctx.bot_data["config"], "add_admin_notes"):
        return await update.effective_message.reply_text("You do not have permission to view private admin notes.")
    if len(ctx.args) != 1:
        return await update.effective_message.reply_text("Usage: /admin_notes TELEGRAM_ID")
    try: target = int(ctx.args[0])
    except ValueError: return await update.effective_message.reply_text("Telegram ID must be numeric.")
    rows = db.list_admin_notes(target)
    lines = [f"Private notes for {target}"] + [f"#{r['id']} {r['created_at']}: {r['note']}" for r in rows]
    await update.effective_message.reply_text(("\n".join(lines) if rows else "No private admin notes.")[:3900])


async def restore_creator(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if role_for(update.effective_user.id, ctx.bot_data["config"]) is not Role.OWNER:
        return await update.effective_message.reply_text("Restore tools are owner-only.")
    if len(ctx.args) < 2:
        return await update.effective_message.reply_text("Usage: /creator_restore TELEGRAM_ID reason")
    try: target = int(ctx.args[0])
    except ValueError: return await update.effective_message.reply_text("Telegram ID must be numeric.")
    if not db.restore_creator(target, update.effective_user.id, _clean(" ".join(ctx.args[1:]))):
        return await update.effective_message.reply_text("Deleted creator record not found.")
    await update.effective_message.reply_text("Creator record restored and audited.")


async def system_health(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if role_for(update.effective_user.id, ctx.bot_data["config"]) is not Role.OWNER:
        return await update.effective_message.reply_text("System health is owner-only.")
    await update.effective_message.reply_text("System health: database reachable; polling process active; no secrets displayed.")


async def registration_queue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not has_permission(update.effective_user.id, ctx.bot_data["config"], "review_registrations"):
        return await update.effective_message.reply_text("You do not have permission to review registrations.")
    rows = [r for r in db.list_creators() if r["status"] == "pending"]
    lines = ["Registration queue"] + [f"{r['display_name']} @{r['username'] or '-'} — {r['telegram_id']}" for r in rows]
    await update.effective_message.reply_text("\n".join(lines) if rows else "No pending registrations.")


async def creator_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not has_permission(update.effective_user.id, ctx.bot_data["config"], "view_creator_reports"):
        return await update.effective_message.reply_text("You do not have permission to search creator records.")
    if not ctx.args:
        return await update.effective_message.reply_text("Usage: /creator_search TELEGRAM_ID or username")
    needle = ctx.args[0].lstrip("@").casefold()
    rows = [r for r in db.list_creators() if str(r["telegram_id"]) == needle or (r["username"] or "").casefold() == needle]
    if not rows:
        return await update.effective_message.reply_text("Creator not found.")
    r = rows[0]
    summary = db.warning_summary(r["telegram_id"])
    token = _token(ctx, f"timeline_nonce_{r['telegram_id']}")
    await update.effective_message.reply_text(
        f"{r['display_name']} ({r['telegram_id']})\nRegistration: {r['status']}\nAvailability: {r['availability']}\n"
        f"Warnings: {summary['warnings']} | Strikes: {summary['strikes']}\nLast meaningful: {r['last_meaningful_at'] or 'none'}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📜 Creator Timeline", callback_data=f"timeline:{token}:{r['telegram_id']}:0")
        ]]))


async def contact_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now = time.monotonic()
    if now - ctx.user_data.get("last_contact_admin", 0) < 60:
        return await update.effective_message.reply_text("Please wait before sending another support message.")
    body = _clean(" ".join(ctx.args), 1500)
    if not body:
        return await update.effective_message.reply_text("Usage: /contact_admin message")
    cfg = ctx.bot_data["config"]
    if not cfg.admin_chat_id:
        return await update.effective_message.reply_text("Admin messaging is not configured. Please try again later.")
    ctx.user_data["last_contact_admin"] = now
    try:
        await send_routed(ctx.bot,cfg,"support",
            f"📨 Support request\nCreator: {update.effective_user.full_name}\nTelegram ID: {update.effective_user.id}\n\n{body}",
            target_telegram_id=update.effective_user.id)
        await update.effective_message.reply_text("Your message was sent to the admin team.")
    except Exception:
        await update.effective_message.reply_text("The message could not be delivered. Please try again later.")


async def guided_contact_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    guided = ctx.user_data.get("guided_input")
    if guided == "support_reply":
        cfg,actor=ctx.bot_data["config"],update.effective_user.id
        if not has_permission(actor,cfg,"manage_support"):
            ctx.user_data.clear();return await update.effective_message.reply_text("Support access is required.")
        request_id=ctx.user_data.pop("support_reply_id",None);ctx.user_data.pop("guided_input",None)
        body=_clean(update.effective_message.text,1500)
        saved=db.add_support_message(request_id,actor,role_for(actor,cfg).name.lower(),body) if request_id and body else None
        if not saved:return await update.effective_message.reply_text("That support request is unavailable. No reply was saved.")
        message_id,target=saved
        try:
            await ctx.bot.send_message(target,f"💬 Admin reply to support request #{request_id}\n\n{body}")
            db.record_audit(actor,"support_reply_delivered","support_message",message_id,target,related_request_id=request_id)
            return await update.effective_message.reply_text("✅ Reply recorded and delivered.")
        except Exception:
            ref="SUP-"+secrets.token_hex(4).upper()
            db.record_delivery_failure(ref,"support_reply",target,None,f"Support reply #{message_id}")
            return await update.effective_message.reply_text(f"The reply was saved, but delivery needs attention. Reference: {ref}")
    if guided == "admin_note":
        cfg,actor=ctx.bot_data["config"],update.effective_user.id
        if not has_permission(actor,cfg,"add_admin_notes"):
            ctx.user_data.pop("guided_input",None);return await update.effective_message.reply_text("Private notes aren’t included in your access.")
        target=ctx.user_data.pop("admin_note_target",None);note=_clean(update.effective_message.text,2000);ctx.user_data.pop("guided_input",None)
        if not target or not note: return await update.effective_message.reply_text("No note was saved.")
        note_id=db.add_admin_note(target,note,actor)
        return await update.effective_message.reply_text(f"✅ Private note #{note_id} saved and audited.")
    if guided == "away_dates":
        parts=update.effective_message.text.split()
        if len(parts)<2: return await update.effective_message.reply_text("Please enter a start date and end date in YYYY-MM-DD format.")
        try:
            start,end=date.fromisoformat(parts[0]),date.fromisoformat(parts[1])
            if end<start or (end-start).days>366: raise ValueError
        except ValueError: return await update.effective_message.reply_text("Those dates don’t look right. Use YYYY-MM-DD YYYY-MM-DD, with the end on or after the start.")
        category=ctx.user_data.pop("away_category","other");ctx.user_data.pop("guided_input",None)
        absence_type="vacation" if category in {"vacation_trip","other"} else "sick"
        note=_clean(" ".join(parts[2:]));token=_token(ctx,"absence_nonce")
        ctx.user_data["absence_draft"]={"type":absence_type,"category":category,"start":start.isoformat(),"end":end.isoformat(),"note":note}
        labels={"vacation_trip":"🌴 Vacation or trip","not_feeling_well":"🤒 Not feeling well","personal_day":"🧠 Mental health or personal day","emergency":"🚨 Emergency","other":"💙 Other time away"}
        return await update.effective_message.reply_text(f"Confirm Away Notice\n\n{labels[category]}\nDates: {start} → {end}\nNote: {note or 'No note'}",reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirm",callback_data=f"absence:{token}:confirm"),InlineKeyboardButton("❌ Cancel",callback_data=f"absence:{token}:cancel")]]))
    if guided == "template_custom":
        cfg,actor=ctx.bot_data["config"],update.effective_user.id
        if not has_permission(actor,cfg,"send_announcements"):
            ctx.user_data.pop("guided_input",None)
            return await update.effective_message.reply_text("Messaging isn’t included in your access.")
        body=_clean(update.effective_message.text,3500)
        if not body: return await update.effective_message.reply_text("Please write a message first.")
        ctx.user_data.pop("guided_input",None);ctx.user_data["custom_template_body"]=body
        nonce=secrets.token_urlsafe(6);ctx.user_data["menu_nonce"]=nonce
        rows=list(db.list_creators())
        buttons=[[InlineKeyboardButton(r["display_name"][:40],callback_data=f"op:{nonce}:template_custom_member_{r['telegram_id']}")] for r in rows[:20]]
        buttons.append([InlineKeyboardButton("❌ Cancel",callback_data=f"op:{nonce}:templates_help")])
        return await update.effective_message.reply_text("Choose a recipient.",reply_markup=InlineKeyboardMarkup(buttons))
    if guided == "warning_reason":
        cfg,actor=ctx.bot_data["config"],update.effective_user.id
        if not has_permission(actor,cfg,"adjust_warnings"):
            ctx.user_data.pop("guided_input",None)
            return await update.effective_message.reply_text("Standing management isn’t included in your access.")
        draft=ctx.user_data.get("warning_draft"); reason=_clean(update.effective_message.text,1000)
        if not draft or not reason: return await update.effective_message.reply_text("Please provide a short reason.")
        draft["reason"]=reason; ctx.user_data.pop("guided_input",None)
        creator,template=db.get_creator(draft["target"]),db.message_template(draft["type"])
        body=_render_template(template["body"],creator["display_name"],reason)
        nonce=secrets.token_urlsafe(6); ctx.user_data["menu_nonce"]=nonce
        return await update.effective_message.reply_text(f"⚠️ Preview\n\nType: {draft['type'].title()}\nReason: {reason}\n\n{body}",reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm, Record & Send",callback_data=f"op:{nonce}:warning_send")],
            [InlineKeyboardButton("❌ Cancel",callback_data=f"op:{nonce}:warnings_help")],
        ]))
    if guided == "access_add":
        cfg, actor = ctx.bot_data["config"], update.effective_user.id
        if role_for(actor,cfg) is not Role.OWNER:
            ctx.user_data.pop("guided_input",None)
            return await update.effective_message.reply_text("Access management is owner-only.")
        try: target = int(update.effective_message.text.strip())
        except ValueError: return await update.effective_message.reply_text("Please enter the numeric Telegram ID only.")
        ctx.user_data.pop("guided_input",None)
        nonce=secrets.token_urlsafe(6); ctx.user_data["menu_nonce"]=nonce
        return await update.effective_message.reply_text("Choose the role to confirm.",reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Admin",callback_data=f"op:{nonce}:access_confirm_admin_{target}")],
            [InlineKeyboardButton("🛡️ Lead Admin",callback_data=f"op:{nonce}:access_confirm_lead_{target}")],
            [InlineKeyboardButton("👑 Owner",callback_data=f"op:{nonce}:access_confirm_owner_{target}")],
            [InlineKeyboardButton("❌ Cancel",callback_data=f"op:{nonce}:roles")],
        ]))
    if guided in {"creator_search_name","creator_search_id"}:
        cfg, actor = ctx.bot_data["config"], update.effective_user.id
        if not has_permission(actor,cfg,"view_creator_reports"):
            ctx.user_data.pop("guided_input",None)
            return await update.effective_message.reply_text("Creator search isn’t included in your access.")
        needle = _clean(update.effective_message.text,100).lstrip("@").casefold()
        rows = list(db.list_creators())
        if guided.endswith("id"):
            rows = [r for r in rows if str(r["telegram_id"]) == needle]
        else:
            rows = [r for r in rows if needle in r["display_name"].casefold() or needle in (r["username"] or "").casefold()]
        ctx.user_data.pop("guided_input",None)
        nonce = secrets.token_urlsafe(6)
        ctx.user_data["menu_nonce"] = nonce
        buttons = [[InlineKeyboardButton(r["display_name"][:40],callback_data=f"op:{nonce}:creator_select_{r['telegram_id']}")] for r in rows[:20]]
        buttons.append([InlineKeyboardButton("🏠 Home",callback_data=f"op:{nonce}:home"),InlineKeyboardButton("◀️ Back",callback_data=f"op:{nonce}:creator_report")])
        return await update.effective_message.reply_text(
            f"🔎 Search Results\n\nSelect a creator below." if rows else "No creator matched that search.",
            reply_markup=InlineKeyboardMarkup(buttons))
    if guided not in {"contact_admin","support_message"}:
        return
    body = _clean(update.effective_message.text,1500)
    if not body:
        return await update.effective_message.reply_text("Please write a short message, without private medical details.")
    ctx.user_data.pop("guided_input",None)
    token = _token(ctx,"contact_nonce")
    ctx.user_data["contact_draft"] = {"body":body,"category":ctx.user_data.pop("support_category","General Question")}
    await update.effective_message.reply_text("💬 Message Preview\n\n" + body,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Send to Admin",callback_data=f"contactflow:{token}:send"),
            InlineKeyboardButton("❌ Cancel",callback_data=f"contactflow:{token}:cancel"),
        ]]))


async def guided_contact_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[1] != ctx.user_data.pop("contact_nonce",None):
        return await query.answer("This message preview expired.",show_alert=True)
    draft = ctx.user_data.pop("contact_draft",None)
    if parts[2] != "send" or not draft:
        await query.answer()
        return await query.edit_message_text("Message cancelled. Nothing was sent.")
    cfg = ctx.bot_data["config"]
    body,category=draft["body"],draft["category"]
    request_id=db.create_support_request(update.effective_user.id,category,body)
    if request_id is None:
        await query.answer()
        return await query.edit_message_text("Please register as a creator before opening a tracked support request.")
    delivered,error_ref=await send_routed(ctx.bot,cfg,"support",
        f"💬 Support Request #{request_id}\nCreator: {update.effective_user.full_name}\nUsername: "+
        (f"@{update.effective_user.username}" if update.effective_user.username else "No username")+
        f"\nTelegram ID: {update.effective_user.id}\nCategory: {category}\n\n{body}",
        payload_summary=f"Support request #{request_id}",target_telegram_id=update.effective_user.id,
        related_request_id=request_id)
    db.update_support_delivery(request_id,"delivered" if delivered else "failed",error_ref)
    text = (f"✅ Support request #{request_id} was received by the admin team." if delivered else
        f"Your request #{request_id} was saved, but delivery needs attention. Reference: {error_ref}")
    await query.answer()
    await query.edit_message_text(text)


async def announce(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cfg, user_id = ctx.bot_data["config"], update.effective_user.id
    if not has_permission(user_id, cfg, "send_announcements"):
        return await update.effective_message.reply_text("Community messages aren’t included in your access.")
    if len(ctx.args) < 2 or ctx.args[0] not in {"all", "available", "away", "admins", "owners"}:
        return await update.effective_message.reply_text("Usage: /announce all|available|away|admins|owners message")
    audience, body = ctx.args[0], _clean(" ".join(ctx.args[1:]), 3500)
    announcement_id = db.create_announcement(audience, body, user_id)
    token = _token(ctx, "announcement_nonce")
    ctx.user_data["announcement_id"] = announcement_id
    await update.effective_message.reply_text(f"Message Preview\nAudience · {audience.title()}\n\n{body}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Send", callback_data=f"announce:{token}:send"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"announce:{token}:cancel"),
        ]]))


async def announcement_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[1] != ctx.user_data.pop("announcement_nonce", None):
        await query.answer("This preview expired or was already used.", show_alert=True)
        return await query.edit_message_text("Announcement not sent.")
    announcement_id = ctx.user_data.pop("announcement_id", None)
    if parts[2] != "send" or not announcement_id:
        await query.answer()
        return await query.edit_message_text("Announcement cancelled.")
    cfg, user_id = ctx.bot_data["config"], update.effective_user.id
    if not has_permission(user_id, cfg, "send_announcements"):
        return await query.answer("You are not authorized.", show_alert=True)
    row = db.announcement(announcement_id)
    recipients = db.announcement_recipients(row["audience"], cfg.owner_user_ids,
        cfg.admin_user_ids | cfg.lead_admin_user_ids)
    delivered = failed = 0
    for recipient in recipients:
        try:
            await ctx.bot.send_message(recipient, f"VAD Announcement\n\n{row['body']}")
            delivered += 1
        except Exception:
            failed += 1
    if not db.mark_announcement_sent(announcement_id, user_id, delivered, failed):
        return await query.answer("Already sent.", show_alert=True)
    await query.answer("Sent")
    await query.edit_message_text(f"Announcement sent. Delivered: {delivered}; failed: {failed}.")


async def export_records(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if role_for(update.effective_user.id, ctx.bot_data["config"]) is not Role.OWNER:
        return await update.effective_message.reply_text("Full record exports are owner-only.")
    data = json.dumps(db.export_snapshot(), indent=2, default=str).encode()
    db.record_audit(update.effective_user.id,"records_exported","system",new_value={"bytes":len(data)})
    await update.effective_message.reply_document(io.BytesIO(data), filename="vad-operations-export.json",
        caption="Owner export created. This action was audited.")


async def role_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cfg, actor = ctx.bot_data["config"], update.effective_user.id
    if role_for(actor, cfg) is not Role.OWNER:
        return await update.effective_message.reply_text("Role management is owner-only.")
    if len(ctx.args) != 2 or ctx.args[1] not in {"admin", "lead", "owner", "none"}:
        return await update.effective_message.reply_text("Usage: /role_set TELEGRAM_ID admin|lead|owner|none")
    try: target = int(ctx.args[0])
    except ValueError: return await update.effective_message.reply_text("Telegram ID must be numeric.")
    previous = role_for(target, cfg).name.lower()
    admins, leads, owners = set(cfg.admin_user_ids), set(cfg.lead_admin_user_ids), set(cfg.owner_user_ids)
    admins.discard(target); leads.discard(target)
    if ctx.args[1] == "none" and target in owners:
        if target == actor:return await update.effective_message.reply_text("You cannot remove your own Owner access.")
        if len(owners)<=1:return await update.effective_message.reply_text("At least one Owner must remain configured.")
        owners.discard(target);admins.add(target)
    if ctx.args[1] == "admin": admins.add(target)
    if ctx.args[1] == "lead": leads.add(target)
    if ctx.args[1] == "owner":owners.add(target)
    cfg.admin_user_ids, cfg.lead_admin_user_ids, cfg.owner_user_ids = frozenset(admins), frozenset(leads), frozenset(owners)
    persist_setting(cfg,"admin_user_ids",cfg.admin_user_ids,actor)
    persist_setting(cfg,"lead_admin_user_ids",cfg.lead_admin_user_ids,actor)
    persist_setting(cfg,"owner_user_ids",cfg.owner_user_ids,actor)
    db.record_audit(actor,"role_changed","admin_role",target,target,previous,ctx.args[1])
    await update.effective_message.reply_text("Additive roles updated, persisted, and audited.")


async def permission_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cfg, actor = ctx.bot_data["config"], update.effective_user.id
    if role_for(actor, cfg) is not Role.OWNER:
        return await update.effective_message.reply_text("Permission management is owner-only.")
    if len(ctx.args) != 3 or ctx.args[2] not in {"on", "off"}:
        return await update.effective_message.reply_text("Usage: /permission_set TELEGRAM_ID PERMISSION on|off")
    try: target = int(ctx.args[0])
    except ValueError: return await update.effective_message.reply_text("Telegram ID must be numeric.")
    if role_for(target, cfg) is Role.OWNER:
        return await update.effective_message.reply_text("Owner permissions cannot be reduced through this command.")
    current = set(cfg.admin_permissions.get(target, frozenset()))
    previous = sorted(current)
    if ctx.args[2] == "on": current.add(ctx.args[1])
    else: current.discard(ctx.args[1])
    cfg.admin_permissions[target] = frozenset(current)
    db.record_audit(actor,"permission_changed","admin_permission",target,target,previous,sorted(current))
    await update.effective_message.reply_text("Permission updated for this running process and audited. Update ADMIN_PERMISSIONS_JSON to persist it.")


async def warning_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cfg, actor = ctx.bot_data["config"], update.effective_user.id
    if not has_permission(actor, cfg, "adjust_warnings"):
        return await update.effective_message.reply_text("You do not have permission to manage warnings.")
    if len(ctx.args) < 3 or ctx.args[1] not in {"warning", "strike"}:
        return await update.effective_message.reply_text("Usage: /warning_add TELEGRAM_ID warning|strike reason")
    try: target = int(ctx.args[0])
    except ValueError: return await update.effective_message.reply_text("Telegram ID must be numeric.")
    reason = _clean(" ".join(ctx.args[2:]), 1000)
    warning_id = db.add_warning(target, ctx.args[1], reason, actor, template_key=ctx.args[1])
    if not warning_id:
        return await update.effective_message.reply_text("Creator not found or warning was invalid.")
    creator = db.get_creator(target)
    template = db.message_template(ctx.args[1])
    try:
        await ctx.bot.send_message(target, _render_template(template["body"],creator["display_name"],reason))
    except Exception:
        db.record_audit(actor,"warning_delivery_failed","creator_warning",warning_id,target,reason="blocked or unavailable",result="error")
    summary = db.warning_summary(target)
    if summary["warnings"] >= 2 or summary["strikes"] >= 3:
        escalation = "🔴 Three strikes — Owner Review Required" if summary["strikes"] >= 3 else "🟠 Second warning requires attention"
        for owner_id in cfg.owner_user_ids:
            try:
                await ctx.bot.send_message(owner_id,f"{escalation}\nMember: {creator['display_name']}\nOpen Owner Dashboard → Needs Attention.")
            except Exception:
                db.record_audit(actor,"owner_escalation_delivery_failed","creator_warning",warning_id,target,result="error")
    await update.effective_message.reply_text(f"{ctx.args[1].title()} #{warning_id} documented and audited.")


async def warning_ack(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) != 1:
        return await update.effective_message.reply_text("Usage: /warning_ack WARNING_ID")
    try: warning_id = int(ctx.args[0])
    except ValueError: return await update.effective_message.reply_text("Warning ID must be numeric.")
    row = db.get_warning(warning_id)
    if not row:
        return await update.effective_message.reply_text("Warning not found.")
    actor, cfg = update.effective_user.id, ctx.bot_data["config"]
    if actor != row["telegram_id"] and not has_permission(actor, cfg, "adjust_warnings"):
        return await update.effective_message.reply_text("You may acknowledge only your own warning.")
    if not db.acknowledge_warning(warning_id, actor):
        return await update.effective_message.reply_text("This warning is no longer awaiting acknowledgment.")
    await update.effective_message.reply_text("Warning acknowledged. Thank you—this is now reflected in your timeline.")


async def warning_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not has_permission(update.effective_user.id, ctx.bot_data["config"], "adjust_warnings"):
        return await update.effective_message.reply_text("You do not have permission to remove warnings.")
    if len(ctx.args) < 2:
        return await update.effective_message.reply_text("Usage: /warning_remove WARNING_ID reason")
    try: warning_id = int(ctx.args[0])
    except ValueError: return await update.effective_message.reply_text("Warning ID must be numeric.")
    if not db.remove_warning(warning_id, update.effective_user.id, _clean(" ".join(ctx.args[1:]))):
        return await update.effective_message.reply_text("Active warning not found.")
    await update.effective_message.reply_text("Warning removed from standing calculations; its audit history remains preserved.")


def _timeline_text(target, page):
    rows = db.creator_timeline(target, 8, page * 8)
    lines = [f"Creator Timeline — {target}"] + [f"{r['occurred_at']}\n{r['action'].replace('_', ' ').title()}" for r in rows]
    return "\n\n".join(lines) if rows else f"Creator Timeline — {target}\n\nNo activity on this page.", len(rows)


async def creator_timeline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    actor, cfg = update.effective_user.id, ctx.bot_data["config"]
    target = actor
    if ctx.args:
        try: target = int(ctx.args[0])
        except ValueError: return await update.effective_message.reply_text("Telegram ID must be numeric.")
    if target != actor and not has_permission(actor, cfg, "view_creator_reports"):
        return await update.effective_message.reply_text("You may view only your own timeline.")
    token = _token(ctx, f"timeline_nonce_{target}")
    text, count = _timeline_text(target, 0)
    buttons = []
    if count == 8: buttons.append(InlineKeyboardButton("Older ➡️", callback_data=f"timeline:{token}:{target}:1"))
    await update.effective_message.reply_text(text[:3900], reply_markup=InlineKeyboardMarkup([buttons]) if buttons else None)


async def timeline_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = (query.data or "").split(":")
    if len(parts) != 4:
        return await query.answer("Invalid timeline action.", show_alert=True)
    _, token, raw_target, raw_page = parts
    try: target, page = int(raw_target), max(0, int(raw_page))
    except ValueError: return await query.answer("Invalid timeline action.", show_alert=True)
    if token != ctx.user_data.get(f"timeline_nonce_{target}"):
        return await query.answer("This timeline button expired.", show_alert=True)
    actor, cfg = update.effective_user.id, ctx.bot_data["config"]
    if target != actor and not has_permission(actor, cfg, "view_creator_reports"):
        return await query.answer("You are not authorized.", show_alert=True)
    await query.answer()
    text, count = _timeline_text(target, page)
    buttons = []
    if page: buttons.append(InlineKeyboardButton("⬅️ Newer", callback_data=f"timeline:{token}:{target}:{page - 1}"))
    if count == 8: buttons.append(InlineKeyboardButton("Older ➡️", callback_data=f"timeline:{token}:{target}:{page + 1}"))
    await query.edit_message_text(text[:3900], reply_markup=InlineKeyboardMarkup([buttons]) if buttons else None)


async def template_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not has_permission(update.effective_user.id, ctx.bot_data["config"], "send_announcements"):
        return await update.effective_message.reply_text("You do not have permission to use message templates.")
    rows = db.message_templates()
    await update.effective_message.reply_text("Message Templates\n" + "\n".join(f"/{r['template_key']} — {r['title']}" for r in rows))


async def template_preview(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not has_permission(update.effective_user.id, ctx.bot_data["config"], "send_announcements"):
        return await update.effective_message.reply_text("You do not have permission to use message templates.")
    if len(ctx.args) < 2:
        return await update.effective_message.reply_text("Usage: /template_preview TEMPLATE_KEY TELEGRAM_ID [reason]")
    template = db.message_template(ctx.args[0])
    try: target = int(ctx.args[1])
    except ValueError: return await update.effective_message.reply_text("Telegram ID must be numeric.")
    creator = db.get_creator(target)
    if not template or not creator:
        return await update.effective_message.reply_text("Template or creator not found.")
    reason = _clean(" ".join(ctx.args[2:])) or "Please contact an admin if you have questions."
    body = _render_template(template["body"],creator["display_name"],reason)
    token = _token(ctx, "template_nonce")
    ctx.user_data["template_draft"] = {"target":target,"key":template["template_key"],"body":body,
        "edited": bool(reason and reason != "Please contact an admin if you have questions.")}
    await update.effective_message.reply_text(f"Template Preview\n\n{body}", reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Send",callback_data=f"template:{token}:send"),
        InlineKeyboardButton("❌ Cancel",callback_data=f"template:{token}:cancel"),
    ]]))


async def template_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[1] != ctx.user_data.pop("template_nonce",None):
        return await query.answer("This template preview expired or was already used.",show_alert=True)
    draft = ctx.user_data.pop("template_draft",None)
    if parts[2] != "send" or not draft:
        await query.answer()
        return await query.edit_message_text("Template message cancelled.")
    if not has_permission(update.effective_user.id,ctx.bot_data["config"],"send_announcements"):
        return await query.answer("You are not authorized.",show_alert=True)
    try:
        await ctx.bot.send_message(draft["target"],draft["body"])
        result = "delivered"
    except Exception:
        result = "failed"
    db.record_audit(update.effective_user.id,"template_message_sent","message_template",
                    target_telegram_id=draft["target"],new_value={"template":draft["key"],"edited":draft["edited"],"length":len(draft["body"])},result="success" if result == "delivered" else "error")
    await query.answer()
    await query.edit_message_text(f"Template message {result}. The action was audited.")


async def template_update(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if role_for(update.effective_user.id, ctx.bot_data["config"]) is not Role.OWNER:
        return await update.effective_message.reply_text("Default message templates are owner-only.")
    if len(ctx.args) < 2:
        return await update.effective_message.reply_text("Usage: /template_update TEMPLATE_KEY new default text")
    key, body = ctx.args[0], _clean(" ".join(ctx.args[1:]), 3500)
    if not db.update_message_template(key, body, update.effective_user.id):
        return await update.effective_message.reply_text("Template not found, unchanged, or empty.")
    await update.effective_message.reply_text("Default template updated. The previous and new text were preserved in owner audit history.")


def register_operations(app):
    app.add_handler(CommandHandler("vacation_request", vacation_request))
    app.add_handler(CommandHandler("sick_request", sick_request))
    app.add_handler(CommandHandler("personal_day_request", personal_day_request))
    app.add_handler(CommandHandler("emergency_away_request", emergency_away_request))
    app.add_handler(CommandHandler("other_away_request", other_away_request))
    app.add_handler(CommandHandler("absence_queue", absence_queue))
    app.add_handler(CommandHandler("absence_calendar", absence_calendar))
    app.add_handler(CommandHandler("admin_note", add_note))
    app.add_handler(CommandHandler("admin_notes", view_notes))
    app.add_handler(CommandHandler("creator_restore", restore_creator))
    app.add_handler(CommandHandler("system_health", system_health))
    app.add_handler(CommandHandler("registration_queue", registration_queue))
    app.add_handler(CommandHandler("creator_search", creator_search))
    app.add_handler(CommandHandler("contact_admin", contact_admin))
    app.add_handler(CommandHandler("announce", announce))
    app.add_handler(CommandHandler("export_records", export_records))
    app.add_handler(CommandHandler("role_set", role_set))
    app.add_handler(CommandHandler("permission_set", permission_set))
    app.add_handler(CommandHandler("warning_add", warning_add))
    app.add_handler(CommandHandler("warning_ack", warning_ack))
    app.add_handler(CommandHandler("warning_remove", warning_remove))
    app.add_handler(CommandHandler("creator_timeline", creator_timeline))
    app.add_handler(CommandHandler("template_list", template_list))
    app.add_handler(CommandHandler("template_preview", template_preview))
    app.add_handler(CommandHandler("template_update", template_update))
    app.add_handler(CallbackQueryHandler(absence_callback, pattern=r"^absence:"))
    app.add_handler(CallbackQueryHandler(review_callback, pattern=r"^review:"))
    app.add_handler(CallbackQueryHandler(review_confirm_callback, pattern=r"^reviewconfirm:"))
    app.add_handler(CallbackQueryHandler(announcement_callback, pattern=r"^announce:"))
    app.add_handler(CallbackQueryHandler(timeline_callback, pattern=r"^timeline:"))
    app.add_handler(CallbackQueryHandler(template_callback, pattern=r"^template:"))
    app.add_handler(CallbackQueryHandler(guided_contact_callback, pattern=r"^contactflow:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,guided_contact_text),group=5)
