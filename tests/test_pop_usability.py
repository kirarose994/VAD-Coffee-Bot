import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))

from navigation import callback
from tracker import POP_FRIDAY_REMINDER_TEXT, pop_reminder_job


ET = ZoneInfo("America/New_York")


def config():
    return SimpleNamespace(timezone=ET, timezone_name="America/New_York",
        pop_due_weekday=3, pop_cutoff_time="23:59", owner_user_ids=frozenset({1}),
        admin_user_ids=frozenset(), lead_admin_user_ids=frozenset(), admin_permissions={})


def pop_row(user_id, status, week_key="2026-W30", name="Creator"):
    return {"telegram_id": user_id, "effective_status": status, "week_key": week_key,
        "display_name": name, "source_message_at": "2026-07-23T12:00:00-04:00",
        "late_by": None}


class FixedDateTime(datetime):
    current = datetime(2026, 7, 23, 10, 0, tzinfo=ET)

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)


class PopReminderTests(unittest.IsolatedAsyncioTestCase):
    async def run_job(self, rows, claims):
        bot = SimpleNamespace(send_message=AsyncMock())
        ctx = SimpleNamespace(bot_data={"config": config()}, bot=bot)
        with patch("tracker.datetime", FixedDateTime), \
             patch("tracker.db.pop_status_report", return_value=rows), \
             patch("tracker.db.claim_notification", side_effect=claims) as claim, \
             patch("tracker.db.record_audit"):
            await pop_reminder_job(ctx)
        return bot, claim

    async def test_thursday_reminds_only_active_creators_still_due(self):
        FixedDateTime.current = datetime(2026, 7, 23, 10, 0, tzinfo=ET)
        bot, claim = await self.run_job([
            pop_row(10, "due_today", name="Due"), pop_row(11, "excused", name="Away"),
            pop_row(12, "on_time", name="Done"),
        ], [True])
        bot.send_message.assert_awaited_once()
        self.assertEqual(bot.send_message.await_args.args[0], 10)
        self.assertEqual(claim.call_args.args, (10, "2026-W30", "pop_thursday_reminder"))

    async def test_friday_reminder_is_private_missing_only_and_deduplicated(self):
        FixedDateTime.current = datetime(2026, 7, 24, 12, 0, tzinfo=ET)
        rows = [pop_row(10, "missing"), pop_row(11, "excused"), pop_row(12, "late")]
        bot, claim = await self.run_job(rows, [True])
        bot.send_message.assert_awaited_once_with(10, POP_FRIDAY_REMINDER_TEXT)
        self.assertEqual(claim.call_args.args, (10, "2026-W30", "pop_friday_reminder"))
        self.assertEqual(bot.send_message.await_count, 1)

    async def test_repeated_scheduler_pass_does_not_repeat_a_friday_reminder(self):
        FixedDateTime.current = datetime(2026, 7, 24, 12, 0, tzinfo=ET)
        bot = SimpleNamespace(send_message=AsyncMock())
        ctx = SimpleNamespace(bot_data={"config": config()}, bot=bot)
        with patch("tracker.datetime", FixedDateTime), \
             patch("tracker.db.pop_status_report", return_value=[pop_row(10, "missing")]), \
             patch("tracker.db.claim_notification", side_effect=[True, False]) as claim, \
             patch("tracker.db.record_audit"):
            await pop_reminder_job(ctx)
            await pop_reminder_job(ctx)
        self.assertEqual(claim.call_count, 2)
        bot.send_message.assert_awaited_once_with(10, POP_FRIDAY_REMINDER_TEXT)

    async def test_reminders_wait_for_their_fixed_eastern_times(self):
        FixedDateTime.current = datetime(2026, 7, 23, 9, 59, tzinfo=ET)
        bot, claim = await self.run_job([pop_row(10, "due_today")], [])
        bot.send_message.assert_not_awaited()
        claim.assert_not_called()

    async def test_friday_reminder_waits_until_noon_eastern(self):
        FixedDateTime.current = datetime(2026, 7, 24, 11, 59, tzinfo=ET)
        bot, claim = await self.run_job([pop_row(10, "missing")], [])
        bot.send_message.assert_not_awaited()
        claim.assert_not_called()


class PopStatusViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_view_lists_requested_creator_names(self):
        query = SimpleNamespace(data="op:n:pop_status_excused", answer=AsyncMock(),
            edit_message_text=AsyncMock(), message=SimpleNamespace())
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1), effective_chat=None)
        ctx = SimpleNamespace(user_data={"menu_nonce": "n"}, bot_data={"config": config()})
        with patch("navigation.db.pop_status_report", return_value=[
                pop_row(10, "excused", name="Alex"), pop_row(11, "missing", name="Blair")]):
            await callback(update, ctx)
        text = query.edit_message_text.await_args.args[0]
        self.assertIn("Excused", text)
        self.assertIn("Alex", text)
        self.assertNotIn("Blair", text)

    async def test_pop_queue_includes_all_four_named_status_views(self):
        query = SimpleNamespace(data="op:n:pop_queue", answer=AsyncMock(),
            edit_message_text=AsyncMock(), message=SimpleNamespace())
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1), effective_chat=None)
        ctx = SimpleNamespace(user_data={"menu_nonce": "n"}, bot_data={"config": config()})
        with patch("navigation.db.pop_status_report", return_value=[]), \
             patch("navigation.db.pop_preservation_review_rows", return_value=[]):
            await callback(update, ctx)
        labels = [button.text for row in query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard for button in row]
        self.assertTrue({"✅ On Time (0)", "🟠 Late (0)", "💙 Excused (0)", "🔴 Missing (0)"}.issubset(labels))


    async def test_qualifying_late_creator_is_excluded_from_missing_view(self):
        query = SimpleNamespace(data="op:n:pop_queue", answer=AsyncMock(),
            edit_message_text=AsyncMock(), message=SimpleNamespace())
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1), effective_chat=None)
        ctx = SimpleNamespace(user_data={"menu_nonce": "n"}, bot_data={"config": config()})
        late=pop_row(10,"late",name="Lia");missing=pop_row(10,"missing",name="Lia")
        late["submission_status"]=missing["submission_status"]=None
        with patch("navigation.db.pop_status_report",return_value=[late,missing]), \
             patch("navigation.db.pop_preservation_review_rows",return_value=[]):
            await callback(update,ctx)
        text=query.edit_message_text.await_args.args[0]
        self.assertIn("Late: 1",text)
        self.assertIn("Missing: 0",text)
        labels=[button.text for row in query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard for button in row]
        self.assertIn("🔴 Missing (0)",labels)


if __name__ == "__main__":
    unittest.main()
