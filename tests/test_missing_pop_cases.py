import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))
import database as db


class MissingPopCaseTests(unittest.TestCase):
    WEEK = "2026-W30"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "case.db"
        db.initialize_database(self.path)
        db.register_creator(1, "creator", "Creator Name", self.path)
        db.set_status(1, "active", 9, self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def case(self, week=None):
        return db.create_missing_pop_case(1, week or self.WEEK, self.path)

    def strike(self, case=None, actor=9):
        return db.issue_missing_pop_strike((case or self.case())["id"], actor, self.path)

    def evidence(self, timing):
        stamp = "2026-07-23T12:00:00-04:00" if timing == "on_time" else "2026-07-24T12:00:00-04:00"
        return db.record_pop_evidence(1, self.WEEK, 100 if timing == "on_time" else 101,
            -100, 7, "photo", timing, source_message_at=stamp, path=self.path)

    def audit_actions(self):
        return [row["action"] for row in db.history(100, self.path)]

    def counts(self):
        with db.get_connection(self.path) as connection:
            return {
                "official": connection.execute("SELECT COUNT(*) FROM official_pop_strikes").fetchone()[0],
                "warnings": connection.execute("SELECT COUNT(*) FROM creator_warnings WHERE warning_type='strike'").fetchone()[0],
            }

    def test_case_creation_is_idempotent_and_unique(self):
        first, second = self.case(), self.case()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(db.list_missing_pop_cases(self.WEEK, self.path)), 1)
        with db.get_connection(self.path) as connection, self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO missing_pop_cases(telegram_id,week_key,created_at) VALUES(1,?,?)",
                (self.WEEK, db.utc_now()))

    def test_listing_includes_identity_and_pending_status(self):
        created = self.case()
        row = db.list_missing_pop_cases(self.WEEK, self.path)[0]
        self.assertEqual((row["id"], row["telegram_id"], row["week_key"], row["status"]),
                         (created["id"], 1, self.WEEK, "pending"))
        self.assertEqual((row["display_name"], row["username"]), ("Creator Name", "creator"))

    def test_pending_review_and_excusal_are_durable_and_audited(self):
        case = self.case()
        self.assertTrue(db.resolve_missing_pop_case(case["id"], "pending", 8, path=self.path))
        pending = db.list_missing_pop_cases(self.WEEK, self.path)[0]
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(pending["reviewed_by"], 8)
        self.assertIsNotNone(pending["reviewed_at"])
        self.assertTrue(db.resolve_missing_pop_case(case["id"], "excused", 9, "Approved exception", self.path))
        excused = db.list_missing_pop_cases(self.WEEK, self.path)[0]
        self.assertEqual((excused["status"], excused["resolution_type"], excused["resolved_by"]),
                         ("excused", "excused", 9))
        self.assertEqual(excused["excusal_reason"], "Approved exception")
        self.assertIsNotNone(excused["resolved_at"])
        self.assertFalse(self.strike(case)["ok"])
        self.assertIn("missing_pop_case_left_pending", self.audit_actions())
        self.assertIn("missing_pop_case_excused", self.audit_actions())

    def test_successful_strike_links_case_warning_and_official_guard(self):
        case = self.case()
        result = self.strike(case)
        self.assertEqual(result["reason"], "strike_issued")
        row = db.list_missing_pop_cases(self.WEEK, self.path)[0]
        self.assertEqual((row["status"], row["resolution_type"], row["resolved_by"]),
                         ("strike_issued", "strike", 9))
        self.assertEqual(row["strike_warning_id"], result["warning_id"])
        self.assertIsNotNone(row["resolved_at"])
        self.assertEqual(self.counts(), {"official": 1, "warnings": 1})
        self.assertIn("missing_pop_strike_confirmed", self.audit_actions())
        duplicate = self.strike(case, 10)
        self.assertEqual(duplicate["reason"], "official_strike_exists")
        self.assertEqual(self.counts(), {"official": 1, "warnings": 1})

    def test_database_enforces_official_and_warning_link_uniqueness(self):
        result = self.strike()
        db.register_creator(2, "other", "Other", self.path)
        db.set_status(2, "active", 9, self.path)
        with db.get_connection(self.path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO official_pop_strikes(telegram_id,week_key,warning_id,created_at) VALUES(1,?,999,?)", (self.WEEK, db.utc_now()))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO official_pop_strikes(telegram_id,week_key,warning_id,created_at) VALUES(2,'2026-W31',?,?)",
                    (result["warning_id"], db.utc_now()))

    def test_external_strike_is_durable_audited_and_never_retryable(self):
        case=self.case()
        result=db.record_external_missing_pop_strike(case["id"],1,self.WEEK,9,"Alex",
            "2026-07-31T09:30:00-04:00","Owner reviewed screenshot",True,self.path)
        self.assertTrue(result["ok"])
        row=dict(db.get_missing_pop_case(case["id"],self.path))
        self.assertEqual((row["status"],row["resolution_type"],row["creator_notified"]),
            ("strike_issued","strike_issued_external",1))
        self.assertEqual((row["issuance_source"],row["recorded_by"],row["external_issued_by"],
            row["external_note"],row["external_proof_reviewed"]),
            ("external",9,"Alex","Owner reviewed screenshot",1))
        self.assertEqual(row["notification_status"],"not_started")
        self.assertFalse(db.retry_missing_pop_notification(case["id"],self.path,actor_id=9)["ok"])
        self.assertEqual(self.counts(),{"official":1,"warnings":1})
        self.assertIn("missing_pop_external_strike_recorded",self.audit_actions())

    def test_external_strike_duplicate_and_concurrent_attempts_create_one(self):
        case=self.case()
        def record(actor):
            return db.record_external_missing_pop_strike(case["id"],1,self.WEEK,actor,"Alex",
                "2026-07-31T09:30:00-04:00","",True,self.path)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(record,(9,10)))
        self.assertEqual(sum(result["ok"] for result in results),1)
        self.assertEqual(self.counts(),{"official":1,"warnings":1})
        duplicate=record(11)
        self.assertEqual(duplicate["reason"],"official_strike_exists")
        self.assertIn("missing_pop_external_duplicate_blocked",self.audit_actions())

    def test_external_strike_rechecks_case_identity_and_eligibility(self):
        case=self.case()
        mismatch=db.record_external_missing_pop_strike(case["id"],999,self.WEEK,9,"Alex",
            "2026-07-31T09:30:00-04:00",path=self.path)
        self.assertEqual(mismatch["reason"],"case_identity_mismatch")
        self.evidence("late")
        blocked=db.record_external_missing_pop_strike(case["id"],1,self.WEEK,9,"Alex",
            "2026-07-31T09:30:00-04:00",path=self.path)
        self.assertEqual(blocked["reason"],"qualifying_evidence")
        self.assertEqual(self.counts(),{"official":0,"warnings":0})

    def test_concurrent_strike_attempts_create_exactly_one(self):
        case = self.case()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda actor: db.issue_missing_pop_strike(case["id"], actor, self.path), (8, 9)))
        self.assertEqual(sum(result["ok"] for result in results), 1)
        self.assertEqual(self.counts(), {"official": 1, "warnings": 1})

    def test_on_time_and_late_evidence_each_block_and_reconcile(self):
        for timing, week in (("on_time", self.WEEK), ("late", "2026-W31")):
            if week != self.WEEK:
                self.WEEK = week
            case = self.case(week)
            self.evidence(timing)
            result = self.strike(case)
            self.assertEqual(result["reason"], "qualifying_evidence")
            self.assertEqual(db.list_missing_pop_cases(week, self.path)[0]["status"], "resolved")
        self.assertEqual(self.counts(), {"official": 0, "warnings": 0})
        self.assertIn("missing_pop_case_manually_reconciled", self.audit_actions())

    def test_pop_excuse_and_approved_away_notice_block(self):
        case = self.case()
        request = db.create_absence_request(1, "vacation", "2026-07-23", "2026-07-23", path=self.path)
        db.review_absence(request, "approved", 9, path=self.path)
        self.assertEqual(self.strike(case)["reason"], "excused")
        with db.get_connection(self.path) as connection:
            connection.execute("DELETE FROM pop_excuses WHERE telegram_id=1 AND week_key=?", (self.WEEK,))
        self.assertEqual(self.strike(case)["reason"], "approved_away_notice")

    def test_inactive_and_archived_creator_block(self):
        case = self.case()
        db.set_status(1, "inactive", 9, self.path)
        self.assertEqual(self.strike(case)["reason"], "creator_ineligible")
        db.set_status(1, "active", 9, self.path)
        db.delete_creator(1, 9, self.path)
        self.assertEqual(self.strike(case)["reason"], "creator_ineligible")

    def test_manual_reconciliation_after_creation_prevents_strike(self):
        case = self.case()
        saved = db.record_manual_pop_reconciliation(1, self.WEEK, "on_time",
            "2026-07-23T12:00:00-04:00", "visible proof", 9, "manual-1", path=self.path)
        self.assertTrue(saved["saved"])
        result = self.strike(case)
        self.assertEqual(result["reason"], "manual_reconciliation")
        self.assertIn("missing_pop_case_manually_reconciled", self.audit_actions())

    def test_already_resolved_case_blocks_strike(self):
        case = self.case()
        self.assertTrue(db.reconcile_missing_pop_case(1, self.WEEK, 9, path=self.path))
        result = self.strike(case)
        self.assertEqual((result["ok"], result["reason"]), (False, "case_resolved"))
        self.assertEqual(self.counts(), {"official": 0, "warnings": 0})

    def test_notification_failure_retry_success_never_duplicates_strike(self):
        case = self.case()
        strike = self.strike(case)
        self.assertTrue(db.record_missing_pop_notification(case["id"], False, "Forbidden", self.path))
        failed = db.list_missing_pop_cases(self.WEEK, self.path)[0]
        self.assertEqual((failed["notification_status"], failed["creator_notified"], failed["notification_error"]),
                         ("failed", 0, "Forbidden"))
        self.assertIsNotNone(failed["notification_updated_at"])
        retry = db.retry_missing_pop_notification(case["id"], self.path, actor_id=9)
        self.assertTrue(retry["ok"])
        self.assertTrue(db.record_missing_pop_notification(case["id"], True, path=self.path, actor_id=9))
        self.assertFalse(db.retry_missing_pop_notification(case["id"], self.path)["ok"])
        delivered = db.list_missing_pop_cases(self.WEEK, self.path)[0]
        self.assertEqual((delivered["notification_status"], delivered["creator_notified"], delivered["notification_error"]),
                         ("delivered", 1, None))
        self.assertEqual(delivered["strike_warning_id"], strike["warning_id"])
        self.assertEqual(self.counts(), {"official": 1, "warnings": 1})
        actions = self.audit_actions()
        self.assertIn("missing_pop_notification_failed", actions)
        self.assertIn("missing_pop_notification_retried", actions)
        self.assertIn("missing_pop_notification_delivered", actions)

    def test_schema_v14_upgrades_to_v17_additively_and_idempotently(self):
        db.add_warning(1,"warning","Preserved moderation warning",9,self.path)
        db.record_pop_evidence(1,self.WEEK,500,-100,7,"photo","on_time",
            source_message_at="2026-07-23T12:00:00-04:00",path=self.path)
        request_id=db.create_absence_request(1,"vacation","2026-08-01","2026-08-02","Private",self.path)
        db.set_system_state("preserved_setting","yes",self.path)
        with db.get_connection(self.path) as connection:
            connection.execute("DROP TABLE missing_pop_evaluations")
            connection.execute("DROP TABLE official_pop_strikes")
            connection.execute("DROP TABLE missing_pop_cases")
            connection.execute("UPDATE schema_version SET version=14")
        db.initialize_database(self.path)
        db.initialize_database(self.path)
        with db.get_connection(self.path) as connection:
            tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            indexes={row[1] for row in connection.execute("PRAGMA index_list(missing_pop_cases)")}
            case_sql=connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='missing_pop_cases'").fetchone()[0]
            strike_sql=connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='official_pop_strikes'").fetchone()[0]
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0],17)
            self.assertTrue({"missing_pop_cases","official_pop_strikes","missing_pop_evaluations"}.issubset(tables))
            self.assertIn("missing_pop_cases_status",indexes)
            self.assertIn("UNIQUE(telegram_id,week_key)",case_sql.replace(" ",""))
            self.assertIn("PRIMARYKEY(telegram_id,week_key)",strike_sql.replace(" ",""))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM creators WHERE telegram_id=1").fetchone()[0],1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM creator_warnings WHERE telegram_id=1").fetchone()[0],1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM pop_submissions WHERE telegram_id=1").fetchone()[0],1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM absence_requests WHERE id=?",(request_id,)).fetchone()[0],1)
            self.assertEqual(connection.execute("SELECT state_value FROM system_state WHERE state_key='preserved_setting'").fetchone()[0],"yes")

    def test_schema_v16_upgrades_to_v17_preserving_existing_strike(self):
        strike=self.strike()
        with db.get_connection(self.path) as connection:
            connection.execute("UPDATE schema_version SET version=16")
            # Rebuild a realistic v16 official table because SQLite cannot drop
            # individual columns portably on every supported runtime.
            connection.executescript("""ALTER TABLE official_pop_strikes RENAME TO official_pop_strikes_v17;
                CREATE TABLE official_pop_strikes(telegram_id INTEGER NOT NULL,week_key TEXT NOT NULL,
                warning_id INTEGER NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(telegram_id,week_key),UNIQUE(warning_id));
                INSERT INTO official_pop_strikes(telegram_id,week_key,warning_id,created_at)
                SELECT telegram_id,week_key,warning_id,created_at FROM official_pop_strikes_v17;
                DROP TABLE official_pop_strikes_v17;""")
        db.initialize_database(self.path);db.initialize_database(self.path)
        with db.get_connection(self.path) as connection:
            columns={row[1] for row in connection.execute("PRAGMA table_info(official_pop_strikes)")}
            preserved=connection.execute("SELECT * FROM official_pop_strikes WHERE warning_id=?",(strike["warning_id"],)).fetchone()
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0],17)
            self.assertTrue({"issuance_source","recorded_by","external_issued_by","external_notice_at","external_note","external_proof_reviewed"}.issubset(columns))
            self.assertEqual(preserved["issuance_source"],"bot")


if __name__ == "__main__":
    unittest.main()
