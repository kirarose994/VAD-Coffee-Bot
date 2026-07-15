import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).parents[1]/"bot"))

from telegram import (BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,BotCommandScopeAllPrivateChats)
from command_menus import (ADMIN_COMMANDS,GROUP_COMMANDS,PRIVATE_COMMANDS,
    register_command_scopes,scoped_command)
from navigation import start
from navigation import callback


def cfg(**changes):
    values=dict(owner_user_ids=frozenset({1}),lead_admin_user_ids=frozenset(),admin_user_ids=frozenset({2}),
        admin_permissions={},timezone=ZoneInfo("America/New_York"))
    values.update(changes);return SimpleNamespace(**values)


def update_for(command,user_id=3,chat_type="private"):
    message=SimpleNamespace(text=f"/{command}",reply_text=AsyncMock())
    return SimpleNamespace(effective_message=message,effective_user=SimpleNamespace(id=user_id,first_name="Ashley",username="ashley",full_name="Ashley"),
        effective_chat=SimpleNamespace(type=chat_type))


class CommandScopeRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_group_and_admin_scopes_are_registered_once(self):
        bot=SimpleNamespace(set_my_commands=AsyncMock())
        app=SimpleNamespace(bot=bot,bot_data={"config":cfg()})
        with patch("command_menus.db.set_system_state") as state:
            await register_command_scopes(app)
        self.assertEqual(3,bot.set_my_commands.await_count)
        scopes=[call.kwargs["scope"] for call in bot.set_my_commands.await_args_list]
        self.assertTrue(any(isinstance(scope,BotCommandScopeAllPrivateChats) for scope in scopes))
        self.assertTrue(any(isinstance(scope,BotCommandScopeAllGroupChats) for scope in scopes))
        self.assertTrue(any(isinstance(scope,BotCommandScopeAllChatAdministrators) for scope in scopes))
        self.assertEqual(3,sum(call.args[1]=="ready" for call in state.call_args_list if call.args[0].startswith("command_scope:")))

    async def test_registration_failure_is_logged_and_does_not_crash(self):
        bot=SimpleNamespace(set_my_commands=AsyncMock(side_effect=[RuntimeError("network"),True,True]))
        app=SimpleNamespace(bot=bot,bot_data={"config":cfg()})
        with patch("command_menus.db.set_system_state") as state:
            await register_command_scopes(app)
        self.assertEqual(3,bot.set_my_commands.await_count)
        self.assertTrue(any(call.args[:2]==("command_scope:private","failed:RuntimeError") for call in state.call_args_list))

    def test_no_duplicate_names_and_no_retired_username_dependency(self):
        for scope in (PRIVATE_COMMANDS,GROUP_COMMANDS,ADMIN_COMMANDS):
            names=[name for name,_ in scope];self.assertEqual(len(names),len(set(names)))
        source=(Path(__file__).parents[1]/"bot"/"command_menus.py").read_text(encoding="utf-8")
        self.assertNotIn("VADCoffeeDateBot",source);self.assertNotIn("VADOperationsBot",source)


class ScopedCommandPrivacyTests(unittest.IsolatedAsyncioTestCase):
    def context(self,user_id=3):
        return SimpleNamespace(user_data={},bot_data={"config":cfg(),"bot_username":"VADOperationsBot"})

    async def test_group_status_never_renders_private_creator_information(self):
        update=update_for("status",chat_type="supergroup")
        with patch("command_menus.db.get_creator",return_value={"telegram_id":3}),patch("navigation.creator_card",return_value="PRIVATE STATUS"):
            await scoped_command(update,self.context())
        text=update.effective_message.reply_text.await_args.args[0]
        self.assertNotIn("PRIVATE STATUS",text);self.assertIn("will not be shown",text)
        markup=update.effective_message.reply_text.await_args.kwargs["reply_markup"]
        self.assertEqual("https://t.me/VADOperationsBot",markup.inline_keyboard[0][0].url)

    async def test_group_start_is_a_minimal_private_redirect(self):
        update=update_for("start",chat_type="supergroup")
        with patch("navigation.db.record_bot_user") as record:
            await start(update,self.context())
        record.assert_not_called();text=update.effective_message.reply_text.await_args.args[0]
        self.assertNotIn("participation",text.casefold());self.assertIn("privately",text.casefold())

    async def test_unauthorized_user_cannot_open_admin_command(self):
        update=update_for("inbox",chat_type="supergroup")
        await scoped_command(update,self.context())
        self.assertIn("not available",update.effective_message.reply_text.await_args.args[0])

    async def test_authorized_admin_command_in_group_still_redirects_privately(self):
        update=update_for("participation",user_id=2,chat_type="supergroup")
        await scoped_command(update,self.context(2))
        text=update.effective_message.reply_text.await_args.args[0]
        self.assertIn("privately",text);self.assertNotIn("creator",text.casefold())

    async def test_owner_can_view_all_three_registration_states(self):
        query=SimpleNamespace(data="op:n:command_scope_status",answer=AsyncMock(),edit_message_text=AsyncMock())
        update=SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=1),effective_chat=SimpleNamespace(type="private"))
        context=SimpleNamespace(user_data={"menu_nonce":"n"},bot_data={"config":cfg()})
        with patch("command_menus.command_scope_status",return_value={"private":"ready","group":"ready","admin":"ready"}):
            await callback(update,context)
        text=query.edit_message_text.await_args.args[0]
        self.assertIn("Private chats",text);self.assertIn("Groups",text);self.assertIn("Group administrators",text)
        self.assertEqual(3,text.count("Ready"))


if __name__=="__main__":unittest.main()
