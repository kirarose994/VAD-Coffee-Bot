"""Presentation helpers for the Admin-only approved Away Notice calendar."""

from calendar import monthrange
from datetime import date, timedelta


VIEW_TITLES = {
    "today": "Today",
    "week": "This Week",
    "30": "Next 30 Days",
    "month": "Month View",
}


def calendar_window(view: str, today: date) -> tuple[date, date]:
    """Return inclusive Eastern-calendar boundaries for a mobile calendar view."""
    if view == "today":
        return today, today
    if view == "week":
        return today, today + timedelta(days=6)
    if view == "month":
        return today, date(today.year, today.month, monthrange(today.year, today.month)[1])
    return today, today + timedelta(days=29)


def default_sections(rows, today: date) -> dict[str, list]:
    """Categorize approved notices for the default operational overview."""
    active = [row for row in rows if date.fromisoformat(row["start_date"]) <= today <= date.fromisoformat(row["end_date"])]
    upcoming = [row for row in rows if today < date.fromisoformat(row["start_date"]) <= today + timedelta(days=7)]
    continuing = [row for row in active if date.fromisoformat(row["start_date"]) < today]
    return {"away_today": active, "starting_soon": upcoming, "continuing": continuing}


def friendly_range(row) -> str:
    start, end = date.fromisoformat(row["start_date"]), date.fromisoformat(row["end_date"])
    if start == end:
        return f"{start.strftime('%b')} {start.day}"
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%b')} {start.day}–{end.day}"
    return f"{start.strftime('%b')} {start.day}–{end.strftime('%b')} {end.day}"


def render_default(rows, today: date) -> str:
    sections = default_sections(rows, today)
    lines = ["📅 Who’s Away", "", "See approved time-away dates and open a notice only when more detail is needed."]
    for title, key, empty in (
        ("Away today", "away_today", "No one is away today."),
        ("Starting within the next 7 days", "starting_soon", "No Away Notices start in the next 7 days."),
        ("Continuing absences", "continuing", "No earlier Away Notices continue today."),
    ):
        lines.extend(["", title])
        values = sections[key]
        lines.extend([f"• {row['display_name']} · {friendly_range(row)}" for row in values] or [empty])
    return "\n".join(lines)


def render_view(rows, view: str) -> str:
    title = VIEW_TITLES.get(view, VIEW_TITLES["30"])
    lines = [f"📅 Who’s Away · {title}", "", "Approved Away Notices in this Eastern Time date range."]
    if not rows:
        lines.extend(["", "💙 No approved Away Notices match this view."])
        return "\n".join(lines)
    current_group = None
    for row in rows:
        start = date.fromisoformat(row["start_date"])
        group = start.strftime("%B %Y")
        if group != current_group:
            lines.extend(["", group])
            current_group = group
        lines.append(f"• {row['display_name']} · {friendly_range(row)}")
    return "\n".join(lines)
