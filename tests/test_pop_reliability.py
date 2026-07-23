import sys
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))

import database as db
from pop_policy import submission_timing
from pop_reliability import classify_pop_candidate, classify_pop_proof, message_has_url
from tracker import observe, pop_preservation_job, startup_recovery_job


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
        document=None, story=None, reply_to_story=None, chat_id=-300, message_thread_id=11, message_id=90,
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

    def test_forwarded_story_qualifies_but_a_story_reply_does_not(self):
        self.assertEqual(classify_pop_proof(message(story=object())), "forwarded_story")
        self.assertIsNone(classify_pop_proof(message(reply_to_story=object())))

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
        decision=classify_pop_candidate(message(text="I posted the weekly flyer to my Instagram story"))
        self.assertEqual(decision.proof_type,"text");self.assertFalse(decision.needs_review)

    def test_ambiguous_text_routes_to_review_and_noise_is_rejected(self):
        self.assertTrue(classify_pop_candidate(message(text="posted it")).needs_review)
        for value in ("hello everyone","💕✨","looks great"):
            with self.subTest(value=value):
                decision=classify_pop_candidate(message(text=value))
                self.assertIsNone(decision.proof_type);self.assertFalse(decision.needs_review)

    def test_image_document_qualifies(self):
        document=SimpleNamespace(mime_type="image/png",file_name="proof.png")
        self.assertEqual(classify_pop_proof(message(document=document)),"image_document")

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
             patch("tracker.db.claim_processed_update",return_value=(True,False)), \
             patch("tracker.db.recent_pop_evidence",return_value=[]), \
             patch("tracker.db.record_pop_evidence",return_value={"created":submit,"duplicate":not submit,"submission_id":1}) as submit_pop:
            await observe(update,ctx)
        return submit_pop

    async def test_correct_photo_and_link_qualify(self):
        for msg in (message(photo=[object()]), message(story=object()),
                    message(text="Proof: https://example.com/item")):
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
            "on_time")

    def test_successful_preservation_updates_creator_status(self):
        self.assertTrue(db.set_pop_preservation_status(self.submission,"preserved",1,"Checked",self.path))
        status=db.creator_current_pop_status(20,THURSDAY,path=self.path)
        self.assertEqual(status,"on_time")

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
            self.assertEqual(migrated.execute("SELECT version FROM schema_version").fetchone()[0],14)


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


class TimingAndRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"recovery.db"
        db.initialize_database(self.path);db.register_creator(20,"creator","Creator",self.path);db.set_status(20,"active",1,self.path)

    def tearDown(self):self.tmp.cleanup()

    def test_thursday_boundary_and_friday_are_classified_from_source_time(self):
        last=THURSDAY.replace(hour=23,minute=59,second=59)
        friday=last+timedelta(seconds=1)
        self.assertEqual(submission_timing(last)[1],"on_time")
        self.assertEqual(submission_timing(friday)[1],"late")

    def test_replayed_evidence_is_idempotent_and_earliest_source_wins(self):
        later=THURSDAY.replace(hour=20).isoformat();earlier=THURSDAY.replace(hour=18).isoformat()
        first=db.record_pop_evidence(20,"2026-W29",2,-300,11,"photo","on_time",
            source_message_at=later,observed_at=later,update_id=102,path=self.path)
        replay=db.record_pop_evidence(20,"2026-W29",2,-300,11,"photo","on_time",
            source_message_at=later,observed_at=later,update_id=102,path=self.path)
        supplement=db.record_pop_evidence(20,"2026-W29",1,-300,11,"link","on_time",
            source_message_at=earlier,observed_at=later,update_id=101,path=self.path)
        self.assertTrue(first["created"]);self.assertTrue(replay["duplicate"]);self.assertFalse(supplement["created"])
        row=db.get_pop_submission(first["submission_id"],self.path)
        self.assertEqual(row["message_id"],1);self.assertEqual(row["source_message_at"],earlier)
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM pop_submissions").fetchone()[0],1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM pop_evidence").fetchone()[0],2)

    def test_reposted_forwarded_story_keeps_one_weekly_credit(self):
        at=THURSDAY.replace(day=17,hour=9).isoformat()
        first=db.record_pop_evidence(20,"2026-W29",20,-300,11,"forwarded_story","late",
            source_message_at=at,observed_at=at,path=self.path)
        repost=db.record_pop_evidence(20,"2026-W29",21,-300,11,"forwarded_story","late",
            source_message_at=(THURSDAY.replace(day=17,hour=10)).isoformat(),observed_at=at,path=self.path)
        self.assertTrue(first["created"]);self.assertFalse(repost["created"])
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM pop_submissions").fetchone()[0],1)

    def test_split_evidence_window_never_crosses_creator_identity(self):
        at=THURSDAY.isoformat()
        db.record_pop_evidence(20,"2026-W29",2,-300,11,"photo","on_time",
            source_message_at=at,observed_at=at,path=self.path)
        db.register_creator(21,"other","Other Creator",self.path);db.set_status(21,"active",1,self.path)
        self.assertEqual(len(db.recent_pop_evidence(20,-300,11,at,path=self.path)),1)
        self.assertEqual(db.recent_pop_evidence(21,-300,11,at,path=self.path),[])
        self.assertEqual(db.recent_pop_evidence(20,-300,99,at,path=self.path),[])

    def test_split_image_and_ambiguous_text_become_one_qualified_record(self):
        text_time=THURSDAY.replace(hour=19,minute=0).isoformat()
        image_time=THURSDAY.replace(hour=19,minute=2).isoformat()
        first=db.record_pop_evidence(20,"2026-W29",1,-300,11,"ambiguous_text","on_time",
            source_message_at=text_time,observed_at=text_time,needs_review_reason="ambiguous_text",path=self.path)
        db.record_pop_evidence(20,"2026-W29",2,-300,11,"photo","on_time",
            source_message_at=image_time,observed_at=image_time,relationship="supporting",path=self.path)
        row=db.get_pop_submission(first["submission_id"],self.path)
        self.assertEqual(row["proof_type"],"combined");self.assertIsNone(row["needs_review_reason"])
        self.assertEqual(row["source_message_at"],text_time)

    def test_away_excuse_remains_effective_with_voluntary_proof(self):
        request=db.create_absence_request(20,"vacation","2026-07-16","2026-07-16",path=self.path)
        db.review_absence(request,"approved",1,path=self.path)
        db.submit_pop(20,"2026-W29",1,-300,11,"photo",self.path,submitted_at=THURSDAY.isoformat())
        row=db.pop_status_report(THURSDAY,path=self.path)[0]
        self.assertEqual(row["effective_status"],"excused")

    def test_recovery_run_counts_replayed_pop_once_and_reports_confidence(self):
        db.set_system_state("runtime:last_heartbeat",(THURSDAY-timedelta(minutes=10)).isoformat(),self.path)
        run_id=db.begin_recovery_run(THURSDAY.isoformat(),catchup_seconds=1,path=self.path)
        first,recovered=db.claim_processed_update(500,"message",(THURSDAY-timedelta(minutes=5)).isoformat(),self.path)
        duplicate,_=db.claim_processed_update(500,"message",(THURSDAY-timedelta(minutes=5)).isoformat(),self.path)
        self.assertTrue(first);self.assertTrue(recovered);self.assertFalse(duplicate)
        complete=db.finalize_recovery_run(run_id,(THURSDAY+timedelta(seconds=2)).isoformat(),self.path)
        self.assertEqual(complete["updates_recovered"],1);self.assertEqual(complete["confidence"],"complete")

    def test_unknown_recovery_does_not_claim_completeness(self):
        run_id=db.begin_recovery_run(THURSDAY.isoformat(),catchup_seconds=1,path=self.path)
        complete=db.finalize_recovery_run(run_id,(THURSDAY+timedelta(seconds=2)).isoformat(),self.path)
        self.assertEqual(complete["confidence"],"unknown");self.assertTrue(complete["unresolved_gap"])


class StartupRecoveryJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_summary_is_private_and_claimed_once(self):
        run={"previous_heartbeat_at":"2026-07-17T00:08:00-04:00","started_at":"2026-07-17T00:21:00-04:00",
            "completed_at":"2026-07-17T00:23:00-04:00","updates_recovered":17,"pop_recovered":3,
            "participation_recovered":11,"away_recovered":1,"pop_on_time":3,"pop_late":0,
            "pop_needs_review":0,"confidence":"complete","unresolved_gap":None}
        cfg=config(owner_user_ids=frozenset({1,2}));bot=SimpleNamespace(send_message=AsyncMock())
        ctx=SimpleNamespace(bot_data={"config":cfg,"recovery_run_id":9},bot=bot)
        with patch("tracker.db.finalize_recovery_run",return_value=run),patch("tracker.db.set_system_state"), \
             patch("tracker.db.claim_recovery_summary",return_value=True),patch("tracker.db.claim_owner_summary",return_value=True):
            await startup_recovery_job(ctx)
        self.assertEqual(bot.send_message.await_count,2)
        self.assertIn("Recovery confidence: Complete",bot.send_message.await_args_list[0].args[1])


class PollingConfigurationTests(unittest.TestCase):
    def test_startup_preserves_pending_updates_and_has_no_second_polling_probe(self):
        source=(Path(__file__).parents[1]/"bot"/"main.py").read_text(encoding="utf-8")
        tracker=(Path(__file__).parents[1]/"bot"/"tracker.py").read_text(encoding="utf-8")
        self.assertIn("drop_pending_updates=False",source)
        self.assertNotIn("drop_pending_updates=True",source)
        self.assertIn('"edited_message"',source)
        self.assertNotIn("get_updates(",tracker)


if __name__ == "__main__":
    unittest.main()
