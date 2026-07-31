"""Durable, permission-checked Telegram workflow for missing weekly POP cases."""

import secrets
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import database as db
from permissions import has_permission
from routing import destination, send_routed


STATE_TTL_SECONDS=900
ACTION_CODES={"s","e","h","c","p","r"}


def _clean(value,limit=500):
    return " ".join((value or "").replace("<","").replace(">","").split())[:limit]


def _week_date(week_key):
    year,week=(int(value) for value in week_key.split("-W"))
    return date.fromisocalendar(year,week,4)


def _week_label(week_key):
    day=_week_date(week_key)
    return f"{day.strftime('%B')} {day.day}, {day.year}"


def _eastern_timestamp(value,timezone_name):
    moment=datetime.fromisoformat(value).astimezone(ZoneInfo(timezone_name))
    hour=moment.strftime("%I").lstrip("0") or "12"
    return f"{moment.strftime('%B %d, %Y')} at {hour}:{moment.strftime('%M %p')} ET"


def strike_level(count):
    return {1:"First POP strike",2:"Second POP strike",3:"Third POP strike"}.get(count,"Additional POP strike")


def official_notice(case):
    name=_clean(case["display_name"],100) or "Creator"
    return ("⚠️ OFFICIAL STRIKE — MISSED POP ⚠️\n\n"
        f"Hi {name},\n\n"
        f"This notice serves as an official strike for failure to complete the required Post Our Promo (POP) for the week of {_week_label(case['week_key'])}.\n\n"
        "POP is a mandatory VAD seller requirement. Sellers must post the designated VAD promotional material by the established deadline, submit qualifying proof in the POP section, and ensure the promotional material remains posted for the required amount of time.\n\n"
        "We did not receive a qualifying POP submission from you before the end of the grace period.\n\n"
        "Failure to complete POP as required results in a strike in accordance with VAD policy.\n\n"
        "This strike has been formally documented.\n\n"
        "Please ensure all future POP requirements are completed correctly and on time to avoid additional disciplinary action. Continued failure to meet seller requirements may result in further strikes or removal from the group.\n\n"
        "Questions or believe this was issued in error? Please contact an admin.")


def case_callback(case,code):
    return f"mpop:{case['id']}:{case['telegram_id']}:{case['week_key']}:{code}"


def case_markup(case):
    if case["status"]!="pending":
        if case["status"]=="strike_issued" and not case["creator_notified"]:
            return InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Retry Notice",callback_data=case_callback(case,"r"))]])
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ Issue POP Strike",callback_data=case_callback(case,"s")),
         InlineKeyboardButton("✅ Mark Excused",callback_data=case_callback(case,"e"))],
        [InlineKeyboardButton("🔎 View POP History",callback_data=case_callback(case,"h")),
         InlineKeyboardButton("📩 Contact Creator",callback_data=case_callback(case,"c"))],
        [InlineKeyboardButton("⏳ Leave Pending",callback_data=case_callback(case,"p"))],
    ])


