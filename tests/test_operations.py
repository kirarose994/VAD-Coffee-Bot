import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))

import database as db
from navigation import callback, home_markup
from permissions import has_permission


class OperationsDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "operations.db"
        db.initialize_database(self.path)
        db.register_creator(10, "creator", "Creator", self.path)
        db.set_status(10, "active", 20, self.path)

    def tearDown(self): self.tmp.cleanup()

    def test_vacation_approval_pauses_expectations_and_excuses_thursday_pop(self):
        request_id = db.create_absence_request(10, "vacation", "2026-07-15", "2026-07-17", "Away", self.path)
        self.assertTrue(db.review_absence(request_id, "approved", 20, path=self.path))
        self.assertIsNotNone(db.approved_absence_on(10, date(2026, 7, 16), self.path))
        report = db.pop_report("2026-W29", self.path)
        self.assertEqual(report[0]["status"], "excused")
        db.sync_absence_availability(date(2026, 7, 16), self.path)
        self.assertEqual(db.get_creator(10, self.path)["availability"], "vacation")
        db.sync_absence_availability(date(2026, 7, 18), self.path)
        self.assertEqual(db.get_creator(10, self.path)["availability"], "unavailable")

    def test_sick_day_approval_uses_extensible_absence_model(self):
        request_id = db.create_absence_request(10, "sick", "2026-07-14", "2026-07-14", None, self.path)
        self.assertTrue(db.review_absence(request_id, "approved", 20, path=self.path))
        self.assertEqual(db.get_creator(10, self.path)["availability"], "sick")

    def test_duplicate_review_is_idempotent(self):
        request_id = db.create_absence_request(10, "vacation", "2026-08-01", "2026-08-02", None, self.path)
        self.assertTrue(db.review_absence(request_id, "approved", 20, path=self.path))
        self.assertFalse(db.review_absence(request_id, "denied", 20, path=self.path))

    def test_soft_delete_is_owner_visible_and_restorable(self):
        self.assertTrue(db.delete_creator(10, 20, self.path))
        self.assertEqual(len(db.deleted_records(self.path)), 1)
        self.assertTrue(db.restore_creator(10, 30, "Mistaken removal", self.path))
        self.assertEqual(len(db.deleted_records(self.path)), 0)
        actions = [row["action"] for row in db.history(20, self.path)]
        self.assertIn("creator_soft_deleted", actions)
        self.assertIn("creator_restored", actions)

    def test_audit_is_append_only_and_preserves_previous_and_new_values(self):
        db.set_availability(10, "available", 10, "self-service", path=self.path)
        row = next(r for r in db.history(20, self.path) if r["action"] == "availability_changed")
        self.assertIsNotNone(row["previous_value"])
        self.assertIsNotNone(row["new_value"])
        with self.assertRaises(PermissionError):
            db.reset_history(30, self.path)


class MenuAndPermissionTests(unittest.TestCase):
    def config(self):
        return SimpleNamespace(
            owner_user_ids=frozenset({1, 2}), lead_admin_user_ids=frozenset({3}),
            admin_user_ids=frozenset({4}), admin_permissions={},
        )

    def labels(self, user_id):
        ctx = SimpleNamespace(user_data={}, bot_data={"config": self.config()})
        markup = home_markup(ctx, user_id)
        return [button.text for row in markup.inline_keyboard for button in row]

    def test_both_configured_owners_have_equal_owner_menu(self):
        self.assertEqual(self.labels(1), self.labels(2))
        self.assertIn("🔐 Owner", self.labels(1))

    def test_creator_cannot_see_admin_or_owner_menu(self):
        labels = self.labels(99)
        self.assertNotIn("👑 Admin", labels)
        self.assertNotIn("🔐 Owner", labels)

    def test_individual_admin_permissions_are_enforced(self):
        cfg = self.config()
        cfg.admin_permissions = {4: frozenset({"review_pop"})}
        self.assertTrue(has_permission(4, cfg, "review_pop"))
        self.assertFalse(has_permission(4, cfg, "send_announcements"))

    def test_eastern_timezone_is_dst_aware(self):
        eastern = ZoneInfo("America/New_York")
        self.assertNotEqual(datetime(2026, 1, 1, tzinfo=eastern).utcoffset(), datetime(2026, 7, 1, tzinfo=eastern).utcoffset())

    def test_active_tree_has_no_coffee_order_modules(self):
        bot = Path(__file__).parents[1] / "bot"
        self.assertFalse((bot / "order.py").exists())
        self.assertFalse((bot / "receipt.py").exists())
        self.assertNotIn("build_order_conversation", (bot / "main.py").read_text(encoding="utf-8"))


class CallbackSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_tampered_or_expired_callback_fails_safe(self):
        cfg = SimpleNamespace(owner_user_ids=frozenset({1}),lead_admin_user_ids=frozenset(),admin_user_ids=frozenset(),admin_permissions={})
        query = SimpleNamespace(data="op:forged:owner",answer=AsyncMock(),edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=99))
        ctx = SimpleNamespace(user_data={"menu_nonce":"real"},bot_data={"config":cfg})
        await callback(update,ctx)
        query.answer.assert_awaited_once()
        self.assertIn("expired", query.edit_message_text.await_args.args[0].casefold())


if __name__ == "__main__": unittest.main()
