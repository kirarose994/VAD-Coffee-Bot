import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))

from pop_history_scanner import (FEATURE_FLAG, PopHistoryScanConfig, ScanScopeError,
    ScanValidationError, scan_pop_history)


CHAT = -100300
TOPIC = 11
OWNER = 1
START = datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 7, 17, 0, 0, tzinfo=timezone.utc)


def config(**changes):
    values = dict(enabled=True, api_id=12345, api_hash="api-hash-secret",
        session_string="session-string-secret", pop_chat_id=CHAT,
        pop_thread_id=TOPIC, owner_user_ids=frozenset({OWNER}))
    values.update(changes)
    return PopHistoryScanConfig(**values)


def message(message_id, at, **changes):
    values = dict(id=message_id, date=at, edit_date=None, chat_id=CHAT,
        message_thread_id=TOPIC, sender_id=20, message="", entities=(),
        photo=None, document=None, voice=None, audio=None, video=None,
        gif=None, animation=None, sticker=None, file=None, reply_to=None)
    values.update(changes)
    return SimpleNamespace(**values)


class FakeClient:
    def __init__(self, messages=(), entity_chat=CHAT, authorized=True):
        self.messages=list(messages);self.entity_chat=entity_chat
        self.authorized=authorized;self.connected=False;self.disconnected=False

    async def connect(self):self.connected=True
    async def disconnect(self):self.disconnected=True
    async def is_user_authorized(self):return self.authorized
    async def get_entity(self, requested):return SimpleNamespace(peer_id=self.entity_chat)
    async def iter_messages(self, entity, offset_date=None, reply_to=None):
        self.requested_topic=reply_to
        for item in self.messages:
            yield item


async def run(client, *, cfg=None, start=START, end=END):
    return await scan_pop_history(cfg or config(),owner_id=OWNER,start=start,end=end,
        client_factory=lambda unused:client,
        peer_id_resolver=lambda entity:entity.peer_id)


class ConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_feature_flag_refuses_before_client_creation(self):
        called=False
        def factory(unused):
            nonlocal called;called=True
            return FakeClient()
        with self.assertRaisesRegex(ScanValidationError,FEATURE_FLAG):
            await scan_pop_history(config(enabled=False),owner_id=OWNER,start=START,end=END,
                client_factory=factory,peer_id_resolver=lambda entity:entity.peer_id)
        self.assertFalse(called)

    async def test_missing_credentials_and_locations_are_named_without_values(self):
        with self.assertRaises(ScanValidationError) as raised:
            await scan_pop_history(PopHistoryScanConfig(enabled=True,
                owner_user_ids=frozenset({OWNER})),owner_id=OWNER,start=START,end=END,
                client_factory=lambda unused:FakeClient(),peer_id_resolver=lambda entity:entity.peer_id)
        text=str(raised.exception)
        self.assertIn("TELEGRAM_API_ID",text);self.assertIn("TELEGRAM_API_HASH",text)
        self.assertIn("TELEGRAM_SESSION_STRING",text);self.assertIn("POP_CHAT_ID",text)
        self.assertIn("POP_THREAD_ID",text)

    async def test_non_group_chat_and_nonpositive_topic_are_rejected(self):
        with self.assertRaisesRegex(ScanValidationError,"POP_CHAT_ID, POP_THREAD_ID"):
            await scan_pop_history(config(pop_chat_id=300,pop_thread_id=0),owner_id=OWNER,
                start=START,end=END,client_factory=lambda unused:FakeClient(),
                peer_id_resolver=lambda entity:entity.peer_id)

    def test_environment_configuration_is_disabled_by_default_and_secrets_are_not_repr(self):
        self.assertFalse(PopHistoryScanConfig.from_env({}).enabled)
        value=config()
        rendered=repr(value)
        self.assertNotIn(value.api_hash,rendered);self.assertNotIn(value.session_string,rendered)


class ScopeAndReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_resolved_chat_is_blocked(self):
        client=FakeClient(entity_chat=-100999)
        with self.assertRaises(ScanScopeError):
            await run(client)
        self.assertTrue(client.disconnected)

    async def test_wrong_topic_is_ignored(self):
        client=FakeClient([message(1,START,message_thread_id=99,photo=object())])
        report=await run(client)
        self.assertEqual(report["total_messages_found"],0)
        self.assertEqual(report["ignored_message_counts"]["wrong_topic"],1)
        self.assertEqual(client.requested_topic,TOPIC)

    async def test_window_boundaries_are_inclusive_and_older_messages_stop_scan(self):
        rows=[message(3,END,photo=object()),message(2,START,photo=object()),
            message(1,START-timedelta(microseconds=1),photo=object())]
        with self.assertNoLogs(level="DEBUG"):
            report=await run(FakeClient(rows))
        self.assertEqual([item["message_id"] for item in report["messages"]],[3,2])
        self.assertEqual(report["ignored_message_counts"]["outside_window"],1)

    async def test_duplicate_message_is_reported_once(self):
        item=message(2,START+timedelta(hours=1),photo=object())
        report=await run(FakeClient([item,item]))
        self.assertEqual(report["total_messages_found"],1)
        self.assertEqual(report["ignored_message_counts"]["duplicate_message"],1)

    async def test_report_contains_indicators_but_no_raw_content_or_secrets(self):
        raw="I posted my weekly POP to https://example.com/private-proof"
        ambiguous="posted it"
        rows=[message(2,START+timedelta(hours=2),message=raw),
            message(1,START+timedelta(hours=1),message=ambiguous)]
        report=await run(FakeClient(rows))
        encoded=json.dumps(report)
        self.assertNotIn(raw,encoded);self.assertNotIn(ambiguous,encoded)
        self.assertNotIn(config().api_hash,encoded);self.assertNotIn(config().session_string,encoded)
        self.assertTrue(report["messages"][0]["has_link"])
        self.assertTrue(report["messages"][1]["ambiguous_evidence"])
        self.assertTrue(report["dry_run"]);self.assertTrue(report["read_only"])

    async def test_photo_is_qualified_without_downloading_media(self):
        report=await run(FakeClient([message(1,START,photo=object())]))
        row=report["messages"][0]
        self.assertEqual(row["media_type"],"photo")
        self.assertTrue(row["qualified_media"])
        self.assertEqual(row["pop_decision"],"qualified")

    async def test_forwarded_story_is_qualified_without_retaining_story_content(self):
        story_media=type("MessageMediaStory",(),{})()
        report=await run(FakeClient([message(1,START,media=story_media)]))
        row=report["messages"][0]
        self.assertEqual(row["media_type"],"forwarded_story")
        self.assertEqual(row["pop_proof_type"],"forwarded_story")
        self.assertTrue(row["qualified_media"])


if __name__ == "__main__":
    unittest.main()
