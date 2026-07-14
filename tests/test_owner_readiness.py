import sys
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock,patch
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).parents[1]/"bot"))

import database as db
from main import startup_readiness_notice
from navigation import callback
from readiness import EXPECTED_MAIN_CHAT_ID,readiness_items,system_check_summary
from tracker import observe


def config(**changes):
    values=dict(token="configured",owner_user_ids=frozenset({1}),lead_admin_user_ids=frozenset(),admin_user_ids=frozenset(),admin_permissions={},
        participation_chat_id=EXPECTED_MAIN_CHAT_ID,participation_topic_ids=frozenset(),creator_group_id=None,pop_thread_id=None,
        admin_chat_id=None,registration_thread_id=None,away_thread_id=None,pop_review_thread_id=None,reports_thread_id=None,
        moderation_thread_id=None,support_thread_id=None,health_thread_id=None,warning_hours=48,alert_hours=72,
        pop_cutoff_time="23:59",timezone_name="America/New_York",girls_chat_id=None,girls_thread_id=None)
    values.update(changes);cfg=SimpleNamespace(**values);cfg.timezone=ZoneInfo(cfg.timezone_name);return cfg


class ReadinessCalculationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"ready.db";db.initialize_database(self.path)
    def tearDown(self):self.tmp.cleanup()

    def test_missing_configuration_is_actionable_and_backup_is_honest(self):
        items={item["key"]:item for item in readiness_items(config(),self.path)}
        self.assertEqual(items["main"]["state"],"ready")
        self.assertEqual(items["participation_topic"]["state"],"setup")
        self.assertEqual(items["backup"]["state"],"setup")
        self.assertNotIn("configured",items["backup"]["detail"].casefold())

    def test_full_check_detects_documentation_and_current_schema(self):
        checks,counts=system_check_summary(config(),self.path,Path(__file__).parents[1]/"docs")
        self.assertEqual(next(i for i in checks if i["key"]=="schema")["state"],"ready")
        self.assertEqual(next(i for i in checks if i["key"]=="docs")["state"],"ready")
        self.assertGreater(counts["setup"],0)

    def test_explicit_general_topic_configuration_is_ready(self):
        db.set_system_state("config:participation_topic_ids","[]",self.path)
        items={item["key"]:item for item in readiness_items(config(),self.path)}
        self.assertEqual(items["participation_topic"]["state"],"ready")
        self.assertIn("explicitly verified",items["participation_topic"]["detail"])

    def test_pending_start_does_not_assign_any_role(self):
        db.record_bot_user(50,"person","Known Person",self.path)
        rows=db.pending_bot_users({1},{2},{3},self.path)
        self.assertEqual(rows[0]["telegram_id"],50)
        self.assertIsNone(db.get_creator(50,self.path));self.assertIsNone(db.get_member(50,self.path))

    def test_real_counted_message_verifies_message_access_and_monitor(self):
        db.register_creator(20,"creator","Creator",self.path);db.set_status(20,"active",1,self.path)
        for key in ("telegram_can_read_all_group_messages","last_participation_message_detected","last_meaningful_participation_counted"):
            db.set_system_state(key,"true",self.path)
        items={item["key"]:item for item in readiness_items(config(participation_topic_ids=frozenset({10})),self.path)}
        self.assertEqual(items["privacy"]["state"],"ready");self.assertEqual(items["ordinary_messages"]["state"],"ready")
        self.assertEqual(items["monitor"]["state"],"ready")


class SafeTestIsolationTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def audio_message(*,duration=15,thread=10,chat=EXPECTED_MAIN_CHAT_ID,voice=True,message_id=100,file_id="audio-1",caption=None):
        media=SimpleNamespace(duration=duration,file_unique_id=file_id,file_id=file_id)
        return SimpleNamespace(text=None,chat_id=chat,message_thread_id=thread,message_id=message_id,
            photo=None,sticker=None,animation=None,video=None,voice=media if voice else None,
            audio=None if voice else media,document=None,caption=caption)

    async def test_safe_message_never_records_real_engagement(self):
        cfg=config(participation_topic_ids=frozenset({10}))
        msg=SimpleNamespace(text="VAD-SAFE-ABC123:meaningful: I am checking thoughtful community participation safely.",
            chat_id=EXPECTED_MAIN_CHAT_ID,message_thread_id=10,reply_text=AsyncMock())
        update=SimpleNamespace(effective_message=msg,effective_user=SimpleNamespace(id=20))
        ctx=SimpleNamespace(bot_data={"config":cfg})
        state={"readiness:test_code":{"value":"ABC123"},"readiness:test_mode":{"value":"meaningful"}}
        with patch("tracker.db.system_state",return_value=state),patch("tracker.db.get_creator",return_value={"status":"active"}),\
             patch("tracker.db.set_system_state") as set_state,patch("tracker.db.record_audit"),patch("tracker.db.record_engagement") as real:
            await observe(update,ctx)
        real.assert_not_called();self.assertTrue(any(call.args[0]=="readiness:meaningful_test" for call in set_state.call_args_list))

    async def test_real_meaningful_message_updates_creator_and_readiness(self):
        cfg=config(participation_topic_ids=frozenset({10}))
        msg=SimpleNamespace(text="I appreciate this thoughtful community discussion today.",chat_id=EXPECTED_MAIN_CHAT_ID,
            message_thread_id=10,message_id=88,photo=None,sticker=None,animation=None,video=None,voice=None,document=None,caption=None)
        update=SimpleNamespace(effective_message=msg,effective_user=SimpleNamespace(id=20));ctx=SimpleNamespace(bot_data={"config":cfg})
        creator={"telegram_id":20,"status":"active","vacation_until":None}
        with patch("tracker.db.system_state",return_value={}),patch("tracker.db.get_creator",return_value=creator), \
             patch("tracker.db.approved_absence_on",return_value=None),patch("tracker.db.recent_hash_exists",return_value=False), \
             patch("tracker.db.record_engagement",return_value=True) as record,patch("tracker.db.set_system_state") as state:
            await observe(update,ctx)
        self.assertEqual(record.call_args.args[5],"accepted")
        keys=[call.args[0] for call in state.call_args_list]
        self.assertIn("last_participation_message_detected",keys);self.assertIn("last_meaningful_participation_counted",keys)
        self.assertIn("readiness:meaningful_test",keys)

    async def test_wrong_chat_records_exact_creator_diagnostic(self):
        cfg=config(participation_topic_ids=frozenset({10}))
        msg=SimpleNamespace(text="I appreciate this thoughtful community discussion today.",chat_id=-999,
            message_thread_id=10,message_id=89,photo=None,sticker=None,animation=None,video=None,voice=None,document=None,caption=None)
        update=SimpleNamespace(effective_message=msg,effective_user=SimpleNamespace(id=20));ctx=SimpleNamespace(bot_data={"config":cfg})
        creator={"telegram_id":20,"status":"active","vacation_until":None}
        with patch("tracker.db.system_state",return_value={}),patch("tracker.db.get_creator",return_value=creator), \
             patch("tracker.db.approved_absence_on",return_value=None),patch("tracker.db.set_system_state") as state:
            await observe(update,ctx)
        diagnostic=next(call for call in state.call_args_list if call.args[0]=="participation:last_creator:20")
        payload=json.loads(diagnostic.args[1])
        self.assertEqual(payload["reason"],"wrong_chat");self.assertEqual(payload["observed_chat_id"],-999)
        self.assertEqual(payload["configured_chat_id"],EXPECTED_MAIN_CHAT_ID);self.assertFalse(payload["chat_matches"])

    async def test_wrong_topic_records_exact_creator_diagnostic(self):
        cfg=config(participation_topic_ids=frozenset({10}))
        msg=SimpleNamespace(text="I appreciate this thoughtful community discussion today.",chat_id=EXPECTED_MAIN_CHAT_ID,
            message_thread_id=77,message_id=90,photo=None,sticker=None,animation=None,video=None,voice=None,document=None,caption=None)
        update=SimpleNamespace(effective_message=msg,effective_user=SimpleNamespace(id=20));ctx=SimpleNamespace(bot_data={"config":cfg})
        creator={"telegram_id":20,"status":"active","vacation_until":None}
        with patch("tracker.db.system_state",return_value={}),patch("tracker.db.get_creator",return_value=creator), \
             patch("tracker.db.approved_absence_on",return_value=None),patch("tracker.db.set_system_state") as state,patch("tracker.db.record_audit"):
            await observe(update,ctx)
        diagnostic=next(call for call in state.call_args_list if call.args[0]=="participation:last_creator:20")
        payload=json.loads(diagnostic.args[1])
        self.assertEqual(payload["reason"],"wrong_topic");self.assertTrue(payload["chat_matches"]);self.assertFalse(payload["topic_matches"])

    async def test_qualifying_voice_message_counts(self):
        cfg=config(participation_topic_ids=frozenset({10}),repeat_window_days=7)
        msg=self.audio_message(duration=15);update=SimpleNamespace(effective_message=msg,effective_user=SimpleNamespace(id=20))
        creator={"telegram_id":20,"status":"active","vacation_until":None};ctx=SimpleNamespace(bot_data={"config":cfg})
        with patch("tracker.db.system_state",return_value={}),patch("tracker.db.get_creator",return_value=creator), \
             patch("tracker.db.approved_absence_on",return_value=None),patch("tracker.db.recent_hash_exists",return_value=False), \
             patch("tracker.db.record_engagement",return_value=True) as record,patch("tracker.db.set_system_state") as state:
            await observe(update,ctx)
        self.assertEqual(record.call_args.args[5:7],("accepted","voice_message"))
        self.assertEqual(record.call_args.kwargs["event_type"],"voice_message")
        diagnostic=next(call for call in state.call_args_list if call.args[0]=="participation:last_creator:20")
        self.assertEqual(json.loads(diagnostic.args[1])["reason"],"accepted_voice_message")

    async def test_short_voice_message_is_ignored(self):
        cfg=config(participation_topic_ids=frozenset({10}),repeat_window_days=7)
        msg=self.audio_message(duration=14);update=SimpleNamespace(effective_message=msg,effective_user=SimpleNamespace(id=20))
        creator={"telegram_id":20,"status":"active","vacation_until":None};ctx=SimpleNamespace(bot_data={"config":cfg})
        with patch("tracker.db.system_state",return_value={}),patch("tracker.db.get_creator",return_value=creator), \
             patch("tracker.db.approved_absence_on",return_value=None),patch("tracker.db.record_engagement",return_value=True) as record, \
             patch("tracker.db.set_system_state"):
            await observe(update,ctx)
        self.assertEqual(record.call_args.args[5:7],("rejected","audio_too_short"))

    async def test_audio_in_wrong_topic_is_rejected_before_counting(self):
        cfg=config(participation_topic_ids=frozenset({10}),repeat_window_days=7)
        msg=self.audio_message(thread=77,voice=False);update=SimpleNamespace(effective_message=msg,effective_user=SimpleNamespace(id=20))
        creator={"telegram_id":20,"status":"active","vacation_until":None};ctx=SimpleNamespace(bot_data={"config":cfg})
        with patch("tracker.db.system_state",return_value={}),patch("tracker.db.get_creator",return_value=creator), \
             patch("tracker.db.approved_absence_on",return_value=None),patch("tracker.db.record_audit"), \
             patch("tracker.db.record_engagement") as record,patch("tracker.db.set_system_state") as state:
            await observe(update,ctx)
        record.assert_not_called();diagnostic=next(call for call in state.call_args_list if call.args[0]=="participation:last_creator:20")
        self.assertEqual(json.loads(diagnostic.args[1])["reason"],"wrong_topic")

    async def test_audio_from_unapproved_user_is_rejected(self):
        cfg=config(participation_topic_ids=frozenset({10}),repeat_window_days=7)
        msg=self.audio_message(voice=False);update=SimpleNamespace(effective_message=msg,effective_user=SimpleNamespace(id=21));ctx=SimpleNamespace(bot_data={"config":cfg})
        pending={"telegram_id":21,"status":"pending","vacation_until":None}
        with patch("tracker.db.system_state",return_value={}),patch("tracker.db.get_creator",return_value=pending), \
             patch("tracker.db.record_audit"),patch("tracker.db.record_engagement") as record,patch("tracker.db.set_system_state") as state:
            await observe(update,ctx)
        record.assert_not_called();diagnostic=next(call for call in state.call_args_list if call.args[0]=="participation:last_creator:21")
        self.assertEqual(json.loads(diagnostic.args[1])["reason"],"creator_not_approved")

    async def test_duplicate_audio_is_ignored(self):
        cfg=config(participation_topic_ids=frozenset({10}),repeat_window_days=7)
        msg=self.audio_message(voice=False);update=SimpleNamespace(effective_message=msg,effective_user=SimpleNamespace(id=20))
        creator={"telegram_id":20,"status":"active","vacation_until":None};ctx=SimpleNamespace(bot_data={"config":cfg})
        with patch("tracker.db.system_state",return_value={}),patch("tracker.db.get_creator",return_value=creator), \
             patch("tracker.db.approved_absence_on",return_value=None),patch("tracker.db.recent_hash_exists",return_value=True), \
             patch("tracker.db.record_engagement",return_value=True) as record,patch("tracker.db.set_system_state"):
            await observe(update,ctx)
        self.assertEqual(record.call_args.args[5:7],("rejected","duplicate_audio"))


class OwnerFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_user_admin_promotion_does_not_create_creator_or_owner(self):
        cfg=config();query=SimpleNamespace(data="op:n:access_confirm_admin_50",answer=AsyncMock(),edit_message_text=AsyncMock(),message=SimpleNamespace())
        update=SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=1),effective_chat=None)
        ctx=SimpleNamespace(user_data={"menu_nonce":"n"},bot_data={"config":cfg})
        with patch("navigation.persist_setting"),patch("navigation.db.record_audit"),patch("navigation.db.get_creator",return_value=None),patch("navigation.db.get_member",return_value=None):
            await callback(update,ctx)
        self.assertIn(50,cfg.admin_user_ids);self.assertNotIn(50,cfg.owner_user_ids)

    async def test_startup_warning_is_private_and_deduplicated(self):
        app=SimpleNamespace(bot_data={"config":config()},bot=SimpleNamespace(send_message=AsyncMock()))
        with patch("main.critical_fingerprint",return_value=("finger",["participation_topic"])),\
             patch("database.system_state",return_value={}),patch("main.set_system_state") as mark:
            await startup_readiness_notice(app)
        app.bot.send_message.assert_awaited_once();self.assertEqual(app.bot.send_message.await_args.args[0],1);mark.assert_called_once()

    async def test_startup_records_telegram_privacy_capability(self):
        bot=SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(can_read_all_group_messages=False)),send_message=AsyncMock())
        app=SimpleNamespace(bot_data={"config":config()},bot=bot)
        with patch("main.critical_fingerprint",return_value=("finger",[])),patch("main.set_system_state") as state:
            await startup_readiness_notice(app)
        self.assertTrue(any(call.args==( "telegram_can_read_all_group_messages","false") for call in state.call_args_list))

    async def test_setup_wizard_resumes_saved_step(self):
        cfg=config();query=SimpleNamespace(data="op:n:setup_wizard",answer=AsyncMock(),edit_message_text=AsyncMock(),message=SimpleNamespace())
        update=SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=1),effective_chat=None)
        ctx=SimpleNamespace(user_data={"menu_nonce":"n"},bot_data={"config":cfg})
        with patch("navigation.db.system_state",return_value={"setup_wizard:1":{"value":"4"}}):
            await callback(update,ctx)
        self.assertIn("Step 4 of 8",query.edit_message_text.await_args.args[0])

    async def test_non_owner_cannot_open_readiness_or_test_center(self):
        cfg=config(owner_user_ids=frozenset({1}),admin_user_ids=frozenset({2}))
        for action in ("readiness","test_center","setup_wizard"):
            query=SimpleNamespace(data=f"op:n:{action}",answer=AsyncMock(),edit_message_text=AsyncMock(),message=SimpleNamespace())
            update=SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=2),effective_chat=None)
            ctx=SimpleNamespace(user_data={"menu_nonce":"n"},bot_data={"config":cfg})
            with patch("navigation.db.get_creator",return_value=None),patch("navigation.db.get_member",return_value=None):await callback(update,ctx)
            self.assertIn("owner-only",query.edit_message_text.await_args.args[0].casefold())

    def test_copyable_instructions_are_visible_and_never_request_creator_ids(self):
        source=(Path(__file__).parents[1]/"bot"/"navigation.py").read_text(encoding="utf-8")
        self.assertIn("Creator Registration Instructions",source);self.assertIn("Admin Setup Instructions",source)
        self.assertIn("Alex Owner Setup Instructions",source);self.assertIn("You do not need to find or send your numeric Telegram ID",source)

    def test_participation_help_explains_purpose_not_just_timing(self):
        from config import RESOURCE_DEFAULTS
        body=RESOURCE_DEFAULTS["engagement"][1]
        self.assertIn("genuine conversation",body)
        self.assertIn("reason to come back",body)
        self.assertIn("do not satisfy",body)


if __name__=="__main__":unittest.main()
