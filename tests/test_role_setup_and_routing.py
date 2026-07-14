import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))

import database as db
from config import Config
from navigation import callback, home_markup, menu_markup
from runtime_config import apply_persisted_settings, persist_setting
from tracker import participation_enabled


def labels(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


class RoleSeparationTests(unittest.TestCase):
    def cfg(self):
        return SimpleNamespace(owner_user_ids=frozenset({1}), lead_admin_user_ids=frozenset(),
            admin_user_ids=frozenset({2,3}), admin_permissions={})

    def menu(self, user_id, creator=None, member=None):
        ctx = SimpleNamespace(user_data={},bot_data={"config":self.cfg()})
        with patch("navigation.db.get_creator",return_value=creator),patch("navigation.db.get_member",return_value=member):
            return labels(home_markup(ctx,user_id))

    def test_creator_sees_only_creator_functions(self):
        visible = self.menu(20,{"telegram_id":20},None)
        self.assertIn("💛 My VAD Home",visible)
        for hidden in ("🛡️ Admin Home","👑 Owner Home"):
            self.assertNotIn(hidden,visible)

    def test_buyer_sees_only_buyer_functions(self):
        visible = self.menu(21,None,{"telegram_id":21,"member_type":"buyer"})
        self.assertIn("🛍️ Buyer Home",visible)
        self.assertNotIn("💛 My VAD Home",visible)
        self.assertNotIn("🛡️ Admin Home",visible)

    def test_admin_and_owner_menus_are_additive(self):
        admin = self.menu(3,None,None)
        owner = self.menu(1,None,None)
        self.assertIn("🛡️ Admin Home",admin)
        self.assertIn("💛 My VAD Home",admin)
        self.assertNotIn("👑 Owner Home",admin)
        self.assertIn("👑 Owner Home",owner)
        self.assertIn("🛡️ Admin Home",owner)
        self.assertIn("💛 My VAD Home",owner)

    def test_owner_without_creator_profile_can_register_as_creator(self):
        self.assertIn("👑 Owner Home",self.menu(1,None,None))


class SetupMenuTests(unittest.IsolatedAsyncioTestCase):
    def cfg(self, owner=True):
        return SimpleNamespace(owner_user_ids=frozenset({1}) if owner else frozenset(),lead_admin_user_ids=frozenset(),
            admin_user_ids=frozenset({2}),admin_permissions={},participation_chat_id=-100,participation_topic_ids=frozenset({10,11}),
            girls_chat_id=-200,pop_chat_id=-300,pop_thread_id=11,admin_chat_id=-400,creator_group_id=-500,
            buyer_group_id=-600,timezone_name="America/New_York",warning_hours=48,alert_hours=72)

    async def screen(self, action, user_id=1, chat_id=-100, thread_id=10, is_forum=True):
        chat = SimpleNamespace(id=chat_id,title="VAD Main Group",is_forum=is_forum)
        message = SimpleNamespace(chat=chat,message_thread_id=thread_id)
        query = SimpleNamespace(data=f"op:menu:{action}",message=message,answer=AsyncMock(),edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=user_id),effective_chat=chat)
        ctx = SimpleNamespace(user_data={"menu_nonce":"menu"},bot_data={"config":self.cfg()})
        await callback(update,ctx)
        return query.edit_message_text.await_args

    async def test_owner_setup_has_clear_configuration_sections(self):
        result = await self.screen("setup")
        text, markup = result.args[0],result.kwargs["reply_markup"]
        self.assertIn("Review where the bot works",text)
        self.assertTrue({"💬 Participation Chat","🧵 Participation Topics","📸 POP Group","🧵 POP Topic",
            "🛡️ Admin Group","👤 Seller Group","🛍️ Buyer Group","🌎 Time Zone","⏰ Reminder Times"}.issubset(labels(markup)))

    async def test_verify_topic_shows_context_and_configuration(self):
        result = await self.screen("verify_topic")
        text = result.args[0]
        self.assertIn("Chat name: VAD Main Group",text)
        self.assertIn("Topic ID: 10",text)
        self.assertIn("Forum: Yes",text)
        self.assertIn("Participation enabled here: Yes",text)
        self.assertIn("Bot permissions:",text)
        self.assertIn("Configuration problems:",text)

    async def test_admin_cannot_tamper_into_owner_setup(self):
        result = await self.screen("setup",user_id=2)
        self.assertIn("only to owners",result.args[0])

    async def test_existing_creator_can_be_selected_for_additive_admin_role(self):
        creator={"telegram_id":50,"display_name":"Keely","status":"active"}
        with patch("navigation.db.list_creators",return_value=[creator]),patch("navigation.db.pending_bot_users",return_value=[]):
            result=await self.screen("access_add")
        self.assertIn("Keely",labels(result.kwargs["reply_markup"]))
        self.assertIn("never creates a duplicate creator record",result.args[0])

    async def test_people_and_roles_shows_only_owner_and_admin_counts(self):
        result=await self.screen("roles")
        text=result.args[0];visible=labels(result.kwargs["reply_markup"])
        self.assertIn("Owners: 1",text);self.assertIn("Admins: 1",text)
        self.assertEqual({label for label in visible if label in {"👑 Owners","👥 Admins"}}, {"👑 Owners","👥 Admins"})

    async def test_add_admin_offers_only_admin_and_owner(self):
        creator={"telegram_id":50,"display_name":"Keeley","status":"active"}
        with patch("navigation.db.get_creator",return_value=creator),patch("navigation.db.pending_bot_users",return_value=[]):
            result=await self.screen("access_candidate_50")
        visible=labels(result.kwargs["reply_markup"])
        self.assertIn("Make Admin",visible);self.assertIn("Make Owner",visible)
        self.assertEqual(2,len([label for label in visible if label.startswith("Make ")]))

    async def test_make_owner_is_owner_only(self):
        result=await self.screen("access_confirm_owner_50",user_id=2)
        self.assertIn("owner-only",result.args[0])

    def test_rendered_menus_have_unique_labels_and_callback_actions(self):
        for user_id in (1,2,20):
            creator={"telegram_id":user_id} if user_id==20 else None
            ctx=SimpleNamespace(user_data={},bot_data={"config":self.cfg()})
            with patch("navigation.db.get_creator",return_value=creator),patch("navigation.db.get_member",return_value=None):
                markup=home_markup(ctx,user_id)
            visible=[button.text for row in markup.inline_keyboard for button in row]
            actions=[button.callback_data.rsplit(":",1)[-1] for row in markup.inline_keyboard for button in row]
            self.assertEqual(len(visible),len(set(visible)))
            self.assertEqual(len(actions),len(set(actions)))

    def test_shared_dashboard_destinations_are_deduplicated(self):
        ctx=SimpleNamespace(user_data={},bot_data={"config":self.cfg()})
        markup=menu_markup(ctx,[("📚 Help Center","resources"),("Help","resources"),
            ("📜 Timeline","timeline_0"),("📜 Timeline","other_timeline"),("📅 Calendar","calendar")],"owner")
        visible=[button.text for row in markup.inline_keyboard for button in row]
        actions=[button.callback_data.rsplit(":",1)[-1] for row in markup.inline_keyboard for button in row]
        self.assertEqual(1,sum(action=="resources" for action in actions))
        self.assertEqual(1,sum(label=="📜 Timeline" for label in visible))
        self.assertEqual(len(actions),len(set(actions)))
        self.assertEqual(len(visible),len(set(visible)))

    async def test_owner_can_explicitly_replace_numbered_topics_with_general(self):
        cfg=self.cfg();chat=SimpleNamespace(id=-100,title="VAD Main Group",is_forum=True)
        message=SimpleNamespace(chat=chat,message_thread_id=None)
        ctx=SimpleNamespace(user_data={"menu_nonce":"menu"},bot_data={"config":cfg})
        query=SimpleNamespace(data="op:menu:setup_prepare_participation_general",message=message,answer=AsyncMock(),edit_message_text=AsyncMock())
        update=SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=1),effective_chat=chat)
        await callback(update,ctx)
        self.assertEqual(ctx.user_data["setup_pending"],{"key":"participation_general","value":"general"})
        query.data=f"op:{ctx.user_data['menu_nonce']}:setup_confirm_change"
        with patch("navigation.persist_setting") as persist:
            await callback(update,ctx)
        persist.assert_called_once_with(cfg,"participation_topic_ids",frozenset(),1)


