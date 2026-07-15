import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).parents[1]/"bot"))

import database as db
from navigation import callback, home_markup
from participation_summary import build_participation_summary, render_today


def cfg(**changes):
    values=dict(owner_user_ids=frozenset({1}),lead_admin_user_ids=frozenset(),admin_user_ids=frozenset({2}),admin_permissions={},
        timezone=ZoneInfo("America/New_York"),timezone_name="America/New_York",warning_hours=48,alert_hours=72,
        pop_due_weekday=3,pop_cutoff_time="23:59",admin_chat_id=None,registration_thread_id=None,away_thread_id=None,
        pop_review_thread_id=None,reports_thread_id=None,moderation_thread_id=None,support_thread_id=None,health_thread_id=None)
    values.update(changes);return SimpleNamespace(**values)


def labels(markup):return [button.text for row in markup.inline_keyboard for button in row]
def actions(markup):return [button.callback_data.rsplit(":",1)[-1] for row in markup.inline_keyboard for button in row]


class RoleAwareMenuTests(unittest.IsolatedAsyncioTestCase):
    async def screen(self,action,user_id,config):
        query=SimpleNamespace(data=f"op:n:{action}",answer=AsyncMock(),edit_message_text=AsyncMock(),message=SimpleNamespace())
        update=SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=user_id),effective_chat=None)
        ctx=SimpleNamespace(user_data={"menu_nonce":"n"},bot_data={"config":config})
        await callback(update,ctx);return query.edit_message_text.await_args

    def test_additive_home_destinations_remain_unique_for_every_role(self):
        config=cfg()
        for user_id,creator in ((1,{"telegram_id":1}),(2,{"telegram_id":2}),(3,{"telegram_id":3})):
            with patch("navigation.db.get_creator",return_value=creator),patch("navigation.db.get_member",return_value=None):
                markup=home_markup(SimpleNamespace(user_data={},bot_data={"config":config}),user_id)
            self.assertEqual(len(labels(markup)),len(set(labels(markup))))
            self.assertEqual(len(actions(markup)),len(set(actions(markup))))
        with patch("navigation.db.get_creator",return_value={"telegram_id":1}),patch("navigation.db.get_member",return_value=None):
            self.assertEqual(set(labels(home_markup(SimpleNamespace(user_data={},bot_data={"config":config}),1))),
                {"👑 Owner Home","🛡️ Admin Home","💛 My VAD Home","📚 Help Center"})

    async def test_admin_home_is_compact_and_owner_home_drills_into_tools(self):
        with patch("navigation.admin_card",return_value="Summary"):
            admin=await self.screen("admin",2,cfg())
        visible=labels(admin.kwargs["reply_markup"]);callbacks=actions(admin.kwargs["reply_markup"])
        self.assertTrue({"📥 Operations Inbox","📊 Participation","👥 Creators","📅 Who’s Away",
            "📸 Thursday POP","💙 Away Notices","📬 Support"}.issubset(visible))
        self.assertEqual(len(visible),len(set(visible)));self.assertEqual(len(callbacks),len(set(callbacks)))
        with patch("navigation.owner_card",return_value="Summary"):
            owner=await self.screen("owner",1,cfg())
        self.assertIn("🔐 Owner Tools",labels(owner.kwargs["reply_markup"]))
        self.assertNotIn("🔐 Audit Log",labels(owner.kwargs["reply_markup"]))

    async def test_creator_cannot_tamper_into_admin_summary(self):
        result=await self.screen("participation_summary",3,cfg())
        self.assertIn("only to authorized Admins and Owners",result.args[0])


class ParticipationSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"summary.db";db.initialize_database(self.path)
        for user_id,name in ((10,"Ashley"),(11,"Jade")):
            db.register_creator(user_id,name.casefold(),name,self.path);db.set_status(user_id,"active",99,self.path)
    def tearDown(self):self.tmp.cleanup()

    def test_today_week_away_and_ignored_counts_share_existing_events(self):
        now=datetime(2026,7,15,12,tzinfo=ZoneInfo("America/New_York"))
        event_time="2026-07-15T01:00:00-04:00"
        with patch("database.utc_now",return_value=event_time):
            db.record_engagement(10,1,-100,None,"one","accepted","meaningful",self.path)
            db.record_engagement(10,2,-100,None,"two","accepted","meaningful",self.path)
            db.record_engagement(11,3,-100,None,"three","rejected","greeting_only",self.path)
        request=db.create_absence_request(11,"vacation","2026-07-15","2026-07-16","Private",self.path)
        self.assertTrue(db.review_absence(request,"approved",99,path=self.path))
        summary=build_participation_summary(cfg(owner_user_ids=frozenset(),admin_user_ids=frozenset()),now,self.path)
        self.assertEqual(summary["today"],{"creators":1,"events":2,"ignored":1,"away":1,"not_participated":1})
        self.assertEqual(summary["week"]["events"],2)
        self.assertTrue(next(row for row in summary["creators"] if row["telegram_id"]==11)["away"])
        self.assertFalse(any(word in render_today(summary).casefold() for word in ("best","worst","top creator")))

    def test_operations_inbox_counts_existing_support_once(self):
        db.create_support_request(10,"general","Help",self.path)
        first=db.needs_attention_counts("2026-W29",self.path,datetime(2026,7,15,12,tzinfo=ZoneInfo("America/New_York")))
        second=db.needs_attention_counts("2026-W29",self.path,datetime(2026,7,15,12,tzinfo=ZoneInfo("America/New_York")))
        self.assertEqual(first["support_requests"],1);self.assertEqual(second["support_requests"],1)
