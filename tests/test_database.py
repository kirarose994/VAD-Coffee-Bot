import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))
import database as db


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.db"
        db.initialize_database(self.path)

    def tearDown(self): self.tmp.cleanup()

    def test_creator_approval_vacation_and_history(self):
        db.register_creator(10, "girl", "Creator", self.path)
        self.assertEqual(db.get_creator(10, self.path)["status"], "pending")
        self.assertTrue(db.set_status(10, "active", 99, self.path))
        self.assertTrue(db.set_vacation(10, "2026-07-31", 99, self.path))
        self.assertEqual(len(db.history(path=self.path)), 3)

    def test_engagement_is_idempotent(self):
        db.register_creator(10, "girl", "Creator", self.path)
        db.set_status(10, "active", 99, self.path)
        self.assertTrue(db.record_engagement(10, 7, -1, 3, "hash", "accepted", "meaningful", self.path))
        self.assertFalse(db.record_engagement(10, 7, -1, 3, "hash", "accepted", "meaningful", self.path))
        self.assertIsNotNone(db.get_creator(10, self.path)["last_meaningful_at"])

    def test_pop_and_notifications_are_idempotent(self):
        db.register_creator(10, "girl", "Creator", self.path)
        db.set_status(10, "active", 99, self.path)
        self.assertTrue(db.submit_pop(10, "2026-W29", 1, -1, 4, "photo", self.path))
        self.assertFalse(db.submit_pop(10, "2026-W29", 2, -1, 4, "photo", self.path))
        self.assertTrue(db.claim_notification(10, "cycle", "warning", self.path))
        self.assertFalse(db.claim_notification(10, "cycle", "warning", self.path))

    def test_migrates_legacy_creator_schema(self):
        legacy = Path(self.tmp.name) / "legacy.db"
        import sqlite3
        conn = sqlite3.connect(legacy)
        conn.executescript("""CREATE TABLE creators(telegram_id INTEGER PRIMARY KEY, username TEXT,
          display_name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, vacation_until TEXT,
          last_meaningful_message TEXT, engagement_score INTEGER DEFAULT 0, date_added TEXT);
          INSERT INTO creators VALUES(22,'old','Legacy',1,NULL,NULL,0,'2026-01-01');""")
        conn.close()
        db.initialize_database(legacy)
        creator = db.get_creator(22, legacy)
        self.assertEqual(creator["status"], "active")
        self.assertEqual(creator["registered_at"], "2026-01-01")

    def test_destructive_actions_and_settings_are_audited(self):
        db.register_creator(10, "girl", "Creator", self.path)
        self.assertTrue(db.delete_creator(10, 99, self.path))
        db.audit_setting_change(99, "warning_hours", 48, 24, self.path)
        actions = [row["action"] for row in db.history(path=self.path)]
        self.assertIn("creator_soft_deleted", actions)
        self.assertIn("setting_changed", actions)
        with self.assertRaises(PermissionError):
            db.reset_history(99, self.path)
        self.assertGreaterEqual(len(db.history(path=self.path)), 3)


if __name__ == "__main__": unittest.main()
