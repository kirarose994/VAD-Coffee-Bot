import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))

import database as db
from navigation import _standing, callback, home_markup, start
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

    def test_participation_during_away_updates_timestamp_without_rewriting_absence_or_history(self):
        request_id = db.create_absence_request(10, "vacation", "2026-07-15", "2026-07-17", "Away", self.path)
        self.assertTrue(db.review_absence(request_id, "approved", 20, path=self.path))
        absence_before = dict(db.get_absence_request(request_id, self.path))
        history_before = [dict(row) for row in db.creator_history(10, self.path)]
        creator_before = dict(db.get_creator(10, self.path))

        self.assertTrue(db.record_engagement(10, 501, -1003543892255, None, "away-message-hash",
            "accepted", "meaningful_text", self.path))

        creator_after = dict(db.get_creator(10, self.path))
        self.assertNotEqual(creator_after["last_meaningful_at"], creator_before["last_meaningful_at"])
        self.assertEqual(dict(db.get_absence_request(request_id, self.path)), absence_before)
        self.assertEqual(db.approved_absence_on(10, date(2026, 7, 16), self.path)["id"], request_id)
        self.assertEqual(db.creator_pop_status(10, "2026-W29", self.path), "excused")
        history_after = [dict(row) for row in db.creator_history(10, self.path)]
        self.assertEqual(history_after[1:], history_before)
        self.assertEqual(history_after[0]["action"], "engagement_counted")
        self.assertEqual(len(db.list_creators(self.path)), 1)

    def test_sick_day_approval_uses_extensible_absence_model(self):
        today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        request_id = db.create_absence_request(10, "sick", today, today, None, self.path)
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

    def test_warning_strike_standing_and_acknowledgment_are_audited(self):
        warning_id = db.add_warning(10,"warning","Participation reminder",20,self.path)
        for number in range(3):
            db.add_warning(10,"strike",f"Strike {number + 1}",20,self.path)
        self.assertEqual(db.warning_summary(10,self.path),{"warnings":1,"strikes":3})
        self.assertTrue(db.acknowledge_warning(warning_id,10,self.path))
        self.assertFalse(db.acknowledge_warning(warning_id,10,self.path))
        actions = [row["action"] for row in db.creator_timeline(10,20,0,self.path)]
        self.assertIn("warning_issued",actions)
        self.assertIn("warning_acknowledged",actions)

    def test_removed_warning_keeps_history_but_leaves_standing(self):
        warning_id = db.add_warning(10,"warning","Temporary issue",20,self.path)
        self.assertTrue(db.remove_warning(warning_id,20,"Resolved",self.path))
        self.assertEqual(db.warning_summary(10,self.path)["warnings"],0)
        self.assertEqual(db.get_warning(warning_id,self.path)["status"],"removed")

    def test_message_templates_are_seeded_and_customizable(self):
        templates = {row["template_key"] for row in db.message_templates(self.path)}
        self.assertTrue({"friendly_reminder","participation_reminder","pop_reminder","welcome","community_checkin","warning","strike"}.issubset(templates))
        body = db.message_template("welcome",self.path)["body"].format(name="Creator",reason="")
        self.assertIn("Creator",body)


class MenuAndPermissionTests(unittest.TestCase):
    def config(self):
        return SimpleNamespace(
            owner_user_ids=frozenset({1, 2}), lead_admin_user_ids=frozenset(),
            admin_user_ids=frozenset({3,4}), admin_permissions={},
        )

    def labels(self, user_id):
        ctx = SimpleNamespace(user_data={}, bot_data={"config": self.config()})
        markup = home_markup(ctx, user_id)
        return [button.text for row in markup.inline_keyboard for button in row]

    def test_both_configured_owners_have_equal_owner_menu(self):
        self.assertEqual(self.labels(1), self.labels(2))
        self.assertIn("👑 Owner Home", self.labels(1))

    def test_creator_cannot_see_admin_or_owner_menu(self):
        labels = self.labels(99)
        self.assertNotIn("👑 Admin Dashboard", labels)
        self.assertNotIn("👑 Owner Home", labels)

    def test_individual_admin_permissions_are_enforced(self):
        cfg = self.config()
        cfg.admin_permissions = {4: frozenset({"review_pop"})}
        self.assertTrue(has_permission(4, cfg, "review_pop"))
        self.assertFalse(has_permission(4, cfg, "send_announcements"))

    def test_standing_indicators_are_supportive_and_escalate_three_strikes(self):
        self.assertIn("Good standing",_standing({"warnings":0,"strikes":0}))
        self.assertIn("1 warning",_standing({"warnings":1,"strikes":0}))
        self.assertIn("2 warnings",_standing({"warnings":2,"strikes":0}))
        self.assertIn("Owner review required",_standing({"warnings":0,"strikes":3}))

    def test_eastern_timezone_is_dst_aware(self):
        eastern = ZoneInfo("America/New_York")
        self.assertNotEqual(datetime(2026, 1, 1, tzinfo=eastern).utcoffset(), datetime(2026, 7, 1, tzinfo=eastern).utcoffset())

    def test_active_tree_has_no_coffee_order_modules(self):
        bot = Path(__file__).parents[1] / "bot"
        self.assertFalse((bot / "order.py").exists())
        self.assertFalse((bot / "receipt.py").exists())
        self.assertNotIn("build_order_conversation", (bot / "main.py").read_text(encoding="utf-8"))


