"""Read-only diagnostic for Eve's Telegram identity in the live SQLite database."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


TELEGRAM_ID = 8129455408
DATABASE_PATH = Path(__file__).resolve().parent / "bot" / "vad_tracker.db"
TABLES = ("bot_users", "community_members", "creators", "user_roles")
ROLE_SETTING_KEYS = {
    "owner": "config:owner_user_ids",
    "admin": "config:admin_user_ids",
    "legacy_elevated": "config:lead_admin_user_ids",
}


def heading(label: str) -> None:
    print(f"\n{'=' * 12} {label} {'=' * 12}")


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def columns_for(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def print_rows(connection: sqlite3.Connection, table: str) -> None:
    heading(table)
    if not table_exists(connection, table):
        print("Table is missing.")
        return
    if "telegram_id" not in columns_for(connection, table):
        print("Column telegram_id is missing.")
        return
    rows = connection.execute(
        f'SELECT * FROM "{table}" WHERE telegram_id=?', (TELEGRAM_ID,)
    ).fetchall()
    print(json.dumps([dict(row) for row in rows], indent=2, default=str))
    if not rows:
        print("No matching rows.")


def print_audit_events(connection: sqlite3.Connection) -> None:
    heading("recent relevant audit_events")
    table = "audit_events"
    if not table_exists(connection, table):
        print("Table is missing.")
        return
    columns = columns_for(connection, table)
    predicates = []
    values: list[int] = []
    if "target_telegram_id" in columns:
        predicates.append("target_telegram_id=?")
        values.append(TELEGRAM_ID)
    else:
        print("Column target_telegram_id is missing.")
    if "actor_id" in columns:
        predicates.append("actor_id=?")
        values.append(TELEGRAM_ID)
    else:
        print("Column actor_id is missing.")
    if not predicates:
        print("No supported identity columns are available.")
        return
    preferred = (
        "id", "occurred_at", "actor_id", "actor_name", "actor_role", "action",
        "target_type", "target_record_id", "target_telegram_id", "previous_value",
        "new_value", "reason", "result", "error_reference",
    )
    selected = [column for column in preferred if column in columns]
    order = "id DESC" if "id" in columns else (
        "occurred_at DESC" if "occurred_at" in columns else "rowid DESC"
    )
    sql = (
        f'SELECT {", ".join(selected)} FROM "{table}" '
        f'WHERE {" OR ".join(predicates)} ORDER BY {order} LIMIT 30'
    )
    rows = connection.execute(sql, values).fetchall()
    print(json.dumps([dict(row) for row in rows], indent=2, default=str))
    if not rows:
        print("No matching audit events.")


def parse_id_environment(name: str) -> set[int]:
    values: set[int] = set()
    for item in os.environ.get(name, "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            values.add(int(item))
        except ValueError:
            pass
    return values


def decode_persisted_ids(value: str) -> set[int] | None:
    try:
        decoded: Any = json.loads(value)
        if not isinstance(decoded, list):
            return None
        return {int(item) for item in decoded}
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def persisted_role_ids(
    connection: sqlite3.Connection, key: str
) -> set[int] | None:
    if not table_exists(connection, "system_state"):
        return None
    columns = columns_for(connection, "system_state")
    if not {"state_key", "state_value"}.issubset(columns):
        return None
    row = connection.execute(
        "SELECT state_value FROM system_state WHERE state_key=?", (key,)
    ).fetchone()
    return decode_persisted_ids(row["state_value"]) if row else None


def print_effective_roles(connection: sqlite3.Connection) -> None:
    heading("effective configured roles")
    owners = parse_id_environment("OWNER_USER_IDS") | parse_id_environment(
        "OWNER_TELEGRAM_IDS"
    )
    legacy = parse_id_environment("LEAD_ADMIN_USER_IDS")
    admins = (parse_id_environment("ADMIN_USER_IDS") | legacy) - owners

    persisted_owner = persisted_role_ids(connection, ROLE_SETTING_KEYS["owner"])
    persisted_admin = persisted_role_ids(connection, ROLE_SETTING_KEYS["admin"])
    persisted_legacy = persisted_role_ids(
        connection, ROLE_SETTING_KEYS["legacy_elevated"]
    )
    if persisted_owner is not None:
        owners = persisted_owner
    if persisted_admin is not None:
        admins = persisted_admin
    if persisted_legacy is not None:
        legacy = persisted_legacy

    legacy_source = TELEGRAM_ID in legacy
    # Match the application's compatibility behavior without printing configuration values.
    admins = (admins | legacy) - owners
    legacy = set()
    print(f"Owner: {TELEGRAM_ID in owners}")
    print(f"Admin: {TELEGRAM_ID in admins or TELEGRAM_ID in owners}")
    print(f"Legacy elevated-admin source configured: {legacy_source}")
    print(f"Legacy elevated-admin configuration: {TELEGRAM_ID in legacy}")
    print("No secret values were displayed.")


def main() -> int:
    print("Eve identity diagnostic (read-only)")
    print(f"Telegram ID: {TELEGRAM_ID}")
    print(f"Database: {DATABASE_PATH}")
    if not DATABASE_PATH.is_file():
        print("Database file is missing.")
        return 1
    uri = f"file:{DATABASE_PATH.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            for table in TABLES:
                print_rows(connection, table)
            print_audit_events(connection)
            print_effective_roles(connection)
    except sqlite3.Error as exc:
        print(f"SQLite diagnostic failed safely: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
