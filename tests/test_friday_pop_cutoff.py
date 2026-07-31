import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).parents[1]/"bot"))

import database as db
from pop_policy import (calculate_status, current_period, latest_completed_period,
    retention_hours, submission_timing)
from tracker import observe, pop_reminder_job


ET=ZoneInfo("America/New_York")
WEEK="2026-W31"


class PopPolicyBoundaryTests(unittest.TestCase):
    def test_wednesday_is_accepted_early_with_48_hour_retention(self):
        at=datetime(2026,7,29,12,0,tzinfo=ET)
        self.assertEqual(submission_timing(at),(WEEK,"on_time"))
        self.assertEqual(retention_hours(at),48)

    def test_thursday_boundaries_are_on_time(self):
        for at in (datetime(2026,7,30,0,0,tzinfo=ET),datetime(2026,7,30,23,59,59,tzinfo=ET)):
            with self.subTest(at=at):self.assertEqual(submission_timing(at)[1],"on_time")

    def test_friday_grace_boundaries_and_noon_cutoff(self):
        self.assertEqual(submission_timing(datetime(2026,7,31,0,0,tzinfo=ET))[1],"late")
        self.assertEqual(submission_timing(datetime(2026,7,31,11,59,59,tzinfo=ET))[1],"late")
        self.assertEqual(submission_timing(datetime(2026,7,31,12,0,tzinfo=ET))[1],"after_cutoff")

    def test_missing_begins_at_friday_noon(self):
        before=datetime(2026,7,31,11,59,59,tzinfo=ET);noon=datetime(2026,7,31,12,0,tzinfo=ET)
        self.assertEqual(calculate_status(before),"still_needed")
        self.assertEqual(calculate_status(noon),"missing")
        self.assertEqual(latest_completed_period(before).week_key,"2026-W30")
        self.assertEqual(latest_completed_period(noon).week_key,WEEK)

    def test_daylight_saving_uses_eastern_wall_clock(self):
        before_dst=datetime(2026,3,6,12,0,tzinfo=ET)
        after_dst=datetime(2026,3,13,11,59,59,tzinfo=ET)
        self.assertEqual(current_period(before_dst).grace_at.utcoffset(),timedelta(hours=-5))
        self.assertEqual(current_period(after_dst).grace_at.utcoffset(),timedelta(hours=-4))
        self.assertEqual(submission_timing(after_dst)[1],"late")


class RetentionAndReminderDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"cutoff.db"
        db.initialize_database(self.path);db.register_creator(1,"creator","Creator",self.path);db.set_status(1,"active",9,self.path)
    def tearDown(self):self.tmp.cleanup()

    def test_wednesday_evidence_persists_a_48_hour_due_time(self):
        source=datetime(2026,7,29,16,30,tzinfo=ET)
        result=db.record_pop_evidence(1,WEEK,10,-100,20,"photo","on_time",source_message_at=source.isoformat(),path=self.path)
        row=db.get_pop_submission(result["submission_id"],self.path)
        self.assertEqual(datetime.fromisoformat(row["preservation_due_at"]),source+timedelta(hours=48))
        self.assertEqual(datetime.fromisoformat(row["source_message_at"]).weekday(),2)

    def test_reminder_stage_claim_is_durable_across_restart(self):
        self.assertTrue(db.claim_pop_reminder(1,WEEK,"pop_thursday_morning",self.path))
        self.assertFalse(db.claim_pop_reminder(1,WEEK,"pop_thursday_morning",self.path))
        db.initialize_database(self.path)
        self.assertFalse(db.claim_pop_reminder(1,WEEK,"pop_thursday_morning",self.path))
        self.assertTrue(db.claim_pop_reminder(1,WEEK,"pop_thursday_evening",self.path))
        self.assertTrue(db.claim_pop_reminder(1,WEEK,"pop_friday_final",self.path))

    def test_schema_v15_upgrades_additively_and_repeatedly(self):
        with db.get_connection(self.path) as connection:
            connection.execute("DROP TABLE pop_reminder_deliveries")
            connection.execute("UPDATE schema_version SET version=15")
            before=connection.execute("SELECT display_name FROM creators WHERE telegram_id=1").fetchone()[0]
        db.initialize_database(self.path);db.initialize_database(self.path)
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0],16)
            self.assertEqual(connection.execute("SELECT display_name FROM creators WHERE telegram_id=1").fetchone()[0],before)
            self.assertIsNotNone(connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='pop_reminder_deliveries'").fetchone())


class ReminderEligibilityIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_friday_reminder_excludes_credited_excused_away_inactive_and_archived_creators(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"eligibility.db";db.initialize_database(path)
            for creator_id,label in enumerate(("Missing","Inactive","Archived","On Time","Late","Excused","Away"),1):
                db.register_creator(creator_id,label.lower().replace(" ","_"),label,path)
                db.set_status(creator_id,"inactive" if creator_id==2 else "active",9,path)
            with db.get_connection(path) as connection:
                connection.execute("UPDATE creators SET registered_at='2026-01-01T00:00:00+00:00'")
                connection.execute("UPDATE creators SET deleted_at='2026-07-01T00:00:00+00:00' WHERE telegram_id=3")
            db.record_pop_evidence(4,WEEK,104,-300,11,"photo","on_time",
                source_message_at="2026-07-30T12:00:00-04:00",path=path)
            db.record_pop_evidence(5,WEEK,105,-300,11,"photo","late",
                source_message_at="2026-07-31T07:30:00-04:00",path=path)
            excused=db.create_absence_request(6,"vacation","2026-07-30","2026-07-30",path=path)
            away=db.create_absence_request(7,"vacation","2026-07-31","2026-07-31",path=path)
            db.review_absence(excused,"approved",9,path=path);db.review_absence(away,"approved",9,path=path)
            now=datetime(2026,7,31,8,0,tzinfo=ET)
            clock=SimpleNamespace(now=lambda timezone=None:now.astimezone(timezone) if timezone else now.replace(tzinfo=None))
            bot=SimpleNamespace(send_message=AsyncMock());ctx=SimpleNamespace(bot_data={"config":config()},bot=bot)
            with patch.object(db,"DATABASE_PATH",path),patch("tracker.datetime",clock):
                await pop_reminder_job(ctx)
            bot.send_message.assert_awaited_once()
            self.assertEqual(bot.send_message.await_args.args[0],1)


def config():
    return SimpleNamespace(timezone=ET,timezone_name="America/New_York",pop_chat_id=-300,
        girls_chat_id=None,pop_thread_id=11,pop_due_weekday=3,pop_cutoff_time="23:59",
        participation_chat_id=-100,participation_topic_ids=frozenset(),girls_thread_id=None,
        repeat_window_days=7,meaningful_min_words=3,meaningful_min_characters=12,
        admin_chat_id=-400,pop_review_thread_id=20,reports_thread_id=21)


def message(at,message_id=90):
    return SimpleNamespace(text=None,caption=None,entities=(),caption_entities=(),photo=[object()],
        sticker=None,animation=None,video=None,voice=None,audio=None,document=None,story=None,
        reply_to_story=None,chat_id=-300,message_thread_id=11,message_id=message_id,date=at,
        edit_date=None,reply_text=AsyncMock())


class SubmissionHandlingTests(unittest.IsolatedAsyncioTestCase):
    async def run_observe(self,msg,created=True):
        update=SimpleNamespace(effective_message=msg,effective_user=SimpleNamespace(id=20),edited_message=None,update_id=77)
        ctx=SimpleNamespace(bot_data={"config":config()},bot=SimpleNamespace())
        with patch("tracker.db.system_state",return_value={}),patch("tracker.db.get_creator",return_value={"telegram_id":20,"status":"active","vacation_until":None}), \
             patch("tracker.db.approved_absence_on",return_value=None),patch("tracker.db.set_system_state"),patch("tracker.db.record_audit"), \
             patch("tracker.db.claim_processed_update",return_value=(True,False)),patch("tracker.db.recent_pop_evidence",return_value=[]), \
             patch("tracker.db.record_pop_evidence",return_value={"created":created,"duplicate":not created,"submission_id":1}) as record:
            await observe(update,ctx)
        return record

    async def test_wednesday_receives_one_early_confirmation(self):
        msg=message(datetime(2026,7,29,16,0,tzinfo=ET))
        record=await self.run_observe(msg,True)
        record.assert_called_once();self.assertIn("EARLY POP RECEIVED",msg.reply_text.await_args.args[0])
        duplicate=message(datetime(2026,7,29,16,0,tzinfo=ET),91)
        await self.run_observe(duplicate,False);duplicate.reply_text.assert_not_awaited()

    async def test_friday_noon_proof_does_not_write_automatic_credit(self):
        msg=message(datetime(2026,7,31,12,0,tzinfo=ET))
        record=await self.run_observe(msg,True)
        record.assert_not_called();self.assertIn("did not automatically change",msg.reply_text.await_args.args[0])


if __name__=="__main__":unittest.main()
