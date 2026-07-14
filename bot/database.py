"""Durable SQLite storage for creator engagement and POP compliance."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DATABASE_PATH = Path(__file__).with_name("vad_tracker.db")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection(path: Path | None = None):
    connection = sqlite3.connect(path or DATABASE_PATH)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(path: Path | None = None):
    with get_connection(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version(version)
          SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
        CREATE TABLE IF NOT EXISTS creators (
          telegram_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','active','inactive','rejected')),
          vacation_until TEXT, last_meaningful_at TEXT, registered_at TEXT NOT NULL,
          approved_at TEXT, approved_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS engagement_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER NOT NULL,
          message_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, thread_id INTEGER,
          normalized_hash TEXT, decision TEXT NOT NULL, reason TEXT NOT NULL,
          created_at TEXT NOT NULL, FOREIGN KEY(telegram_id) REFERENCES creators(telegram_id),
          UNIQUE(chat_id, message_id)
        );
        CREATE INDEX IF NOT EXISTS engagement_creator_time ON engagement_events(telegram_id, created_at);
        CREATE TABLE IF NOT EXISTS notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER NOT NULL,
          cycle_at TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('warning','alert')),
          sent_at TEXT NOT NULL, UNIQUE(telegram_id, cycle_at, kind),
          FOREIGN KEY(telegram_id) REFERENCES creators(telegram_id)
        );
        CREATE TABLE IF NOT EXISTS pop_submissions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER NOT NULL,
          week_key TEXT NOT NULL, message_id INTEGER NOT NULL, chat_id INTEGER NOT NULL,
          thread_id INTEGER, proof_type TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
          submitted_at TEXT NOT NULL, reviewed_at TEXT, reviewed_by INTEGER, review_note TEXT,
          FOREIGN KEY(telegram_id) REFERENCES creators(telegram_id),
          UNIQUE(telegram_id, week_key)
        );
        CREATE TABLE IF NOT EXISTS audit_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER NOT NULL,
          target_id INTEGER, action TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL
        );
        """)
        _migrate_legacy_schema(db)


def _columns(db, table):
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}


def _add_columns(db, table, definitions):
    existing = _columns(db, table)
    for name, definition in definitions.items():
        if name not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _migrate_legacy_schema(db):
    """Upgrade the tracker stub uploaded before versioned migrations existed."""
    _add_columns(db, "creators", {
        "status": "TEXT NOT NULL DEFAULT 'pending'",
        "registered_at": "TEXT", "approved_at": "TEXT", "approved_by": "INTEGER",
    })
    creator_columns = _columns(db, "creators")
    if "date_added" in creator_columns:
        db.execute("UPDATE creators SET registered_at=COALESCE(registered_at,date_added,?)", (utc_now(),))
    else:
        db.execute("UPDATE creators SET registered_at=COALESCE(registered_at,?)", (utc_now(),))
    if "active" in creator_columns:
        db.execute("UPDATE creators SET status=CASE WHEN active=1 THEN 'active' ELSE 'inactive' END WHERE status='pending'")
    _add_columns(db, "engagement_events", {
        "thread_id": "INTEGER", "normalized_hash": "TEXT", "decision": "TEXT",
        "reason": "TEXT",
    })
    db.execute("UPDATE engagement_events SET decision=COALESCE(decision,'accepted'), reason=COALESCE(reason,'legacy')")
    _add_columns(db, "pop_submissions", {
        "week_key": "TEXT", "reviewed_at": "TEXT",
    })
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS engagement_message_unique ON engagement_events(chat_id,message_id)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS pop_creator_week_unique ON pop_submissions(telegram_id,week_key) WHERE week_key IS NOT NULL")


def register_creator(telegram_id, username, display_name, path=None):
    now = utc_now()
    with get_connection(path) as db:
        db.execute("""INSERT INTO creators(telegram_id,username,display_name,registered_at)
          VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
          username=excluded.username, display_name=excluded.display_name""",
          (telegram_id, username, display_name, now))


