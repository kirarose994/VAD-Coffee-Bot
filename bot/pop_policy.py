"""Single source of truth for Thursday POP periods, deadlines, and display states."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


POP_TIMEZONE_NAME="America/New_York"
POP_DUE_WEEKDAY=3


@dataclass(frozen=True)
class PopPeriod:
    week_key: str
    week_start: datetime
    early_opens_at: datetime
    due_at: datetime
    grace_at: datetime


LABELS = {
    "not_due": "⚪ Not due yet",
    "due_today": "📸 Due today",
    "still_needed": "🟡 Still needed",
    "missing": "🔴 Missing",
    "submitted": "✅ Submitted",
    "awaiting_review": "⏳ Awaiting review",
    "excused": "💙 Excused",
    "resubmission_requested": "🟡 Resubmission requested",
    "rejected": "🔴 Missing",
    "complete_preservation_pending": "✅ Complete — preservation pending",
    "complete_preserved": "✅ Complete — retention requirement satisfied",
    "needs_review": "🟡 Needs review",
    "on_time": "✅ On Time",
    "late": "🟠 Late",
    "submitted_needs_review": "🟡 Submitted — Needs Review",
}


def current_period(now: datetime, due_weekday=3, cutoff_time="23:59", timezone_name="America/New_York") -> PopPeriod:
    zone = ZoneInfo(POP_TIMEZONE_NAME)
    local = now.astimezone(zone)
    monday = (local - timedelta(days=local.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)
    due_day = monday + timedelta(days=POP_DUE_WEEKDAY)
    cutoff = time(23,59)
    # Policy deadlines include the complete displayed minute in Eastern Time.
    due_at = due_day.replace(hour=cutoff.hour,minute=cutoff.minute,second=59,microsecond=999999)
    early_opens_at=(due_day-timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
    grace_at=(due_day+timedelta(days=1)).replace(hour=11,minute=59,second=59,microsecond=999999)
    year, week, _ = monday.isocalendar()
    return PopPeriod(f"{year}-W{week:02d}",monday,early_opens_at,due_at,grace_at)


def latest_completed_period(now: datetime, due_weekday=3, cutoff_time="23:59",
                            timezone_name="America/New_York") -> PopPeriod:
    """Return the latest week whose Friday grace period has fully closed."""
    zone=ZoneInfo(POP_TIMEZONE_NAME);local=now.astimezone(zone)
    period=current_period(local,due_weekday,cutoff_time,timezone_name)
    if local > period.grace_at:
        return period
    return current_period(local-timedelta(days=7),due_weekday,cutoff_time,timezone_name)


def calculate_status(now: datetime, *, submission_status=None, excused=False,
                     registered_at=None, due_weekday=3, cutoff_time="23:59",
                     timezone_name="America/New_York") -> str:
    period = current_period(now,due_weekday,cutoff_time,timezone_name)
    local = now.astimezone(ZoneInfo(POP_TIMEZONE_NAME))
    if excused or submission_status == "excused": return "excused"
    if submission_status == "pending": return "awaiting_review"
    if submission_status == "approved": return "submitted"
    if submission_status == "resubmission_requested": return "resubmission_requested"
    if registered_at:
        try:
            if datetime.fromisoformat(registered_at).astimezone(ZoneInfo(POP_TIMEZONE_NAME)) > period.due_at:
                return "not_due"
        except (TypeError,ValueError):
            pass
    if local < period.due_at.replace(hour=0,minute=0,second=0,microsecond=0): return "not_due"
    if local <= period.due_at: return "due_today"
    if local <= period.grace_at: return "still_needed"
    return "missing"


def label(status: str) -> str:
    return LABELS.get(status,status.replace("_"," ").title())


def submission_timing(source_at: datetime, due_weekday=3, cutoff_time="23:59",
                      timezone_name="America/New_York") -> tuple[str, str]:
    """Return the source message's canonical week and ET timing classification."""
    period = current_period(source_at,due_weekday,cutoff_time,timezone_name)
    local = source_at.astimezone(ZoneInfo(POP_TIMEZONE_NAME))
    if local < period.early_opens_at:
        return period.week_key,"not_yet_due"
    if local <= period.due_at:
        return period.week_key,"on_time"
    if local <= period.grace_at:
        return period.week_key,"late"
    return period.week_key,"after_cutoff"


def retention_hours(source_at: datetime, due_weekday=3,
                    timezone_name="America/New_York") -> int:
    """Return the retention requirement for the source post in Eastern Time."""
    local=source_at.astimezone(ZoneInfo(POP_TIMEZONE_NAME))
    return 48 if local.weekday()==POP_DUE_WEEKDAY-1 else 24


def lateness_minutes(source_at: datetime, due_weekday=3, cutoff_time="23:59",
                     timezone_name="America/New_York") -> int:
    """Return whole clock minutes after the configured ET cutoff, without persisting them.

    The configured cutoff names a minute (for example 23:59) and that entire minute
    remains on time.  Human-facing lateness is measured from the named clock minute,
    so Friday 00:15 is displayed as 16 minutes after a Thursday 23:59 cutoff.
    """
    zone = ZoneInfo(POP_TIMEZONE_NAME)
    local = source_at.astimezone(zone)
    period = current_period(local,due_weekday,cutoff_time,timezone_name)
    if local <= period.due_at:
        return 0
    cutoff_minute = period.due_at.replace(second=0,microsecond=0)
    return max(1,int((local-cutoff_minute).total_seconds()//60))


def format_lateness(source_at: datetime, due_weekday=3, cutoff_time="23:59",
                    timezone_name="America/New_York") -> str:
    minutes=lateness_minutes(source_at,due_weekday,cutoff_time,timezone_name)
    hours,remainder=divmod(minutes,60)
    parts=[]
    if hours:parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if remainder or not parts:parts.append(f"{remainder} minute{'s' if remainder != 1 else ''}")
    return " ".join(parts)


def posted_time(source_at: datetime, timezone_name="America/New_York") -> str:
    local=source_at.astimezone(ZoneInfo(POP_TIMEZONE_NAME))
    hour=local.strftime("%I").lstrip("0") or "0"
    return f"{local.strftime('%A')} at {hour}:{local.strftime('%M %p')} ET"
