"""Human-readable, privacy-aware Telegram presentation helpers."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


ACTION_LABELS = {
    "creator_registered": "📝 Creator registered",
    "creator_status_changed": "🛡️ Creator status changed",
    "availability_changed": "🟢 Availability changed",
    "availability_changed_automatically": "💙 Away status started",
    "availability_restored_automatically": "🟢 Returned from time away",
    "pop_submitted": "📸 Thursday POP submitted",
    "pop_approved": "✅ Thursday POP approved",
    "pop_rejected": "🔴 Thursday POP needs follow-up",
    "absence_requested": "💙 Away Notice submitted",
    "absence_approved": "💙 Away Notice recorded as excused",
    "absence_clarification": "💬 Away Notice clarification requested",
    "warning_issued": "💛 Warning issued",
    "strike_issued": "🔴 Strike issued",
    "warning_acknowledged": "✅ Warning acknowledged",
    "creator_soft_deleted": "🗃️ Creator archived",
    "creator_restored": "♻️ Creator restored",
    "system_error": "⚠️ System error recorded",
}


def friendly_timestamp(value, now=None, timezone_name="America/New_York"):
    zone = ZoneInfo(timezone_name)
    try: moment = datetime.fromisoformat(value).astimezone(zone)
    except (TypeError,ValueError): return "Time unavailable"
    now = (now or datetime.now(zone)).astimezone(zone)
    clock = f"{moment.strftime('%I').lstrip('0')}:{moment.strftime('%M %p')} ET"
    if moment.date() == now.date(): return f"Today · {clock}"
    if moment.date() == now.date() - timedelta(days=1): return f"Yesterday · {clock}"
    short_date = f"{moment.strftime('%b')} {moment.day}"
    if moment.year == now.year: return f"{short_date} · {clock}"
    return f"{short_date}, {moment.year} · {clock}"


def _value(value):
    if value is None: return None
    if not isinstance(value,str): return value
    try: return json.loads(value)
    except (ValueError,TypeError): return value


def change_summary(previous,new):
    previous,new = _value(previous),_value(new)
    if previous is None and new is None: return ""
    if isinstance(previous,dict) and isinstance(new,dict):
        keys = [key for key in new if previous.get(key) != new.get(key)]
        if keys:
            key = keys[0]
            return f"{str(previous.get(key,'Not set')).title()} → {str(new.get(key,'Not set')).title()}"
    if previous is not None and new is not None:
        return f"{str(previous).title()} → {str(new).title()}"
    return ""


def actor_name(row, resolver=None):
    actor_id = row["actor_id"]
    if row["actor_name"]: return row["actor_name"]
    if actor_id is None:
        return "Automated Scheduler" if row["actor_role"] == "system" else "System"
    if row["actor_role"] == "legacy": return "Legacy Imported Record"
    resolved = resolver(actor_id) if resolver else None
    return resolved or "Unknown Actor"


def timeline_entry(row, timezone_name="America/New_York"):
    label = ACTION_LABELS.get(row["action"],row["action"].replace("_"," ").title())
    change = change_summary(row["previous_value"],row["new_value"])
    parts = [label]
    if change: parts.append(change)
    parts.append(friendly_timestamp(row["occurred_at"],timezone_name=timezone_name))
    return "\n".join(parts)


def audit_entry(row, resolver=None, timezone_name="America/New_York"):
    label = ACTION_LABELS.get(row["action"],row["action"].replace("_"," ").title())
    actor = actor_name(row,resolver)
    parts = [label,f"By: {actor}",friendly_timestamp(row["occurred_at"],timezone_name=timezone_name)]
    change = change_summary(row["previous_value"],row["new_value"])
    if change: parts.insert(2,change)
    if row["error_reference"]: parts.append(f"Reference: {row['error_reference']}")
    if row["action"] == "system_error":
        details=_value(row["new_value"])
        if isinstance(details,dict) and details.get("exception_type"):
            parts.append(f"Exception: {details['exception_type']}")
    if row["result"] == "error": parts.append("Status: Needs review")
    return "\n".join(parts)


def system_error_detail(row,timezone_name="America/New_York"):
    """Render stored diagnostics for the Owner-only Telegram detail screen."""
    details=_value(row["new_value"])
    if not isinstance(details,dict) or not details.get("exception_type"):
        return (f"⚠️ System Error\n\nReference: {row['error_reference'] or 'Unavailable'}\n"
            f"Time: {friendly_timestamp(row['occurred_at'],timezone_name=timezone_name)}\nStatus: Needs review\n\n"
            "Detailed exception data was not stored for this historical error. Match the reference in the Replit console logs to recover its stack trace.")
    return (f"⚠️ System Error\n\nReference: {row['error_reference']}\n"
        f"Time: {friendly_timestamp(row['occurred_at'],timezone_name=timezone_name)}\n"
        f"Exception: {details.get('exception_type','Unknown')}\nMessage: {details.get('message','Unavailable')}\n"
        f"Status: Needs review\n\nStack trace\n{details.get('traceback','Traceback unavailable.')}")
