import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))

import database as db
from config import Config
from navigation import callback, creator_card
from operations import absence_request
from tracker import inactivity_job


class V11DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "v11.db"
        db.initialize_database(self.path)
        db.register_creator(10,"creator","Creator",self.path)
        db.set_status(10,"active",1,self.path)

    def tearDown(self): self.tmp.cleanup()

    def test_additive_schema_v4_preserves_creator_and_general_member_identity(self):
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0],7)
            member = connection.execute("SELECT * FROM community_members WHERE telegram_id=10").fetchone()
        self.assertEqual(member["member_type"],"creator")

    def test_away_notice_categories_preserve_original_snapshot(self):
        request_id = db.create_absence_request(10,"sick","2026-08-01","2026-08-01","Private",self.path,category="personal_day")
        row = db.get_absence_request(request_id,self.path)
        self.assertEqual(row["absence_category"],"personal_day")
        self.assertIn('"category": "personal_day"',row["original_snapshot"])

    def test_needs_attention_aggregates_actionable_counts(self):
        db.register_creator(11,"pending","Pending",self.path)
        db.create_absence_request(10,"vacation","2026-08-01","2026-08-02",path=self.path)
        db.add_warning(10,"warning","Please check in",1,self.path)
        counts = db.needs_attention_counts("2026-W31",self.path)
        self.assertEqual(counts["registrations"],1)
        self.assertEqual(counts["away_notices"],1)
        self.assertEqual(counts["unacknowledged_warnings"],1)
        self.assertGreaterEqual(counts["total"],3)

    def test_three_strikes_create_owner_review_case(self):
        for number in range(3): db.add_warning(10,"strike",f"Strike {number}",1,self.path)
        self.assertEqual(db.needs_attention_counts("2026-W31",self.path)["owner_reviews"],1)

    def test_owner_summary_claim_is_restart_idempotent(self):
        self.assertTrue(db.claim_owner_summary(1,"owner-summary:2026-07-14",self.path))
        self.assertFalse(db.claim_owner_summary(1,"owner-summary:2026-07-14",self.path))

    def test_template_edit_preserves_revision_and_audit(self):
        self.assertTrue(db.update_message_template("welcome","Updated welcome {name}",1,path=self.path))
        with db.get_connection(self.path) as connection:
            revision = connection.execute("SELECT * FROM template_revisions").fetchone()
        self.assertIn("Welcome",revision["previous_body"])
        self.assertEqual(revision["new_body"],"Updated welcome {name}")
        self.assertIn("message_template_changed",[row["action"] for row in db.history(20,self.path)])

    def test_availability_icon_never_conflicts_with_unavailable_text(self):
        cfg = SimpleNamespace(timezone=ZoneInfo("America/New_York"))
        with patch("navigation.db.get_creator",return_value=db.get_creator(10,self.path)), \
             patch("navigation.db.warning_summary",return_value={"warnings":0,"strikes":0}), \
             patch("navigation.db.creator_current_pop_status",return_value="not_due"), \
             patch("navigation.db.latest_absence",return_value=None):
            card = creator_card(10,cfg)
        self.assertIn("⚪ Unavailable",card)
        self.assertNotIn("🟢 Availability",card)