class ParticipationRoutingTests(unittest.TestCase):
    def test_multiple_topics_are_allow_listed(self):
        cfg=SimpleNamespace(participation_chat_id=-100,participation_topic_ids=frozenset({10,11}),girls_chat_id=None,girls_thread_id=None)
        self.assertTrue(participation_enabled(cfg,-100,10))
        self.assertTrue(participation_enabled(cfg,-100,11))
        self.assertFalse(participation_enabled(cfg,-100,12))
        self.assertFalse(participation_enabled(cfg,-200,10))

    def test_pop_location_never_becomes_participation_location(self):
        cfg=SimpleNamespace(participation_chat_id=-100,participation_topic_ids=frozenset({10}),
            girls_chat_id=-200,girls_thread_id=None,pop_chat_id=-200,pop_thread_id=11)
        self.assertFalse(participation_enabled(cfg,-200,11))

    def test_empty_topic_list_means_general_only(self):
        cfg=SimpleNamespace(participation_chat_id=-100,participation_topic_ids=frozenset(),girls_chat_id=None,girls_thread_id=None)
        self.assertTrue(participation_enabled(cfg,-100,None))
        self.assertFalse(participation_enabled(cfg,-100,10))

    def test_environment_supports_multiple_topics_and_separate_pop_group(self):
        values={"TELEGRAM_BOT_TOKEN":"test-only","PARTICIPATION_CHAT_ID":"-100","PARTICIPATION_TOPIC_IDS":"10,11","POP_CHAT_ID":"-300"}
        with patch.dict(os.environ,values,clear=True):
            cfg=Config.from_env()
        self.assertEqual(cfg.participation_topic_ids,frozenset({10,11}))
        self.assertEqual(cfg.pop_chat_id,-300)

    def test_main_chat_defaults_to_general_even_with_legacy_creator_topic(self):
        values={"TELEGRAM_BOT_TOKEN":"test-only","MAIN_CHAT_ID":"-100","GIRLS_CHAT_ID":"-200","GIRLS_THREAD_ID":"99"}
        with patch.dict(os.environ,values,clear=True):
            cfg=Config.from_env()
        self.assertEqual(cfg.participation_chat_id,-100)
        self.assertEqual(cfg.participation_topic_ids,frozenset())
        self.assertTrue(participation_enabled(cfg,-100,None))
        self.assertFalse(participation_enabled(cfg,-100,99))

    def test_legacy_elevated_environment_ids_become_admins_without_duplicating_owners(self):
        values={"TELEGRAM_BOT_TOKEN":"test-only","OWNER_USER_IDS":"1","ADMIN_USER_IDS":"60",
            "LEAD_ADMIN_USER_IDS":"1,50"}
        with patch.dict(os.environ,values,clear=True):cfg=Config.from_env()
        self.assertEqual(cfg.owner_user_ids,frozenset({1}))
        self.assertEqual(cfg.admin_user_ids,frozenset({50,60}))
        self.assertEqual(cfg.lead_admin_user_ids,frozenset())


