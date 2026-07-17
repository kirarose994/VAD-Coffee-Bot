"""Durable SQLite storage for creator engagement and POP compliance."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from pop_policy import calculate_status, current_period

DATABASE_PATH = Path(__file__).with_name("vad_tracker.db")


def utc_now() -> str:
    """Legacy function name; persisted operational timestamps are Eastern Time."""
    return datetime.now(ZoneInfo("America/New_York")).isoformat()


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
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','resubmission_requested','excused')),
          submitted_at TEXT NOT NULL, reviewed_at TEXT, reviewed_by INTEGER, review_note TEXT,
          preservation_status TEXT NOT NULL DEFAULT 'pending_24h',
          preservation_due_at TEXT, preservation_checked_at TEXT,
          preservation_reviewed_by INTEGER, preservation_note TEXT,
          preservation_alerted_at TEXT,
          timing_status TEXT, source_message_at TEXT, observed_at TEXT,
          recovered_after_outage INTEGER NOT NULL DEFAULT 0,
          needs_review_reason TEXT, source_update_id INTEGER,
          FOREIGN KEY(telegram_id) REFERENCES creators(telegram_id),
          UNIQUE(telegram_id, week_key)
        );
        CREATE TABLE IF NOT EXISTS pop_evidence (
          id INTEGER PRIMARY KEY AUTOINCREMENT, submission_id INTEGER,
          telegram_id INTEGER NOT NULL, week_key TEXT NOT NULL,
          message_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, thread_id INTEGER,
          update_id INTEGER, proof_type TEXT NOT NULL, confidence TEXT NOT NULL,
          source_message_at TEXT NOT NULL, observed_at TEXT NOT NULL,
          recovered_after_outage INTEGER NOT NULL DEFAULT 0,
          relationship TEXT NOT NULL DEFAULT 'primary',
          FOREIGN KEY(submission_id) REFERENCES pop_submissions(id),
          FOREIGN KEY(telegram_id) REFERENCES creators(telegram_id),
          UNIQUE(chat_id,message_id)
        );
        CREATE INDEX IF NOT EXISTS pop_evidence_creator_time
          ON pop_evidence(telegram_id,week_key,source_message_at);
        CREATE TABLE IF NOT EXISTS recovery_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
          previous_heartbeat_at TEXT, catchup_until TEXT NOT NULL,
          completed_at TEXT, confidence TEXT NOT NULL DEFAULT 'unknown',
          status TEXT NOT NULL DEFAULT 'catching_up',
          updates_recovered INTEGER NOT NULL DEFAULT 0,
          pop_recovered INTEGER NOT NULL DEFAULT 0,
          participation_recovered INTEGER NOT NULL DEFAULT 0,
          away_recovered INTEGER NOT NULL DEFAULT 0,
          pop_on_time INTEGER NOT NULL DEFAULT 0, pop_late INTEGER NOT NULL DEFAULT 0,
          pop_excused INTEGER NOT NULL DEFAULT 0, pop_needs_review INTEGER NOT NULL DEFAULT 0,
          unresolved_gap TEXT, summary_claimed_at TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_open_recovery_run
          ON recovery_runs(status) WHERE status='catching_up';
        CREATE TABLE IF NOT EXISTS processed_updates (
          update_id INTEGER PRIMARY KEY, update_type TEXT NOT NULL,
          source_message_at TEXT, processed_at TEXT NOT NULL,
          recovered_after_outage INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS audit_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER NOT NULL,
          target_id INTEGER, action TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS absence_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          telegram_id INTEGER NOT NULL,
          absence_type TEXT NOT NULL CHECK(absence_type IN ('vacation','sick')),
          start_date TEXT NOT NULL, end_date TEXT NOT NULL, note TEXT,
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','denied','cancelled')),
          submitted_at TEXT NOT NULL, reviewed_at TEXT, reviewed_by INTEGER,
          review_reason TEXT, clarification_requested_at TEXT,
          original_snapshot TEXT NOT NULL, deleted_at TEXT, deleted_by INTEGER,
          deletion_reason TEXT, restored_at TEXT, restored_by INTEGER, restoration_reason TEXT,
          FOREIGN KEY(telegram_id) REFERENCES creators(telegram_id)
        );
        CREATE INDEX IF NOT EXISTS absence_creator_dates ON absence_requests(telegram_id,start_date,end_date,status);
        CREATE INDEX IF NOT EXISTS absence_queue ON absence_requests(status,absence_type,submitted_at);
        CREATE TABLE IF NOT EXISTS availability_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER NOT NULL,
          previous_status TEXT, new_status TEXT NOT NULL, changed_at TEXT NOT NULL,
          changed_by INTEGER NOT NULL, expires_at TEXT, reason TEXT,
          FOREIGN KEY(telegram_id) REFERENCES creators(telegram_id)
        );
        CREATE TABLE IF NOT EXISTS admin_notes (
          id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER NOT NULL,
          note TEXT NOT NULL, created_at TEXT NOT NULL, created_by INTEGER NOT NULL,
          updated_at TEXT, updated_by INTEGER, deleted_at TEXT, deleted_by INTEGER,
          deletion_reason TEXT, FOREIGN KEY(telegram_id) REFERENCES creators(telegram_id)
        );
        CREATE TABLE IF NOT EXISTS audit_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL,
          actor_id INTEGER, actor_name TEXT, actor_role TEXT NOT NULL,
          action TEXT NOT NULL, target_type TEXT, target_record_id INTEGER,
          target_telegram_id INTEGER, previous_value TEXT, new_value TEXT,
          reason TEXT, source_chat_id INTEGER, source_thread_id INTEGER,
          related_request_id INTEGER, related_submission_id INTEGER,
          result TEXT NOT NULL DEFAULT 'success', error_reference TEXT
        );
        CREATE INDEX IF NOT EXISTS audit_events_time ON audit_events(occurred_at DESC);
        CREATE INDEX IF NOT EXISTS audit_events_actor ON audit_events(actor_id,occurred_at DESC);
        CREATE TABLE IF NOT EXISTS announcements (
          id INTEGER PRIMARY KEY AUTOINCREMENT, audience TEXT NOT NULL, body TEXT NOT NULL,
          created_at TEXT NOT NULL, created_by INTEGER NOT NULL, sent_at TEXT,
          delivered_count INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS pop_excuses (
          id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER NOT NULL,
          week_key TEXT NOT NULL, absence_request_id INTEGER NOT NULL,
          created_at TEXT NOT NULL, created_by INTEGER NOT NULL,
          UNIQUE(telegram_id,week_key),
          FOREIGN KEY(telegram_id) REFERENCES creators(telegram_id),
          FOREIGN KEY(absence_request_id) REFERENCES absence_requests(id)
        );
        CREATE TABLE IF NOT EXISTS resources (
          resource_key TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
          updated_at TEXT NOT NULL, updated_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS creator_warnings (
          id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER NOT NULL,
          warning_type TEXT NOT NULL CHECK(warning_type IN ('warning','strike')),
          reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active'
            CHECK(status IN ('active','acknowledged','removed')),
          issued_at TEXT NOT NULL, issued_by INTEGER NOT NULL,
          acknowledged_at TEXT, acknowledged_by INTEGER,
          removed_at TEXT, removed_by INTEGER, removal_reason TEXT,
          FOREIGN KEY(telegram_id) REFERENCES creators(telegram_id)
        );
        CREATE INDEX IF NOT EXISTS creator_warnings_status
          ON creator_warnings(telegram_id,status,warning_type,issued_at DESC);
        CREATE TABLE IF NOT EXISTS message_templates (
          template_key TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
          category TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
          updated_at TEXT NOT NULL, updated_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS owner_summary_deliveries (
          owner_id INTEGER NOT NULL, cycle_key TEXT NOT NULL, claimed_at TEXT NOT NULL,
          PRIMARY KEY(owner_id,cycle_key)
        );
        CREATE TABLE IF NOT EXISTS community_members (
          telegram_id INTEGER PRIMARY KEY, member_type TEXT NOT NULL DEFAULT 'buyer'
            CHECK(member_type IN ('creator','buyer','community')),
          display_name TEXT NOT NULL, username TEXT, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS member_warnings (
          id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER NOT NULL,
          warning_type TEXT NOT NULL CHECK(warning_type IN ('warning','strike')),
          reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
          issued_at TEXT NOT NULL, issued_by INTEGER NOT NULL, acknowledged_at TEXT,
          acknowledged_by INTEGER, template_key TEXT, notes TEXT,
          deleted_at TEXT, deleted_by INTEGER, deletion_reason TEXT,
          FOREIGN KEY(telegram_id) REFERENCES community_members(telegram_id)
        );
        CREATE TABLE IF NOT EXISTS template_revisions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, template_key TEXT NOT NULL,
          previous_body TEXT NOT NULL, new_body TEXT NOT NULL, changed_at TEXT NOT NULL,
          changed_by INTEGER NOT NULL, reason TEXT,
          FOREIGN KEY(template_key) REFERENCES message_templates(template_key)
        );
        CREATE TABLE IF NOT EXISTS system_state (
          state_key TEXT PRIMARY KEY, state_value TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS support_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER NOT NULL,
          category TEXT NOT NULL, message TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','assigned','escalated','resolved')),
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, assigned_to INTEGER,
          resolved_at TEXT, resolved_by INTEGER, resolution_note TEXT,
          delivery_status TEXT NOT NULL DEFAULT 'pending', delivery_error_ref TEXT,
          FOREIGN KEY(telegram_id) REFERENCES creators(telegram_id)
        );
        CREATE INDEX IF NOT EXISTS support_queue ON support_requests(status,created_at);
        CREATE TABLE IF NOT EXISTS support_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL,
          sender_id INTEGER NOT NULL, sender_role TEXT NOT NULL, body TEXT NOT NULL,
          created_at TEXT NOT NULL, delivered_at TEXT, delivery_error_ref TEXT,
          FOREIGN KEY(request_id) REFERENCES support_requests(id)
        );
        CREATE TABLE IF NOT EXISTS delivery_failures (
          id INTEGER PRIMARY KEY AUTOINCREMENT, error_reference TEXT NOT NULL UNIQUE,
          event_type TEXT NOT NULL, destination_chat_id INTEGER,
          destination_thread_id INTEGER, payload_summary TEXT,
          created_at TEXT NOT NULL, resolved_at TEXT, retry_claimed_at TEXT,
          retry_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS delivery_failures_open ON delivery_failures(resolved_at,created_at);
        CREATE TABLE IF NOT EXISTS bot_users (
          telegram_id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, username TEXT,
          first_started_at TEXT NOT NULL, last_started_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_roles (
          telegram_id INTEGER NOT NULL, role TEXT NOT NULL
            CHECK(role IN ('creator','admin','owner')),
          active INTEGER NOT NULL DEFAULT 1, assigned_at TEXT NOT NULL,
          assigned_by INTEGER, removed_at TEXT, removed_by INTEGER,
          PRIMARY KEY(telegram_id,role)
        );
        CREATE INDEX IF NOT EXISTS user_roles_active ON user_roles(role,active,telegram_id);
        CREATE TABLE IF NOT EXISTS daily_brief_deliveries (
          cycle_date TEXT PRIMARY KEY, claimed_at TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('pending','sent','failed')),
          sent_at TEXT, error_reference TEXT
        );
        CREATE TABLE IF NOT EXISTS system_incidents (
          id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL,
          error_reference TEXT NOT NULL UNIQUE, category TEXT NOT NULL,
          source TEXT NOT NULL, exception_type TEXT NOT NULL, message TEXT,
          traceback TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
          occurrence_count INTEGER NOT NULL DEFAULT 1,
          status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved')),
          resolved_at TEXT, operation TEXT, escalated_at TEXT, resolution_reason TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS system_incidents_one_open
          ON system_incidents(fingerprint) WHERE status='open';
        CREATE TABLE IF NOT EXISTS process_leases (
          lease_name TEXT PRIMARY KEY,
          instance_id TEXT NOT NULL,
          acquired_at TEXT NOT NULL,
          heartbeat_at TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          startup_source TEXT
        );
        """)
        _migrate_legacy_schema(db)
        _seed_message_templates(db)
        db.execute("UPDATE schema_version SET version=13")