class CallbackSecurityTests(unittest.IsolatedAsyncioTestCase):
    def metrics(self):
        return {key:0 for key in ("active_creators","pending_registrations","pending_vacations","pending_sick","pending_pop","missing_pop","active_warnings","active_strikes","away_now","deleted_records","audit_events")}

    async def test_start_explains_support_and_fair_away_notices(self):
        cfg = SimpleNamespace(owner_user_ids=frozenset(),lead_admin_user_ids=frozenset(),admin_user_ids=frozenset(),admin_permissions={})
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(effective_user=SimpleNamespace(id=99,first_name="Kira"),effective_message=message)
        ctx = SimpleNamespace(user_data={},bot_data={"config":cfg})
        with patch("navigation.db.get_creator",return_value=None):
            await start(update,ctx)
        text = message.reply_text.await_args.args[0]
        self.assertIn("here to help",text)
        self.assertIn("Away Notices",text)
        self.assertIn("fair",text)

    async def test_tampered_or_expired_callback_fails_safe(self):
        cfg = SimpleNamespace(owner_user_ids=frozenset({1}),lead_admin_user_ids=frozenset(),admin_user_ids=frozenset(),admin_permissions={})
        query = SimpleNamespace(data="op:forged:owner",answer=AsyncMock(),edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=99))
        ctx = SimpleNamespace(user_data={"menu_nonce":"real"},bot_data={"config":cfg})
        await callback(update,ctx)
        query.answer.assert_awaited_once()
        self.assertIn("expired", query.edit_message_text.await_args.args[0].casefold())

    async def test_admin_dashboard_hides_unassigned_tools(self):
        cfg = SimpleNamespace(owner_user_ids=frozenset(),lead_admin_user_ids=frozenset(),admin_user_ids=frozenset({4}),admin_permissions={4:frozenset({"review_pop"})},timezone=ZoneInfo("America/New_York"))
        query = SimpleNamespace(data="op:menu:admin",answer=AsyncMock(),edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=4))
        ctx = SimpleNamespace(user_data={"menu_nonce":"menu"},bot_data={"config":cfg})
        with patch("navigation.db.dashboard_metrics",return_value=self.metrics()),patch("navigation.db.pop_status_counts",return_value={"awaiting_review":0,"missing":0}):
            await callback(update,ctx)
        markup = query.edit_message_text.await_args.kwargs["reply_markup"]
        labels = [button.text for row in markup.inline_keyboard for button in row]
        self.assertIn("📸 POP Reviews",labels)
        self.assertNotIn("📝 Registrations",labels)
        self.assertNotIn("💬 Messages",labels)

    async def test_hidden_admin_tool_still_rechecks_permission(self):
        cfg = SimpleNamespace(owner_user_ids=frozenset(),lead_admin_user_ids=frozenset(),admin_user_ids=frozenset({4}),admin_permissions={4:frozenset({"review_pop"})},timezone=ZoneInfo("America/New_York"))
        query = SimpleNamespace(data="op:menu:registration_queue",answer=AsyncMock(),edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=4))
        ctx = SimpleNamespace(user_data={"menu_nonce":"menu"},bot_data={"config":cfg})
        await callback(update,ctx)
        self.assertIn("isn’t included",query.edit_message_text.await_args.args[0])

    async def test_owner_dashboard_is_compact_and_scannable(self):
        cfg = SimpleNamespace(owner_user_ids=frozenset({1}),lead_admin_user_ids=frozenset(),admin_user_ids=frozenset(),admin_permissions={},timezone=ZoneInfo("America/New_York"))
        query = SimpleNamespace(data="op:menu:owner",answer=AsyncMock(),edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=1))
        ctx = SimpleNamespace(user_data={"menu_nonce":"menu"},bot_data={"config":cfg})
        with patch("navigation.db.dashboard_metrics",return_value=self.metrics()),patch("navigation.db.pop_status_counts",return_value={"awaiting_review":0,"missing":0}):
            await callback(update,ctx)
        markup = query.edit_message_text.await_args.kwargs["reply_markup"]
        labels = [button.text for row in markup.inline_keyboard for button in row]
        self.assertEqual(labels[0],"🚨 Needs Attention")
        self.assertNotIn("❌ Cancel",labels)
        self.assertTrue(all(len(row) <= 2 for row in markup.inline_keyboard))


if __name__ == "__main__": unittest.main()
