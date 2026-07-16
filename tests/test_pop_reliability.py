import sys
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))

import database as db
from pop_reliability import classify_pop_proof, message_has_url
from tracker import observe, pop_preservation_job


ET = ZoneInfo("America/New_York")
THURSDAY = datetime(2026, 7, 16, 16, 0, tzinfo=ET)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return THURSDAY.astimezone(tz) if tz else THURSDAY.replace(tzinfo=None)


def message(**changes):
    values = dict(
        text=None, caption=None, entities=(), caption_entities=(), photo=None,
        sticker=None, animation=None, video=None, voice=None, audio=None,
        document=None, chat_id=-300, message_thread_id=11, message_id=90,
        date=THURSDAY, edit_date=None, reply_text=AsyncMock(),
    )
    values.update(changes)
    return SimpleNamespace(**values)


def config(**changes):
    values = dict(
        timezone=ET, timezone_name="America/New_York", pop_chat_id=-300,
        girls_chat_id=None, pop_thread_id=11, pop_due_weekday=3,
        participation_chat_id=-100, participation_topic_ids=frozenset(),
        girls_thread_id=None, repeat_window_days=7, meaningful_min_words=3,
        meaningful_min_characters=12, admin_chat_id=-400,
        pop_review_thread_id=20, reports_thread_id=21,
    )
    values.update(changes)
    return SimpleNamespace(**values)


class ProofClassificationTests(unittest.TestCase):
    def test_photo_without_caption_qualifies(self):
        self.assertEqual(classify_pop_proof(message(photo=[object()])), "photo")

    def test_photo_with_caption_qualifies(self):
        self.assertEqual(classify_pop_proof(message(photo=[object()], caption="weekly screenshot")), "photo")

    def test_plain_and_described_urls_qualify(self):
        self.assertEqual(classify_pop_proof(message(text="https://example.com/proof")), "link")
        self.assertEqual(classify_pop_proof(message(text="Here is my story https://example.com/proof today")), "link")

    def test_telegram_story_channel_and_message_links_qualify(self):
        for value in ("https://t.me/example/s/10", "https://t.me/example/10", "t.me/c/123/456"):
            with self.subTest(value=value):
                self.assertTrue(message_has_url(message(text=value)))
                self.assertEqual(classify_pop_proof(message(text=value)), "link")

    def test_url_entities_qualify_without_extracting_or_storing_url(self):
        entity=SimpleNamespace(type="url",url=None)
        hidden=SimpleNamespace(type="text_link",url="https://example.com/private")
        self.assertTrue(message_has_url(message(text="proof",entities=[entity])))
        self.assertTrue(message_has_url(message(text="proof",entities=[hidden])))

    def test_text_only_description_is_not_proof(self):
        self.assertIsNone(classify_pop_proof(message(text="I posted my weekly story today")))

    def test_existing_media_with_caption_qualifies(self):
        for kind in ("animation","video","voice","audio"):
            with self.subTest(kind=kind):
                self.assertEqual(classify_pop_proof(message(**{kind:object(),"caption":"weekly evidence"})),kind)


class ObserverReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def run_observe(self,msg,*,creator=None,edited=False,submit=True):
        creator = creator if creator is not None else {"telegram_id":20,"status":"active","vacation_until":None}
        update=SimpleNamespace(effective_message=msg,effective_user=SimpleNamespace(id=20),
            edited_message=msg if edited else None)
        ctx=SimpleNamespace(bot_data={"config":config()})
        with patch("tracker.datetime",FixedDateTime),patch("tracker.db.system_state",return_value={}), \
             patch("tracker.db.get_creator",return_value=creator),patch("tracker.db.approved_absence_on",return_value=None), \
             patch("tracker.db.set_system_state"),patch("tracker.db.record_audit"), \
             patch("tracker.db.submit_pop",return_value=submit) as submit_pop:
            await observe(update,ctx)
        return submit_pop

    async def test_correct_photo_and_link_qualify(self):
        for msg in (message(photo=[object()]),message(text="Proof: https://example.com/item")):
            with self.subTest(text=msg.text):
                submit=await self.run_observe(msg)
                submit.assert_called_once()

    async def test_wrong_chat_and_thread_do_not_qualify(self):
        for msg in (message(photo=[object()],chat_id=-999),message(photo=[object()],message_thread_id=99)):
            submit=await self.run_observe(msg)
            submit.assert_not_called()

    async def test_inactive_buyer_and_unregistered_users_do_not_qualify(self):
        for creator in ({"telegram_id":20,"status":"inactive","vacation_until":None},False):
            submit=await self.run_observe(message(photo=[object()]),creator=creator)
            submit.assert_not_called()

    async def test_inherited_staff_creator_qualifies_by_active_profile(self):
        submit=await self.run_observe(message(photo=[object()]),
            creator={"telegram_id":20,"status":"active","vacation_until":None})
        submit.assert_called_once()

    async def test_edited_nonqualifying_message_can_become_qualifying(self):
        first=await self.run_observe(message(text="description only"))
        first.assert_not_called()
        edited=await self.run_observe(message(text="description https://t.me/example/1",edit_date=THURSDAY),edited=True)
        edited.assert_called_once()

    async def test_edited_qualifying_message_remains_weekly_deduplicated(self):
        submit=await self.run_observe(message(photo=[object()],edit_date=THURSDAY),edited=True,submit=False)
        submit.assert_called_once()

    async def test_edited_wrong_topic_is_ignored(self):
        submit=await self.run_observe(message(text="https://t.me/example/1",message_thread_id=99,edit_date=THURSDAY),edited=True)
        submit.assert_not_called()


class PreservationDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"pop.db"
        db.initialize_database(self.path);db.register_creator(20,"creator","Creator",self.path);db.set_status(20,"active",1,self.path)
        self.submitted="2026-07-16T12:00:00-04:00"
        self.assertTrue(db.submit_pop(20,"2026-W29",90,-300,11,"photo",self.path,submitted_at=self.submitted))
        self.submission=db.pop_report("2026-W29",self.path)[0]["id"]

    def tearDown(self):self.tmp.cleanup()

    def test_preservation_check_is_restart_safe_and_idempotent(self):
        self.assertEqual(db.pop_preservation_due(datetime(2026,7,17,11,59,tzinfo=ET),self.path),[])
        due=db.pop_preservation_due(datetime(2026,7,17,12,1,tzinfo=ET),self.path)
        self.assertEqual([row["id"] for row in due],[self.submission])
        self.assertTrue(db.mark_pop_preservation_unavailable(self.submission,"2026-07-17T12:01:00-04:00",self.path))
        self.assertFalse(db.mark_pop_preservation_unavailable(self.submission,"2026-07-17T12:02:00-04:00",self.path))
        self.assertTrue(db.claim_pop_preservation_alert(self.submission,self.path))
        self.assertFalse(db.claim_pop_preservation_alert(self.submission,self.path))
        self.assertEqual(db.get_pop_submission(self.submission,self.path)["preservation_status"],"unable_to_verify")
        counts=db.needs_attention_counts("2026-W29",self.path,THURSDAY)
        self.assertEqual(counts["preservation_reviews"],1)

    def test_new_proof_status_is_complete_with_preservation_pending(self):
        self.assertEqual(db.creator_current_pop_status(20,THURSDAY,path=self.path),
            "complete_preservation_pending")

    def test_successful_preservation_updates_creator_status(self):
        self.assertTrue(db.set_pop_preservation_status(self.submission,"preserved",1,"Checked",self.path))
        status=db.creator_current_pop_status(20,THURSDAY,path=self.path)
        self.assertEqual(status,"complete_preserved")

    def test_confirmed_early_removal_has_one_alert_claim(self):
        self.assertTrue(db.set_pop_preservation_status(self.submission,"early_removed",1,"Directly confirmed",self.path))
        self.assertTrue(db.claim_pop_preservation_alert(self.submission,self.path))
        self.assertFalse(db.claim_pop_preservation_alert(self.submission,self.path))
        self.assertEqual(db.creator_current_pop_status(20,THURSDAY,path=self.path),"needs_review")

    def test_version_ten_records_migrate_without_false_verification_claim(self):
        legacy=Path(self.tmp.name)/"version10.db";connection=sqlite3.connect(legacy)
        connection.executescript("""CREATE TABLE schema_version(version INTEGER NOT NULL);
          INSERT INTO schema_version VALUES(10);
          CREATE TABLE pop_submissions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL,
            week_key TEXT NOT NULL,message_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,
            thread_id INTEGER,proof_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
              CHECK(status IN ('pending','approved','rejected','resubmission_requested','excused')),
            submitted_at TEXT NOT NULL,reviewed_at TEXT,reviewed_by INTEGER,review_note TEXT,
            deleted_at TEXT,deleted_by INTEGER,deletion_reason TEXT,
            UNIQUE(telegram_id,week_key));
          INSERT INTO pop_submissions
            (telegram_id,week_key,message_id,chat_id,thread_id,proof_type,status,submitted_at)
            VALUES(20,'2026-W28',1,-300,11,'photo','approved','2026-07-09T12:00:00-04:00');""")
        connection.close();db.initialize_database(legacy)
        with db.get_connection(legacy) as migrated:
            row=migrated.execute("SELECT preservation_status FROM pop_submissions").fetchone()
            self.assertEqual(row["preservation_status"],"legacy_record")
            self.assertEqual(migrated.execute("SELECT version FROM schema_version").fetchone()[0],11)


class PreservationJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_inconclusive_check_routes_review_without_accusation(self):
        row={"id":7,"telegram_id":20,"display_name":"Creator","week_key":"2026-W29",
            "submitted_at":"2026-07-16T12:00:00-04:00"}
        ctx=SimpleNamespace(bot_data={"config":config()},bot=SimpleNamespace())
        with patch("tracker.db.pop_preservation_due",return_value=[row]), \
             patch("tracker.db.mark_pop_preservation_unavailable",return_value=True), \
             patch("tracker.db.claim_pop_preservation_alert",return_value=True), \
             patch("tracker.send_routed",new_callable=AsyncMock) as routed:
            await pop_preservation_job(ctx)
        body=routed.call_args.args[3]
        self.assertIn("inconclusive",body.casefold())
        self.assertIn("not evidence of early removal",body.casefold())


if __name__ == "__main__":
    unittest.main()
