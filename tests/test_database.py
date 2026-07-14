import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

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
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()["version"], 9)

    def test_repeat_registration_preserves_approval_and_prevents_duplicates(self):
        self.assertEqual(db.register_creator(6558268505,"kira","Kira",self.path),"created")
        db.set_status(6558268505,"active",99,self.path)
        self.assertEqual(db.register_creator(6558268505,"new_name","Kira Rose",self.path),"active")
        with db.get_connection(self.path) as connection:
            count=connection.execute("SELECT COUNT(*) FROM creators WHERE telegram_id=?",(6558268505,)).fetchone()[0]
        self.assertEqual(count,1)
        self.assertEqual(db.get_creator(6558268505,self.path)["status"],"active")

    def test_person_identity_deduplicates_id_and_prefers_approved_creator_name(self):
        user_id=8129455408
        db.record_bot_user(user_id,"bambola","Telegram user 8129455408",self.path)
        db.register_creator(user_id,"bambolawife","Bambolawife",self.path)
        db.set_status(user_id,"active",99,self.path)
        db.record_engagement(user_id,77,-100,None,"identity-history","accepted","meaningful",self.path)
        last_meaningful=db.get_creator(user_id,self.path)["last_meaningful_at"]
        cfg=SimpleNamespace(owner_user_ids=frozenset(),lead_admin_user_ids=frozenset(),admin_user_ids=frozenset({user_id}))
        db.synchronize_role_memberships(cfg,self.path)
        people=db.people_for_ids([user_id,user_id,user_id],self.path)
        self.assertEqual(len(people),1)
        self.assertEqual(people[0]["telegram_id"],user_id)
        self.assertEqual(people[0]["display_name"],"Bambolawife")
        self.assertEqual(db.roles_for_user(user_id,self.path),frozenset({"creator","admin"}))
        self.assertEqual(db.get_creator(user_id,self.path)["last_meaningful_at"],last_meaningful)
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM creators WHERE telegram_id=?",(user_id,)).fetchone()[0],1)

    def test_same_visible_name_on_different_ids_remains_two_people(self):
        for user_id in (101,202):
            db.register_creator(user_id,f"same{user_id}","Same Name",self.path)
            db.set_status(user_id,"active",99,self.path)
        people=db.people_for_ids([101,202],self.path)
        creators=db.list_creators(self.path)
        self.assertEqual([row["telegram_id"] for row in people],[101,202])
        self.assertEqual({row["telegram_id"] for row in creators},{101,202})

    def test_person_name_fallback_priority(self):
        db.record_bot_user(301,"telegram301","Telegram Full Name",self.path)
        db.register_member(301,"member301","Preferred Name","buyer",self.path)
        db.record_bot_user(302,"telegram302","Telegram Full Name",self.path)
        db.record_bot_user(303,"telegram303","Telegram user 303",self.path)
        resolved={row["telegram_id"]:row["display_name"] for row in db.people_for_ids([301,302,303,304],self.path)}
        self.assertEqual(resolved[301],"Preferred Name")
        self.assertEqual(resolved[302],"Telegram Full Name")
        self.assertEqual(resolved[303],"telegram303")
        self.assertEqual(resolved[304],"Telegram user 304")

    def test_archived_creator_is_not_resolved_as_active_identity(self):
        db.register_creator(6558268505,"kira","Kira",self.path)
        db.delete_creator(6558268505,99,self.path)
        self.assertIsNone(db.get_creator(6558268505,self.path))
        status=db.creator_identity_status(6558268505,self.path)
        self.assertEqual(status["state"],"archived")
        self.assertFalse(status["directory_visible"])

    def test_engagement_is_idempotent(self):
        db.register_creator(10, "girl", "Creator", self.path)
        db.set_status(10, "active", 99, self.path)
        self.assertTrue(db.record_engagement(10, 7, -1, 3, "hash", "accepted", "meaningful", self.path))
        self.assertFalse(db.record_engagement(10, 7, -1, 3, "hash", "accepted", "meaningful", self.path))
        self.assertIsNotNone(db.get_creator(10, self.path)["last_meaningful_at"])

    def test_voice_engagement_updates_last_meaningful_and_timeline(self):
        db.register_creator(10,"girl","Creator",self.path);db.set_status(10,"active",99,self.path)
        self.assertTrue(db.record_engagement(10,8,-1,3,"voice-hash","accepted","voice_message",self.path,event_type="voice_message"))
        self.assertIsNotNone(db.get_creator(10,self.path)["last_meaningful_at"])
        actions=[row["action"] for row in db.creator_timeline(10,20,0,self.path)]
        self.assertIn("engagement_counted_voice_message",actions)

    def test_role_migration_preserves_creator_history_and_adds_staff_capabilities(self):
        db.register_creator(10,"kira","Kira",self.path);db.set_status(10,"active",99,self.path)
        db.record_engagement(10,70,-100,None,"existing","accepted","meaningful",self.path)
        previous=db.get_creator(10,self.path)["last_meaningful_at"]
        db.record_bot_user(20,"keely","Keely",self.path)
        db.register_creator(30,"eve","Eve",self.path)
        cfg=SimpleNamespace(owner_user_ids=frozenset({10}),lead_admin_user_ids=frozenset(),admin_user_ids=frozenset({20,30}))
        result=db.synchronize_role_memberships(cfg,self.path)
        self.assertEqual(result["created_creator_profiles"],[20])
        self.assertEqual(result["activated_creator_profiles"],[30])
        self.assertEqual(db.roles_for_user(10,self.path),frozenset({"creator","admin","owner"}))
        self.assertEqual(db.roles_for_user(20,self.path),frozenset({"creator","admin"}))
        self.assertEqual(db.get_creator(10,self.path)["last_meaningful_at"],previous)
        self.assertEqual(db.get_creator(20,self.path)["status"],"active")
        self.assertEqual(db.get_creator(30,self.path)["status"],"active")
        db.synchronize_role_memberships(cfg,self.path)
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM creators WHERE telegram_id=10").fetchone()[0],1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM creators WHERE telegram_id=20").fetchone()[0],1)
        cfg.admin_user_ids=frozenset({30});db.synchronize_role_memberships(cfg,self.path)
        self.assertEqual(db.roles_for_user(20,self.path),frozenset({"creator"}))
        self.assertIsNotNone(db.get_creator(20,self.path))

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
        self.assertEqual(db.get_member(22,legacy)["member_type"],"creator")

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
