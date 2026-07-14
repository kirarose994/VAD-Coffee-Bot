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
            owner_user_ids=frozenset({3}),
            lead_admin_user_ids=frozenset(), admin_user_ids=frozenset({1,2})
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

    def test_creator_report_reaches_tracker_and_coffee_conversation_is_absent(self):
        update = self.command_update()
        handlers = self.app.handlers[0]
        first_match = next(handler for handler in handlers if handler.check_update(update))
        self.assertIs(first_match.callback, creator_report)
        report_index = handlers.index(first_match)
        self.assertFalse(any(isinstance(handler, ConversationHandler) for handler in handlers))

    def test_generic_tracker_observers_do_not_match_slash_commands(self):
        update = self.command_update()
        self.assertTrue(self.app.handlers.get(10))
        self.assertFalse(any(handler.check_update(update) for handler in self.app.handlers[10]))

    def test_generic_tracker_observer_matches_ordinary_group_text(self):
        update=Update.de_json({"update_id":2,"message":{"message_id":11,"date":0,
            "chat":{"id":-100,"type":"supergroup","title":"VAD"},
            "from":{"id":20,"is_bot":False,"first_name":"Creator"},"text":"A thoughtful community contribution today."}},self.app.bot)
        self.assertTrue(any(handler.check_update(update) for handler in self.app.handlers[10]))

    def test_tracker_observer_matches_voice_and_audio_messages(self):
        for field in ("voice","audio"):
            update=Update.de_json({"update_id":3,"message":{"message_id":12,"date":0,
                "chat":{"id":-100,"type":"supergroup","title":"VAD"},
                "from":{"id":20,"is_bot":False,"first_name":"Creator"},
                field:{"file_id":f"{field}-file","file_unique_id":f"{field}-unique","duration":15}}},self.app.bot)
            self.assertTrue(any(handler.check_update(update) for handler in self.app.handlers[10]),field)

    def test_temporary_setup_handlers_are_not_loaded(self):
        source=(Path(__file__).parents[1]/"bot"/"main.py").read_text(encoding="utf-8")
        self.assertNotIn("register_setup_handlers",source)


if __name__ == "__main__": unittest.main()