def render_case(case,timezone_name="America/New_York"):
    name=_clean(case["display_name"],100) or f"Telegram user {case['telegram_id']}"
    username=f"@{_clean(case['username'],100)}" if case.get("username") else "No username available"
    def actor_label(actor_id):
        if actor_id is None:return "Not recorded"
        people=db.people_for_ids([actor_id])
        return _clean(people[0]["display_name"],100) if people else f"Admin {actor_id}"
    if case["status"]=="pending":
        reviewed=(f"\nReviewed By: Admin {case['reviewed_by']}\nReview Status: Left pending"
            if case.get("reviewed_by") else "")
        return ("⚠️ MISSING POP REVIEW\n\n"
            f"Creator: {name}\nUsername: {username}\nPOP Week: {_week_label(case['week_key'])}\n"
            f"Current Status: ❌ Missing\nPrevious POP Strikes: {db.official_pop_strike_count(case['telegram_id'])}\n"
            "Submission Found: No\nExcused: No\nCase Status: Pending Review"
            f"{reviewed}\n\nPlease select an action.")
    handled="Not recorded"
    if case.get("resolved_at"):
        try:
            handled=_eastern_timestamp(case["resolved_at"],timezone_name)
        except (TypeError,ValueError):handled=case["resolved_at"]
    if case["status"]=="strike_issued":
        count=db.official_pop_strike_count(case["telegram_id"])
        notified="Yes" if case["creator_notified"] else "No — Manual delivery required"
        error=f"\nDelivery Reference: {_clean(case.get('notification_error'),120)}" if case.get("notification_error") else ""
        return ("✅ POP CASE RESOLVED\n\n"
            f"Creator: {name}\nPOP Week: {_week_label(case['week_key'])}\nResolution: Official POP strike issued\n"
            f"Strike Level: {strike_level(count)}\nHandled By: {actor_label(case.get('resolved_by'))}\n"
            f"Handled At: {handled}\nCreator Notified: {notified}{error}\nCase Status: Closed")
    resolution="Marked Excused" if case["status"]=="excused" else "Reconciled / no longer eligible"
    reason=f"\nReason: {_clean(case.get('excusal_reason'),500)}" if case["status"]=="excused" else ""
    return ("✅ POP CASE RESOLVED\n\n"
        f"Creator: {name}\nPOP Week: {_week_label(case['week_key'])}\nResolution: {resolution}{reason}\n"
        f"Handled By: {actor_label(case.get('resolved_by') or case.get('reviewed_by'))}\nHandled At: {handled}\nCase Status: Closed")


async def _send_card(bot,cfg,case,replacement=False):
    chat_id,thread_id=destination(cfg,"pop_review")
    if chat_id is None:raise RuntimeError("POP Review destination is not configured")
    message=await bot.send_message(chat_id,render_case(case,cfg.timezone_name),message_thread_id=thread_id,
        reply_markup=case_markup(case))
    message_id=getattr(message,"message_id",None)
    if message_id is None:raise RuntimeError("Telegram did not return a card message ID")
    db.record_missing_pop_case_card(case["id"],chat_id,thread_id,message_id,replacement=replacement)
    return message


async def ensure_missing_pop_case_cards(bot,cfg,cases):
    created=0;errors=[]
    for raw_case in cases:
        case=dict(raw_case)
        if case["status"]!="pending" or case.get("review_message_id") is not None:continue
        if not db.claim_missing_pop_case_card(case["id"]):continue
        try:
            await _send_card(bot,cfg,db.get_missing_pop_case(case["id"]));created+=1
        except Exception as exc:
            db.release_missing_pop_case_card_claim(case["id"])
            db.record_audit(None,"missing_pop_case_card_delivery_failed","missing_pop_case",case["id"],case["telegram_id"],
                result="error",error_reference="POP-CARD",new_value={"error_type":type(exc).__name__})
            errors.append({"case_id":case["id"],"error":type(exc).__name__})
    return {"cards_created":created,"card_errors":errors}


async def refresh_case_card(bot,cfg,case):
    case=db.get_missing_pop_case(case["id"])
    if not case:return False
    if case.get("review_chat_id") is not None and case.get("review_message_id") is not None:
        try:
            await bot.edit_message_text(render_case(case,cfg.timezone_name),chat_id=case["review_chat_id"],
                message_id=case["review_message_id"],reply_markup=case_markup(case))
            return True
        except Exception as exc:
            db.record_audit(None,"missing_pop_case_card_edit_failed","missing_pop_case",case["id"],case["telegram_id"],
                result="error",error_reference="POP-CARD-EDIT",new_value={"error_type":type(exc).__name__})
            if not db.claim_missing_pop_case_card_replacement(case["id"],case["review_message_id"]):return False
    try:
        await _send_card(bot,cfg,case,replacement=True);return True
    except Exception as exc:
        if case.get("review_message_id") is not None:
            db.release_missing_pop_case_card_replacement(case["id"],case["review_message_id"])
        db.record_audit(None,"missing_pop_case_card_replacement_failed","missing_pop_case",case["id"],case["telegram_id"],
            result="error",error_reference="POP-CARD-REPLACE",new_value={"error_type":type(exc).__name__})
        return False


