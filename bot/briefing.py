"""Daily Admin Brief rendering and idempotent delivery."""
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import database as db
from community_snapshot import actionable_total, build_snapshot, section_lines
from routing import destination, send_routed

BRIEF_BUTTONS = InlineKeyboardMarkup([
    [InlineKeyboardButton("Open Community Snapshot", callback_data="brief:snapshot")],
    [InlineKeyboardButton("Open Needs Attention", callback_data="brief:attention"),
     InlineKeyboardButton("Run System Check", callback_data="brief:health")],
])

def _section(title, rows):
    return title + "\n" + "\n".join(f"{label}: {value}" for label, value in rows)

def format_daily_brief(snapshot, config, *, test=False):
    now=snapshot["generated_at"]
    title="🧪 TEST — Daily VAD Operations Brief" if test else "📊 Daily VAD Operations Brief"
    stamp=f"{now.strftime('%A, %B')} {now.day} • {now.strftime('%I').lstrip('0')}:{now.strftime('%M %p')} ET"
    sections=[]
    for key,heading in (("creators","CREATORS"),("participation","PARTICIPATION"),("pop","THURSDAY POP"),
        ("away","AWAY NOTICES"),("support","SUPPORT"),("accountability","ACCOUNTABILITY")):
        sections.append(_section(heading,section_lines(snapshot,key,config.daily_brief_include_zero)))
    if config.daily_brief_include_health:
        sections.append(_section("SYSTEM HEALTH",section_lines(snapshot,"system",config.daily_brief_include_zero)))
    ending=("Everything currently requiring Admin attention is caught up." if actionable_total(snapshot)==0
        else f"🚨 {actionable_total(snapshot)} item(s) currently need attention.")
    return f"{title}\n{stamp}\n\n"+"\n\n".join(sections)+f"\n\n{ending}"

async def deliver_daily_brief(bot,config,*,now=None,test=False):
    now=now or datetime.now(config.timezone)
    if not test:
        if not config.daily_brief_enabled or (not config.daily_brief_weekends and now.weekday()>=5):return False,"disabled"
        try:hour,minute=map(int,config.daily_brief_time.split(":",1))
        except (TypeError,ValueError):return False,"invalid_time"
        if (now.hour,now.minute)<(hour,minute):return False,"not_due"
        if not db.claim_daily_brief(now.date().isoformat()):return False,"already_claimed"
    snapshot=build_snapshot(config,now)
    if test:
        chat_id,thread_id=destination(config,"daily_brief")
        if chat_id is None:return False,"destination_not_configured"
        try:
            await bot.send_message(chat_id,format_daily_brief(snapshot,config,test=True),message_thread_id=thread_id,reply_markup=BRIEF_BUTTONS)
            return True,None
        except Exception:
            return False,"test_delivery_failed"
    ok,ref=await send_routed(bot,config,"daily_brief",format_daily_brief(snapshot,config,test=test),
        reply_markup=BRIEF_BUTTONS,payload_summary="Test Daily Admin Brief" if test else "Daily Admin Brief")
    if not test:db.finish_daily_brief(now.date().isoformat(),"sent" if ok else "failed",ref)
    return ok,ref

async def daily_admin_brief_job(ctx):
    await deliver_daily_brief(ctx.bot,ctx.bot_data["config"])
