"""Human-readable, role-safe participation summaries for Admins and Owners."""

from datetime import datetime, time, timedelta, timezone

import database as db
from community_snapshot import build_snapshot
from presentation import friendly_timestamp


REMINDER_LABELS = {
    "up_to_date": "🟢 Up to date",
    "approaching": "🟡 Approaching reminder",
    "reminder_due": "🟠 Friendly check-in due",
    "follow_up": "🔴 Admin follow-up",
    "excused": "🔵 Away — expectations paused",
}


def _utc_window(local_start, local_end):
    return (local_start.astimezone(timezone.utc).isoformat(),local_end.astimezone(timezone.utc).isoformat())


def build_participation_summary(config, now=None, path=None):
    """Build all views from one set of Eastern Time boundaries and shared status policy."""
    now=(now or datetime.now(config.timezone)).astimezone(config.timezone)
    today_start=datetime.combine(now.date(),time.min,config.timezone)
    tomorrow=today_start+timedelta(days=1)
    week_start=today_start-timedelta(days=today_start.weekday())
    day=db.participation_activity(*_utc_window(today_start,tomorrow),path)
    week=db.participation_activity(*_utc_window(week_start,tomorrow),path)
    snapshot=build_snapshot(config,now,path)
    state_by_id={row["telegram_id"]:key for key,rows in snapshot["participation"].items() for row in rows}
    pop_by_id={row["telegram_id"]:row["effective_status"] for rows in snapshot["pop"].values() for row in rows}
    day_counts={row["telegram_id"]:row["count"] for row in day["accepted"]}
    week_counts={row["telegram_id"]:row["count"] for row in week["accepted"]}
    creators=[]
    for creator in snapshot["creators"]["approved"]:
        item=dict(creator);telegram_id=item["telegram_id"]
        item.update({"today_count":day_counts.get(telegram_id,0),"week_count":week_counts.get(telegram_id,0),
            "away":state_by_id.get(telegram_id)=="excused","reminder_state":state_by_id.get(telegram_id,"up_to_date"),
            "pop_status":pop_by_id.get(telegram_id,"not_due")})
        creators.append(item)
    return {"generated_at":now,"today":{"creators":len(day_counts),"events":sum(day_counts.values()),
        "ignored":day["ignored"],"away":len(snapshot["creators"]["away"]),
        "not_participated":sum(not row["today_count"] for row in creators)},
        "week":{"creators":len(week_counts),"events":sum(week_counts.values())},
        "creators":creators,"status":snapshot["participation"]}


def render_today(summary):
    today=summary["today"]
    return ("📊 Participation · Today\n\nSee today’s meaningful participation without ranking creators.\n\n"
        f"👥 Participated today: {today['creators']}\n💬 Meaningful events: {today['events']}\n"
        f"⚪ Not counted: {today['ignored']}\n🌴 Away today: {today['away']}\n"
        f"🌼 Still to check in today: {today['not_participated']}")


def today_groups(summary):
    """Return privacy-safe Today drill-down groups without Away Notice notes."""
    participated=[row for row in summary["creators"] if row["today_count"]]
    away=[row for row in summary["creators"] if row["away"]]
    still=[row for row in summary["creators"] if not row["today_count"] and not row["away"]]
    return {"participated":participated,"away":away,"still":still}


def render_today_group(summary,group):
    groups=today_groups(summary);rows=groups[group]
    titles={"participated":"🟢 Participated Today","away":"🌴 Away Today","still":"🌼 Still to Check In"}
    if group=="participated":
        lines=[f"• {row['display_name']} — {row['today_count']} meaningful event{'s' if row['today_count'] != 1 else ''}" for row in rows]
    elif group=="away":
        lines=[f"• {row['display_name']} — expectations paused" for row in rows]
    else:lines=[f"• {row['display_name']}" for row in rows]
    return f"{titles[group]}\n\n"+("\n".join(lines) if lines else "✅ No creators in this view.")


def render_week(summary, timezone_name="America/New_York"):
    active=[row for row in summary["creators"] if row["week_count"]]
    lines=["📊 Participation · This Week","","See who joined meaningful conversation this week; this is not a ranking.","",
        f"Creators participating: {summary['week']['creators']}",f"Meaningful events: {summary['week']['events']}"]
    for row in active:
        lines.extend(["",f"{row['display_name']} · {row['week_count']} meaningful event{'s' if row['week_count'] != 1 else ''}",
            f"Last: {friendly_timestamp(row['last_meaning_at'],timezone_name=timezone_name) if row.get('last_meaning_at') else 'No participation recorded'}",
            f"Away: {'Yes — expectations paused' if row['away'] else 'No'}",
            f"Status: {REMINDER_LABELS.get(row['reminder_state'],row['reminder_state'])}"])
    return "\n".join(lines)


def creator_detail(row, timezone_name="America/New_York"):
    last=(friendly_timestamp(row["last_meaning_at"],timezone_name=timezone_name)
        if row.get("last_meaning_at") else "No participation recorded")
    pop=str(row.get("pop_status","not_due")).replace("_"," ").title()
    return (f"📊 {row['display_name']}\n\nMeaningful events today: {row['today_count']}\n"
        f"Meaningful events this week: {row['week_count']}\nLast meaningful participation: {last}\n"
        f"Away status: {'Away — expectations paused' if row['away'] else 'No active Away Notice'}\n"
        f"Reminder state: {REMINDER_LABELS.get(row['reminder_state'],row['reminder_state'])}\nThursday POP: {pop}")
