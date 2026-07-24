import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).parents[1]/"bot"))

import database as db
from pop_policy import format_lateness, lateness_minutes, posted_time
from pop_reliability import classify_pop_candidate
from tracker import observe
from navigation import callback


ET=ZoneInfo("America/New_York")
WEEK="2026-W29"
THURSDAY=datetime(2026,7,16,20,0,tzinfo=ET)


def proof_message(**changes):
    values=dict(text=None,caption=None,entities=(),caption_entities=(),photo=None,sticker=None,
        animation=None,video=None,voice=None,audio=None,document=None,chat_id=-300,
        message_thread_id=11,message_id=90,date=THURSDAY,edit_date=None,reply_text=AsyncMock())
    values.update(changes);return SimpleNamespace(**values)


def cfg(**changes):
    values=dict(timezone=ET,timezone_name="America/New_York",pop_chat_id=-300,girls_chat_id=None,
        pop_thread_id=11,pop_due_weekday=3,pop_cutoff_time="23:59",participation_chat_id=-100,
        participation_topic_ids=frozenset(),girls_thread_id=None,repeat_window_days=7,
        meaningful_min_words=3,meaningful_min_characters=12,admin_chat_id=-400,
        pop_review_thread_id=20,reports_thread_id=21)
    values.update(changes);return SimpleNamespace(**values)


class LatePolicyTests(unittest.TestCase):
    def test_requested_clock_lateness_examples(self):
        fifteen=datetime(2026,7,17,0,15,tzinfo=ET);one_thirty_two=datetime(2026,7,17,1,32,tzinfo=ET)
        self.assertEqual(lateness_minutes(fifteen),16)
        self.assertEqual(format_lateness(fifteen),"16 minutes")
        self.assertEqual(lateness_minutes(one_thirty_two),93)
        self.assertEqual(format_lateness(one_thirty_two),"1 hour 33 minutes")
        self.assertEqual(posted_time(one_thirty_two),"Friday at 1:32 AM ET")

    def test_reconciliation_weeks_are_generated_and_only_include_completed_deadlines(self):
        friday=datetime(2026,7,17,12,0,tzinfo=ET);thursday=datetime(2026,7,16,12,0,tzinfo=ET)
        self.assertEqual(db.recent_pop_week_keys(friday,count=2),["2026-W29","2026-W28"])
        self.assertEqual(db.recent_pop_week_keys(thursday,count=1),["2026-W28"])

    def test_real_proof_formats_remain_qualified(self):
        image=SimpleNamespace(mime_type="image/png",file_name="flyer.png")
        examples=(
            proof_message(photo=[object()]),
            proof_message(photo=[object()],forward_origin=object()),
            proof_message(document=image),
            proof_message(text="t.me/example/123"),
            proof_message(photo=[object()],caption="Story: https://t.me/example/123"),
        )
        for item in examples:
            with self.subTest(item=item):self.assertIsNotNone(classify_pop_candidate(item).proof_type)


class LateDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"late.db"
        db.initialize_database(self.path);db.register_creator(20,"creator","Creator",self.path);db.set_status(20,"active",1,self.path)

    def tearDown(self):self.tmp.cleanup()

    def record(self,when,message_id=1):
        return db.record_pop_evidence(20,WEEK,message_id,-300,11,"photo","late",
            source_message_at=when.isoformat(),observed_at=when.isoformat(),path=self.path)

    def test_late_submission_is_never_missing_and_earliest_evidence_wins(self):
        later=datetime(2026,7,17,1,32,tzinfo=ET);earlier=datetime(2026,7,17,0,15,tzinfo=ET)
        first=self.record(later,2);self.record(earlier,1)
        row=db.pop_status_report_for_week(WEEK,path=self.path)[0]
        self.assertEqual(row["effective_status"],"late");self.assertEqual(row["late_by"],"16 minutes")
        stored=db.get_pop_submission(first["submission_id"],self.path)
        self.assertEqual(stored["message_id"],1);self.assertEqual(stored["source_message_at"],earlier.isoformat())

    def test_late_alert_claim_is_once_per_creator_week(self):
        result=self.record(datetime(2026,7,17,1,32,tzinfo=ET))
        self.assertIsNotNone(db.claim_late_pop_alert(result["submission_id"],self.path))
        self.assertIsNone(db.claim_late_pop_alert(result["submission_id"],self.path))
        self.record(datetime(2026,7,17,2,0,tzinfo=ET),2)
        self.assertIsNone(db.claim_late_pop_alert(result["submission_id"],self.path))

    def test_approved_away_notice_remains_excused_even_with_late_evidence(self):
        request=db.create_absence_request(20,"vacation","2026-07-16","2026-07-16",path=self.path)
        db.review_absence(request,"approved",1,path=self.path)
        result=self.record(datetime(2026,7,17,0,15,tzinfo=ET))
        row=db.pop_status_report_for_week(WEEK,path=self.path)[0]
        self.assertEqual(row["effective_status"],"excused")
        self.assertIsNotNone(db.claim_late_pop_alert(result["submission_id"],self.path))
        self.assertEqual(db.pop_status_report_for_week(WEEK,path=self.path)[0]["effective_status"],"excused")


class ManualReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"manual.db"
        db.initialize_database(self.path);db.register_creator(20,"creator","Creator",self.path);db.set_status(20,"active",1,self.path)

    def tearDown(self):self.tmp.cleanup()

    def test_schema_thirteen_is_additive_and_does_not_store_lateness_duration(self):
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0],14)
            tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            submission_columns={row[1] for row in connection.execute("PRAGMA table_info(pop_submissions)")}
            manual_columns={row[1] for row in connection.execute("PRAGMA table_info(pop_manual_reconciliations)")}
        self.assertIn("pop_manual_reconciliations",tables);self.assertIn("late_alerted_at",submission_columns)
        self.assertFalse({"lateness","late_by","late_minutes"}&submission_columns)
        self.assertTrue({"status","source_message_at","source_reference","request_key"}.issubset(manual_columns))

    def save(self,status,source=None,key="request-1",overwrite=False,reference=None):
        return db.record_manual_pop_reconciliation(20,WEEK,status,source,reference,1,key,
            allow_reliable_overwrite=overwrite,path=self.path)

    def test_manual_late_is_audited_without_inventing_telegram_evidence(self):
        source=datetime(2026,7,17,1,32,tzinfo=ET).isoformat()
        result=self.save("late",source,reference="visible Telegram post")
        self.assertTrue(result["saved"])
        row=db.pop_status_report_for_week(WEEK,path=self.path)[0]
        self.assertEqual(row["effective_status"],"late");self.assertEqual(row["late_by"],"1 hour 33 minutes")
        self.assertIsNone(row["id"]);self.assertIsNone(row["message_id"])
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM pop_submissions").fetchone()[0],0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM pop_evidence").fetchone()[0],0)
            audit=connection.execute("SELECT * FROM audit_events WHERE action='pop_historical_reconciled'").fetchone()
            self.assertEqual(audit["reason"],"Manual historical reconciliation after pre-recovery outage")

    def test_request_key_is_idempotent(self):
        first=self.save("missing");duplicate=self.save("missing")
        self.assertTrue(first["saved"]);self.assertTrue(duplicate["duplicate"])
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM pop_manual_reconciliations").fetchone()[0],1)

    def test_reliable_evidence_requires_second_confirmation_and_is_not_rewritten(self):
        source=THURSDAY.isoformat()
        submission=db.record_pop_evidence(20,WEEK,1,-300,11,"photo","on_time",
            source_message_at=source,observed_at=source,path=self.path)
        blocked=self.save("missing",key="overwrite")
        self.assertTrue(blocked["requires_second_confirmation"])
        saved=self.save("missing",key="overwrite",overwrite=True)
        self.assertTrue(saved["saved"])
        original=db.get_pop_submission(submission["submission_id"],self.path)
        self.assertEqual(original["timing_status"],"on_time");self.assertEqual(original["message_id"],1)
        self.assertEqual(db.pop_status_report_for_week(WEEK,path=self.path)[0]["effective_status"],"missing")

    def test_qualifying_late_evidence_cannot_also_display_as_missing(self):
        source=datetime(2026,7,17,1,32,tzinfo=ET).isoformat()
        submission=db.record_pop_evidence(20,WEEK,1,-300,11,"photo","late",
            source_message_at=source,observed_at=source,path=self.path)
        saved=self.save("missing",key="late-overwrite",overwrite=True)
        self.assertTrue(saved["saved"])
        self.assertEqual(db.get_pop_submission(submission["submission_id"],self.path)["timing_status"],"late")
        self.assertEqual(db.pop_status_report_for_week(WEEK,path=self.path)[0]["effective_status"],"late")

    def test_manual_status_must_match_original_timestamp(self):
        friday=datetime(2026,7,17,0,15,tzinfo=ET).isoformat()
        result=self.save("on_time",friday)
        self.assertEqual(result["error"],"timestamp_status_mismatch")


class LateAlertDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_valid_late_proof_routes_one_informational_alert(self):
        source=datetime(2026,7,17,1,32,tzinfo=ET);msg=proof_message(photo=[object()],date=source)
        update=SimpleNamespace(effective_message=msg,effective_user=SimpleNamespace(id=20),edited_message=None,update_id=77)
        context=SimpleNamespace(bot_data={"config":cfg()},bot=SimpleNamespace())
        late={"id":9,"telegram_id":20,"display_name":"Creator","week_key":WEEK,
            "source_message_at":source.isoformat()}
        with patch("tracker.db.system_state",return_value={}),patch("tracker.db.get_creator",return_value={"telegram_id":20,"status":"active","vacation_until":None}),\
             patch("tracker.db.approved_absence_on",return_value=None),patch("tracker.db.set_system_state"),\
             patch("tracker.db.record_audit"),patch("tracker.db.claim_processed_update",return_value=(True,False)),\
             patch("tracker.db.recent_pop_evidence",return_value=[]),\
             patch("tracker.db.record_pop_evidence",return_value={"created":True,"duplicate":False,"submission_id":9}),\
             patch("tracker.db.claim_late_pop_alert",return_value=late),patch("tracker.send_routed",new_callable=AsyncMock) as routed:
            await observe(update,context)
        body=routed.await_args.args[3]
        self.assertIn("POP Submitted During Grace Period",body)
        self.assertIn("Creator: Creator",body)
        self.assertIn("Submitted: Friday at 1:32 AM ET",body)
        self.assertIn("Week: 2026-W29",body)
        self.assertIn("Delay: 1 hour 33 minutes",body)
        self.assertIn("Status: Accepted",body)
        self.assertIn("Friday grace period",body)
        self.assertIn("due Thursday at 11:59 PM Eastern",body)
        self.assertIn("through Friday at 11:59 PM Eastern",body)
        self.assertIn("remain available for at least 24 hours from the original posting time",body)
        self.assertIn("None required",body)
        self.assertIn("No warning or strike was created automatically",body)


class OwnerReconciliationAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    def config(self):
        return SimpleNamespace(owner_user_ids=frozenset({1}),lead_admin_user_ids=frozenset(),
            admin_user_ids=frozenset({2}),admin_permissions={},timezone=ET,timezone_name="America/New_York",
            pop_due_weekday=3,pop_cutoff_time="23:59")

    async def screen(self,action,user_id,user_data=None):
        query=SimpleNamespace(data=f"op:n:{action}",answer=AsyncMock(),edit_message_text=AsyncMock(),message=SimpleNamespace())
        update=SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=user_id),effective_chat=None)
        data={"menu_nonce":"n"};data.update(user_data or {})
        context=SimpleNamespace(user_data=data,bot_data={"config":self.config()})
        await callback(update,context)
        return query.edit_message_text.await_args,context

    async def test_regular_admin_cannot_open_reconciliation_mutations(self):
        result,_=await self.screen("pop_reconcile_weeks",2)
        self.assertIn("Owner-only",result.args[0])

    async def test_reliable_evidence_requires_two_owner_confirmations(self):
        draft={"telegram_id":20,"week_key":WEEK,"status":"missing","request_key":"key"}
        context={"creator":{"display_name":"Creator"},"submission":{"id":9},"manual":None,
            "excused":False,"reliable_submission":True}
        with patch("navigation.db.pop_reconciliation_context",return_value=context),\
             patch("navigation.db.record_manual_pop_reconciliation") as record:
            first,_=await self.screen("pop_reconcile_confirm",1,{"pop_reconciliation_draft":draft})
        self.assertIn("Second Confirmation Required",first.args[0]);record.assert_not_called()
        with patch("navigation.db.pop_reconciliation_context",return_value=context),\
             patch("navigation.db.record_manual_pop_reconciliation",return_value={"saved":True}) as record:
            saved,_=await self.screen("pop_reconcile_confirm_overwrite",1,{"pop_reconciliation_draft":draft})
        self.assertIn("saved and audited",saved.args[0])
        self.assertTrue(record.call_args.kwargs["allow_reliable_overwrite"])

    async def test_guessed_second_confirmation_cannot_skip_the_preview(self):
        draft={"telegram_id":20,"week_key":WEEK,"status":"missing","request_key":"key"}
        with patch("navigation.db.record_manual_pop_reconciliation") as record:
            result,_=await self.screen("pop_reconcile_confirm_overwrite",1,{"pop_reconciliation_draft":draft})
        self.assertIn("first confirmation was not completed",result.args[0]);record.assert_not_called()


if __name__=="__main__":unittest.main()
