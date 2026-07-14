import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).parents[1]/"bot"))

import database as db
from handlers.error import error_handler, safe_error_details
from navigation import callback
from pop_policy import calculate_status, current_period
from presentation import actor_name, audit_entry, friendly_timestamp, system_error_detail
from telegram.error import BadRequest

ET=ZoneInfo("America/New_York")


class PopDeadlineTests(unittest.TestCase):
    def at(self,year,month,day,hour=12): return datetime(year,month,day,hour,tzinfo=ET)

    def test_monday_through_wednesday_are_not_due(self):
        for day in (13,14,15): self.assertEqual(calculate_status(self.at(2026,7,day)),"not_due")

    def test_thursday_before_cutoff_is_due_today_not_missing(self):
        self.assertEqual(calculate_status(self.at(2026,7,16,17),cutoff_time="18:00"),"due_today")

    def test_thursday_after_cutoff_is_missing(self):
        self.assertEqual(calculate_status(self.at(2026,7,16,19),cutoff_time="18:00"),"missing")

    def test_friday_onward_is_missing(self):
        self.assertEqual(calculate_status(self.at(2026,7,17)),"missing")

    def test_pending_submission_and_excuse_override_deadline(self):
        now=self.at(2026,7,17)
        self.assertEqual(calculate_status(now,submission_status="pending"),"awaiting_review")
        self.assertEqual(calculate_status(now,excused=True),"excused")

    def test_creator_registered_after_cutoff_is_not_due_for_that_period(self):
        now=self.at(2026,7,17)
        registered=self.at(2026,7,16,23).isoformat()
        self.assertEqual(calculate_status(now,registered_at=registered,cutoff_time="18:00"),"not_due")

    def test_deadline_is_dst_aware(self):
        winter=current_period(self.at(2026,1,8),cutoff_time="18:00")
        summer=current_period(self.at(2026,7,16),cutoff_time="18:00")
        self.assertNotEqual(winter.due_at.utcoffset(),summer.due_at.utcoffset())

    def test_database_report_and_count_are_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"pop.db";db.initialize_database(path)
            db.register_creator(10,"creator","Creator",path);db.set_status(10,"active",1,path)
            now=self.at(2026,7,14)
            rows=db.pop_status_report(now,path=path);counts=db.pop_status_counts(now,path=path)
            self.assertEqual(rows[0]["effective_status"],"not_due")
            self.assertEqual(counts["not_due"],1);self.assertEqual(counts["missing"],0)


class PresentationTests(unittest.TestCase):
    def test_human_readable_timestamps(self):
        now=datetime(2026,7,14,16,tzinfo=ET)
        self.assertEqual(friendly_timestamp(datetime(2026,7,14,4,8,tzinfo=ET).isoformat(),now),"Today · 4:08 AM ET")
        self.assertEqual(friendly_timestamp(datetime(2026,7,13,19,42,tzinfo=ET).isoformat(),now),"Yesterday · 7:42 PM ET")
        self.assertIn("Jul 10 · 2:15 PM ET",friendly_timestamp(datetime(2026,7,10,14,15,tzinfo=ET).isoformat(),now))

    def test_audit_actor_never_displays_none(self):
        row={"actor_id":None,"actor_name":None,"actor_role":"system","action":"system_error",
            "previous_value":None,"new_value":None,"occurred_at":datetime.now(ET).isoformat(),
            "error_reference":"ERR-0047","result":"error"}
        text=audit_entry(row)
        self.assertIn("System",text);self.assertNotIn("actor=None",text)

    def test_system_error_detail_displays_stored_exception(self):
        row={"action":"system_error","occurred_at":datetime.now(ET).isoformat(),"error_reference":"ERR-0047",
            "new_value":'{"exception_type":"ValueError","message":"bad setup value","traceback":"Traceback line"}'}
        text=system_error_detail(row)
        self.assertIn("ValueError",text);self.assertIn("bad setup value",text);self.assertIn("Traceback line",text)

    def test_error_capture_redacts_telegram_token_shape(self):
        fake_token="123456789:"+"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
        try:raise RuntimeError("token "+fake_token)
        except RuntimeError as error:details=safe_error_details(error)
        self.assertEqual(details["exception_type"],"RuntimeError")
        self.assertIn("[REDACTED TELEGRAM TOKEN]",details["message"])
        self.assertNotIn(fake_token,details["traceback"])