async def _alert_notice_failure(bot,cfg,case,reference):
    retry=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Retry Notice",callback_data=case_callback(case,"r"))]])
    await send_routed(bot,cfg,"pop_review",
        "⚠️ POP STRIKE NOTICE DELIVERY REQUIRED\n\n"
        f"Creator: {_clean(case['display_name'],100)}\nUsername: @{case['username'] or 'No username'}\n"
        f"Telegram ID: {case['telegram_id']}\nPOP Week: {_week_label(case['week_key'])}\nError reference: {reference}\n\n"
        "The strike is already recorded. Do not issue it again; use Retry Notice or deliver it manually.",
        reply_markup=retry,payload_summary=f"POP notice delivery failure {reference}")


def _authorized(update,ctx):
    actor=getattr(getattr(update,"effective_user",None),"id",None)
    return actor,has_permission(actor,ctx.bot_data["config"],"review_pop")


def _parse_case_action(data):
    parts=(data or "").split(":")
    if len(parts)!=5 or parts[0]!="mpop" or parts[4] not in ACTION_CODES:return None
    try:return int(parts[1]),int(parts[2]),parts[3],parts[4]
    except ValueError:return None


def _case_matches(parsed):
    case_id,telegram_id,week_key,_=parsed;case=db.get_missing_pop_case(case_id)
    return case if case and case["telegram_id"]==telegram_id and case["week_key"]==week_key else None


def _confirmation_state(ctx,key,case,actor):
    nonce=secrets.token_urlsafe(7)
    ctx.user_data[key]={"nonce":nonce,"case_id":case["id"],"telegram_id":case["telegram_id"],
        "week_key":case["week_key"],"actor_id":actor,"expires_at":time.time()+STATE_TTL_SECONDS}
    return nonce


def _valid_state(ctx,key,nonce,actor,pop=True):
    state=ctx.user_data.get(key)
    valid=bool(state and state.get("nonce")==nonce and state.get("actor_id")==actor and state.get("expires_at",0)>=time.time())
    if pop:ctx.user_data.pop(key,None)
    return state if valid else None


def _blocked_text(reason):
    return {"qualifying_evidence":"Qualifying POP evidence was credited before confirmation.",
        "manual_reconciliation":"This POP week was manually reconciled.","excused":"The creator is excused.",
        "approved_away_notice":"An approved Away Notice covers this POP week.","creator_ineligible":"The creator is no longer eligible.",
        "official_strike_exists":"An official POP strike already exists for this creator and week.",
        "case_resolved":"Another admin already resolved this case."}.get(reason,"The case changed and is no longer eligible for this action.")