class V11NavigationTests(unittest.IsolatedAsyncioTestCase):
    def cfg(self, owner=True):
        return SimpleNamespace(owner_user_ids=frozenset({1}) if owner else frozenset(),
            lead_admin_user_ids=frozenset(),admin_user_ids=frozenset({2}),admin_permissions={},
            timezone=ZoneInfo("America/New_York"),warning_hours=48,alert_hours=72)

    async def test_empty_needs_attention_has_clear_empty_state_and_no_cancel(self):
        query = SimpleNamespace(data="op:menu:needs_attention",answer=AsyncMock(),edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=1))
        ctx = SimpleNamespace(user_data={"menu_nonce":"menu"},bot_data={"config":self.cfg()})
        empty = {key:0 for key in ("total","registrations","away_notices","pop_reviews","near_two_days","three_day_alerts","unacknowledged_warnings","owner_reviews","failed_notifications","recent_archive_changes")}
        with patch("navigation.db.needs_attention_counts",return_value=empty): await callback(update,ctx)
        self.assertIn("Nothing needs your attention",query.edit_message_text.await_args.args[0])
        labels = [b.text for row in query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard for b in row]
        self.assertNotIn("❌ Cancel",labels)

    async def test_admin_cannot_tamper_into_owner_needs_attention(self):
        query = SimpleNamespace(data="op:menu:needs_attention",answer=AsyncMock(),edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=2))
        ctx = SimpleNamespace(user_data={"menu_nonce":"menu"},bot_data={"config":self.cfg()})
        await callback(update,ctx)
        self.assertIn("only to owners",query.edit_message_text.await_args.args[0])

    async def test_cancel_is_present_during_active_away_notice_confirmation(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(effective_user=SimpleNamespace(id=10),effective_message=message)
        ctx = SimpleNamespace(args=["2026-08-01","2026-08-02"],user_data={})
        with patch("operations.db.get_creator",return_value={"status":"active"}):
            await absence_request(update,ctx,"vacation")
        markup = message.reply_text.await_args.kwargs["reply_markup"]
        self.assertIn("❌ Cancel",[button.text for row in markup.inline_keyboard for button in row])

    async def test_two_day_notification_is_supportive_and_deduplicated(self):
        anchor = (datetime.now(timezone.utc)-timedelta(hours=49)).isoformat()
        creator = {"telegram_id":10,"display_name":"Creator","last_meaningful_at":anchor,
            "approved_at":anchor,"registered_at":anchor,"vacation_until":None}
        cfg = SimpleNamespace(timezone=ZoneInfo("America/New_York"),warning_hours=48,alert_hours=72,
            admin_chat_id=-100,reports_thread_id=1)
        bot = SimpleNamespace(send_message=AsyncMock())
        ctx = SimpleNamespace(bot=bot,bot_data={"config":cfg})
        with patch("tracker.db.sync_absence_availability"),patch("tracker.db.set_system_state"),patch("tracker.db.due_creators",return_value=[creator]), \
             patch("tracker.db.approved_absence_on",return_value=None),patch("tracker.db.calendar_absences",return_value=[]), \
             patch("tracker.db.claim_notification",side_effect=[True,False]),patch("tracker.db.record_audit"):
            await inactivity_job(ctx); await inactivity_job(ctx)
        self.assertEqual(bot.send_message.await_count,2)  # creator reminder plus one admin flag
        self.assertTrue(any("Another full day" in call.args[1] for call in bot.send_message.await_args_list))

    async def test_three_day_alert_goes_to_admin_topic(self):
        anchor = (datetime.now(timezone.utc)-timedelta(hours=73)).isoformat()
        creator = {"telegram_id":10,"display_name":"Creator","last_meaningful_at":anchor,
            "approved_at":anchor,"registered_at":anchor,"vacation_until":None}
        cfg = SimpleNamespace(timezone=ZoneInfo("America/New_York"),warning_hours=48,alert_hours=72,
            admin_chat_id=-100,reports_thread_id=7)
        bot = SimpleNamespace(send_message=AsyncMock())
        ctx = SimpleNamespace(bot=bot,bot_data={"config":cfg})
        with patch("tracker.db.sync_absence_availability"),patch("tracker.db.set_system_state"),patch("tracker.db.due_creators",return_value=[creator]), \
             patch("tracker.db.approved_absence_on",return_value=None),patch("tracker.db.calendar_absences",return_value=[]), \
             patch("tracker.db.claim_notification",return_value=True),patch("tracker.db.record_audit"):
            await inactivity_job(ctx)
        self.assertEqual(bot.send_message.await_args.args[0],-100)
        self.assertEqual(bot.send_message.await_args.kwargs["message_thread_id"],7)
        self.assertIn("Admin follow-up required",bot.send_message.await_args.args[1])


class V11ConfigTests(unittest.TestCase):
    def test_daily_owner_summary_is_disabled_by_default(self):
        with patch.dict(os.environ,{"TELEGRAM_BOT_TOKEN":"test-token"},clear=True):
            cfg = Config.from_env()
        self.assertFalse(cfg.daily_owner_summary_enabled)
        self.assertEqual(cfg.daily_owner_summary_time,"09:00")


if __name__ == "__main__": unittest.main()
