import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))
import database as db
from pop_policy import latest_completed_period
from tracker import missing_pop_case_job, pop_report_command, render_missing_pop_summary

ET=ZoneInfo("America/New_York");WEEK="2026-W30"

def config():
    return SimpleNamespace(timezone=ET,timezone_name="America/New_York",pop_due_weekday=3,
        pop_cutoff_time="23:59",admin_chat_id=-1001,pop_review_thread_id=77,reports_thread_id=88,
        owner_user_ids=frozenset({9}),admin_user_ids=frozenset(),lead_admin_user_ids=frozenset(),admin_permissions={})

class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"scheduler.db";db.initialize_database(self.path)
    def tearDown(self):self.tmp.cleanup()
    def creator(self,user_id,name=None,status="active",archived=False):
        db.register_creator(user_id,f"user{user_id}",name or f"Creator {user_id}",self.path);db.set_status(user_id,status,9,self.path)
        with db.get_connection(self.path) as con:
            con.execute("UPDATE creators SET registered_at=?,deleted_at=? WHERE telegram_id=?",
                ("2026-01-01T12:00:00+00:00","2026-07-20T12:00:00+00:00" if archived else None,user_id))
    def evidence(self,user_id,timing,message_id):
        stamp="2026-07-23T18:00:00-04:00" if timing=="on_time" else "2026-07-24T11:00:00-04:00"
        db.record_pop_evidence(user_id,WEEK,message_id,-200,44,"photo",timing,source_message_at=stamp,path=self.path)
    def evaluate(self):return db.evaluate_missing_pop_week(WEEK,"2026-07-25T00:05:00-04:00",path=self.path)

    def test_first_run_creates_one_genuinely_missing_case(self):
        self.creator(1,"Missing Creator");result=self.evaluate()
        self.assertEqual((result["eligible_active_creators"],result["cases_newly_created"],result["open_missing_cases"]),(1,1,1))
        self.assertEqual(db.list_missing_pop_cases(WEEK,self.path)[0]["telegram_id"],1)

    def test_on_time_and_friday_late_are_excluded(self):
        self.creator(1,"On Time");self.creator(2,"Late");self.evidence(1,"on_time",101);self.evidence(2,"late",102)
        result=self.evaluate();self.assertEqual((result["on_time"],result["late"],result["cases_newly_created"]),(1,1,0))

    def test_excused_and_approved_away_are_excluded(self):
        self.creator(1,"Excused");self.creator(2,"Away")
        excused=db.create_absence_request(1,"vacation","2026-07-23","2026-07-23",path=self.path)
        away=db.create_absence_request(2,"vacation","2026-07-23","2026-07-24",path=self.path)
        db.review_absence(excused,"approved",9,path=self.path);db.review_absence(away,"approved",9,path=self.path)
        with db.get_connection(self.path) as con:con.execute("UPDATE absence_requests SET status='cancelled' WHERE id=?",(excused,))
        result=self.evaluate();self.assertEqual((result["excused"],result["away_excluded"],result["cases_newly_created"]),(1,1,0))

    def test_inactive_archived_and_duplicate_identity_are_excluded(self):
        self.creator(1,status="inactive");self.creator(2,archived=True);self.creator(3,"Canonical")
        db.register_creator(3,"changed","Canonical Updated",self.path);result=self.evaluate()
        self.assertEqual(result["inactive_archived_excluded"],2)
        self.assertEqual([(r["telegram_id"],r["display_name"]) for r in db.list_missing_pop_cases(WEEK,self.path)],[(3,"Canonical Updated")])

    def test_manual_reconciliation_is_excluded(self):
        self.creator(1,"Reconciled")
        self.assertTrue(db.record_manual_pop_reconciliation(1,WEEK,"missing",None,"Owner reviewed",9,"manual-1",path=self.path)["saved"])
        result=self.evaluate();self.assertEqual((result["skipped_reconciliation"],result["cases_newly_created"]),(1,0))

    def test_repeated_runs_and_existing_case_do_not_duplicate(self):
        self.creator(1);db.create_missing_pop_case(1,WEEK,self.path)
        first=self.evaluate();second=self.evaluate()
        self.assertEqual((first["cases_already_existing"],second["cases_already_existing"]),(1,1))
        self.assertEqual(len(db.list_missing_pop_cases(WEEK,self.path)),1)

    def test_evidence_credited_after_case_creation_reconciles_existing_case(self):
        self.creator(1);case=db.create_missing_pop_case(1,WEEK,self.path);self.evidence(1,"late",103)
        result=self.evaluate();current=db.get_missing_pop_case(case["id"],self.path)
        self.assertEqual((result["late"],result["skipped_reconciliation"]),(1,1))
        self.assertEqual(current["status"],"resolved")

    def test_multiple_creators_return_structured_counts(self):
        for user_id in range(1,5):self.creator(user_id)
        self.evidence(1,"on_time",101);self.evidence(2,"late",102);result=self.evaluate()
        self.assertEqual((result["eligible_active_creators"],result["on_time"],result["late"],result["cases_newly_created"]),(4,1,1,2))
        self.assertEqual(result["errors"],[])

class JobAndReportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"job.db";db.initialize_database(self.path)
        db.register_creator(1,"missing","Missing Creator",self.path);db.set_status(1,"active",9,self.path)
        with db.get_connection(self.path) as con:con.execute("UPDATE creators SET registered_at='2026-01-01T12:00:00+00:00' WHERE telegram_id=1")
        self.ctx=SimpleNamespace(bot_data={"config":config()},
            bot=SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=700))))
    def tearDown(self):self.tmp.cleanup()

    async def test_post_grace_run_sends_one_summary_across_repeats(self):
        routed=AsyncMock(return_value=(True,None))
        with patch.object(db,"DATABASE_PATH",self.path),patch("tracker.send_routed",routed):
            first=await missing_pop_case_job(self.ctx,datetime(2026,7,24,12,0,tzinfo=ET))
            second=await missing_pop_case_job(self.ctx,datetime(2026,7,24,12,20,tzinfo=ET))
        self.assertEqual((first["week_key"],first["cases_newly_created"],second["cases_already_existing"]),(WEEK,1,1))
        routed.assert_awaited_once();self.assertEqual(routed.await_args.args[2],"pop_review");self.assertIn("Missing Creator",routed.await_args.args[3])
        self.ctx.bot.send_message.assert_awaited_once()
        card=db.get_missing_pop_case(db.list_missing_pop_cases(WEEK,self.path)[0]["id"],self.path)
        self.assertEqual((card["review_chat_id"],card["review_thread_id"],card["review_message_id"]),(-1001,77,700))

    async def test_delayed_restart_evaluates_latest_closed_week(self):
        routed=AsyncMock(return_value=(True,None));self.assertEqual(latest_completed_period(datetime(2026,7,27,9,tzinfo=ET)).week_key,WEEK)
        with patch.object(db,"DATABASE_PATH",self.path),patch("tracker.send_routed",routed):
            result=await missing_pop_case_job(self.ctx,datetime(2026,7,27,9,tzinfo=ET))
        self.assertEqual(result["cases_newly_created"],1);routed.assert_awaited_once()

    async def test_first_run_after_friday_noon_evaluates_current_cycle_without_strike(self):
        routed=AsyncMock(return_value=(True,None))
        with patch.object(db,"DATABASE_PATH",self.path),patch("tracker.send_routed",routed):
            result=await missing_pop_case_job(self.ctx,datetime(2026,7,31,12,5,tzinfo=ET))
        self.assertEqual(result["week_key"],"2026-W31");self.assertEqual(result["cases_newly_created"],1)
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM official_pop_strikes").fetchone()[0],0)

    async def test_all_clear_is_sent_at_most_once(self):
        with db.get_connection(self.path) as con:con.execute("UPDATE creators SET status='inactive' WHERE telegram_id=1")
        routed=AsyncMock(return_value=(True,None))
        with patch.object(db,"DATABASE_PATH",self.path),patch("tracker.send_routed",routed):
            await missing_pop_case_job(self.ctx,datetime(2026,7,24,13,tzinfo=ET));await missing_pop_case_job(self.ctx,datetime(2026,7,24,14,tzinfo=ET))
        routed.assert_awaited_once();self.assertIn("No creators require",routed.await_args.args[3])

    async def test_pop_report_lists_named_case_state(self):
        db.create_missing_pop_case(1,WEEK,self.path)
        update=SimpleNamespace(effective_user=SimpleNamespace(id=9),message=SimpleNamespace(reply_text=AsyncMock()),effective_message=SimpleNamespace(reply_text=AsyncMock()))
        fixed=SimpleNamespace(now=lambda tz=None:datetime(2026,7,24,12,0,tzinfo=ET).astimezone(tz) if tz else datetime(2026,7,24,12,0))
        with patch.object(db,"DATABASE_PATH",self.path),patch("tracker.require_permission",AsyncMock(return_value=True)),patch("tracker.datetime",fixed):
            await pop_report_command(update,SimpleNamespace(bot_data={"config":config()}))
        text=update.message.reply_text.await_args.args[0];self.assertIn("Pending Review: 1",text);self.assertIn("Missing Creator: Pending Review",text)

    def test_summary_contract_has_totals_names_and_no_auto_strike(self):
        result={"week_key":WEEK,"cases_newly_created":1,"cases_already_existing":2}
        text=render_missing_pop_summary(result,[{"status":"pending","display_name":"Creator One","username":"one"}])
        self.assertIn("Missing POP Cases: 1",text);self.assertIn("Creator One",text);self.assertIn("No official strikes",text)
        self.assertIn("Thursday at 11:59 p.m. ET",text);self.assertIn("Friday at 11:59 a.m. ET",text)

if __name__=="__main__":unittest.main()