async def missing_pop_case_callback(update,ctx):
    query=update.callback_query
    actor,authorized=_authorized(update,ctx)
    if not authorized:return await query.answer("This action is unavailable.",show_alert=True)
    parsed=_parse_case_action(query.data)
    if not parsed:return await query.answer("Invalid or expired action.",show_alert=True)
    case=_case_matches(parsed)
    if not case:return await query.answer("This case is unavailable.",show_alert=True)
    action=parsed[3];cfg=ctx.bot_data["config"]
    if action=="r":
        if case["status"]!="strike_issued" or case["creator_notified"]:return await query.answer("This notice is not retryable.",show_alert=True)
        retry=db.retry_missing_pop_notification(case["id"],actor_id=actor)
        if not retry["ok"]:return await query.answer("This notice is not retryable.",show_alert=True)
        await query.answer()
        try:
            await ctx.bot.send_message(case["telegram_id"],official_notice(case));db.record_missing_pop_notification(case["id"],True,actor_id=actor)
        except Exception as exc:
            reference="POP-NOTIFY-"+secrets.token_hex(3).upper()
            db.record_missing_pop_notification(case["id"],False,reference,actor_id=actor)
            await _alert_notice_failure(ctx.bot,cfg,case,reference)
        await refresh_case_card(ctx.bot,cfg,case);return
    if case["status"]!="pending":
        await query.answer("This case has already been resolved.",show_alert=True)
        await refresh_case_card(ctx.bot,cfg,case);return
    if action=="s":
        await query.answer()
        nonce=_confirmation_state(ctx,"missing_pop_strike_confirm",case,actor)
        markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm and Send",callback_data=f"mpconfirm:{nonce}:yes"),
            InlineKeyboardButton("❌ Cancel",callback_data=f"mpconfirm:{nonce}:no")]])
        return await query.edit_message_text("⚠️ CONFIRM OFFICIAL POP STRIKE\n\n"
            f"You are about to issue an official POP strike to {_clean(case['display_name'],100)} for the POP week of {_week_label(case['week_key'])}.\n\n"
            "This will:\n• Add one documented official POP strike\n• Send the creator the official notice\n"
            "• Record the acting admin and timestamp\n• Resolve the missing-POP case",reply_markup=markup)
    if action=="e":
        await query.answer()
        ctx.user_data["guided_input"]="missing_pop_excuse"
        ctx.user_data["missing_pop_excuse_draft"]={"case_id":case["id"],"telegram_id":case["telegram_id"],
            "week_key":case["week_key"],"actor_id":actor,"expires_at":time.time()+STATE_TTL_SECONDS}
        return await query.edit_message_text("Enter a short privacy-safe excusal reason (500 characters maximum), or send Cancel.")
    if action=="p":
        await query.answer()
        db.resolve_missing_pop_case(case["id"],"pending",actor);await refresh_case_card(ctx.bot,cfg,case);return
    if action=="h":
        await query.answer()
        rows=db.missing_pop_case_history(case["telegram_id"])
        lines=[f"POP History — {_clean(case['display_name'],100)}"]
        for row in rows:
            status=str(row["status"] or "missing").replace("_"," ").title();stamp=row.get("occurred_at")
            if stamp:
                try:stamp=_eastern_timestamp(stamp,cfg.timezone_name)
                except (TypeError,ValueError):pass
            lines.append(f"{row['week_key']}: {status}"+(f" — {stamp}" if stamp else ""))
        await ctx.bot.send_message(actor,"\n".join(lines)[:3900]);return
    username=f"https://t.me/{case['username']}" if case.get("username") else "No username link available"
    return await query.answer(f"Contact information\n{username}\nTelegram ID: {case['telegram_id']}\nContacting the creator does not change this case.",show_alert=True)


async def missing_pop_confirm_callback(update,ctx):
    query=update.callback_query;parts=(query.data or "").split(":")
    actor,authorized=_authorized(update,ctx)
    if not authorized or len(parts)!=3 or parts[0]!="mpconfirm" or parts[2] not in {"yes","no"}:
        return await query.answer("This confirmation is unavailable.",show_alert=True)
    state=_valid_state(ctx,"missing_pop_strike_confirm",parts[1],actor)
    if not state:return await query.answer("This confirmation expired or was already used.",show_alert=True)
    case=db.get_missing_pop_case(state["case_id"])
    if not case or case["telegram_id"]!=state["telegram_id"] or case["week_key"]!=state["week_key"]:
        return await query.answer("This case changed and was not modified.",show_alert=True)
    if parts[2]!="yes":
        await query.answer()
        return await query.edit_message_text(render_case(case,ctx.bot_data["config"].timezone_name),reply_markup=case_markup(case))
    await query.answer()
    result=db.issue_missing_pop_strike(case["id"],actor)
    if not result["ok"]:
        case=db.get_missing_pop_case(case["id"])
        return await query.edit_message_text(_blocked_text(result["reason"])+"\n\n"+render_case(case,ctx.bot_data["config"].timezone_name),reply_markup=case_markup(case))
    case=db.get_missing_pop_case(case["id"])
    try:
        await ctx.bot.send_message(case["telegram_id"],official_notice(case));db.record_missing_pop_notification(case["id"],True,actor_id=actor)
    except Exception as exc:
        reference="POP-NOTIFY-"+secrets.token_hex(3).upper()
        db.record_missing_pop_notification(case["id"],False,reference,actor_id=actor)
        await _alert_notice_failure(ctx.bot,ctx.bot_data["config"],case,reference)
    await refresh_case_card(ctx.bot,ctx.bot_data["config"],case)


