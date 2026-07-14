import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))

from tracker import approve, creator_report, history_command, pop_approve, setting_set, vacation


class AuditVisibilityTests(unittest.IsolatedAsyncioTestCase):
    def context(self, args=None):
        return SimpleNamespace(args=args or [], bot_data={"config": SimpleNamespace(
            owner_user_ids=frozenset({10}),
            lead_admin_user_ids=frozenset({20}),
            admin_user_ids=frozenset({30}),
        )})

    def update(self, user_id):
        reply_text = AsyncMock()
        message = SimpleNamespace(reply_text=reply_text)
        return SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id),
            effective_message=message,
            message=message,
        )

    async def test_owner_can_view_audit_actor_information(self):
        update = self.update(10)
        row = {
            "occurred_at": "2026-07-14T12:00:00+00:00",
            "actor_id": 20,
            "target_telegram_id": 99,
            "action": "creator_status_changed",
            "new_value": '{"status":"active"}',
        }
        with patch("tracker.db.history", return_value=[row]) as history:
            await history_command(update, self.context())
        history.assert_called_once_with()
        response = update.message.reply_text.await_args.args[0]
        self.assertIn("actor=20", response)
        self.assertIn("target=99", response)

    async def test_lead_admin_cannot_view_audit_information(self):
        update = self.update(20)
        with patch("tracker.db.history") as history:
            await history_command(update, self.context())
        history.assert_not_called()
        update.message.reply_text.assert_awaited_once_with(
            "Sorry, the private audit log is for owners only."
        )

    async def test_admin_cannot_view_audit_information(self):
        update = self.update(30)
        with patch("tracker.db.history") as history:
            await history_command(update, self.context())
        history.assert_not_called()
        update.message.reply_text.assert_awaited_once_with(
            "Sorry, the private audit log is for owners only."
        )

    async def test_admin_can_approve_creators(self):
        update = self.update(30)
        with patch("tracker.db.set_status", return_value=True) as set_status:
            await approve(update, self.context(["99"]))
        set_status.assert_called_once_with(99, "active", 30)
        update.message.reply_text.assert_awaited_once_with("Creator 99 is approved and ready to participate.")

    async def test_admin_can_manage_other_creator_vacations(self):
        update = self.update(30)
        with patch("tracker.db.set_vacation", return_value=True) as set_vacation:
            await vacation(update, self.context(["99", "2026-07-31"]))
        set_vacation.assert_called_once_with(99, "2026-07-31", 30)

    async def test_admin_can_approve_pop_submissions(self):
        update = self.update(30)
        with patch("tracker.db.get_pop_submission", return_value=None), \
             patch("tracker.db.review_pop", return_value=True) as review_pop:
            await pop_approve(update, self.context(["7", "verified"]))
        review_pop.assert_called_once_with(7, "approved", 30, "verified")

    async def test_admin_can_run_creator_reports(self):
        update = self.update(30)
        with patch("tracker.db.list_creators", return_value=[]) as list_creators:
            await creator_report(update, self.context())
        list_creators.assert_called_once_with()
        self.assertIn("No creators are registered yet.", update.message.reply_text.await_args.args[0])

    async def test_admin_can_make_day_to_day_configuration_changes(self):
        update = self.update(30)
        ctx = self.context(["warning_hours", "36"])
        ctx.bot_data["config"].warning_hours = 48
        with patch("tracker.db.audit_setting_change") as audit_change:
            await setting_set(update, ctx)
        self.assertEqual(ctx.bot_data["config"].warning_hours, 36)
        audit_change.assert_called_once_with(30, "warning_hours", 48, 36)


if __name__ == "__main__":
    unittest.main()
