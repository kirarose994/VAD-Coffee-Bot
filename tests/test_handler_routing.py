import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))

from telegram import Update, User
from telegram.ext import Application, ConversationHandler
from main import register_application_handlers
from tracker import creator_report


class HandlerRoutingTests(unittest.TestCase):
    def setUp(self):
        self.app = Application.builder().token(
            "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        ).build()
        self.app.bot._bot_user = User(
            id=999, is_bot=True, first_name="Coffee Bot", username="vad_coffee_bot"
        )
        self.app.bot_data["config"] = SimpleNamespace(
            lead_admin_user_ids=frozenset({1}), admin_user_ids=frozenset({2})
        )
        register_application_handlers(self.app)

    def command_update(self):
        return Update.de_json({
            "update_id": 1,
            "message": {
                "message_id": 10,
                "date": 0,
                "chat": {"id": 1, "type": "private", "first_name": "Lead"},
                "from": {"id": 1, "is_bot": False, "first_name": "Lead"},
                "text": "/creator_report",
                "entities": [{"type": "bot_command", "offset": 0, "length": 15}],
            },
        }, self.app.bot)

    def test_creator_report_reaches_tracker_before_coffee_conversation(self):
        update = self.command_update()
        handlers = self.app.handlers[0]
        first_match = next(handler for handler in handlers if handler.check_update(update))
        self.assertIs(first_match.callback, creator_report)
        report_index = handlers.index(first_match)
        conversation_index = next(
            index for index, handler in enumerate(handlers)
            if isinstance(handler, ConversationHandler)
        )
        self.assertLess(report_index, conversation_index)

    def test_generic_tracker_observers_do_not_match_slash_commands(self):
        update = self.command_update()
        self.assertTrue(self.app.handlers.get(10))
        self.assertFalse(any(handler.check_update(update) for handler in self.app.handlers[10]))


if __name__ == "__main__": unittest.main()
