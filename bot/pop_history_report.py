"""Owner-friendly, read-only rendering for POP history scan reports."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import database as db
from pop_policy import submission_timing


SECTION_ORDER = (
    "ready_to_recover",
    "already_credited_skipped",
    "needs_owner_review",
    "not_eligible_unqualified",
    "unmatched_inactive",
)
SECTION_TITLES = {
    "ready_to_recover": "Ready to Recover",
    "already_credited_skipped": "Already Credited / Skipped",
    "needs_owner_review": "Needs Owner Review",
    "not_eligible_unqualified": "Not Eligible / Unqualified",
    "unmatched_inactive": "Unmatched or Inactive Creators",
}


class OwnerReportError(ValueError):
    """Invalid or unavailable read-only report input."""


def _configured_timezone(path: Path | str | None, environ: Mapping[str, str] | None) -> str:
    values = os.environ if environ is None else environ
    candidate = (values.get("TIMEZONE") or "America/New_York").strip()
    with db.get_readonly_connection(path) as connection:
        row = connection.execute("""SELECT state_value FROM system_state
          WHERE state_key='config:timezone_name'""").fetchone()
    if row:
        try:
            candidate = str(json.loads(row["state_value"])).strip()
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError as exc:
        raise OwnerReportError("The configured project timezone is unavailable") from exc
    return candidate


def _source_time(value: str, timezone_name: str) -> tuple[datetime, str]:
    try:
        source = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise OwnerReportError("A scan result has an invalid original timestamp") from exc
    if source.tzinfo is None:
        raise OwnerReportError("A scan result timestamp is missing its timezone offset")
    local = source.astimezone(ZoneInfo(timezone_name))
    hour = local.strftime("%I").lstrip("0") or "0"
    readable = (f"{local.strftime('%A, %B')} {local.day}, {local.year} at "
        f"{hour}:{local.strftime('%M %p')} ET")
    return local, readable


def _username(value: str | None) -> str | None:
    value = (value or "").strip().lstrip("@")
    return f"@{value}" if value else None


def _identity_label(identity: Mapping[str, Any]) -> str:
    telegram_id = identity["telegram_id"]
    username = _username(identity.get("username"))
    suffix = f" ({username})" if username else ""
    if not identity["creator_matched"]:
        return f"Unmatched Telegram ID {telegram_id}{suffix}"
    name = identity.get("approved_creator_name") or identity.get("display_name") or f"Telegram ID {telegram_id}"
    return f"{name}{suffix}"


def _configured_staff_ids(environ: Mapping[str, str]) -> dict[int, set[str]]:
    roles: dict[int, set[str]] = {}
    for key, role in (("OWNER_USER_IDS", "owner"), ("OWNER_TELEGRAM_IDS", "owner"),
                      ("ADMIN_USER_IDS", "admin"), ("LEAD_ADMIN_USER_IDS", "admin")):
        for raw in environ.get(key, "").split(","):
            raw = raw.strip()
            if raw:
                try:
                    roles.setdefault(int(raw), set()).add(role)
                except ValueError:
                    continue
    return roles


def _unmatched_resolution(
    connection,
    telegram_id: int,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """Explain an unresolved immutable ID without fuzzy or username matching."""

    creator = connection.execute("SELECT * FROM creators WHERE telegram_id=?",
        (telegram_id,)).fetchone()
    member = connection.execute("SELECT * FROM community_members WHERE telegram_id=?",
        (telegram_id,)).fetchone()
    bot_user = connection.execute("SELECT * FROM bot_users WHERE telegram_id=?",
        (telegram_id,)).fetchone()
    roles = connection.execute("""SELECT role,active,assigned_at,removed_at
      FROM user_roles WHERE telegram_id=? ORDER BY role""", (telegram_id,)).fetchall()
    registration_events = connection.execute("""SELECT action,occurred_at,target_type
      FROM audit_events WHERE target_telegram_id=? AND
        (action LIKE '%register%' OR action LIKE 'creator_profile_%')
      ORDER BY occurred_at,id""", (telegram_id,)).fetchall()
    legacy_events = connection.execute("""SELECT action,created_at
      FROM audit_history WHERE target_id=? AND action LIKE '%register%'
      ORDER BY created_at,id""", (telegram_id,)).fetchall()
    configured_roles = sorted(_configured_staff_ids(environ).get(telegram_id, ()))
    active_creator = bool(creator and creator["status"] == "active" and not creator["deleted_at"])
    inactive_creator = bool(creator and creator["status"] == "inactive" and not creator["deleted_at"])
    archived_creator = bool(creator and creator["deleted_at"])
    staff_profile_events = [row for row in registration_events
        if row["action"].startswith("creator_profile_")]

    source_checks = [
        {"source": "active_creators", "found": active_creator,
         "detail": ("active canonical creator row found" if active_creator
             else "no active creator row with this Telegram ID")},
        {"source": "inactive_creators", "found": inactive_creator,
         "detail": ("inactive canonical creator row found" if inactive_creator
             else "no inactive creator row with this Telegram ID")},
        {"source": "archived_creators", "found": archived_creator,
         "detail": ("archived canonical creator row found" if archived_creator
             else "no archived creator row with this Telegram ID")},
        {"source": "other_creator_registration_states", "found": bool(
            creator and not active_creator and not inactive_creator and not archived_creator),
         "detail": (f"status={creator['status']}" if creator and not active_creator
             and not inactive_creator and not archived_creator else
             "no pending or rejected creator row with this Telegram ID")},
        {"source": "community_members", "found": bool(member),
         "detail": (f"member_type={member['member_type']}" if member
             else "no row with this Telegram ID")},
        {"source": "bot_users", "found": bool(bot_user),
         "detail": ("private bot identity exists" if bot_user
             else "no row with this Telegram ID")},
        {"source": "user_roles", "found": bool(roles),
         "detail": (", ".join(f"{row['role']} ({'active' if row['active'] else 'inactive'})"
             for row in roles) if roles else "no role row with this Telegram ID")},
        {"source": "configured_staff_roles", "found": bool(configured_roles),
         "detail": (", ".join(configured_roles) if configured_roles
             else "not configured as Owner or Admin under this Telegram ID")},
        {"source": "staff_inherited_creator_profiles", "found": bool(
            creator and (configured_roles or roles or staff_profile_events)),
         "detail": ("staff-inherited creator profile exists under this Telegram ID"
             if creator and (configured_roles or roles or staff_profile_events) else
             "no staff-inherited creator profile with this Telegram ID")},
        {"source": "historical_registration_audit", "found": bool(registration_events or legacy_events),
         "detail": (", ".join(
             [f"{row['action']} at {row['occurred_at']}" for row in registration_events] +
             [f"{row['action']} at {row['created_at']}" for row in legacy_events])
             if registration_events or legacy_events else
             "no registration audit row with this Telegram ID")},
    ]
    if creator:
        safe_match = True
        reason = "canonical_creator_found_by_immutable_telegram_id"
    elif configured_roles or roles:
        safe_match = False
        reason = "staff_identity_exists_but_canonical_creator_profile_is_missing"
    elif member and member["member_type"] == "creator":
        safe_match = False
        reason = "historical_creator_membership_exists_but_canonical_creator_profile_is_missing"
    elif registration_events or legacy_events:
        safe_match = False
        reason = "historical_registration_exists_but_no_current_creator_profile"
    elif member:
        safe_match = False
        reason = f"telegram_id_belongs_to_{member['member_type']}_not_creator"
    elif bot_user:
        safe_match = False
        reason = "telegram_user_is_known_but_has_no_creator_registration"
    else:
        safe_match = False
        reason = "telegram_id_absent_from_all_available_identity_sources"
    return {
        "telegram_id": telegram_id,
        "safe_match_found": safe_match,
        "automatic_credit_eligible": False,
        "resolution_status": "resolved_by_telegram_id" if safe_match else "unresolved_excluded",
        "exact_reason": reason,
        "source_checks": source_checks,
        "identify_creator_action": {
            "label": "Identify Creator",
            "action": "identify_creator",
            "owner_only": True,
            "enabled": False,
            "source_telegram_id": telegram_id,
            "match_policy": "immutable_telegram_id_only",
            "requires_existing_creator": True,
            "requires_explicit_confirmation": True,
            "requires_audit_logging": True,
            "write_performed": False,
            "blocked_reason": "identity_linking_not_implemented",
        },
    }


def _message_view(
    row: Mapping[str, Any],
    timezone_name: str,
    due_weekday: int,
    cutoff_time: str,
) -> dict[str, Any]:
    local, readable = _source_time(row.get("original_timestamp"), timezone_name)
    week_key, timing_status = submission_timing(
        local, due_weekday, cutoff_time, timezone_name)
    decision = row.get("pop_decision") or "unqualified"
    return {
        "message_id": int(row["message_id"]),
        "original_timestamp": local.isoformat(),
        "original_timestamp_display": readable,
        "proof_type": row.get("pop_proof_type") or row.get("media_type") or "other",
        "status": decision,
        "reason": row.get("pop_reason") or "No classifier reason was recorded",
        "week_key": week_key,
        "timing_status": timing_status,
    }


def build_owner_report(
    scan_report: Mapping[str, Any],
    *,
    creator_database: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Group a privacy-minimal scanner report by immutable creator identity."""

    messages = []
    seen_messages: set[tuple[int, int]] = set()
    configured_chat_id = int(scan_report.get("configured_chat_id") or 0)
    for row in scan_report.get("messages", ()):
        identity = (configured_chat_id, int(row["message_id"]))
        if identity in seen_messages:
            continue
        seen_messages.add(identity)
        messages.append(row)
    values = os.environ if environ is None else environ
    try:
        due_weekday = int(values.get("POP_DUE_WEEKDAY", "3"))
    except (TypeError, ValueError) as exc:
        raise OwnerReportError("POP_DUE_WEEKDAY is invalid") from exc
    cutoff_time = values.get("POP_CUTOFF_TIME", "23:59")
    sender_ids = {int(row["sender_telegram_id"]) for row in messages}
    timezone_name = _configured_timezone(creator_database, environ)
    identities = {row["telegram_id"]: row for row in
        db.creator_identities_for_ids(sender_ids, creator_database)}
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in messages:
        grouped.setdefault(int(row["sender_telegram_id"]), []).append(
            _message_view(row, timezone_name, due_weekday, cutoff_time))

    existing_credits: dict[tuple[int, str], dict[str, Any]] = {}
    identity_resolutions: list[dict[str, Any]] = []
    with db.get_readonly_connection(creator_database) as connection:
        for telegram_id, creator_messages in grouped.items():
            for week_key in {row["week_key"] for row in creator_messages}:
                credit = connection.execute("""SELECT id,status,week_key,message_id
                  FROM pop_submissions WHERE telegram_id=? AND week_key=?
                    AND deleted_at IS NULL""", (telegram_id, week_key)).fetchone()
                if credit:
                    existing_credits[(telegram_id, week_key)] = dict(credit)
        identity_resolutions = [_unmatched_resolution(connection, telegram_id, values)
            for telegram_id, identity in identities.items()
            if not identity["creator_matched"]]
    identity_resolutions.sort(key=lambda row: row["telegram_id"])

    sections = {key: [] for key in SECTION_ORDER}
    for telegram_id, creator_messages in grouped.items():
        creator_messages.sort(key=lambda row: (row["original_timestamp"], row["message_id"]))
        identity = identities[telegram_id]
        qualified = [row for row in creator_messages if row["status"] == "qualified"]
        review = [row for row in creator_messages if row["status"] == "needs_review"]
        unqualified = [row for row in creator_messages if row["status"] == "unqualified"]
        comparison = qualified[0] if qualified else review[0] if review else unqualified[0]
        existing_credit = existing_credits.get((telegram_id, comparison["week_key"]))
        if existing_credit:
            section = "already_credited_skipped"
            outcome, eligibility_reason, primary = (
                "Skipped — POP Credit Already Exists", "existing_weekly_credit", comparison)
        elif not identity["eligible_for_recovery"]:
            section = "unmatched_inactive"
            if not identity["creator_matched"]:
                outcome, eligibility_reason = "Not Eligible — Unmatched Telegram ID", "creator_not_found"
            elif identity["creator_archived"]:
                outcome, eligibility_reason = "Not Eligible — Archived Creator", "creator_archived"
            else:
                status = identity.get("creator_status") or "unknown"
                outcome, eligibility_reason = f"Not Eligible — {status.title()} Creator", "creator_not_active"
            primary = qualified[0] if qualified else review[0] if review else creator_messages[0]
        elif qualified:
            section = "ready_to_recover"
            outcome, eligibility_reason, primary = "Ready to Recover", None, qualified[0]
        elif review:
            section = "needs_owner_review"
            outcome, eligibility_reason, primary = "Needs Owner Review", "ambiguous_evidence", review[0]
        else:
            section = "not_eligible_unqualified"
            outcome, eligibility_reason, primary = "Not Eligible / Unqualified", "no_qualified_evidence", unqualified[0]
        additional = [row for row in creator_messages if row is not primary]
        recovery_status = {
            "ready_to_recover": "ready_to_recover",
            "already_credited_skipped": "already_credited",
            "needs_owner_review": "needs_owner_review",
            "not_eligible_unqualified": "unqualified",
            "unmatched_inactive": "ineligible",
        }[section]
        sections[section].append({
            "telegram_id": telegram_id,
            "creator_name": identity.get("approved_creator_name") or identity.get("display_name"),
            "username": _username(identity.get("username")),
            "identity_label": _identity_label(identity),
            "creator_matched": identity["creator_matched"],
            "creator_status": identity.get("creator_status"),
            "creator_archived": identity["creator_archived"],
            "eligible_for_recovery": identity["eligible_for_recovery"],
            "final_outcome": outcome,
            "recovery_status": recovery_status,
            "include_in_future_write_set": section == "ready_to_recover",
            "eligibility_reason": eligibility_reason,
            "earliest_qualifying_timestamp": (
                qualified[0]["original_timestamp"] if qualified else None),
            "earliest_qualifying_timestamp_display": (
                qualified[0]["original_timestamp_display"] if qualified else None),
            "primary_evidence": primary,
            "selected_recovery_evidence": primary if section == "ready_to_recover" else None,
            "comparison_evidence": primary if section == "already_credited_skipped" else None,
            "additional_messages_found": len(additional),
            "additional_messages": additional,
            "unqualified_or_review_reasons": [
                {"message_id": row["message_id"], "status": row["status"], "reason": row["reason"]}
                for row in creator_messages if row["status"] in {"unqualified", "needs_review"}
            ],
            "existing_credit": existing_credit,
        })
    for rows in sections.values():
        rows.sort(key=lambda row: (row["identity_label"].casefold(), row["telegram_id"]))
    message_totals = {
        "total": len(messages),
        "qualified": sum(row.get("pop_decision") == "qualified" for row in messages),
        "needs_review": sum(row.get("pop_decision") == "needs_review" for row in messages),
        "unqualified": sum(row.get("pop_decision") == "unqualified" for row in messages),
    }
    creator_totals = {
        "total": len(grouped),
        "ready_to_recover": len(sections["ready_to_recover"]),
        "already_credited_skipped": len(sections["already_credited_skipped"]),
        "needs_owner_review": len(sections["needs_owner_review"]),
        "not_eligible_unqualified": len(sections["not_eligible_unqualified"]),
        "unmatched_inactive": len(sections["unmatched_inactive"]),
    }
    recovery_candidates = [{
        "telegram_id": row["telegram_id"],
        "creator_name": row["creator_name"],
        "username": row["username"],
        "week_key": row["selected_recovery_evidence"]["week_key"],
        "message_id": row["selected_recovery_evidence"]["message_id"],
        "original_timestamp": row["selected_recovery_evidence"]["original_timestamp"],
        "original_timestamp_display": row["selected_recovery_evidence"]["original_timestamp_display"],
        "proof_type": row["selected_recovery_evidence"]["proof_type"],
    } for row in sections["ready_to_recover"]]
    return {"read_only": True, "timezone": timezone_name,
        "message_totals": message_totals, "creator_totals": creator_totals,
        "sections": sections, "recovery_candidates": recovery_candidates,
        "unmatched_identity_resolution": identity_resolutions}


