import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))
from setup_mode import (
    DISABLED_MESSAGE, GROUP_ADMIN_MESSAGE, chatid_command, myid_command, threadid_command,
)


def objects(*, enabled=True, status="administrator", topic=True):
    message = SimpleNamespace(
        reply_text=AsyncMock(), is_topic_message=topic,
        message_thread_id=777 if topic else None,
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=12345),
        effective_chat=SimpleNamespace(id=-100987, type="supergroup"),
        effective_message=message,
    )
    bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status=status)))
    context = SimpleNamespace(bot_data={"config": SimpleNamespace(setup_mode=enabled)}, bot=bot)
    return update, context


class SetupModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_myid_works_for_any_user_when_enabled(self):
        update, context = objects(status="member")
        await myid_command(update, context)
        update.effective_message.reply_text.assert_awaited_once_with("Your Telegram user ID is: 12345")
        context.bot.get_chat_member.assert_not_awaited()

    async def test_chatid_works_for_current_group_admin(self):
        update, context = objects()
        await chatid_command(update, context)
        context.bot.get_chat_member.assert_awaited_once_with(-100987, 12345)
        update.effective_message.reply_text.assert_awaited_once_with("This Telegram chat ID is: -100987")

    async def test_threadid_works_for_current_group_admin_in_topic(self):
        update, context = objects()
        await threadid_command(update, context)
        update.effective_message.reply_text.assert_awaited_once_with("This forum topic thread ID is: 777")

    async def test_threadid_requires_topic(self):
        update, context = objects(topic=False)
        await threadid_command(update, context)
        update.effective_message.reply_text.assert_awaited_once_with(
            "Run /threadid inside the forum topic whose ID you need."
        )

    async def test_group_ids_reject_non_admin(self):
        update, context = objects(status="member")
        await chatid_command(update, context)
        update.effective_message.reply_text.assert_awaited_once_with(GROUP_ADMIN_MESSAGE)

    async def test_all_commands_are_disabled_when_setup_mode_is_false(self):
        for command in (myid_command, chatid_command, threadid_command):
            with self.subTest(command=command.__name__):
                update, context = objects(enabled=False)
                await command(update, context)
                update.effective_message.reply_text.assert_awaited_once_with(DISABLED_MESSAGE)
                context.bot.get_chat_member.assert_not_awaited()


if __name__ == "__main__": unittest.main()