DEFAULT_MESSAGE_TEMPLATES = {
    "friendly_reminder": ("Friendly Reminder", "Hi {name}! Just a friendly check-in from the VAD team. 💛", "community"),
    "participation_reminder": ("Participation Reminder", "Hi {name}! Meaningful participation helps keep the community lively and gives members a reason to come back. Join a discussion, respond thoughtfully, or ask a genuine question when you can. Taking time away? Record an Away Notice so tracking stays fair.", "participation"),
    "two_day_reminder": ("Friendly Participation Check-In", "Hi {name}. We haven’t seen a meaningful message from you in a couple of days. Regular conversation helps keep the community lively and welcoming. There’s no pressure if life is busy—an Away Notice pauses participation expectations while you take time away.", "participation"),
    "three_day_followup": ("Three-Day Supportive Check-In", "Hi {name}. We still haven’t seen recent meaningful participation from you. Staying involved helps keep the community active and interesting. If you’re taking time away, use an Away Notice so reminders pause and your standing stays protected.", "participation"),
    "pop_reminder": ("POP Reminder", "Hi {name}! This is your friendly Thursday POP reminder. Please submit in the designated topic, or make sure an Away Notice is on file.", "pop"),
    "welcome": ("Welcome", "Welcome, {name}! The VAD Operations Bot is here to help you stay informed and keep participation tracking fair.", "welcome"),
    "community_checkin": ("Community Check-In", "Hi {name}! The team is checking in. Let us know if you need support or time away.", "community"),
    "missing_pop": ("Missing POP", "Hi {name}. Thursday POP has not been received for this week. Please submit in the designated topic or contact an admin if an Away Notice applies.", "pop"),
    "away_acknowledgement": ("Away Notice Acknowledgement", "Hi {name}. Your away notice has been acknowledged. Your community status and any applicable Thursday POP requirements have been updated. 💙", "away"),
    "clarification_request": ("Clarification Request", "Hi {name}. An admin needs a little more information about your Away Notice: {reason}", "away"),
    "good_standing": ("Good Standing", "Hi {name}! Your community status is in good standing. Thank you for participating. 💚", "community"),
    "owner_review_outcome": ("Owner Review Outcome", "Hi {name}. The owner review is complete: {reason}", "warning"),
    "warning": ("Warning Notice", "Hi {name}. A participation warning has been documented: {reason}. Please contact an admin if you need clarification or support.", "warning"),
    "strike": ("Strike Notice", "Hi {name}. A strike has been documented: {reason}. The record is available in your dashboard, and you may contact an admin for support.", "warning"),
}