class GuidedScreenTests(unittest.IsolatedAsyncioTestCase):
    def cfg(self): return SimpleNamespace(owner_user_ids=frozenset(),lead_admin_user_ids=frozenset(),
        admin_user_ids=frozenset({2}),admin_permissions={},timezone=ET,timezone_name="America/New_York",
        warning_hours=48,alert_hours=72,pop_due_weekday=3,pop_cutoff_time="23:59")

    async def test_creator_directory_is_button_driven(self):
        query=SimpleNamespace(data="op:menu:creator_report",answer=AsyncMock(),edit_message_text=AsyncMock())
        update=SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=2))
        ctx=SimpleNamespace(user_data={"menu_nonce":"menu"},bot_data={"config":self.cfg()})
        await callback(update,ctx)
        labels=[b.text for row in query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard for b in row]
        self.assertIn("🔎 Search by Name",labels);self.assertIn("📋 Browse All Creators",labels)
        self.assertNotIn("/creator_search",query.edit_message_text.await_args.args[0])

    async def test_harmless_duplicate_edit_is_not_a_system_error(self):
        ctx=SimpleNamespace(error=BadRequest("Message is not modified"))
        with patch("handlers.error.db.record_audit") as audit:
            await error_handler(None,ctx)
        audit.assert_not_called()

    async def test_system_errors_filter_offers_owner_detail_button(self):
        cfg=SimpleNamespace(owner_user_ids=frozenset({1}),lead_admin_user_ids=frozenset(),admin_user_ids=frozenset(),
            admin_permissions={},timezone=ET,timezone_name="America/New_York")
        row={"id":47,"actor_id":None,"actor_name":None,"actor_role":"system","action":"system_error",
            "previous_value":None,"new_value":'{"exception_type":"ValueError","message":"bad","traceback":"trace"}',
            "occurred_at":datetime.now(ET).isoformat(),"error_reference":"ERR-0047","result":"error"}
        query=SimpleNamespace(data="op:menu:audit_filter_errors",answer=AsyncMock(),edit_message_text=AsyncMock())
        update=SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=1))
        ctx=SimpleNamespace(user_data={"menu_nonce":"menu"},bot_data={"config":cfg})
        with patch("navigation.db.history",return_value=[row]),patch("navigation.db.get_creator",return_value=None):await callback(update,ctx)
        labels=[b.text for buttons in query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard for b in buttons]
        self.assertIn("View ERR-0047",labels)

    async def screen(self,action,user_id=1,cfg=None):
        cfg=cfg or SimpleNamespace(owner_user_ids=frozenset({1}),lead_admin_user_ids=frozenset(),
            admin_user_ids=frozenset(),admin_permissions={},timezone=ET,timezone_name="America/New_York",
            warning_hours=48,alert_hours=72,pop_due_weekday=3,pop_cutoff_time="23:59",daily_owner_summary_enabled=False,
            admin_chat_id=-100,reports_thread_id=7)
        query=SimpleNamespace(data=f"op:menu:{action}",answer=AsyncMock(),edit_message_text=AsyncMock())
        update=SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=user_id))
        ctx=SimpleNamespace(user_data={"menu_nonce":"menu"},bot_data={"config":cfg},bot=SimpleNamespace())
        await callback(update,ctx)
        return query.edit_message_text.await_args.args[0],query.edit_message_text.await_args.kwargs["reply_markup"]

    async def test_owner_access_export_and_settings_are_button_driven(self):
        for action,expected in (("roles","➕ Add Admin"),("export_help","📦 Full Owner Export"),("settings","📸 POP Deadline")):
            text,markup=await self.screen(action)
            labels=[b.text for row in markup.inline_keyboard for b in row]
            self.assertIn(expected,labels)
            for command in ("/settings","/role_set","/permission_set","/export_records"):
                self.assertNotIn(command,text)

    async def test_warning_and_template_centers_are_button_driven(self):
        cfg=self.cfg();cfg.admin_permissions={2:frozenset({"adjust_warnings","send_announcements"})}
        with patch("navigation.db.list_creators",return_value=[]),patch("navigation.db.message_templates",return_value=[]):
            text,markup=await self.screen("warnings_help",2,cfg)
            self.assertIn("Select a member",text);self.assertNotIn("/warning",text)
            text,markup=await self.screen("templates_help",2,cfg)
            self.assertIn("Message Center",text);self.assertNotIn("/template",text)

    async def test_help_center_uses_supportive_away_notice_wording(self):
        text,markup=await self.screen("resources")
        labels=[b.text for row in markup.inline_keyboard for b in row]
        self.assertIn("💙 Away Notice Guide",labels);self.assertIn("💬 Contact Admin",labels)
        self.assertNotIn("Vacation Policy",text);self.assertNotIn("Sick-Day Policy",text)


if __name__=="__main__": unittest.main()
