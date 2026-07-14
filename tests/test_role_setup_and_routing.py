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
from navigation import callback, home_markup
from tracker import participation_enabled


def labels(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


class RoleSeparationTests(unittest.TestCase):
    def cfg(self):
        return SimpleNamespace(owner_user_ids=frozenset({1}), lead_admin_user_ids=frozenset({2}),
            admin_user_ids=frozenset({3}), admin_permissions={})

    def menu(self, user_id, creator=None, member=None):
        ctx = SimpleNamespace(user_data={},bot_data={"config":self.cfg()})
        with patch("navigation.db.get_creator",return_value=creator),patch("navigation.db.get_member",return_value=member):
            return labels(home_markup(ctx,user_id))

    def test_creator_sees_only_creator_functions(self):
        visible = self.menu(20,{"telegram_id":20},None)
        self.assertIn("👤 My Creator Hub",visible)
        for hidden in ("🛡️ Admin Tools","🔐 Owner Dashboard"):
            self.assertNotIn(hidden,visible)

    def test_buyer_sees_only_buyer_functions(self):
        visible = self.menu(21,None,{"telegram_id":21,"member_type":"buyer"})
        self.assertIn("🛍️ Buyer Home",visible)
        self.assertNotIn("👤 My Creator Hub",visible)
        self.assertNotIn("🛡️ Admin Tools",visible)

    def test_admin_and_owner_menus_are_distinct(self):
        admin = self.menu(3,None,None)
        owner = self.menu(1,None,None)
        self.assertIn("🛡️ Admin Tools",admin)
        self.assertNotIn("🔐 Owner Dashboard",admin)
        self.assertIn("🔐 Owner Dashboard",owner)


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
            "🛡️ Admin Group","👤 Creator Group","🛍️ Buyer Group","🌎 Time Zone","⏰ Reminder Times"}.issubset(labels(markup)))

    async def test_verify_topic_shows_context_and_configuration(self):
        result = await self.screen("verify_topic")
        text = result.args[0]
        self.assertIn("Chat name: VAD Main Group",text)
        self.assertIn("Topic ID: 10",text)
        self.assertIn("Forum: Yes",text)
        self.assertIn("Participation enabled here: Yes",text)

    async def test_admin_cannot_tamper_into_owner_setup(self):
        result = await self.screen("setup",user_id=2)
        self.assertIn("only to owners",result.args[0])


class ParticipationRoutingTests(unittest.TestCase):
    def test_multiple_topics_are_allow_listed(self):
        cfg=SimpleNamespace(participation_chat_id=-100,participation_topic_ids=frozenset({10,11}),girls_chat_id=None,girls_thread_id=None)
        self.assertTrue(participation_enabled(cfg,-100,10))
        self.assertTrue(participation_enabled(cfg,-100,11))
        self.assertFalse(participation_enabled(cfg,-100,12))
        self.assertFalse(participation_enabled(cfg,-200,10))

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


class BuyerIdentityTests(unittest.TestCase):
    def test_buyer_identity_does_not_create_creator(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"bot.db";db.initialize_database(path)
            db.register_member(50,"buyer","Buyer Person","buyer",path)
            self.assertEqual(db.get_member(50,path)["member_type"],"buyer")
            self.assertIsNone(db.get_creator(50,path))