def _seed_message_templates(db):
    now = utc_now()
    for key, (title, body, category) in DEFAULT_MESSAGE_TEMPLATES.items():
        db.execute("INSERT OR IGNORE INTO message_templates(template_key,title,body,category,updated_at) VALUES(?,?,?,?,?)",
                   (key,title,body,category,now))


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
    pop_columns_before = _columns(db, "pop_submissions")
    _add_columns(db, "pop_submissions", {
        "week_key": "TEXT", "reviewed_at": "TEXT", "deleted_at": "TEXT",
        "deleted_by": "INTEGER", "deletion_reason": "TEXT",
    })
    pop_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='pop_submissions'").fetchone()
    if pop_sql and "resubmission_requested" not in (pop_sql["sql"] or ""):
        db.execute("DROP INDEX IF EXISTS pop_creator_week_unique")
        db.execute("ALTER TABLE pop_submissions RENAME TO pop_submissions_v1")
        db.execute("""CREATE TABLE pop_submissions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER NOT NULL,
          week_key TEXT NOT NULL, message_id INTEGER NOT NULL, chat_id INTEGER NOT NULL,
          thread_id INTEGER, proof_type TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','resubmission_requested','excused')),
          submitted_at TEXT NOT NULL, reviewed_at TEXT, reviewed_by INTEGER, review_note TEXT,
          deleted_at TEXT, deleted_by INTEGER, deletion_reason TEXT,
          FOREIGN KEY(telegram_id) REFERENCES creators(telegram_id), UNIQUE(telegram_id,week_key))""")
        db.execute("""INSERT INTO pop_submissions
          (id,telegram_id,week_key,message_id,chat_id,thread_id,proof_type,status,submitted_at,
           reviewed_at,reviewed_by,review_note,deleted_at,deleted_by,deletion_reason)
          SELECT id,telegram_id,week_key,message_id,chat_id,thread_id,proof_type,status,submitted_at,
           reviewed_at,reviewed_by,review_note,deleted_at,deleted_by,deletion_reason FROM pop_submissions_v1""")
        db.execute("DROP TABLE pop_submissions_v1")
    _add_columns(db, "pop_submissions", {
        "preservation_status": "TEXT", "preservation_due_at": "TEXT",
        "preservation_checked_at": "TEXT", "preservation_reviewed_by": "INTEGER",
        "preservation_note": "TEXT", "preservation_alerted_at": "TEXT",
        "timing_status": "TEXT", "source_message_at": "TEXT", "observed_at": "TEXT",
        "recovered_after_outage": "INTEGER NOT NULL DEFAULT 0",
        "needs_review_reason": "TEXT", "source_update_id": "INTEGER",
    })
    if "preservation_status" not in pop_columns_before:
        # Existing records predate preservation tracking. Treat them as legacy rather
        # than generating a false review storm or claiming they were verified.
        db.execute("""UPDATE pop_submissions SET preservation_status='legacy_record'
          WHERE preservation_status IS NULL""")
    db.execute("""UPDATE pop_submissions SET source_message_at=COALESCE(source_message_at,submitted_at),
      observed_at=COALESCE(observed_at,submitted_at),timing_status=COALESCE(timing_status,'legacy')""")
    db.executescript("""CREATE TABLE IF NOT EXISTS pop_evidence (
      id INTEGER PRIMARY KEY AUTOINCREMENT,submission_id INTEGER,telegram_id INTEGER NOT NULL,
      week_key TEXT NOT NULL,message_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,thread_id INTEGER,
      update_id INTEGER,proof_type TEXT NOT NULL,confidence TEXT NOT NULL,
      source_message_at TEXT NOT NULL,observed_at TEXT NOT NULL,recovered_after_outage INTEGER NOT NULL DEFAULT 0,
      relationship TEXT NOT NULL DEFAULT 'primary',FOREIGN KEY(submission_id) REFERENCES pop_submissions(id),
      FOREIGN KEY(telegram_id) REFERENCES creators(telegram_id),UNIQUE(chat_id,message_id));
      CREATE INDEX IF NOT EXISTS pop_evidence_creator_time ON pop_evidence(telegram_id,week_key,source_message_at);
      CREATE TABLE IF NOT EXISTS recovery_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,started_at TEXT NOT NULL,previous_heartbeat_at TEXT,
      catchup_until TEXT NOT NULL,completed_at TEXT,confidence TEXT NOT NULL DEFAULT 'unknown',
      status TEXT NOT NULL DEFAULT 'catching_up',updates_recovered INTEGER NOT NULL DEFAULT 0,
      pop_recovered INTEGER NOT NULL DEFAULT 0,participation_recovered INTEGER NOT NULL DEFAULT 0,
      away_recovered INTEGER NOT NULL DEFAULT 0,pop_on_time INTEGER NOT NULL DEFAULT 0,
      pop_late INTEGER NOT NULL DEFAULT 0,pop_excused INTEGER NOT NULL DEFAULT 0,
      pop_needs_review INTEGER NOT NULL DEFAULT 0,unresolved_gap TEXT,summary_claimed_at TEXT);
      CREATE UNIQUE INDEX IF NOT EXISTS one_open_recovery_run ON recovery_runs(status) WHERE status='catching_up';
      CREATE TABLE IF NOT EXISTS processed_updates (
      update_id INTEGER PRIMARY KEY,update_type TEXT NOT NULL,source_message_at TEXT,processed_at TEXT NOT NULL,
      recovered_after_outage INTEGER NOT NULL DEFAULT 0);""")
    _add_columns(db, "creators", {
        "availability": "TEXT NOT NULL DEFAULT 'unavailable'",
        "availability_since": "TEXT", "availability_changed_by": "INTEGER",
        "availability_expires_at": "TEXT", "previous_availability": "TEXT",
        "availability_reason": "TEXT", "deleted_at": "TEXT", "deleted_by": "INTEGER",
        "deletion_reason": "TEXT", "restored_at": "TEXT", "restored_by": "INTEGER",
    })
    _add_columns(db, "audit_events", {"legacy_audit_id": "INTEGER"})
    _add_columns(db, "absence_requests", {"absence_category": "TEXT"})
    _add_columns(db, "system_incidents", {
        "operation": "TEXT", "escalated_at": "TEXT", "resolution_reason": "TEXT",
    })
    _add_columns(db, "creator_warnings", {
        "template_key": "TEXT", "notes": "TEXT", "updated_at": "TEXT",
        "updated_by": "INTEGER", "deleted_at": "TEXT", "deleted_by": "INTEGER",
        "deletion_reason": "TEXT", "restored_at": "TEXT", "restored_by": "INTEGER",
    })
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS audit_legacy_unique ON audit_events(legacy_audit_id) WHERE legacy_audit_id IS NOT NULL")
    if "audit_history" in {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        db.execute("""INSERT OR IGNORE INTO audit_events
          (occurred_at,actor_id,actor_role,action,target_type,target_telegram_id,new_value,result,legacy_audit_id)
          SELECT created_at,actor_id,'legacy',action,'legacy',target_id,details,'success',id FROM audit_history""")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS engagement_message_unique ON engagement_events(chat_id,message_id)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS pop_creator_week_unique ON pop_submissions(telegram_id,week_key) WHERE week_key IS NOT NULL")
    # Older creator rows predate the general member table. Backfill the shared identity so
    # role-aware menus never disagree with the creator directory after migration.
    now = utc_now()
    db.execute("""INSERT INTO community_members
      (telegram_id,member_type,display_name,username,created_at,updated_at)
      SELECT telegram_id,'creator',display_name,username,COALESCE(registered_at,?),?
      FROM creators WHERE 1
      ON CONFLICT(telegram_id) DO UPDATE SET member_type='creator',
      display_name=excluded.display_name,username=excluded.username,updated_at=excluded.updated_at""",(now,now))


def _lease_timestamp(value=None):
    """Return a timezone-aware UTC instant for process-lease comparisons."""
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError("Process lease timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _lease_connection(path=None):
    connection = sqlite3.connect(path or DATABASE_PATH, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def acquire_process_lease(lease_name, instance_id, ttl_seconds, startup_source=None,
                          path=None, now=None):
    """Atomically acquire or take over a clearly expired singleton lease.

    ``BEGIN IMMEDIATE`` serializes competing SQLite writers before either can
    inspect the current lease. Each process receives a unique instance ID, so a
    stale process can never refresh or release a successor's lease.
    """
    if not lease_name or not instance_id or ttl_seconds <= 0:
        raise ValueError("A lease name, instance ID, and positive TTL are required")
    current = _lease_timestamp(now)
    expires = current + timedelta(seconds=ttl_seconds)
    acquired_at = current.isoformat()
    connection = _lease_connection(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT instance_id,expires_at FROM process_leases WHERE lease_name=?",
            (lease_name,),
        ).fetchone()
        if row:
            try:
                active = _lease_timestamp(row["expires_at"]) > current
            except (TypeError, ValueError):
                # Corrupt or unverifiable ownership must fail closed.
                connection.rollback()
                return False
            if active and row["instance_id"] != instance_id:
                connection.rollback()
                return False
        connection.execute("""INSERT INTO process_leases
          (lease_name,instance_id,acquired_at,heartbeat_at,expires_at,startup_source)
          VALUES(?,?,?,?,?,?)
          ON CONFLICT(lease_name) DO UPDATE SET
          instance_id=excluded.instance_id,acquired_at=excluded.acquired_at,
          heartbeat_at=excluded.heartbeat_at,expires_at=excluded.expires_at,
          startup_source=excluded.startup_source""",
          (lease_name,instance_id,acquired_at,acquired_at,expires.isoformat(),
           (startup_source or "unknown")[:160]))
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def heartbeat_process_lease(lease_name, instance_id, ttl_seconds, path=None, now=None):
    """Extend an active lease only while the caller still owns it."""
    if not lease_name or not instance_id or ttl_seconds <= 0:
        raise ValueError("A lease name, instance ID, and positive TTL are required")
    current = _lease_timestamp(now)
    expires = current + timedelta(seconds=ttl_seconds)
    connection = _lease_connection(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT instance_id,expires_at FROM process_leases WHERE lease_name=?",
            (lease_name,),
        ).fetchone()
        if not row or row["instance_id"] != instance_id:
            connection.rollback()
            return False
        try:
            active = _lease_timestamp(row["expires_at"]) > current
        except (TypeError, ValueError):
            connection.rollback()
            return False
        if not active:
            connection.rollback()
            return False
        changed = connection.execute("""UPDATE process_leases
          SET heartbeat_at=?,expires_at=?
          WHERE lease_name=? AND instance_id=?""",
          (current.isoformat(),expires.isoformat(),lease_name,instance_id)).rowcount
        connection.commit()
        return changed == 1
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def release_process_lease(lease_name, instance_id, path=None):
    """Release a lease only if it is still owned by this process instance."""
    connection = _lease_connection(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        changed = connection.execute(
            "DELETE FROM process_leases WHERE lease_name=? AND instance_id=?",
            (lease_name,instance_id),
        ).rowcount
        connection.commit()
        return changed == 1
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_process_lease(lease_name, path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM process_leases WHERE lease_name=?",(lease_name,)).fetchone()


def clear_expired_process_lease(lease_name, expected_instance_id, path=None, now=None):
    """Delete only the specifically inspected lease after it has expired."""
    current = _lease_timestamp(now)
    connection = _lease_connection(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT instance_id,expires_at FROM process_leases WHERE lease_name=?",
            (lease_name,),
        ).fetchone()
        if not row or row["instance_id"] != expected_instance_id:
            connection.rollback()
            return False
        try:
            expired = _lease_timestamp(row["expires_at"]) <= current
        except (TypeError, ValueError):
            connection.rollback()
            return False
        if not expired:
            connection.rollback()
            return False
        changed = connection.execute(
            "DELETE FROM process_leases WHERE lease_name=? AND instance_id=?",
            (lease_name,expected_instance_id),
        ).rowcount
        connection.commit()
        return changed == 1
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def register_creator(telegram_id, username, display_name, path=None):
    """Register a creator without overwriting approval or archival state.

    Telegram ID is the canonical identity and primary key, so duplicates cannot be
    created. Repeat registration refreshes Telegram profile fields only.
    """
    now = utc_now()
    with get_connection(path) as db:
        existing = db.execute("SELECT * FROM creators WHERE telegram_id=?",(telegram_id,)).fetchone()
        db.execute("""INSERT INTO creators(telegram_id,username,display_name,registered_at)
          VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
          username=excluded.username, display_name=excluded.display_name""",
          (telegram_id, username, display_name, now))
        db.execute("""INSERT INTO community_members(telegram_id,member_type,display_name,username,created_at,updated_at)
          VALUES(?,?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET member_type='creator',
          display_name=excluded.display_name,username=excluded.username,updated_at=excluded.updated_at""",
          (telegram_id,"creator",display_name,username,now,now))
        if existing:
            audit_event(db,telegram_id,"creator_identity_refreshed","creator",telegram_id,telegram_id,
                previous_value={"username":existing["username"],"display_name":existing["display_name"]},
                new_value={"username":username,"display_name":display_name})
            return "archived" if existing["deleted_at"] else existing["status"]
        _audit(db,telegram_id,telegram_id,"creator_registered",{"username":username,"display_name":display_name},now)
        audit_event(db,telegram_id,"creator_registered","creator",telegram_id,telegram_id,
                    new_value={"username":username,"display_name":display_name})
        return "created"


def get_creator(telegram_id, path=None, include_deleted=False):
    """Return creator data with the canonical Telegram-ID identity applied."""
    with get_connection(path) as db:
        try:
            sql = "SELECT * FROM creators WHERE telegram_id=?"
            if not include_deleted:
                sql += " AND deleted_at IS NULL"
            row=db.execute(sql,(telegram_id,)).fetchone()
            return _resolved_person_row(db,row) if row else None
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            return None


def creator_identity_status(telegram_id, path=None):
    """Explain registration, directory, and member-identity state for diagnostics."""
    creator = get_creator(telegram_id,path,include_deleted=True)
    member = get_member(telegram_id,path)
    if not creator:
        return {"state":"not_registered","creator":None,"member":member,"directory_visible":False}
    archived = bool(creator["deleted_at"])
    state = "archived" if archived else creator["status"]
    return {"state":state,"creator":creator,"member":member,
        "directory_visible":not archived,"identity_consistent":bool(member and member["member_type"] == "creator")}


def register_member(telegram_id, username, display_name, member_type="buyer", path=None):
    """Create or refresh a non-privileged community identity."""
    if member_type not in {"buyer", "community"}:
        raise ValueError("member_type must be buyer or community")
    now = utc_now()
    with get_connection(path) as db:
        db.execute("""INSERT INTO community_members
          (telegram_id,member_type,display_name,username,created_at,updated_at)
          VALUES(?,?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
          member_type=CASE WHEN community_members.member_type='creator' THEN 'creator' ELSE excluded.member_type END,
          display_name=excluded.display_name,username=excluded.username,updated_at=excluded.updated_at""",
          (telegram_id,member_type,display_name,username,now,now))


def get_member(telegram_id, path=None):
    with get_connection(path) as db:
        try:
            return db.execute("SELECT * FROM community_members WHERE telegram_id=?", (telegram_id,)).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            return None


def record_bot_user(telegram_id,username,display_name,path=None):
    """Remember a private /start without assigning any role."""
    now=utc_now()
    with get_connection(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS bot_users (
          telegram_id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, username TEXT,
          first_started_at TEXT NOT NULL, last_started_at TEXT NOT NULL)""")
        db.execute("""INSERT INTO bot_users(telegram_id,display_name,username,first_started_at,last_started_at)
          VALUES(?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET display_name=excluded.display_name,
          username=excluded.username,last_started_at=excluded.last_started_at""",
          (telegram_id,display_name,username,now,now))


def synchronize_role_memberships(config,path=None):
    """Attach additive roles and ensure configured staff have one creator profile.

    Existing creator rows are never replaced or re-approved. Missing staff profiles are
    created active from the best Telegram identity already stored by the bot.
    """
    now=utc_now();owners=set(getattr(config,"owner_user_ids",()) or ())
    admins=set(getattr(config,"admin_user_ids",()) or ())|set(getattr(config,"lead_admin_user_ids",()) or ())|owners
    created=[];activated=[]
    with get_connection(path) as db:
        for user_id in sorted(admins):
            creator=db.execute("SELECT * FROM creators WHERE telegram_id=?",(user_id,)).fetchone()
            if not creator:
                identity=db.execute("SELECT display_name,username FROM bot_users WHERE telegram_id=?",(user_id,)).fetchone()
                display_name=identity["display_name"] if identity else f"Telegram user {user_id}"
                username=identity["username"] if identity else None
                db.execute("""INSERT INTO creators
                  (telegram_id,username,display_name,status,registered_at,approved_at,approved_by)
                  VALUES(?,?,?,'active',?,?,0)""",(user_id,username,display_name,now,now))
                db.execute("""INSERT INTO community_members
                  (telegram_id,member_type,display_name,username,created_at,updated_at)
                  VALUES(?,'creator',?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                  member_type='creator',display_name=excluded.display_name,
                  username=excluded.username,updated_at=excluded.updated_at""",
                  (user_id,display_name,username,now,now))
                audit_event(db,0,"creator_profile_created_for_staff_role","creator",user_id,user_id,
                    new_value={"status":"active"},reason="Admin and Owner roles include Creator capabilities",actor_role="system")
                created.append(user_id)
            elif not creator["deleted_at"] and creator["status"] != "active":
                db.execute("""UPDATE creators SET status='active',approved_at=COALESCE(approved_at,?),
                  approved_by=COALESCE(approved_by,0) WHERE telegram_id=?""",(now,user_id))
                audit_event(db,0,"creator_activated_for_staff_role","creator",user_id,user_id,
                    previous_value={"status":creator["status"]},new_value={"status":"active"},
                    reason="Admin and Owner roles include Creator capabilities",actor_role="system")
                activated.append(user_id)
        creator_rows=db.execute("SELECT telegram_id,deleted_at FROM creators").fetchall()
        desired={(row["telegram_id"],"creator") for row in creator_rows if not row["deleted_at"]}
        desired|={(user_id,"admin") for user_id in admins}
        desired|={(user_id,"owner") for user_id in owners}
        for user_id,role in desired:
            db.execute("""INSERT INTO user_roles(telegram_id,role,active,assigned_at,assigned_by)
              VALUES(?,?,1,?,0) ON CONFLICT(telegram_id,role) DO UPDATE SET
              active=1,removed_at=NULL,removed_by=NULL""",(user_id,role,now))
        for role,ids in (("admin",admins),("owner",owners)):
            if ids:
                placeholders=",".join("?" for _ in ids)
                db.execute(f"""UPDATE user_roles SET active=0,removed_at=?,removed_by=0
                  WHERE role=? AND active=1 AND telegram_id NOT IN ({placeholders})""",(now,role,*sorted(ids)))
            else:
                db.execute("UPDATE user_roles SET active=0,removed_at=?,removed_by=0 WHERE role=? AND active=1",(now,role))
    return {"created_creator_profiles":created,"activated_creator_profiles":activated,
        "owners":len(owners),"admins":len(admins)}


def roles_for_user(telegram_id,path=None):
    with get_connection(path) as db:
        return frozenset(row["role"] for row in db.execute(
            "SELECT role FROM user_roles WHERE telegram_id=? AND active=1",(telegram_id,)).fetchall())


def pending_bot_users(owner_ids=(),admin_ids=(),lead_ids=(),path=None):
    excluded=set(owner_ids)|set(admin_ids)|set(lead_ids)
    with get_connection(path) as db:
        rows=db.execute("""SELECT b.* FROM bot_users b LEFT JOIN community_members m ON m.telegram_id=b.telegram_id
          WHERE m.telegram_id IS NULL ORDER BY b.last_started_at DESC""").fetchall()
        return [_resolved_person_row(db,row) for row in rows if row["telegram_id"] not in excluded]


def _usable_person_name(value, telegram_id):
    value=(value or "").strip()
    return value if value and value.casefold() != f"telegram user {telegram_id}".casefold() else None


def _person_identity(db, telegram_id):
    """Resolve one display identity without ever combining different Telegram IDs."""
    creator=db.execute("SELECT * FROM creators WHERE telegram_id=?",(telegram_id,)).fetchone()
    member=db.execute("SELECT * FROM community_members WHERE telegram_id=?",(telegram_id,)).fetchone()
    bot_user=db.execute("SELECT * FROM bot_users WHERE telegram_id=?",(telegram_id,)).fetchone()
    approved_name = (_usable_person_name(creator["display_name"],telegram_id)
        if creator and creator["status"] == "active" and not creator["deleted_at"] else None)
    stored_name = _usable_person_name(member["display_name"],telegram_id) if member else None
    telegram_name = _usable_person_name(bot_user["display_name"],telegram_id) if bot_user else None
    username = next((row["username"] for row in (creator,member,bot_user)
        if row and row["username"]),None)
    return {"telegram_id":telegram_id,
        "display_name":approved_name or stored_name or telegram_name or username or f"Telegram user {telegram_id}",
        "username":username}


def _resolved_person_row(db, row):
    resolved = dict(row)
    if row["telegram_id"] is not None:
        resolved.update(_person_identity(db, row["telegram_id"]))
    return resolved


def people_for_ids(telegram_ids, path=None):
    """Return exactly one resolved person per immutable Telegram ID."""
    with get_connection(path) as db:
        people=[_person_identity(db,user_id) for user_id in set(telegram_ids)]
    return sorted(people,key=lambda row:(row["display_name"].casefold(),row["telegram_id"]))


def list_creators(path=None):
    with get_connection(path) as db:
        rows=db.execute("SELECT * FROM creators WHERE deleted_at IS NULL").fetchall()
        return sorted((_resolved_person_row(db,row) for row in rows),
            key=lambda row:(row["display_name"].casefold(),row["telegram_id"]))


def creator_directory(config,path=None,active_only=True):
    """Return the canonical creator directory after reconciling inherited roles.

    Admin and Owner authorization is configured independently from creator profile data.
    Reconcile those sources before rendering a directory so inherited Creator access can
    never exist without the same Telegram identity being represented once in creators.
    Archived profiles remain archived; inactive profiles remain excluded from active views.
    """
    synchronize_role_memberships(config,path)
    rows=list_creators(path)
    return [row for row in rows if row["status"] == "active"] if active_only else rows


def set_availability(target_id, new_status, actor_id, reason=None, expires_at=None, path=None):
    if new_status not in {"available", "unavailable", "vacation", "sick"}:
        return False
    now = utc_now()
    with get_connection(path) as db:
        row = db.execute("SELECT availability FROM creators WHERE telegram_id=? AND deleted_at IS NULL", (target_id,)).fetchone()
        if not row:
            return False
        previous = row["availability"]
        db.execute("""UPDATE creators SET previous_availability=availability,availability=?,
          availability_since=?,availability_changed_by=?,availability_expires_at=?,availability_reason=?
          WHERE telegram_id=?""", (new_status, now, actor_id, expires_at, reason, target_id))
        db.execute("INSERT INTO availability_history(telegram_id,previous_status,new_status,changed_at,changed_by,expires_at,reason) VALUES(?,?,?,?,?,?,?)",
                   (target_id,previous,new_status,now,actor_id,expires_at,reason))
        audit_event(db, actor_id, "availability_changed", "creator", target_telegram_id=target_id,
                    previous_value=previous, new_value=new_status, reason=reason)
        return True


def create_absence_request(telegram_id, absence_type, start_date, end_date, note=None, path=None, category=None):
    if absence_type not in {"vacation", "sick"} or date.fromisoformat(start_date) > date.fromisoformat(end_date):
        raise ValueError("Invalid absence request")
    category = category or ("vacation_trip" if absence_type == "vacation" else "not_feeling_well")
    snapshot = {"type": absence_type, "category": category, "start_date": start_date, "end_date": end_date, "note": note or ""}
    with get_connection(path) as db:
        cur = db.execute("""INSERT INTO absence_requests
          (telegram_id,absence_type,absence_category,start_date,end_date,note,submitted_at,original_snapshot)
          VALUES(?,?,?,?,?,?,?,?)""", (telegram_id,absence_type,category,start_date,end_date,(note or "")[:1000],utc_now(),json.dumps(snapshot,sort_keys=True)))
        request_id = cur.lastrowid
        audit_event(db, telegram_id, "absence_requested", "absence_request", request_id,
                    telegram_id, new_value=snapshot, related_request_id=request_id)
        return request_id


def list_absence_requests(status="pending", absence_type=None, path=None):
    with get_connection(path) as db:
        sql = "SELECT a.*,c.display_name FROM absence_requests a JOIN creators c ON c.telegram_id=a.telegram_id WHERE a.deleted_at IS NULL AND a.status=?"
        params = [status]
        if absence_type:
            sql += " AND a.absence_type=?"
            params.append(absence_type)
        rows=db.execute(sql + " ORDER BY a.submitted_at", params).fetchall()
        return [_resolved_person_row(db,row) for row in rows]


def creator_absences(telegram_id, path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM absence_requests WHERE telegram_id=? AND deleted_at IS NULL ORDER BY start_date DESC", (telegram_id,)).fetchall()


def get_absence_request(request_id, path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM absence_requests WHERE id=?", (request_id,)).fetchone()


def review_absence(request_id, decision, actor_id, reason=None, path=None):
    if decision not in {"approved", "denied", "clarification"}:
        return False
    now = utc_now()
    with get_connection(path) as db:
        row = db.execute("SELECT * FROM absence_requests WHERE id=? AND status='pending' AND deleted_at IS NULL", (request_id,)).fetchone()
        if not row:
            return False
        if decision == "clarification":
            db.execute("UPDATE absence_requests SET clarification_requested_at=?,review_reason=? WHERE id=?", (now,(reason or "")[:1000],request_id))
        else:
            db.execute("UPDATE absence_requests SET status=?,reviewed_at=?,reviewed_by=?,review_reason=? WHERE id=?",
                       (decision,now,actor_id,(reason or "")[:1000],request_id))
            if decision == "approved":
                availability = "vacation" if row["absence_type"] == "vacation" else "sick"
                eastern_today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
                if row["start_date"] <= eastern_today <= row["end_date"]:
                    db.execute("""UPDATE creators SET previous_availability=availability,availability=?,availability_since=?,
                      availability_changed_by=?,availability_expires_at=?,availability_reason=? WHERE telegram_id=?""",
                      (availability,now,actor_id,row["end_date"],f"approved absence #{request_id}",row["telegram_id"]))
                start_day, end_day = date.fromisoformat(row["start_date"]), date.fromisoformat(row["end_date"])
                cursor = start_day
                while cursor <= end_day:
                    if cursor.weekday() == 3:
                        iso_year, iso_week, _ = cursor.isocalendar()
                        key = f"{iso_year}-W{iso_week:02d}"
                        db.execute("INSERT OR IGNORE INTO pop_excuses(telegram_id,week_key,absence_request_id,created_at,created_by) VALUES(?,?,?,?,?)",
                                   (row["telegram_id"],key,request_id,now,actor_id))
                        audit_event(db,actor_id,"pop_excused","pop_requirement",target_telegram_id=row["telegram_id"],
                                    new_value={"week_key":key},related_request_id=request_id)
                    cursor += date.resolution
        audit_event(db, actor_id, f"absence_{decision}", "absence_request", request_id,
                    row["telegram_id"], previous_value="pending", new_value=decision,
                    reason=reason, related_request_id=request_id)
        return True


def approved_absence_on(telegram_id, day, path=None):
    day = day.isoformat() if hasattr(day, "isoformat") else str(day)
    with get_connection(path) as db:
        return db.execute("""SELECT * FROM absence_requests WHERE telegram_id=? AND status='approved'
          AND deleted_at IS NULL AND start_date<=? AND end_date>=? ORDER BY id DESC LIMIT 1""",
          (telegram_id,day,day)).fetchone()


def sync_absence_availability(day, path=None):
    """Idempotently apply active absences and restore status after they end."""
    day = day.isoformat() if hasattr(day, "isoformat") else str(day)
    now = utc_now()
    with get_connection(path) as db:
        active = db.execute("""SELECT a.*,c.availability FROM absence_requests a JOIN creators c
          ON c.telegram_id=a.telegram_id WHERE a.status='approved' AND a.deleted_at IS NULL
          AND a.start_date<=? AND a.end_date>=?""", (day,day)).fetchall()
        active_ids = set()
        for row in active:
            active_ids.add(row["telegram_id"])
            expected = "vacation" if row["absence_type"] == "vacation" else "sick"
            if row["availability"] != expected:
                db.execute("""UPDATE creators SET previous_availability=availability,availability=?,availability_since=?,
                  availability_changed_by=0,availability_expires_at=?,availability_reason=? WHERE telegram_id=?""",
                  (expected,now,row["end_date"],f"approved absence #{row['id']}",row["telegram_id"]))
                audit_event(db,0,"availability_changed_automatically","creator",row["telegram_id"],row["telegram_id"],
                            previous_value=row["availability"],new_value=expected,reason=f"approved absence #{row['id']}")
        expired = db.execute("""SELECT telegram_id,availability,previous_availability FROM creators
          WHERE availability IN ('vacation','sick') AND availability_expires_at<?""", (day,)).fetchall()
        for row in expired:
            if row["telegram_id"] in active_ids:
                continue
            restored = row["previous_availability"] if row["previous_availability"] in {"available","unavailable"} else "unavailable"
            db.execute("""UPDATE creators SET availability=?,availability_since=?,availability_changed_by=0,
              availability_expires_at=NULL,availability_reason='absence ended' WHERE telegram_id=?""",
              (restored,now,row["telegram_id"]))
            audit_event(db,0,"availability_restored_automatically","creator",row["telegram_id"],row["telegram_id"],
                        previous_value=row["availability"],new_value=restored,reason="approved absence ended")


def creator_history(telegram_id, path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM audit_events WHERE target_telegram_id=? ORDER BY id DESC", (telegram_id,)).fetchall()


def creator_timeline(telegram_id, limit=10, offset=0, path=None):
    with get_connection(path) as db:
        return db.execute("""SELECT id,occurred_at,action,target_type,previous_value,new_value,reason
          FROM audit_events WHERE target_telegram_id=? ORDER BY occurred_at DESC,id DESC
          LIMIT ? OFFSET ?""", (telegram_id,limit,offset)).fetchall()


def latest_absence(telegram_id, path=None):
    with get_connection(path) as db:
        return db.execute("""SELECT * FROM absence_requests WHERE telegram_id=? AND deleted_at IS NULL
          ORDER BY submitted_at DESC,id DESC LIMIT 1""", (telegram_id,)).fetchone()


def creator_pop_status(telegram_id, week_key, path=None):
    with get_connection(path) as db:
        excuse = db.execute("SELECT 1 FROM pop_excuses WHERE telegram_id=? AND week_key=?", (telegram_id,week_key)).fetchone()
        if excuse:
            return "excused"
        row = db.execute("SELECT status FROM pop_submissions WHERE telegram_id=? AND week_key=? AND deleted_at IS NULL", (telegram_id,week_key)).fetchone()
        return row["status"] if row else "not submitted"


def add_warning(telegram_id, warning_type, reason, actor_id, path=None, template_key=None, notes=None):
    if warning_type not in {"warning", "strike"} or not reason.strip():
        return None
    with get_connection(path) as db:
        if not db.execute("SELECT 1 FROM creators WHERE telegram_id=? AND deleted_at IS NULL", (telegram_id,)).fetchone():
            return None
        cur = db.execute("""INSERT INTO creator_warnings
          (telegram_id,warning_type,reason,issued_at,issued_by,template_key,notes)
          VALUES(?,?,?,?,?,?,?)""",
          (telegram_id,warning_type,reason[:1000],utc_now(),actor_id,template_key,(notes or "")[:1000] or None))
        audit_event(db,actor_id,f"{warning_type}_issued","creator_warning",cur.lastrowid,telegram_id,
                    new_value={"type":warning_type,"status":"active"},reason=reason)
        return cur.lastrowid


def warning_summary(telegram_id, path=None):
    with get_connection(path) as db:
        row = db.execute("""SELECT
          SUM(CASE WHEN warning_type='warning' AND status!='removed' THEN 1 ELSE 0 END) AS warnings,
          SUM(CASE WHEN warning_type='strike' AND status!='removed' THEN 1 ELSE 0 END) AS strikes
          FROM creator_warnings WHERE telegram_id=?""", (telegram_id,)).fetchone()
        return {"warnings": row["warnings"] or 0, "strikes": row["strikes"] or 0}


def list_warnings(telegram_id, path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM creator_warnings WHERE telegram_id=? AND deleted_at IS NULL ORDER BY issued_at DESC,id DESC", (telegram_id,)).fetchall()


def get_warning(warning_id, path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM creator_warnings WHERE id=?", (warning_id,)).fetchone()


def acknowledge_warning(warning_id, actor_id, path=None):
    with get_connection(path) as db:
        row = db.execute("SELECT * FROM creator_warnings WHERE id=? AND status='active'", (warning_id,)).fetchone()
        if not row:
            return False
        db.execute("UPDATE creator_warnings SET status='acknowledged',acknowledged_at=?,acknowledged_by=? WHERE id=?",
                   (utc_now(),actor_id,warning_id))
        audit_event(db,actor_id,"warning_acknowledged","creator_warning",warning_id,row["telegram_id"],
                    previous_value="active",new_value="acknowledged")
        return True


def remove_warning(warning_id, actor_id, reason, path=None):
    with get_connection(path) as db:
        row = db.execute("SELECT * FROM creator_warnings WHERE id=? AND status!='removed'", (warning_id,)).fetchone()
        if not row:
            return False
        db.execute("UPDATE creator_warnings SET status='removed',removed_at=?,removed_by=?,removal_reason=? WHERE id=?",
                   (utc_now(),actor_id,reason[:1000],warning_id))
        audit_event(db,actor_id,"warning_removed","creator_warning",warning_id,row["telegram_id"],
                    previous_value=row["status"],new_value="removed",reason=reason)
        return True


def message_templates(path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM message_templates WHERE active=1 ORDER BY category,title").fetchall()


def message_template(template_key, path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM message_templates WHERE template_key=? AND active=1", (template_key,)).fetchone()


def update_message_template(template_key, new_body, actor_id, reason="Owner update", path=None):
    new_body = (new_body or "").strip()[:3500]
    if not new_body:
        return False
    with get_connection(path) as db:
        row = db.execute("SELECT * FROM message_templates WHERE template_key=?", (template_key,)).fetchone()
        if not row or row["body"] == new_body:
            return False
        now = utc_now()
        db.execute("INSERT INTO template_revisions(template_key,previous_body,new_body,changed_at,changed_by,reason) VALUES(?,?,?,?,?,?)",
                   (template_key,row["body"],new_body,now,actor_id,reason[:1000]))
        db.execute("UPDATE message_templates SET body=?,updated_at=?,updated_by=? WHERE template_key=?",
                   (new_body,now,actor_id,template_key))
        audit_event(db,actor_id,"message_template_changed","message_template",target_record_id=None,
                    previous_value={"key":template_key,"body":row["body"]},
                    new_value={"key":template_key,"body":new_body},reason=reason)
        return True


def dashboard_metrics(week_key, path=None):
    """Compact operational counts for mobile dashboards."""
    with get_connection(path) as db:
        scalar = lambda sql, params=(): db.execute(sql,params).fetchone()[0]
        eastern_now=datetime.now(ZoneInfo("America/New_York"));eastern_start=datetime.combine(eastern_now.date(),time.min,ZoneInfo("America/New_York"))
        utc_start=eastern_start.astimezone(timezone.utc).isoformat();utc_end=(eastern_start+timedelta(days=1)).astimezone(timezone.utc).isoformat()
        attention_rows=_participation_attention_rows(db,48,72)
        metrics = {
            "active_creators": scalar("SELECT COUNT(*) FROM creators WHERE status='active' AND deleted_at IS NULL"),
            "participated_today": scalar("""SELECT COUNT(DISTINCT telegram_id) FROM engagement_events
              WHERE decision='accepted' AND datetime(created_at)>=datetime(?) AND datetime(created_at)<datetime(?)""",(utc_start,utc_end)),
            "pending_registrations": scalar("SELECT COUNT(*) FROM creators WHERE status='pending' AND deleted_at IS NULL"),
            "pending_vacations": scalar("SELECT COUNT(*) FROM absence_requests WHERE status='pending' AND absence_type='vacation' AND deleted_at IS NULL"),
            "pending_sick": scalar("SELECT COUNT(*) FROM absence_requests WHERE status='pending' AND absence_type='sick' AND deleted_at IS NULL"),
            "pending_pop": scalar("SELECT COUNT(*) FROM pop_submissions WHERE week_key=? AND status='pending' AND deleted_at IS NULL",(week_key,)),
            "preservation_reviews": scalar("""SELECT COUNT(*) FROM pop_submissions
              WHERE preservation_status IN ('unable_to_verify','early_removed')
              AND deleted_at IS NULL"""),
            "missing_pop": 0,
            "active_warnings": scalar("SELECT COUNT(*) FROM creator_warnings WHERE status IN ('active','acknowledged') AND warning_type='warning'"),
            "active_strikes": scalar("SELECT COUNT(*) FROM creator_warnings WHERE status IN ('active','acknowledged') AND warning_type='strike'"),
            "away_now": scalar("SELECT COUNT(*) FROM creators WHERE status='active' AND deleted_at IS NULL AND availability IN ('vacation','sick')"),
            "deleted_records": scalar("SELECT COUNT(*) FROM creators WHERE deleted_at IS NOT NULL"),
            "audit_events": scalar("SELECT COUNT(*) FROM audit_events"),
            "audit_today": scalar("SELECT COUNT(*) FROM audit_events WHERE substr(occurred_at,1,10)=?", (datetime.now(ZoneInfo("America/New_York")).date().isoformat(),)),
            "failed_notifications": scalar("SELECT COUNT(*) FROM delivery_failures WHERE resolved_at IS NULL"),
            "support_requests": scalar("SELECT COUNT(*) FROM support_requests WHERE status!='resolved'"),
            "three_day_alerts": sum(row["hours"]>=72 for row in attention_rows),
        }
        metrics["participation_flags"] = len(attention_rows)
        metrics["needs_attention"] = (
            metrics["pending_registrations"] + metrics["pending_vacations"] + metrics["pending_sick"]
            + metrics["pending_pop"] + metrics["preservation_reviews"]
            + metrics["participation_flags"] + metrics["failed_notifications"]
            + scalar("SELECT COUNT(*) FROM creator_warnings WHERE status='active'")
        )
        return metrics


def pop_status_report(now=None, due_weekday=3, cutoff_time="23:59", timezone_name="America/New_York", path=None):
    """Return every active creator's status from the shared POP deadline policy."""
    now = now or datetime.now(ZoneInfo(timezone_name))
    period = current_period(now,due_weekday,cutoff_time,timezone_name)
    with get_connection(path) as db:
        rows = db.execute("""SELECT c.telegram_id,c.display_name,c.registered_at,p.id,p.message_id,p.chat_id,p.thread_id,
          p.status AS submission_status,
          p.submitted_at,p.proof_type,p.preservation_status,p.preservation_due_at,
          p.preservation_checked_at,p.timing_status,p.source_message_at,p.observed_at,
          p.recovered_after_outage,p.needs_review_reason,
          CASE WHEN x.id IS NULL THEN 0 ELSE 1 END AS excused
          FROM creators c
          LEFT JOIN pop_submissions p ON p.telegram_id=c.telegram_id AND p.week_key=? AND p.deleted_at IS NULL
          LEFT JOIN pop_excuses x ON x.telegram_id=c.telegram_id AND x.week_key=?
          WHERE c.status='active' AND c.deleted_at IS NULL ORDER BY c.display_name COLLATE NOCASE""",
          (period.week_key,period.week_key)).fetchall()
        result = []
        for row in rows:
            item = _resolved_person_row(db,row)
            item["week_key"] = period.week_key
            item["due_at"] = period.due_at
            item["effective_status"] = calculate_status(now,submission_status=row["submission_status"],
                excused=bool(row["excused"]),registered_at=row["registered_at"],due_weekday=due_weekday,
                cutoff_time=cutoff_time,timezone_name=timezone_name)
            if item["excused"]:
                item["effective_status"] = item["creator_status"] = "excused"
            elif item["id"] is not None and item["needs_review_reason"]:
                item["effective_status"] = item["creator_status"] = "submitted_needs_review"
            elif item["id"] is not None and item["preservation_status"] in {"unable_to_verify","early_removed"}:
                item["creator_status"] = "needs_review"
                item["effective_status"] = "submitted_needs_review"
            elif item["id"] is not None and item["timing_status"] in {"on_time","late"}:
                item["effective_status"] = item["creator_status"] = item["timing_status"]
            else:
                item["creator_status"] = item["effective_status"]
            result.append(item)
        return result


def pop_status_counts(now=None, due_weekday=3, cutoff_time="23:59", timezone_name="America/New_York", path=None):
    rows = pop_status_report(now,due_weekday,cutoff_time,timezone_name,path)
    keys = {"not_due","due_today","still_needed","missing","submitted","awaiting_review","excused",
        "resubmission_requested","rejected","on_time","late","submitted_needs_review"}
    counts = {key:0 for key in keys}
    for row in rows: counts[row["effective_status"]] = counts.get(row["effective_status"],0) + 1
    counts["total"] = len(rows)
    return counts


def creator_current_pop_status(telegram_id, now=None, due_weekday=3, cutoff_time="23:59", timezone_name="America/New_York", path=None):
    for row in pop_status_report(now,due_weekday,cutoff_time,timezone_name,path):
        if row["telegram_id"] == telegram_id:
            return row["creator_status"]
    return "not_due"


def _participation_attention_rows(connection, warning_hours, alert_hours):
    now = datetime.now(timezone.utc)
    rows = []
    for row in connection.execute("""SELECT * FROM creators
      WHERE status='active' AND deleted_at IS NULL AND availability NOT IN ('vacation','sick')""").fetchall():
        anchor = row["last_meaningful_at"] or row["approved_at"] or row["registered_at"]
        if not anchor:
            continue
        try:
            hours = (now - datetime.fromisoformat(anchor).astimezone(timezone.utc)).total_seconds() / 3600
        except (TypeError, ValueError):
            continue
        if hours >= max(0, warning_hours - 6):
            item = dict(row)
            item["hours"] = hours
            rows.append(item)
    return sorted(rows, key=lambda item: item["hours"], reverse=True)


def participation_attention(warning_hours=48, alert_hours=72, path=None):
    with get_connection(path) as connection:
        return _participation_attention_rows(connection, warning_hours, alert_hours)


def needs_attention_counts(week_key, path=None, now=None, due_weekday=3, cutoff_time="23:59", timezone_name="America/New_York"):
    """Actionable owner/admin counts; informational metrics do not inflate the total."""
    with get_connection(path) as connection:
        scalar = lambda sql, params=(): connection.execute(sql, params).fetchone()[0]
        attention = _participation_attention_rows(connection, 48, 72)
        pop = pop_status_counts(now,due_weekday,cutoff_time,timezone_name,path)
        counts = {
            "registrations": scalar("SELECT COUNT(*) FROM creators WHERE status='pending' AND deleted_at IS NULL"),
            "away_notices": scalar("SELECT COUNT(*) FROM absence_requests WHERE status='pending' AND deleted_at IS NULL"),
            "pop_reviews": pop["awaiting_review"],
            "preservation_reviews": scalar("""SELECT COUNT(*) FROM pop_submissions
              WHERE preservation_status IN ('unable_to_verify','early_removed')
              AND deleted_at IS NULL"""),
            "missing_pop": pop["missing"],
            "near_two_days": sum(42 <= row["hours"] < 72 for row in attention),
            "three_day_alerts": sum(row["hours"] >= 72 for row in attention),
            "unacknowledged_warnings": scalar("SELECT COUNT(*) FROM creator_warnings WHERE status='active'"),
            "owner_reviews": scalar("""SELECT COUNT(*) FROM (
              SELECT telegram_id FROM creator_warnings WHERE status!='removed' AND warning_type='strike'
              GROUP BY telegram_id HAVING COUNT(*)>=3)"""),
            "failed_notifications": scalar("SELECT COUNT(*) FROM delivery_failures WHERE resolved_at IS NULL"),
            "recent_archive_changes": scalar("""SELECT COUNT(*) FROM audit_events
              WHERE action IN ('creator_soft_deleted','creator_restored')
              AND occurred_at>=?""", ((datetime.now(ZoneInfo("America/New_York")) - timedelta(days=7)).isoformat(),)),
            "support_requests": scalar("SELECT COUNT(*) FROM support_requests WHERE status!='resolved'"),
        }
        counts["total"] = sum(counts.values())
        return counts


def add_admin_note(telegram_id, note, actor_id, path=None):
    with get_connection(path) as db:
        cur = db.execute("INSERT INTO admin_notes(telegram_id,note,created_at,created_by) VALUES(?,?,?,?)",
                         (telegram_id,note[:2000],utc_now(),actor_id))
        audit_event(db,actor_id,"admin_note_created","admin_note",cur.lastrowid,telegram_id,
                    new_value={"note_length":len(note)})
        return cur.lastrowid


def list_admin_notes(telegram_id, path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM admin_notes WHERE telegram_id=? AND deleted_at IS NULL ORDER BY id DESC", (telegram_id,)).fetchall()


def create_announcement(audience, body, actor_id, path=None):
    with get_connection(path) as db:
        cur = db.execute("INSERT INTO announcements(audience,body,created_at,created_by) VALUES(?,?,?,?)",
                         (audience,body[:3500],utc_now(),actor_id))
        audit_event(db,actor_id,"announcement_created","announcement",cur.lastrowid,new_value={"audience":audience})
        return cur.lastrowid


def mark_announcement_sent(announcement_id, actor_id, delivered, failed, path=None):
    with get_connection(path) as db:
        cur = db.execute("UPDATE announcements SET sent_at=?,delivered_count=?,failed_count=? WHERE id=? AND sent_at IS NULL",
                         (utc_now(),delivered,failed,announcement_id))
        if cur.rowcount:
            audit_event(db,actor_id,"announcement_delivered","announcement",announcement_id,
                        new_value={"delivered":delivered,"failed":failed})
        return bool(cur.rowcount)


def announcement(announcement_id, path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM announcements WHERE id=?", (announcement_id,)).fetchone()


def announcement_recipients(audience, owner_ids=(), admin_ids=(), path=None):
    if audience == "owners":
        return list(owner_ids)
    if audience == "admins":
        return list(set(admin_ids) | set(owner_ids))
    with get_connection(path) as db:
        condition = "status='active' AND deleted_at IS NULL"
        if audience == "available": condition += " AND availability='available'"
        if audience == "away": condition += " AND availability IN ('vacation','sick')"
        return [r[0] for r in db.execute(f"SELECT telegram_id FROM creators WHERE {condition}").fetchall()]


def calendar_absences(start_date, end_date, path=None):
    with get_connection(path) as db:
        rows=db.execute("""SELECT a.*,c.display_name FROM absence_requests a JOIN creators c ON c.telegram_id=a.telegram_id
          WHERE a.status='approved' AND a.deleted_at IS NULL AND a.start_date<=? AND a.end_date>=?
          ORDER BY a.start_date,c.display_name""", (end_date,start_date)).fetchall()
        return [_resolved_person_row(db,row) for row in rows]


def approved_absence_detail(request_id, path=None):
    """Return one visible approved notice for an authorized detail screen."""
    with get_connection(path) as db:
        row=db.execute("""SELECT a.*,c.display_name,c.username FROM absence_requests a
          JOIN creators c ON c.telegram_id=a.telegram_id
          WHERE a.id=? AND a.status='approved' AND a.deleted_at IS NULL
          AND c.deleted_at IS NULL""",(request_id,)).fetchone()
        return _resolved_person_row(db,row) if row else None


def record_audit(actor_id, action, target_type=None, target_record_id=None,
                 target_telegram_id=None, previous_value=None, new_value=None,
                 reason=None, result="success", path=None, error_reference=None,
                 related_request_id=None,related_submission_id=None):
    with get_connection(path) as connection:
        audit_event(connection,actor_id,action,target_type,target_record_id,target_telegram_id,
                    previous_value,new_value,reason,related_request_id=related_request_id,
                    related_submission_id=related_submission_id,result=result,error_reference=error_reference)


def export_snapshot(path=None):
    """Return owner export data without private message bodies."""
    with get_connection(path) as db:
        return {
            "creators": [dict(r) for r in db.execute("SELECT * FROM creators").fetchall()],
            "absences": [dict(r) for r in db.execute("SELECT * FROM absence_requests").fetchall()],
            "pop": [dict(r) for r in db.execute("SELECT * FROM pop_submissions").fetchall()],
            "warnings": [dict(r) for r in db.execute("SELECT * FROM creator_warnings").fetchall()],
            "notifications": [dict(r) for r in db.execute("SELECT * FROM notifications").fetchall()],
            "support_requests": [dict(r) for r in db.execute("SELECT * FROM support_requests").fetchall()],
            "support_messages": [dict(r) for r in db.execute("SELECT * FROM support_messages").fetchall()],
            "delivery_failures": [dict(r) for r in db.execute("SELECT * FROM delivery_failures").fetchall()],
            "bot_users": [dict(r) for r in db.execute("SELECT * FROM bot_users").fetchall()],
            "audit": [dict(r) for r in db.execute("SELECT * FROM audit_events").fetchall()],
        }


def set_status(target_id, status, actor_id, path=None):
    now = utc_now()
    with get_connection(path) as db:
        previous = db.execute("SELECT status FROM creators WHERE telegram_id=? AND deleted_at IS NULL", (target_id,)).fetchone()
        cur = db.execute("UPDATE creators SET status=?, approved_at=CASE WHEN ?='active' THEN ? ELSE approved_at END, approved_by=CASE WHEN ?='active' THEN ? ELSE approved_by END WHERE telegram_id=? AND deleted_at IS NULL",
                         (status, status, now, status, actor_id, target_id))
        if not cur.rowcount:
            return False
        _audit(db, actor_id, target_id, "creator_status_changed", {"status": status}, now)
        audit_event(db,actor_id,"creator_status_changed","creator",target_id,target_id,
                    previous_value=previous["status"] if previous else None,new_value=status)
        return True


def delete_creator(target_id, actor_id, path=None):
    with get_connection(path) as db:
        creator = db.execute("SELECT * FROM creators WHERE telegram_id=? AND deleted_at IS NULL", (target_id,)).fetchone()
        if not creator:
            return False
        now = utc_now()
        db.execute("UPDATE creators SET deleted_at=?,deleted_by=?,deletion_reason=? WHERE telegram_id=?",
                   (now,actor_id,"operational removal",target_id))
        audit_event(db, actor_id, "creator_soft_deleted", "creator", target_id,
                    target_id, previous_value=dict(creator), new_value={"deleted_at": now})
        return True


def deleted_records(path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM creators WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC").fetchall()


def restore_creator(target_id, actor_id, reason, path=None):
    with get_connection(path) as db:
        row = db.execute("SELECT * FROM creators WHERE telegram_id=? AND deleted_at IS NOT NULL", (target_id,)).fetchone()
        if not row:
            return False
        now = utc_now()
        db.execute("UPDATE creators SET deleted_at=NULL,deleted_by=NULL,deletion_reason=NULL,restored_at=?,restored_by=? WHERE telegram_id=?",
                   (now,actor_id,target_id))
        audit_event(db, actor_id, "creator_restored", "creator", target_id, target_id,
                    previous_value={"deleted_at": row["deleted_at"]}, new_value={"restored_at": now}, reason=reason)
        return True


def set_vacation(target_id, until, actor_id, path=None):
    with get_connection(path) as db:
        cur = db.execute("UPDATE creators SET vacation_until=? WHERE telegram_id=?", (until, target_id))
        if cur.rowcount:
            _audit(db, actor_id, target_id, "vacation", {"until": until})
            audit_event(db,actor_id,"legacy_vacation_changed","creator",target_id,target_id,new_value={"until":until})
        return bool(cur.rowcount)


def record_engagement(telegram_id, message_id, chat_id, thread_id, normalized_hash, decision, reason, path=None, event_type="text_message"):
    now = utc_now()
    with get_connection(path) as db:
        try:
            db.execute("INSERT INTO engagement_events(telegram_id,message_id,chat_id,thread_id,normalized_hash,decision,reason,created_at) VALUES(?,?,?,?,?,?,?,?)",
                       (telegram_id,message_id,chat_id,thread_id,normalized_hash,decision,reason,now))
        except sqlite3.IntegrityError:
            return False
        if decision == "accepted":
            db.execute("UPDATE creators SET last_meaningful_at=? WHERE telegram_id=?", (now,telegram_id))
        audit_action = f"engagement_counted_{event_type}" if decision == "accepted" and event_type != "text_message" else (
            "engagement_counted" if decision == "accepted" else "engagement_ignored")
        audit_event(db, telegram_id, audit_action,
                    "engagement", target_telegram_id=telegram_id, new_value=decision,
                    reason=reason, source_chat_id=chat_id, source_thread_id=thread_id)
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
            audit_event(db,None,f"{kind}_created","notification",target_telegram_id=telegram_id,new_value={"cycle_at":cycle_at})
            return True
        except sqlite3.IntegrityError:
            return False


def record_pop_evidence(telegram_id, week_key, message_id, chat_id, thread_id, proof_type,
                        timing_status, *, source_message_at, observed_at=None, update_id=None,
                        recovered_after_outage=False, needs_review_reason=None,
                        relationship="primary", path=None):
    """Attach evidence to one canonical creator/week record, retaining the earliest proof."""
    observed_at=observed_at or utc_now();confidence="needs_review" if needs_review_reason else "qualified"
    with get_connection(path) as db:
        existing_evidence=db.execute("SELECT * FROM pop_evidence WHERE chat_id=? AND message_id=?",
            (chat_id,message_id)).fetchone()
        if existing_evidence:
            # Edited messages may strengthen a prior candidate, but cannot move it to
            # another creator, location, or week.
            if (existing_evidence["telegram_id"]!=telegram_id or existing_evidence["thread_id"]!=thread_id
                    or existing_evidence["week_key"]!=week_key):
                return {"created":False,"duplicate":True,"submission_id":existing_evidence["submission_id"]}
            db.execute("""UPDATE pop_evidence SET proof_type=?,confidence=?,update_id=COALESCE(?,update_id),
              observed_at=?,recovered_after_outage=MAX(recovered_after_outage,?) WHERE id=?""",
              (proof_type,confidence,update_id,observed_at,int(recovered_after_outage),existing_evidence["id"]))
        canonical=db.execute("SELECT * FROM pop_submissions WHERE telegram_id=? AND week_key=? AND deleted_at IS NULL",
            (telegram_id,week_key)).fetchone()
        created=False
        combined_qualified=bool(canonical and relationship=="supporting" and
            (not needs_review_reason or not canonical["needs_review_reason"]))
        canonical_proof="combined" if combined_qualified else proof_type
        canonical_review_reason=None if combined_qualified else needs_review_reason
        if not canonical:
            due_at=(datetime.fromisoformat(source_message_at)+timedelta(hours=24)).isoformat()
            db.execute("""INSERT INTO pop_submissions
              (telegram_id,week_key,message_id,chat_id,thread_id,proof_type,submitted_at,
               preservation_status,preservation_due_at,timing_status,source_message_at,observed_at,
               recovered_after_outage,needs_review_reason,source_update_id)
              VALUES(?,?,?,?,?,?,?,'pending_24h',?,?,?,?,?,?,?)""",
              (telegram_id,week_key,message_id,chat_id,thread_id,canonical_proof,source_message_at,due_at,
               timing_status,source_message_at,observed_at,int(recovered_after_outage),canonical_review_reason,update_id))
            submission_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            canonical=db.execute("SELECT * FROM pop_submissions WHERE id=?",(submission_id,)).fetchone();created=True
            audit_event(db, telegram_id, "pop_submitted", "pop_submission", submission_id,
                        telegram_id, related_submission_id=submission_id,
                        source_chat_id=chat_id, source_thread_id=thread_id)
        else:
            submission_id=canonical["id"]
            if datetime.fromisoformat(source_message_at)<datetime.fromisoformat(canonical["source_message_at"] or canonical["submitted_at"]):
                due_at=(datetime.fromisoformat(source_message_at)+timedelta(hours=24)).isoformat()
                db.execute("""UPDATE pop_submissions SET message_id=?,chat_id=?,thread_id=?,proof_type=?,
                  submitted_at=?,source_message_at=?,preservation_due_at=?,timing_status=?,
                  recovered_after_outage=MAX(recovered_after_outage,?),needs_review_reason=?,
                  source_update_id=? WHERE id=?""",
                  (message_id,chat_id,thread_id,canonical_proof,source_message_at,source_message_at,due_at,
                   timing_status,int(recovered_after_outage),canonical_review_reason,update_id,submission_id))
            elif combined_qualified:
                db.execute("UPDATE pop_submissions SET proof_type='combined',needs_review_reason=NULL WHERE id=?",
                    (submission_id,))
        if not existing_evidence:
            db.execute("""INSERT INTO pop_evidence(submission_id,telegram_id,week_key,message_id,chat_id,thread_id,
              update_id,proof_type,confidence,source_message_at,observed_at,recovered_after_outage,relationship)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (submission_id,telegram_id,week_key,message_id,chat_id,thread_id,update_id,proof_type,
               confidence,source_message_at,observed_at,int(recovered_after_outage),relationship))
        else:
            db.execute("UPDATE pop_evidence SET submission_id=? WHERE id=?",(submission_id,existing_evidence["id"]))
        if recovered_after_outage and (created or not existing_evidence):
            _increment_recovery(db,"pop",timing_status,needs_review=bool(canonical_review_reason))
        return {"created":created,"duplicate":bool(existing_evidence),"submission_id":submission_id}


def submit_pop(telegram_id, week_key, message_id, chat_id, thread_id, proof_type, path=None,
               submitted_at=None, timing_status="on_time", observed_at=None, update_id=None,
               recovered_after_outage=False, needs_review_reason=None):
    """Backward-compatible canonical submission helper."""
    result=record_pop_evidence(telegram_id,week_key,message_id,chat_id,thread_id,proof_type,timing_status,
        source_message_at=submitted_at or utc_now(),observed_at=observed_at,update_id=update_id,
        recovered_after_outage=recovered_after_outage,needs_review_reason=needs_review_reason,path=path)
    return result["created"]


def recent_pop_evidence(telegram_id, chat_id, thread_id, source_at, seconds=300, path=None):
    """Return same-creator/same-topic evidence close enough for safe split correlation."""
    moment=datetime.fromisoformat(source_at);start=(moment-timedelta(seconds=seconds)).isoformat()
    end=(moment+timedelta(seconds=seconds)).isoformat()
    with get_connection(path) as db:
        return db.execute("""SELECT * FROM pop_evidence WHERE telegram_id=? AND chat_id=? AND thread_id=?
          AND source_message_at BETWEEN ? AND ? ORDER BY source_message_at""",
          (telegram_id,chat_id,thread_id,start,end)).fetchall()


def begin_recovery_run(started_at=None, catchup_seconds=90, path=None):
    started_at=started_at or utc_now()
    with get_connection(path) as db:
        open_run=db.execute("SELECT * FROM recovery_runs WHERE status='catching_up' ORDER BY id DESC LIMIT 1").fetchone()
        if open_run:return open_run["id"]
        previous=db.execute("SELECT state_value FROM system_state WHERE state_key='runtime:last_heartbeat'").fetchone()
        previous_at=previous["state_value"] if previous else None
        catchup=(datetime.fromisoformat(started_at)+timedelta(seconds=catchup_seconds)).isoformat()
        cur=db.execute("""INSERT INTO recovery_runs(started_at,previous_heartbeat_at,catchup_until,unresolved_gap)
          VALUES(?,?,?,?)""",(started_at,previous_at,catchup,
          None if previous_at else "No prior runtime heartbeat is available"))
        return cur.lastrowid


def active_recovery_run(path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM recovery_runs WHERE status='catching_up' ORDER BY id DESC LIMIT 1").fetchone()


def claim_processed_update(update_id, update_type, source_message_at=None, path=None):
    """Record one Telegram update for recovery accounting without blocking other handlers."""
    if update_id is None:return True,False
    now=utc_now()
    with get_connection(path) as db:
        run=db.execute("SELECT * FROM recovery_runs WHERE status='catching_up' ORDER BY id DESC LIMIT 1").fetchone()
        recovered=bool(run and source_message_at and datetime.fromisoformat(source_message_at)<datetime.fromisoformat(run["started_at"]))
        try:
            db.execute("INSERT INTO processed_updates VALUES(?,?,?,?,?)",
                (update_id,update_type,source_message_at,now,int(recovered)))
        except sqlite3.IntegrityError:return False,recovered
        if recovered:
            db.execute("UPDATE recovery_runs SET updates_recovered=updates_recovered+1 WHERE id=?",(run["id"],))
        return True,recovered


def _increment_recovery(connection, kind, timing_status=None, needs_review=False):
    column={"pop":"pop_recovered","participation":"participation_recovered","away":"away_recovered"}[kind]
    run=connection.execute("SELECT id FROM recovery_runs WHERE status='catching_up' ORDER BY id DESC LIMIT 1").fetchone()
    if not run:return
    fields=[f"{column}={column}+1"]
    if kind=="pop":
        if timing_status in {"on_time","late"}:fields.append(f"pop_{timing_status}=pop_{timing_status}+1")
        if needs_review:fields.append("pop_needs_review=pop_needs_review+1")
    connection.execute(f"UPDATE recovery_runs SET {','.join(fields)} WHERE id=?",(run["id"],))


def count_recovered_event(kind, path=None):
    with get_connection(path) as db:_increment_recovery(db,kind)


def finalize_recovery_run(run_id, now=None, path=None):
    now=now or utc_now()
    with get_connection(path) as db:
        row=db.execute("SELECT * FROM recovery_runs WHERE id=? AND status='catching_up'",(run_id,)).fetchone()
        if not row:return None
        if datetime.fromisoformat(now)<datetime.fromisoformat(row["catchup_until"]):return None
        if not row["previous_heartbeat_at"]:confidence="unknown"
        else:
            gap=datetime.fromisoformat(row["started_at"])-datetime.fromisoformat(row["previous_heartbeat_at"])
            confidence="complete" if gap<=timedelta(hours=23) else "partial"
        unresolved=None if confidence=="complete" else (row["unresolved_gap"] or "Telegram queue retention may not cover the full outage")
        db.execute("UPDATE recovery_runs SET status='complete',completed_at=?,confidence=?,unresolved_gap=? WHERE id=?",
            (now,confidence,unresolved,run_id))
        return db.execute("SELECT * FROM recovery_runs WHERE id=?",(run_id,)).fetchone()


def claim_recovery_summary(run_id, path=None):
    with get_connection(path) as db:
        cur=db.execute("UPDATE recovery_runs SET summary_claimed_at=? WHERE id=? AND summary_claimed_at IS NULL",
            (utc_now(),run_id))
        return bool(cur.rowcount)


def latest_recovery_run(path=None):
    with get_connection(path) as db:return db.execute("SELECT * FROM recovery_runs ORDER BY id DESC LIMIT 1").fetchone()


def record_runtime_heartbeat(path=None):
    set_system_state("runtime:last_heartbeat",utc_now(),path)


def pop_preservation_due(now=None, path=None):
    """Return new proofs whose 24-hour check is due, including resolved identity."""
    now = (now or datetime.now(ZoneInfo("America/New_York"))).isoformat()
    with get_connection(path) as db:
        rows = db.execute("""SELECT p.*,c.display_name,c.username FROM pop_submissions p
          JOIN creators c ON c.telegram_id=p.telegram_id
          WHERE p.deleted_at IS NULL AND p.preservation_status='pending_24h'
          AND p.preservation_due_at IS NOT NULL
          AND datetime(p.preservation_due_at)<=datetime(?)
          ORDER BY p.preservation_due_at,p.id""",(now,)).fetchall()
        return [_resolved_person_row(db,row) for row in rows]


def mark_pop_preservation_unavailable(submission_id, checked_at=None, path=None):
    """Atomically route a due proof to review when Telegram cannot verify existence."""
    checked_at = checked_at or utc_now()
    with get_connection(path) as db:
        cur=db.execute("""UPDATE pop_submissions
          SET preservation_status='unable_to_verify',preservation_checked_at=?,
              preservation_note='Telegram Bot API cannot verify arbitrary message existence'
          WHERE id=? AND preservation_status='pending_24h'
          AND preservation_due_at IS NOT NULL
          AND datetime(preservation_due_at)<=datetime(?)""",
          (checked_at,submission_id,checked_at))
        if not cur.rowcount:return False
        row=db.execute("SELECT telegram_id FROM pop_submissions WHERE id=?",(submission_id,)).fetchone()
        audit_event(db,None,"pop_preservation_unavailable","pop_submission",submission_id,
            row["telegram_id"],new_value="unable_to_verify",
            reason="Inconclusive Telegram API result; Admin review required",
            related_submission_id=submission_id)
        return True


def set_pop_preservation_status(submission_id, status, actor_id, note="", path=None):
    """Record a human-confirmed preservation result without changing POP ownership."""
    if status not in {"preserved","early_removed"}:
        return False
    with get_connection(path) as db:
        row=db.execute("SELECT * FROM pop_submissions WHERE id=? AND deleted_at IS NULL",(submission_id,)).fetchone()
        if not row or row["preservation_status"] == status:return False
        previous=row["preservation_status"]
        db.execute("""UPDATE pop_submissions SET preservation_status=?,preservation_checked_at=?,
          preservation_reviewed_by=?,preservation_note=? WHERE id=?""",
          (status,utc_now(),actor_id,(note or "")[:500] or None,submission_id))
        audit_event(db,actor_id,f"pop_preservation_{status}","pop_submission",submission_id,
            row["telegram_id"],previous_value=previous,new_value=status,reason=note,
            related_submission_id=submission_id)
        return True


def claim_pop_preservation_alert(submission_id, path=None):
    """Claim at most one preservation alert for a submission across restarts."""
    with get_connection(path) as db:
        cur=db.execute("""UPDATE pop_submissions SET preservation_alerted_at=?
          WHERE id=? AND preservation_alerted_at IS NULL
          AND preservation_status IN ('unable_to_verify','early_removed')""",
          (utc_now(),submission_id))
        return bool(cur.rowcount)


def pop_preservation_review_rows(path=None):
    with get_connection(path) as db:
        rows=db.execute("""SELECT p.*,c.display_name,c.username FROM pop_submissions p
          JOIN creators c ON c.telegram_id=p.telegram_id
          WHERE p.deleted_at IS NULL
          AND p.preservation_status IN ('unable_to_verify','early_removed')
          ORDER BY p.preservation_checked_at DESC,p.id DESC""").fetchall()
        return [_resolved_person_row(db,row) for row in rows]


def claim_owner_summary(owner_id, cycle_key, path=None):
    with get_connection(path) as db:
        try:
            db.execute("INSERT INTO owner_summary_deliveries(owner_id,cycle_key,claimed_at) VALUES(?,?,?)",
                       (owner_id,cycle_key,utc_now()))
            return True
        except sqlite3.IntegrityError:
            return False


def claim_daily_brief(cycle_date,path=None):
    """Claim one normal Admin Brief per Eastern calendar day."""
    with get_connection(path) as db:
        try:
            db.execute("INSERT INTO daily_brief_deliveries(cycle_date,claimed_at,status) VALUES(?,?,'pending')",(cycle_date,utc_now()))
            return True
        except sqlite3.IntegrityError:return False


def finish_daily_brief(cycle_date,status,error_reference=None,path=None):
    if status not in {"sent","failed"}:return False
    with get_connection(path) as db:
        cur=db.execute("UPDATE daily_brief_deliveries SET status=?,sent_at=CASE WHEN ?='sent' THEN ? ELSE sent_at END,error_reference=? WHERE cycle_date=?",
            (status,status,utc_now(),error_reference,cycle_date))
        return bool(cur.rowcount)


def daily_brief_record(cycle_date,path=None):
    with get_connection(path) as db:return db.execute("SELECT * FROM daily_brief_deliveries WHERE cycle_date=?",(cycle_date,)).fetchone()


def resolve_delivery_failure(error_reference,path=None):
    with get_connection(path) as db:
        cur=db.execute("UPDATE delivery_failures SET resolved_at=? WHERE error_reference=? AND resolved_at IS NULL",(utc_now(),error_reference))
        return bool(cur.rowcount)


def get_pop_submission(submission_id, path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM pop_submissions WHERE id=?", (submission_id,)).fetchone()


def review_pop(submission_id, status, actor_id, note="", path=None):
    if status not in {"approved", "rejected", "resubmission_requested"}:
        return False
    with get_connection(path) as db:
        cur=db.execute("UPDATE pop_submissions SET status=?,reviewed_at=?,reviewed_by=?,review_note=? WHERE id=? AND status='pending'",
                       (status,utc_now(),actor_id,note,submission_id))
        if cur.rowcount:
            row = db.execute("SELECT telegram_id FROM pop_submissions WHERE id=?", (submission_id,)).fetchone()
            audit_event(db,actor_id,f"pop_{status}","pop_submission",submission_id,
                        row["telegram_id"],previous_value="pending",new_value=status,
                        reason=note,related_submission_id=submission_id)
        return bool(cur.rowcount)


def pop_report(week_key, path=None):
    with get_connection(path) as db:
        rows=db.execute("""SELECT c.telegram_id,c.display_name,p.id,
          CASE WHEN x.id IS NOT NULL THEN 'excused' ELSE p.status END AS status,p.submitted_at
          FROM creators c LEFT JOIN pop_submissions p ON p.telegram_id=c.telegram_id AND p.week_key=?
          LEFT JOIN pop_excuses x ON x.telegram_id=c.telegram_id AND x.week_key=?
          WHERE c.status='active' AND c.deleted_at IS NULL ORDER BY c.display_name COLLATE NOCASE""", (week_key,week_key)).fetchall()
        return [_resolved_person_row(db,row) for row in rows]


def history(limit=50, path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def get_audit_event(audit_id,path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM audit_events WHERE id=?",(audit_id,)).fetchone()


def record_system_incident(fingerprint,reference,category,source,details,path=None,operation=None,now=None):
    """Create one open incident or atomically count a repeated occurrence."""
    now=now or utc_now();operation=operation or details.get("operation")
    with get_connection(path) as db:
        row=db.execute("SELECT * FROM system_incidents WHERE fingerprint=? AND status='open'",(fingerprint,)).fetchone()
        if row:
            db.execute("""UPDATE system_incidents SET last_seen=?,occurrence_count=occurrence_count+1,
              exception_type=?,message=?,traceback=?,operation=COALESCE(?,operation) WHERE id=?""",
              (now,details["exception_type"],details.get("message"),details.get("traceback"),operation,row["id"]))
            return db.execute("SELECT * FROM system_incidents WHERE id=?",(row["id"],)).fetchone(),False
        cur=db.execute("""INSERT INTO system_incidents
          (fingerprint,error_reference,category,source,operation,exception_type,message,traceback,first_seen,last_seen)
          VALUES(?,?,?,?,?,?,?,?,?,?)""",(fingerprint,reference,category,source,operation,details["exception_type"],
          details.get("message"),details.get("traceback"),now,now))
        return db.execute("SELECT * FROM system_incidents WHERE id=?",(cur.lastrowid,)).fetchone(),True


def get_system_incident(incident_id,path=None):
    with get_connection(path) as db:return db.execute("SELECT * FROM system_incidents WHERE id=?",(incident_id,)).fetchone()


def resolve_transient_incidents(path=None,operation=None,source=None,resolution_reason="matching_operation_succeeded"):
    """Resolve only transport incidents matching the operation that recovered."""
    now=utc_now()
    with get_connection(path) as db:
        sql="SELECT * FROM system_incidents WHERE category='transient_network' AND status='open'";params=[]
        if operation is not None:sql+=" AND operation=?";params.append(operation)
        if source is not None:sql+=" AND source=?";params.append(source)
        rows=db.execute(sql,params).fetchall()
        for row in rows:
            db.execute("UPDATE system_incidents SET status='resolved',resolved_at=?,resolution_reason=? WHERE id=?",
                (now,resolution_reason,row["id"]))
            audit_event(db,None,"system_incident_resolved","system_incident",row["id"],
                previous_value="open",new_value="resolved",error_reference=row["error_reference"],actor_role="system")
        return len(rows)


def claim_polling_escalation(incident_id,path=None,now=None):
    """Durably claim the one allowed Owner escalation for a polling incident."""
    with get_connection(path) as db:
        cur=db.execute("UPDATE system_incidents SET escalated_at=? WHERE id=? AND escalated_at IS NULL AND status='open'",
            (now or utc_now(),incident_id))
        return bool(cur.rowcount)


def polling_incidents_due_escalation(path=None,now=None):
    """Return unnotified polling incidents that crossed count or duration thresholds."""
    current=datetime.fromisoformat(now or utc_now());rows=[]
    with get_connection(path) as db:
        candidates=db.execute("""SELECT * FROM system_incidents WHERE status='open' AND category='transient_network'
          AND source='telegram_polling' AND operation='get_updates' AND escalated_at IS NULL""").fetchall()
    for row in candidates:
        age=(current-datetime.fromisoformat(row["first_seen"])).total_seconds()
        if row["occurrence_count"]>=3 or (row["occurrence_count"]>=2 and age>=300):rows.append(row)
    return rows


def resolve_quiet_polling_incidents(path=None,now=None,quiet_seconds=120):
    """Resolve getUpdates incidents only after their own failure stream stays quiet."""
    current=datetime.fromisoformat(now or utc_now());resolved=0
    with get_connection(path) as db:
        rows=db.execute("""SELECT * FROM system_incidents WHERE status='open' AND category='transient_network'
          AND source='telegram_polling' AND operation='get_updates'""").fetchall()
        for row in rows:
            if (current-datetime.fromisoformat(row["last_seen"])).total_seconds()<quiet_seconds:continue
            db.execute("""UPDATE system_incidents SET status='resolved',resolved_at=?,resolution_reason='polling_quiet_window'
              WHERE id=?""",(current.isoformat(),row["id"]));resolved+=1
            audit_event(db,None,"system_incident_resolved","system_incident",row["id"],previous_value="open",
                new_value="resolved",reason="Polling remained quiet for two minutes",
                error_reference=row["error_reference"],actor_role="system")
    return resolved


def create_support_request(telegram_id, category, message, path=None):
    """Create a durable request before attempting Telegram delivery."""
    now=utc_now()
    with get_connection(path) as db:
        creator=db.execute("SELECT 1 FROM creators WHERE telegram_id=? AND deleted_at IS NULL",(telegram_id,)).fetchone()
        if not creator:
            return None
        cur=db.execute("""INSERT INTO support_requests
          (telegram_id,category,message,created_at,updated_at) VALUES(?,?,?,?,?)""",
          (telegram_id,category,message,now,now))
        request_id=cur.lastrowid
        audit_event(db,telegram_id,"support_request_created","support_request",request_id,telegram_id,
            new_value={"category":category,"length":len(message)})
        return request_id


def update_support_delivery(request_id, status, error_reference=None, path=None):
    with get_connection(path) as db:
        db.execute("UPDATE support_requests SET delivery_status=?,delivery_error_ref=?,updated_at=? WHERE id=?",
            (status,error_reference,utc_now(),request_id))


def support_requests_for(telegram_id, path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM support_requests WHERE telegram_id=? ORDER BY created_at DESC",(telegram_id,)).fetchall()


def support_messages_for(request_id,telegram_id,path=None):
    """Return replies only when the request belongs to the requesting creator."""
    with get_connection(path) as db:
        return db.execute("""SELECT m.* FROM support_messages m JOIN support_requests s ON s.id=m.request_id
          WHERE m.request_id=? AND s.telegram_id=? ORDER BY m.created_at""",(request_id,telegram_id)).fetchall()


def get_support_request(request_id,path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM support_requests WHERE id=?",(request_id,)).fetchone()


def support_queue(path=None):
    with get_connection(path) as db:
        rows=db.execute("""SELECT s.*,c.display_name,c.username FROM support_requests s
          JOIN creators c ON c.telegram_id=s.telegram_id
          WHERE s.status!='resolved' ORDER BY s.created_at""").fetchall()
        return [_resolved_person_row(db,row) for row in rows]


def update_support_request(request_id, action, actor_id, note=None, path=None):
    states={"assign":"assigned","escalate":"escalated","resolve":"resolved","open":"open"}
    if action not in states: return False
    now=utc_now();new_status=states[action]
    with get_connection(path) as db:
        row=db.execute("SELECT * FROM support_requests WHERE id=?",(request_id,)).fetchone()
        if not row or row["status"]=="resolved": return False
        db.execute("""UPDATE support_requests SET status=?,assigned_to=CASE WHEN ?='assign' THEN ? ELSE assigned_to END,
          resolved_at=CASE WHEN ?='resolve' THEN ? ELSE resolved_at END,
          resolved_by=CASE WHEN ?='resolve' THEN ? ELSE resolved_by END,
          resolution_note=CASE WHEN ?='resolve' THEN ? ELSE resolution_note END,updated_at=? WHERE id=?""",
          (new_status,action,actor_id,action,now,action,actor_id,action,note,now,request_id))
        audit_event(db,actor_id,f"support_request_{action}","support_request",request_id,row["telegram_id"],
            previous_value=row["status"],new_value=new_status,reason=note)
        return True


def add_support_message(request_id,sender_id,sender_role,body,path=None):
    with get_connection(path) as db:
        request=db.execute("SELECT * FROM support_requests WHERE id=?",(request_id,)).fetchone()
        if not request:return None
        cur=db.execute("INSERT INTO support_messages(request_id,sender_id,sender_role,body,created_at) VALUES(?,?,?,?,?)",
            (request_id,sender_id,sender_role,body[:1500],utc_now()))
        audit_event(db,sender_id,"support_reply_created","support_message",cur.lastrowid,request["telegram_id"],
            related_request_id=request_id,new_value={"length":len(body)})
        return cur.lastrowid,request["telegram_id"]


def record_delivery_failure(error_reference,event_type,chat_id,thread_id,payload_summary,path=None):
    with get_connection(path) as db:
        db.execute("""INSERT OR IGNORE INTO delivery_failures
          (error_reference,event_type,destination_chat_id,destination_thread_id,payload_summary,created_at)
          VALUES(?,?,?,?,?,?)""",(error_reference,event_type,chat_id,thread_id,payload_summary,utc_now()))
        audit_event(db,None,"notification_delivery_failed","delivery",new_value={"event":event_type,"destination":chat_id},
            source_chat_id=chat_id,source_thread_id=thread_id,result="error",error_reference=error_reference)


def open_delivery_failures(path=None):
    with get_connection(path) as db:
        return db.execute("SELECT * FROM delivery_failures WHERE resolved_at IS NULL ORDER BY created_at DESC").fetchall()


def participation_monitor(path=None):
    today=datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    with get_connection(path) as db:
        scalar=lambda sql,args=(): db.execute(sql,args).fetchone()[0]
        ignored=db.execute("""SELECT reason,COUNT(*) count FROM engagement_events
          WHERE decision='rejected' AND substr(created_at,1,10)=? GROUP BY reason ORDER BY count DESC""",(today,)).fetchall()
        return {"tracked":scalar("SELECT COUNT(*) FROM creators WHERE status='active' AND deleted_at IS NULL"),
            "ignored_today":sum(r["count"] for r in ignored),"ignored_categories":ignored,
            "last_detected":db.execute("SELECT updated_at AS created_at FROM system_state WHERE state_key='last_participation_message_detected'").fetchone()
                or db.execute("SELECT created_at FROM engagement_events ORDER BY id DESC LIMIT 1").fetchone(),
            "last_counted":db.execute("SELECT created_at FROM engagement_events WHERE decision='accepted' ORDER BY id DESC LIMIT 1").fetchone(),
            "failures":scalar("SELECT COUNT(*) FROM delivery_failures WHERE resolved_at IS NULL")}


def participation_events(limit=30,path=None):
    with get_connection(path) as db:
        rows=db.execute("""SELECT e.created_at,e.decision,e.reason,e.telegram_id,c.display_name
          FROM engagement_events e LEFT JOIN creators c ON c.telegram_id=e.telegram_id
          ORDER BY e.id DESC LIMIT ?""",(limit,)).fetchall()
        return [_resolved_person_row(db,row) for row in rows]


def participation_activity(start_utc, end_utc, path=None):
    """Aggregate existing participation events inside one half-open UTC window."""
    with get_connection(path) as db:
        rows=db.execute("""SELECT e.telegram_id,COUNT(*) AS count,MAX(e.created_at) AS last_event,
          c.display_name,c.username FROM engagement_events e JOIN creators c ON c.telegram_id=e.telegram_id
          WHERE e.decision='accepted' AND datetime(e.created_at)>=datetime(?) AND datetime(e.created_at)<datetime(?)
          AND c.status='active' AND c.deleted_at IS NULL GROUP BY e.telegram_id
          ORDER BY c.display_name COLLATE NOCASE""",(start_utc,end_utc)).fetchall()
        ignored=db.execute("""SELECT COUNT(*) FROM engagement_events
          WHERE decision!='accepted' AND datetime(created_at)>=datetime(?) AND datetime(created_at)<datetime(?)""",(start_utc,end_utc)).fetchone()[0]
        return {"accepted":[_resolved_person_row(db,row) for row in rows],"ignored":ignored}


def creator_participation_diagnostics(path=None):
    """Return active creators and their latest sanitized observer outcome."""
    with get_connection(path) as db:
        creators=[_resolved_person_row(db,row) for row in db.execute("""SELECT telegram_id,display_name,username FROM creators
          WHERE status='active' AND deleted_at IS NULL ORDER BY display_name COLLATE NOCASE""").fetchall()]
        states={row["state_key"].rsplit(":",1)[-1]:row for row in db.execute("""SELECT state_key,state_value,updated_at
          FROM system_state WHERE state_key LIKE 'participation:last_creator:%'""").fetchall()}
    results=[]
    for creator in creators:
        state=states.get(str(creator["telegram_id"]));diagnostic=None
        if state:
            try:
                diagnostic=json.loads(state["state_value"])
            except (TypeError,json.JSONDecodeError):
                diagnostic={"reason":"unreadable_diagnostic","observed_at":state["updated_at"]}
        results.append({"creator":creator,"diagnostic":diagnostic})
    return results


def reset_history(actor_id, path=None):
    raise PermissionError("The audit trail is append-only and cannot be reset.")


def audit_setting_change(actor_id, key, old_value, new_value, path=None):
    with get_connection(path) as db:
        audit_event(db, actor_id, "setting_changed", "setting", previous_value={key: old_value}, new_value={key: new_value})


def set_system_state(key, value, path=None):
    with get_connection(path) as db:
        db.execute("""INSERT INTO system_state(state_key,state_value,updated_at) VALUES(?,?,?)
          ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=excluded.updated_at""",
          (key,str(value),utc_now()))


def system_state(path=None):
    with get_connection(path) as db:
        return {row["state_key"]:{"value":row["state_value"],"updated_at":row["updated_at"]}
            for row in db.execute("SELECT * FROM system_state").fetchall()}


def schema_version(path=None):
    with get_connection(path) as db:
        return db.execute("SELECT version FROM schema_version").fetchone()[0]


def audit_event(db, actor_id, action, target_type=None, target_record_id=None,
                target_telegram_id=None, previous_value=None, new_value=None, reason=None,
                source_chat_id=None, source_thread_id=None, related_request_id=None,
                related_submission_id=None, result="success", error_reference=None,
                actor_name=None, actor_role="unknown"):
    def encoded(value):
        return None if value is None else json.dumps(value, sort_keys=True, default=str)
    db.execute("""INSERT INTO audit_events
      (occurred_at,actor_id,actor_name,actor_role,action,target_type,target_record_id,
       target_telegram_id,previous_value,new_value,reason,source_chat_id,source_thread_id,
       related_request_id,related_submission_id,result,error_reference)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (utc_now(),actor_id,actor_name,actor_role,action,target_type,target_record_id,
       target_telegram_id,encoded(previous_value),encoded(new_value),reason,
       source_chat_id,source_thread_id,related_request_id,related_submission_id,result,error_reference))


def _audit(db, actor_id, target_id, action, details, now=None):
    db.execute("INSERT INTO audit_history(actor_id,target_id,action,details,created_at) VALUES(?,?,?,?,?)",
               (actor_id,target_id,action,json.dumps(details,sort_keys=True),now or utc_now()))