class BuyerIdentityTests(unittest.TestCase):
    def test_buyer_identity_does_not_create_creator(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"bot.db";db.initialize_database(path)
            db.register_member(50,"buyer","Buyer Person","buyer",path)
            self.assertEqual(db.get_member(50,path)["member_type"],"buyer")
            self.assertIsNone(db.get_creator(50,path))


class PersistedSetupTests(unittest.TestCase):
    def test_owner_setting_survives_new_config_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"bot.db";db.initialize_database(path)
            defaults=dict(participation_chat_id=None,participation_topic_ids=frozenset(),pop_chat_id=None,
                pop_thread_id=None,admin_chat_id=None,creator_group_id=None,buyer_group_id=None,
                timezone_name="America/New_York",warning_hours=48,alert_hours=72,pop_cutoff_time="23:59",
                meaningful_min_words=3,meaningful_min_characters=12,repeat_window_days=7)
            first=SimpleNamespace(**defaults)
            persist_setting(first,"participation_chat_id",-1003543892255,1,path)
            persist_setting(first,"participation_topic_ids",frozenset({123}),1,path)
            second=SimpleNamespace(**defaults)
            apply_persisted_settings(second,path)
            self.assertEqual(second.participation_chat_id,-1003543892255)
            self.assertEqual(second.participation_topic_ids,frozenset({123}))
            self.assertIn("setting_changed",[row["action"] for row in db.history(20,path)])

    def test_owner_admin_assignment_is_additive_and_persistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"bot.db";db.initialize_database(path);db.record_bot_user(50,"keely","Keely",path)
            cfg=SimpleNamespace(owner_user_ids=frozenset({1}),admin_user_ids=frozenset(),lead_admin_user_ids=frozenset())
            persist_setting(cfg,"admin_user_ids",frozenset({50}),1,path)
            self.assertEqual(db.roles_for_user(50,path),frozenset({"creator","admin"}))
            self.assertEqual(db.get_creator(50,path)["status"],"active")
            persist_setting(cfg,"owner_user_ids",frozenset({1,50}),1,path)
            self.assertEqual(db.roles_for_user(50,path),frozenset({"creator","admin","owner"}))
            restored=SimpleNamespace(owner_user_ids=frozenset({1}),admin_user_ids=frozenset(),lead_admin_user_ids=frozenset())
            apply_persisted_settings(restored,path)
            self.assertEqual(restored.owner_user_ids,frozenset({1,50}))
            self.assertEqual(restored.admin_user_ids,frozenset())

    def test_legacy_elevated_admins_migrate_to_owner_or_admin(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"bot.db";db.initialize_database(path)
            db.set_system_state("config:lead_admin_user_ids","[1, 50]",path)
            cfg=SimpleNamespace(owner_user_ids=frozenset({1}),admin_user_ids=frozenset({60}),lead_admin_user_ids=frozenset())
            apply_persisted_settings(cfg,path)
            self.assertEqual(cfg.owner_user_ids,frozenset({1}))
            self.assertEqual(cfg.admin_user_ids,frozenset({50,60}))
            self.assertEqual(cfg.lead_admin_user_ids,frozenset())
