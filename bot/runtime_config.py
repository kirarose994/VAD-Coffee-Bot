"""Persist and restore owner-approved operational configuration.

Environment configuration remains the bootstrap source. Owner changes are stored in the
existing append-safe SQLite system-state table and are reapplied after database startup.
Every change also creates an audit event.
"""

import json
from zoneinfo import ZoneInfo

import database as db
from constants import PERSISTED_SETTING_ATTRIBUTES, SETTING_PREFIX


def _decode(key, raw):
    value = json.loads(raw)
    if key in {"participation_topic_ids","admin_user_ids","lead_admin_user_ids","owner_user_ids"}:
        return frozenset(int(item) for item in value)
    if key == "timezone_name":
        ZoneInfo(str(value))
    return value


def apply_persisted_settings(config, path=None):
    """Overlay valid database-backed settings without exposing or changing secrets."""
    state = db.system_state(path)
    for key, attribute in PERSISTED_SETTING_ATTRIBUTES.items():
        row = state.get(SETTING_PREFIX + key)
        if not row:
            continue
        try:
            setattr(config, attribute, _decode(key, row["value"]))
        except (TypeError, ValueError, KeyError):
            # Invalid persisted data is ignored; the environment/default remains active.
            continue
    # One-time compatibility migration: stored elevated administrators become regular
    # Admins unless their immutable ID already belongs to an Owner.
    legacy = set(getattr(config,"lead_admin_user_ids",frozenset()))
    owners = set(getattr(config,"owner_user_ids",frozenset()))
    config.admin_user_ids = frozenset((set(getattr(config,"admin_user_ids",frozenset())) | legacy) - owners)
    config.lead_admin_user_ids = frozenset()
    return config


def persist_setting(config, key, value, actor_id, path=None):
    """Update one allow-listed runtime setting, persist it, and append an audit record."""
    attribute = PERSISTED_SETTING_ATTRIBUTES.get(key)
    if not attribute:
        raise ValueError("Unsupported operational setting")
    if key == "timezone_name":
        ZoneInfo(str(value))
    if key in {"participation_topic_ids","admin_user_ids","lead_admin_user_ids","owner_user_ids"}:
        value = frozenset(int(item) for item in value)
        encoded = json.dumps(sorted(value))
    else:
        encoded = json.dumps(value)
    previous = getattr(config, attribute)
    setattr(config, attribute, value)
    db.set_system_state(SETTING_PREFIX + key, encoded, path)
    db.audit_setting_change(actor_id, key, previous, value, path)
    if key in {"admin_user_ids","lead_admin_user_ids","owner_user_ids"}:
        db.synchronize_role_memberships(config,path)
    return previous
