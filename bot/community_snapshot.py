"""One source of truth for Community Snapshot, Daily Brief, and filtered details."""

from datetime import date, datetime, timedelta, timezone

import database as db
from pop_policy import current_period


PARTICIPATION_POLICY = (
    "Approved creators should not go more than two full days without meaningful participation "
    "in the configured Main VAD discussion area. A friendly reminder is triggered at two days. "
    "At three full days without meaningful participation, and without an active Away Notice, "
    "the Admin team receives a follow-up alert."
)


def build_snapshot(config,now=None,path=None):
    """Build all counts and rows once, using shared POP and absence policies."""
    now=now or datetime.now(config.timezone);today=now.date();creators=[dict(r) for r in db.list_creators(path) if r["status"]=="active"]
    participation={key:[] for key in ("up_to_date","approaching","reminder_due","follow_up","excused")}
    away_now=[]
    for creator in creators:
        absence=db.approved_absence_on(creator["telegram_id"],today,path)
        if absence or creator["availability"] in {"vacation","sick"}:
            participation["excused"].append(creator);away_now.append(creator);continue
        anchor=creator["last_meaningful_at"] or creator["approved_at"] or creator["registered_at"]
        try:hours=(now.astimezone(timezone.utc)-datetime.fromisoformat(anchor).astimezone(timezone.utc)).total_seconds()/3600
        except (TypeError,ValueError):hours=0
        creator["inactive_hours"]=hours
        if hours>=config.alert_hours:participation["follow_up"].append(creator)
        elif hours>=config.warning_hours:participation["reminder_due"].append(creator)
        elif hours>=max(0,config.warning_hours-6):participation["approaching"].append(creator)
        else:participation["up_to_date"].append(creator)
    pop_rows=[dict(r) for r in db.pop_status_report(now,config.pop_due_weekday,config.pop_cutoff_time,config.timezone_name,path)]
    pop={key:[r for r in pop_rows if r["effective_status"]==key] for key in
        ("not_due","due_today","still_needed","missing","submitted","awaiting_review","excused","resubmission_requested","rejected")}
    pending_away=[dict(r) for r in db.list_absence_requests("pending",path=path)]
    upcoming=[dict(r) for r in db.calendar_absences((today+timedelta(days=1)).isoformat(),(today+timedelta(days=30)).isoformat(),path)
        if date.fromisoformat(r["start_date"])>today]
    support=[dict(r) for r in db.support_queue(path)];metrics=db.dashboard_metrics(current_period(now,config.pop_due_weekday,config.pop_cutoff_time,config.timezone_name).week_key,path)
    failures=[dict(r) for r in db.open_delivery_failures(path)];state=db.system_state(path)
    owner_reviews=db.needs_attention_counts(current_period(now,config.pop_due_weekday,config.pop_cutoff_time,config.timezone_name).week_key,
        path,now,config.pop_due_weekday,config.pop_cutoff_time,config.timezone_name)["owner_reviews"]
    routing_attrs=("admin_chat_id","registration_thread_id","away_thread_id","pop_review_thread_id","reports_thread_id","moderation_thread_id","support_thread_id","health_thread_id")
    scheduler=state.get("last_scheduled_check");scheduler_ok=False
    if scheduler:
        try:scheduler_ok=now-datetime.fromisoformat(scheduler["value"]).astimezone(config.timezone)<=timedelta(hours=1)
        except (TypeError,ValueError):pass
    backup=state.get("last_database_backup")
    return {
        "generated_at":now,"creators":{"approved":creators,"active":[r for r in creators if r not in away_now],"away":away_now,
            "pending":[dict(r) for r in db.list_creators(path) if r["status"]=="pending"]},
        "participation":participation,"pop":pop,
        "away":{"current":away_now,"upcoming":upcoming,"pending":pending_away},
        "support":{"open":support,"unassigned":[r for r in support if r["assigned_to"] is None],"escalated":[r for r in support if r["status"]=="escalated"]},
        "accountability":{"warnings":metrics["active_warnings"],"strikes":metrics["active_strikes"],"owner_reviews":owner_reviews},
        "system":{"bot_online":True,"scheduler_ok":scheduler_ok,"monitor_ok":bool(state.get("last_participation_message_detected")),
            "routing_ok":all(getattr(config,attr,None) is not None for attr in routing_attrs),"failures":failures,"backup":backup},
    }


def pop_attention(snapshot):
    pop=snapshot["pop"]
    return pop["awaiting_review"]+pop["resubmission_requested"]+pop["rejected"]+pop["missing"]


def section_lines(snapshot,section,include_zero=True):
    p=snapshot["participation"];pop=snapshot["pop"];away=snapshot["away"];support=snapshot["support"];acct=snapshot["accountability"];system=snapshot["system"]
    rows={
        "creators":[("Approved",len(snapshot["creators"]["approved"])),("Active",len(snapshot["creators"]["active"])),("Currently away",len(snapshot["creators"]["away"])),("Pending registrations",len(snapshot["creators"]["pending"]))],
        "participation":[("🟢 Up to date",len(p["up_to_date"])),("🟡 Approaching reminder",len(p["approaching"])),("🟠 Reminder due or sent",len(p["reminder_due"])),("🔴 Admin follow-up",len(p["follow_up"])),("🔵 Excused",len(p["excused"]))],
        "pop":[("Not due yet",len(pop["not_due"])),("Received",len(pop["submitted"])+len(pop["awaiting_review"])),("Excused",len(pop["excused"])),("Still due today",len(pop["due_today"])+len(pop["still_needed"])),("Missing after deadline",len(pop["missing"])),("Needs attention",len(pop_attention(snapshot)))],
        "away":[("Currently away",len(away["current"])),("Upcoming",len(away["upcoming"])),("Waiting for Admin attention",len(away["pending"]))],
        "support":[("Open",len(support["open"])),("Unassigned",len(support["unassigned"])),("Escalated to Owner",len(support["escalated"]))],
        "accountability":[("Active warnings",acct["warnings"]),("Active strikes",acct["strikes"]),("Owner-review cases",acct["owner_reviews"])],
        "system":[("Bot online","🟢" if system["bot_online"] else "🔴"),("Scheduler","🟢" if system["scheduler_ok"] else "🟡"),("Participation monitor","🟢" if system["monitor_ok"] else "⚪"),("Routing","🟢" if system["routing_ok"] else "🟡"),("Unresolved delivery failures",len(system["failures"])),("Last confirmed backup",system["backup"]["value"] if system["backup"] else "Not yet confirmed")],
    }[section]
    return [row for row in rows if include_zero or row[1] not in (0,"0")]


def actionable_total(snapshot):
    return (len(snapshot["creators"]["pending"])+len(snapshot["participation"]["follow_up"])+len(pop_attention(snapshot))+
        len(snapshot["away"]["pending"])+len(snapshot["support"]["open"])+snapshot["accountability"]["owner_reviews"]+
        len(snapshot["system"]["failures"]))
