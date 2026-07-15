import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))

import database as db
from away_calendar import calendar_window, default_sections, render_default
from navigation import callback


def config(*, owner=False, admin=False):
    return SimpleNamespace(owner_user_ids=frozenset({1}) if owner else frozenset(),lead_admin_user_ids=frozenset(),
        admin_user_ids=frozenset({2}) if admin else frozenset(),admin_permissions={},
        timezone=ZoneInfo("America/New_York"),timezone_name="America/New_York")


def notice(request_id, name, start, end, note="Private note"):
    return {"id":request_id,"telegram_id":request_id+100,"display_name":name,
        "start_date":start.isoformat(),"end_date":end.isoformat(),"status":"approved",
        "absence_type":"vacation","category":"vacation_trip","note":note,"deleted_at":None}


def button_labels(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


class AwayCalendarLogicTests(unittest.TestCase):
    def test_overlapping_and_multiday_notices_are_active_today(self):
        today=date(2026,7,15)
        rows=[notice(1,"Ashley",today-timedelta(days=2),today+timedelta(days=2)),
              notice(2,"Jade",today,today),notice(3,"Pepe",today+timedelta(days=3),today+timedelta(days=5))]
        sections=default_sections(rows,today)
        self.assertEqual([r["display_name"] for r in sections["away_today"]],["Ashley","Jade"])
        self.assertEqual([r["display_name"] for r in sections["continuing"]],["Ashley"])
        self.assertEqual([r["display_name"] for r in sections["starting_soon"]],["Pepe"])

    def test_month_view_stops_at_month_boundary_and_excludes_past_days(self):
        self.assertEqual(calendar_window("month",date(2026,7,30)),(date(2026,7,30),date(2026,7,31)))
        self.assertEqual(calendar_window("30",date(2026,7,30)),(date(2026,7,30),date(2026,8,28)))


class AwayCalendarDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"away.db";db.initialize_database(self.path)
        for user_id,name in ((10,"Ashley"),(11,"Jade"),(12,"Pepe")):
            db.register_creator(user_id,name.casefold(),name,self.path);db.set_status(user_id,"active",99,self.path)
    def tearDown(self):self.tmp.cleanup()

    def test_calendar_returns_only_current_approved_unarchived_notices(self):
        approved=db.create_absence_request(10,"vacation","2026-07-14","2026-07-18","Visible only in detail",self.path)
        pending=db.create_absence_request(11,"sick","2026-07-15","2026-07-16","Pending",self.path)
        rejected=db.create_absence_request(12,"vacation","2026-07-15","2026-07-17","Rejected",self.path)
        self.assertTrue(db.review_absence(approved,"approved",99,path=self.path))
        self.assertTrue(db.review_absence(rejected,"denied",99,path=self.path))
        rows=db.calendar_absences("2026-07-15","2026-07-31",self.path)
        self.assertEqual([row["id"] for row in rows],[approved])
        self.assertNotIn(pending,[row["id"] for row in rows])
        self.assertIsNotNone(db.approved_absence_detail(approved,self.path))
        self.assertIsNone(db.approved_absence_detail(rejected,self.path))


class AwayCalendarNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def screen(self, action, user_id, cfg):
        query=SimpleNamespace(data=f"op:n:{action}",answer=AsyncMock(),edit_message_text=AsyncMock(),message=SimpleNamespace())
        update=SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=user_id),effective_chat=None)
        ctx=SimpleNamespace(user_data={"menu_nonce":"n"},bot_data={"config":cfg})
        await callback(update,ctx)
        return query.edit_message_text.await_args

    async def test_creators_cannot_open_whos_away(self):
        result=await self.screen("whos_away",20,config())
        self.assertIn("only to Admins and Owners",result.args[0])

    async def test_admin_and_owner_can_open_whos_away(self):
        today=date.today();rows=[notice(1,"Ashley",today,today+timedelta(days=2))]
        for user_id,cfg in ((1,config(owner=True)),(2,config(admin=True))):
            with patch("navigation.db.calendar_absences",return_value=rows):
                result=await self.screen("whos_away",user_id,cfg)
            self.assertIn("📅 Who’s Away",result.args[0])

    async def test_admin_home_has_whos_away_entry_and_calendar_has_all_views(self):
        with patch("navigation.admin_card",return_value="All caught up"):
            home=await self.screen("admin",2,config(admin=True))
        self.assertIn("📅 Who’s Away",button_labels(home.kwargs["reply_markup"]))
        with patch("navigation.db.calendar_absences",return_value=[]):
            calendar=await self.screen("whos_away",2,config(admin=True))
        self.assertTrue({"Today","This Week","Next 30 Days","Month View"}.issubset(
            button_labels(calendar.kwargs["reply_markup"])))

    async def test_main_list_hides_notes_but_detail_shows_authorized_note(self):
        today=date.today();row=notice(7,"Ashley",today,today+timedelta(days=2),"Family matter")
        with patch("navigation.db.calendar_absences",return_value=[row]):
            listing=await self.screen("whos_away",2,config(admin=True))
        self.assertNotIn("Family matter",listing.args[0])
        with patch("navigation.db.approved_absence_detail",return_value=row):
            detail=await self.screen("whos_away_notice_7",2,config(admin=True))
        self.assertIn("Category: Vacation Trip",detail.args[0])
        self.assertIn("Note: Family matter",detail.args[0])

    def test_default_renderer_never_includes_private_notes(self):
        today=date(2026,7,15);text=render_default([notice(1,"Ashley",today,today,note="Do not show")],today)
        self.assertNotIn("Do not show",text)
