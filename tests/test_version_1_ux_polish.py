import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).parents[1]/"bot"))

from community_pulse import build_community_pulse,render_community_pulse
from navigation import callback
from participation_summary import render_today,render_today_group
from weekly_encouragement import render_weekly_encouragement


def cfg():
    return SimpleNamespace(owner_user_ids=frozenset({1}),lead_admin_user_ids=frozenset(),admin_user_ids=frozenset({2}),
        admin_permissions={},timezone=ZoneInfo("America/New_York"),timezone_name="America/New_York",
        warning_hours=48,alert_hours=72,pop_due_weekday=3,pop_cutoff_time="23:59")


def labels(markup):return [b.text for row in markup.inline_keyboard for b in row]
def actions(markup):return [b.callback_data.rsplit(":",1)[-1] for row in markup.inline_keyboard for b in row]


class VersionOnePolishTests(unittest.IsolatedAsyncioTestCase):
    async def screen(self,action,user_id=1):
        query=SimpleNamespace(data=f"op:n:{action}",answer=AsyncMock(),edit_message_text=AsyncMock(),message=SimpleNamespace())
        update=SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=user_id),effective_chat=None)
        context=SimpleNamespace(user_data={"menu_nonce":"n"},bot_data={"config":cfg()})
        await callback(update,context);return query.edit_message_text.await_args

    async def test_owner_tools_are_grouped_and_setup_is_nested(self):
        result=await self.screen("owner_tools");visible=labels(result.kwargs["reply_markup"])
        self.assertTrue({"📊 Daily Operations","🛠 System","♻️ Recovery","⚙️ System Setup","📚 Help Center"}.issubset(visible))
        self.assertNotIn("✅ Setup & Readiness",visible)
        setup=await self.screen("owner_setup_tools");setup_labels=labels(setup.kwargs["reply_markup"])
        self.assertIn("✅ Setup & Readiness",setup_labels);self.assertIn("📍 Telegram Locations",setup_labels)

    async def test_renamed_owner_destinations_keep_existing_callbacks(self):
        daily=await self.screen("owner_daily_tools");mapping={b.text:b.callback_data.rsplit(":",1)[-1]
            for row in daily.kwargs["reply_markup"].inline_keyboard for b in row}
        self.assertEqual("participation_monitor",mapping["📈 Participation Health"])
        self.assertEqual("roles",mapping["👥 Team & Roles"])
        recovery=await self.screen("owner_recovery_tools");callbacks=actions(recovery.kwargs["reply_markup"])
        self.assertIn("deleted",callbacks);self.assertIn("restore_help",callbacks)

    async def test_creator_cannot_tamper_into_pulse_or_weekly_preview(self):
        self.assertIn("only to owners",(await self.screen("community_pulse",3)).args[0])
        self.assertIn("owner-only",(await self.screen("weekly_preview",3)).args[0])

    async def test_help_center_contains_one_whats_new_destination(self):
        result=await self.screen("resources");visible=labels(result.kwargs["reply_markup"]);callbacks=actions(result.kwargs["reply_markup"])
        self.assertEqual(1,visible.count("🆕 What’s New"));self.assertEqual(1,callbacks.count("resource_whats_new"))

    async def test_setup_warning_is_conditional_and_never_duplicates(self):
        with patch("navigation._owner_setup_incomplete",return_value=False),patch("navigation.owner_card",return_value="Summary"):
            complete=await self.screen("owner")
        self.assertNotIn("⚠️ Complete Setup",labels(complete.kwargs["reply_markup"]))
        with patch("navigation._owner_setup_incomplete",return_value=True),patch("navigation.owner_card",return_value="Summary"):
            incomplete=await self.screen("owner")
        self.assertEqual(1,labels(incomplete.kwargs["reply_markup"]).count("⚠️ Complete Setup"))


class CommunityPulseTests(unittest.TestCase):
    def snapshot(self):
        return {"creators":{"approved":[1,2,3],"active":[1,2],"pending":[1]},"away":{"pending":[1]},
            "pop":{"due_today":[1],"still_needed":[],"missing":[],"awaiting_review":[1],"resubmission_requested":[],"rejected":[]},
            "participation":{"approaching":[1],"follow_up":[1]},"support":{"open":[]},
            "accountability":{"owner_reviews":0},"system":{"failures":[]}}

    @patch("community_pulse.build_snapshot")
    @patch("community_pulse.build_participation_summary")
    def test_counts_use_existing_sources_and_render_calmly(self,summary,snapshot):
        summary.return_value={"today":{"creators":2,"events":4,"away":1},"creators":[
            {"today_count":1,"away":False},{"today_count":0,"away":True},{"today_count":0,"away":False}]}
        snapshot.return_value=self.snapshot();pulse=build_community_pulse(cfg(),datetime(2026,7,15,0,30,tzinfo=ZoneInfo("America/New_York")))
        self.assertEqual((2,3,1,1,2),(pulse["active_today"],pulse["active_creators"],pulse["away_today"],pulse["still"],pulse["pop_attention"]))
        text=render_community_pulse(pulse);self.assertIn("A few items may need a friendly follow-up.",text);self.assertNotIn("Private",text)

    def test_today_drilldowns_are_grouped_and_hide_notes(self):
        summary={"today":{"creators":1,"events":1,"ignored":2,"away":1,"not_participated":2},"creators":[
            {"display_name":"Ashley","today_count":1,"away":False},
            {"display_name":"Jade","today_count":0,"away":True,"note":"private secret"},
            {"display_name":"Pepe","today_count":0,"away":False}]}
        self.assertIn("Not counted",render_today(summary));self.assertIn("Still to check in",render_today(summary))
        away=render_today_group(summary,"away");self.assertIn("Jade",away);self.assertNotIn("private secret",away)
        self.assertIn("Pepe",render_today_group(summary,"still"))


class WeeklyEncouragementTests(unittest.TestCase):
    def test_preview_is_noncompetitive_and_volume_neutral(self):
        text=render_weekly_encouragement({"display_name":"Ashley","week_count":40,"pop_status":"excused","away_used":True})
        lowered=text.casefold()
        for forbidden in ("top creator","superstar","best creator","worst creator","40 events"):
            self.assertNotIn(forbidden,lowered)
        self.assertIn("not a ranking",lowered);self.assertIn("does not reward message volume",lowered)


if __name__=="__main__":unittest.main()
