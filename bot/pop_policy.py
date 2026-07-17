"""Single source of truth for Thursday POP periods, deadlines, and display states."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class PopPeriod:
    week_key: str
    week_start: datetime
    due_at: datetime


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
    "complete_preserved": "✅ Complete — 24-hour requirement satisfied",
    "needs_review": "🟡 Needs review",
    "on_time": "✅ On Time",
    "late": "🟠 Late",
    "submitted_needs_review": "🟡 Submitted — Needs Review",
}


def _cutoff(value: str) -> time:
    try:
        hour, minute = map(int, value.split(":", 1))
        return time(hour, minute)
    except (TypeError, ValueError):
        return time(23, 59)


def current_period(now: datetime, due_weekday=3, cutoff_time="23:59", timezone_name="America/New_York") -> PopPeriod:
    zone = ZoneInfo(timezone_name)
    local = now.astimezone(zone)
    monday = (local - timedelta(days=local.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)
    due_day = monday + timedelta(days=int(due_weekday))
    cutoff = _cutoff(cutoff_time)
    # A minute-based setting describes the whole selected minute.  The default
    # 23:59 cutoff therefore includes Thursday 11:59:59.999999 PM ET.
    due_at = due_day.replace(hour=cutoff.hour,minute=cutoff.minute,second=59,microsecond=999999)
    year, week, _ = monday.isocalendar()
    return PopPeriod(f"{year}-W{week:02d}",monday,due_at)


def calculate_status(now: datetime, *, submission_status=None, excused=False,
                     registered_at=None, due_weekday=3, cutoff_time="23:59",
                     timezone_name="America/New_York") -> str:
    period = current_period(now,due_weekday,cutoff_time,timezone_name)
    local = now.astimezone(ZoneInfo(timezone_name))
    if excused or submission_status == "excused": return "excused"
    if submission_status == "pending": return "awaiting_review"
    if submission_status == "approved": return "submitted"
    if submission_status == "resubmission_requested": return "resubmission_requested"
    if registered_at:
        try:
            if datetime.fromisoformat(registered_at).astimezone(ZoneInfo(timezone_name)) > period.due_at:
                return "not_due"
        except (TypeError,ValueError):
            pass
    if local.date() < period.due_at.date(): return "not_due"
    if local.date() == period.due_at.date() and local <= period.due_at: return "due_today"
    return "missing"


def label(status: str) -> str:
    return LABELS.get(status,status.replace("_"," ").title())


def submission_timing(source_at: datetime, due_weekday=3, cutoff_time="23:59",
                      timezone_name="America/New_York") -> tuple[str, str]:
    """Return the source message's canonical week and ET timing classification."""
    period = current_period(source_at,due_weekday,cutoff_time,timezone_name)
    local = source_at.astimezone(ZoneInfo(timezone_name))
    if local.date() < period.due_at.date():
        return period.week_key,"not_yet_due"
    return period.week_key, "on_time" if local <= period.due_at else "late"
