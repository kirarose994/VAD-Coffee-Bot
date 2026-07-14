import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).parents[1]/"bot"))
import database as db
from briefing import deliver_daily_brief, format_daily_brief
from community_snapshot import PARTICIPATION_POLICY
from navigation import _snapshot_sections


def snapshot(now):
    return {"generated_at":now,"creators":{"approved":[1],"active":[1],"away":[],"pending":[]},
        "participation":{"up_to_date":[1],"approaching":[],"reminder_due":[],"follow_up":[],"excused":[]},
        "pop":{"not_due":[1],"due_today":[],"still_needed":[],"missing":[],"submitted":[],"awaiting_review":[],
            "excused":[],"resubmission_requested":[],"rejected":[]},
        "away":{"current":[],"upcoming":[],"pending":[]},
        "support":{"open":[],"unassigned":[],"escalated":[]},
        "accountability":{"warnings":0,"strikes":0,"owner_reviews":0},
        "system":{"bot_online":True,"scheduler_ok":True,"monitor_ok":True,"routing_ok":True,"failures":[],"backup":None}}

def config(**changes):
    values=dict(timezone=ZoneInfo("America/New_York"),daily_brief_enabled=True,daily_brief_time="09:00",
        daily_brief_weekends=True,daily_brief_include_health=True,daily_brief_include_zero=True,
        daily_brief_chat_id=-100,daily_brief_thread_id=8,owner_user_ids=frozenset({1}))
    values.update(changes);return SimpleNamespace(**values)


class CommunityBriefTests(unittest.IsolatedAsyncioTestCase):
    def test_admin_snapshot_contains_only_assigned_sections(self):
        cfg=config(owner_user_ids=frozenset(),admin_user_ids=frozenset({7}),lead_admin_user_ids=frozenset(),
            admin_permissions={7:frozenset({"review_pop","manage_support"})})
        self.assertEqual(_snapshot_sections(7,cfg),["pop","support"])

    def test_creator_has_no_snapshot_sections(self):
        cfg=config(owner_user_ids=frozenset(),admin_user_ids=frozenset(),lead_admin_user_ids=frozenset(),admin_permissions={})
        self.assertEqual(_snapshot_sections(7,cfg),[])

    def test_policy_explains_two_and_three_full_days(self):
        self.assertIn("two full days",PARTICIPATION_POLICY)
        self.assertIn("three full days",PARTICIPATION_POLICY)

    def test_healthy_pre_deadline_brief_never_says_missing(self):
        text=format_daily_brief(snapshot(datetime(2026,7,14,9,tzinfo=ZoneInfo("America/New_York"))),config())
        self.assertIn("Not due yet: 1",text)
        self.assertNotIn("Missing after deadline: 1",text)
        self.assertIn("Everything currently requiring Admin attention is caught up.",text)

    def test_test_brief_is_clearly_labeled(self):
        text=format_daily_brief(snapshot(datetime(2026,7,14,9,tzinfo=ZoneInfo("America/New_York"))),config(),test=True)
        self.assertTrue(text.startswith("🧪 TEST"))

    async def test_normal_delivery_claim_prevents_restart_duplicate(self):
        now=datetime(2026,7,14,9,tzinfo=ZoneInfo("America/New_York"));bot=SimpleNamespace(send_message=AsyncMock())
        with patch("briefing.build_snapshot",return_value=snapshot(now)),patch("briefing.db.claim_daily_brief",side_effect=[True,False]), \
             patch("briefing.db.finish_daily_brief"),patch("briefing.send_routed",new=AsyncMock(return_value=(True,None))) as routed:
            self.assertEqual((await deliver_daily_brief(bot,config(),now=now))[0],True)
            self.assertEqual((await deliver_daily_brief(bot,config(),now=now))[1],"already_claimed")
            self.assertEqual(routed.await_count,1)

    async def test_test_brief_does_not_claim_or_write_delivery_history(self):
        now=datetime(2026,7,14,9,tzinfo=ZoneInfo("America/New_York"));bot=SimpleNamespace(send_message=AsyncMock())
        with patch("briefing.build_snapshot",return_value=snapshot(now)),patch("briefing.db.claim_daily_brief") as claim, \
             patch("briefing.send_routed",new=AsyncMock()) as routed:
            self.assertEqual((await deliver_daily_brief(bot,config(),now=now,test=True))[0],True)
            claim.assert_not_called();routed.assert_not_awaited();bot.send_message.assert_awaited_once()

    async def test_weekend_setting_skips_delivery(self):
        now=datetime(2026,7,18,9,tzinfo=ZoneInfo("America/New_York"))
        self.assertEqual(await deliver_daily_brief(SimpleNamespace(),config(daily_brief_weekends=False),now=now),(False,"disabled"))

    async def test_eastern_schedule_handles_daylight_saving_zone(self):
        before=datetime(2026,11,1,8,59,tzinfo=ZoneInfo("America/New_York"))
        self.assertEqual(await deliver_daily_brief(SimpleNamespace(),config(),now=before),(False,"not_due"))


class DailyBriefDatabaseTests(unittest.TestCase):
    def test_daily_claim_is_durable_and_unique(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"test.db";db.initialize_database(path)
            self.assertTrue(db.claim_daily_brief("2026-07-14",path))
            self.assertFalse(db.claim_daily_brief("2026-07-14",path))
            self.assertTrue(db.finish_daily_brief("2026-07-14","sent",path=path))
            self.assertEqual(db.daily_brief_record("2026-07-14",path)["status"],"sent")