def render_owner_report(report: Mapping[str, Any]) -> str:
    """Render a grouped report without exposing raw Telegram content."""

    messages=report["message_totals"];creators=report["creator_totals"]
    lines=["POP History Recovery · Owner Dry Run","",
        f"Timezone: {report['timezone']}",
        (f"Creator totals: {creators['total']} total · {creators['ready_to_recover']} ready · "
         f"{creators['already_credited_skipped']} already credited/skipped · "
         f"{creators['needs_owner_review']} needs review · "
         f"{creators['not_eligible_unqualified']} unqualified · "
         f"{creators['unmatched_inactive']} unmatched/inactive"),
        (f"Message totals: {messages['total']} total · {messages['qualified']} qualified · "
         f"{messages['needs_review']} needs review · {messages['unqualified']} unqualified")]
    for section in SECTION_ORDER:
        lines += ["", SECTION_TITLES[section]]
        rows=report["sections"][section]
        if not rows:
            lines.append("• None")
            continue
        for row in rows:
            primary=row["primary_evidence"]
            evidence_label=("Selected recovery evidence"
                if row["selected_recovery_evidence"] else
                "Historical evidence for comparison" if row["comparison_evidence"] else
                "Evidence")
            lines += ["",f"• {row['identity_label']}",f"  Telegram ID: {row['telegram_id']}",
                f"  Outcome: {row['final_outcome']}",
                f"  {evidence_label}: {primary['original_timestamp_display']}",
                f"  Proof: {primary['proof_type']} · message {primary['message_id']}",
                f"  Additional messages found: {row['additional_messages_found']}"]
            if row.get("eligibility_reason"):lines.append(f"  Eligibility reason: {row['eligibility_reason']}")
            if row.get("existing_credit"):
                credit=row["existing_credit"]
                lines.append(
                    f"  Existing credit: week {credit['week_key']} · status {credit['status']} · "
                    f"submission {credit['id']}")
            for extra in row["additional_messages"]:
                lines.append(f"    - message {extra['message_id']} · {extra['original_timestamp_display']} · "
                    f"{extra['proof_type']} · {extra['status']} · {extra['reason']}")
            for reason in row["unqualified_or_review_reasons"]:
                if reason["message_id"] == primary["message_id"] or not any(
                    extra["message_id"] == reason["message_id"] for extra in row["additional_messages"]):
                    lines.append(f"  {reason['status'].replace('_',' ').title()} reason: {reason['reason']}")
    lines += ["", "Unmatched Identity Resolution"]
    resolutions=report.get("unmatched_identity_resolution", [])
    if not resolutions:
        lines.append("• None")
    for resolution in resolutions:
        lines += ["", f"• Telegram ID {resolution['telegram_id']}",
            f"  Resolution: {resolution['resolution_status']}",
            f"  Exact reason: {resolution['exact_reason']}",
            "  Immutable-ID source checks:"]
        for check in resolution["source_checks"]:
            marker="found" if check["found"] else "not found"
            lines.append(f"    - {check['source']}: {marker} · {check['detail']}")
        action=resolution["identify_creator_action"]
        lines += [f"  Owner review action: {action['label']} (not enabled)",
            "  Requires explicit Owner confirmation and audit logging before any identity link."]
    return "\n".join(lines)