async def handle_missing_pop_excuse_text(update,ctx):
    actor,authorized=_authorized(update,ctx);draft=ctx.user_data.get("missing_pop_excuse_draft")
    if not authorized or not draft or draft.get("actor_id")!=actor or draft.get("expires_at",0)<time.time():
        ctx.user_data.pop("guided_input",None);ctx.user_data.pop("missing_pop_excuse_draft",None)
        return await update.effective_message.reply_text("This excusal request expired. Nothing changed.")
    raw=(update.effective_message.text or "").strip()
    if raw.casefold()=="cancel":
        ctx.user_data.pop("guided_input",None);ctx.user_data.pop("missing_pop_excuse_draft",None)
        await refresh_case_card(ctx.bot,ctx.bot_data["config"],db.get_missing_pop_case(draft["case_id"]))
        return await update.effective_message.reply_text("Excusal cancelled. Nothing changed.")
    reason=_clean(raw,500)
    if not reason:return await update.effective_message.reply_text("Enter a short reason or send Cancel.")
    ctx.user_data.pop("guided_input",None);draft["reason"]=reason
    case=db.get_missing_pop_case(draft["case_id"])
    if not case or case["status"]!="pending":return await update.effective_message.reply_text("This case is no longer pending. Nothing changed.")
    nonce=_confirmation_state(ctx,"missing_pop_excuse_confirm",case,actor);ctx.user_data["missing_pop_excuse_confirm"]["reason"]=reason
    markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm Excusal",callback_data=f"mpexcuse:{nonce}:yes"),
        InlineKeyboardButton("❌ Cancel",callback_data=f"mpexcuse:{nonce}:no")]])
    return await update.effective_message.reply_text(f"Confirm excusal for {_clean(case['display_name'],100)}?\nReason: {reason}",reply_markup=markup)


async def missing_pop_excuse_confirm_callback(update,ctx):
    query=update.callback_query;parts=(query.data or "").split(":");actor,authorized=_authorized(update,ctx)
    if not authorized or len(parts)!=3 or parts[0]!="mpexcuse" or parts[2] not in {"yes","no"}:
        return await query.answer("This confirmation is unavailable.",show_alert=True)
    state=_valid_state(ctx,"missing_pop_excuse_confirm",parts[1],actor)
    if not state:return await query.answer("This confirmation expired or was already used.",show_alert=True)
    case=db.get_missing_pop_case(state["case_id"])
    if parts[2]!="yes":
        await query.answer()
        if case:await refresh_case_card(ctx.bot,ctx.bot_data["config"],case)
        return await query.edit_message_text("Excusal cancelled. Nothing changed.")
    if not case or case["telegram_id"]!=state["telegram_id"] or case["week_key"]!=state["week_key"] or case["status"]!="pending":
        return await query.answer("This case changed and was not modified.",show_alert=True)
    await query.answer()
    changed=db.resolve_missing_pop_case(case["id"],"excused",actor,state["reason"])
    await refresh_case_card(ctx.bot,ctx.bot_data["config"],case)
    return await query.edit_message_text("POP case marked Excused and closed." if changed else "No change was recorded.")