def get_creator(telegram_id, path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM creators WHERE telegram_id=?", (telegram_id,)).fetchone()


def list_creators(path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM creators ORDER BY display_name COLLATE NOCASE").fetchall()


def set_status(target_id, status, actor_id, path=None):
    now = utc_now()
    with get_connection(path) as db:
        cur = db.execute("UPDATE creators SET status=?, approved_at=CASE WHEN ?='active' THEN ? ELSE approved_at END, approved_by=CASE WHEN ?='active' THEN ? ELSE approved_by END WHERE telegram_id=?",
                         (status, status, now, status, actor_id, target_id))
        if not cur.rowcount:
            return False
        _audit(db, actor_id, target_id, "status", {"status": status}, now)
        return True


def set_vacation(target_id, until, actor_id, path=None):
    with get_connection(path) as db:
        cur = db.execute("UPDATE creators SET vacation_until=? WHERE telegram_id=?", (until, target_id))
        if cur.rowcount:
            _audit(db, actor_id, target_id, "vacation", {"until": until})
        return bool(cur.rowcount)


def record_engagement(telegram_id, message_id, chat_id, thread_id, normalized_hash, decision, reason, path=None):
    now = utc_now()
    with get_connection(path) as db:
        try:
            db.execute("INSERT INTO engagement_events(telegram_id,message_id,chat_id,thread_id,normalized_hash,decision,reason,created_at) VALUES(?,?,?,?,?,?,?,?)",
                       (telegram_id,message_id,chat_id,thread_id,normalized_hash,decision,reason,now))
        except sqlite3.IntegrityError:
            return False
        if decision == "accepted":
            db.execute("UPDATE creators SET last_meaningful_at=? WHERE telegram_id=?", (now,telegram_id))
        return True


def recent_hash_exists(telegram_id, normalized_hash, since, path=None):
    with get_connection(path) as db:
        return bool(db.execute("SELECT 1 FROM engagement_events WHERE telegram_id=? AND normalized_hash=? AND decision='accepted' AND created_at>=? LIMIT 1",
                               (telegram_id, normalized_hash, since)).fetchone())


def due_creators(path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM creators WHERE status='active'").fetchall()


def claim_notification(telegram_id, cycle_at, kind, path=None):
    with get_connection(path) as db:
        try:
            db.execute("INSERT INTO notifications(telegram_id,cycle_at,kind,sent_at) VALUES(?,?,?,?)", (telegram_id,cycle_at,kind,utc_now()))
            return True
        except sqlite3.IntegrityError:
            return False


def submit_pop(telegram_id, week_key, message_id, chat_id, thread_id, proof_type, path=None):
    with get_connection(path) as db:
        try:
            db.execute("INSERT INTO pop_submissions(telegram_id,week_key,message_id,chat_id,thread_id,proof_type,submitted_at) VALUES(?,?,?,?,?,?,?)",
                       (telegram_id,week_key,message_id,chat_id,thread_id,proof_type,utc_now()))
            return True
        except sqlite3.IntegrityError:
            return False


def review_pop(submission_id, status, actor_id, note="", path=None):
    with get_connection(path) as db:
        cur=db.execute("UPDATE pop_submissions SET status=?,reviewed_at=?,reviewed_by=?,review_note=? WHERE id=? AND status='pending'",
                       (status,utc_now(),actor_id,note,submission_id))
        if cur.rowcount:
            _audit(db,actor_id,None,"pop_review",{"submission_id":submission_id,"status":status})
        return bool(cur.rowcount)


def pop_report(week_key, path=None):
    with get_connection(path) as db:
        return db.execute("""SELECT c.telegram_id,c.display_name,p.id,p.status,p.submitted_at
          FROM creators c LEFT JOIN pop_submissions p ON p.telegram_id=c.telegram_id AND p.week_key=?
          WHERE c.status='active' ORDER BY c.display_name COLLATE NOCASE""", (week_key,)).fetchall()


def history(limit=50, path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM audit_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def _audit(db, actor_id, target_id, action, details, now=None):
    db.execute("INSERT INTO audit_history(actor_id,target_id,action,details,created_at) VALUES(?,?,?,?,?)",
               (actor_id,target_id,action,json.dumps(details,sort_keys=True),now or utc_now()))
