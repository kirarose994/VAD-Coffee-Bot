import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).parents[1]/"bot"))
import database as db
import missing_pop_workflow as workflow

WEEK="2026-W30";ET=ZoneInfo("America/New_York")

def cfg(**changes):
    values=dict(timezone=ET,timezone_name="America/New_York",admin_chat_id=-1001,
        pop_review_thread_id=77,reports_thread_id=88,owner_user_ids=frozenset({9}),
        admin_user_ids=frozenset({10}),lead_admin_user_ids=frozenset(),
        admin_permissions={10:frozenset({"review_pop"})})
    values.update(changes);return SimpleNamespace(**values)

def bot(message_id=500):
    return SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=message_id)),edit_message_text=AsyncMock())

def update(data,user_id=9,name="Admin"):
    query=SimpleNamespace(data=data,answer=AsyncMock(),edit_message_text=AsyncMock(),message=SimpleNamespace())
    return SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=user_id,full_name=name),effective_message=SimpleNamespace(reply_text=AsyncMock()))

class MissingPopWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"workflow.db";db.initialize_database(self.path)
        db.register_creator(1,"creator","Creator Name",self.path);db.set_status(1,"active",9,self.path)
        with db.get_connection(self.path) as con:con.execute("UPDATE creators SET registered_at='2026-01-01T00:00:00+00:00' WHERE telegram_id=1")
        self.case=db.create_missing_pop_case(1,WEEK,self.path);self.bot=bot();self.ctx=SimpleNamespace(bot=self.bot,bot_data={"config":cfg()},user_data={})
        self.path_patch=patch.object(db,"DATABASE_PATH",self.path);self.path_patch.start()
    def tearDown(self):self.path_patch.stop();self.tmp.cleanup()
    def current(self):return db.get_missing_pop_case(self.case["id"],self.path)
    def counts(self):
        with db.get_connection(self.path) as con:return (con.execute("SELECT COUNT(*) FROM official_pop_strikes").fetchone()[0],con.execute("SELECT COUNT(*) FROM creator_warnings").fetchone()[0])

    async def test_one_card_is_created_persisted_and_not_duplicated(self):
        first=await workflow.ensure_missing_pop_case_cards(self.bot,cfg(),db.list_missing_pop_cases(WEEK,self.path))
        second=await workflow.ensure_missing_pop_case_cards(self.bot,cfg(),db.list_missing_pop_cases(WEEK,self.path))
        self.assertEqual((first["cards_created"],second["cards_created"]),(1,0));self.assertEqual(self.bot.send_message.await_count,1)
        row=self.current();self.assertEqual((row["review_chat_id"],row["review_thread_id"],row["review_message_id"]),(-1001,77,500))

    async def test_unauthorized_malformed_and_identity_mismatch_are_rejected(self):
        for data,user_id in ((workflow.case_callback(dict(self.current()),"p"),99),("mpop:bad",9),(f"mpop:{self.case['id']}:999:{WEEK}:p",9)):
            item=update(data,user_id);await workflow.missing_pop_case_callback(item,self.ctx)
            self.assertTrue(item.callback_query.answer.await_args.kwargs.get("show_alert"));self.assertEqual(self.current()["reviewed_by"],None)

    async def test_issue_opens_confirmation_and_cancel_changes_nothing(self):
        item=update(workflow.case_callback(dict(self.current()),"s"));await workflow.missing_pop_case_callback(item,self.ctx)
        self.assertEqual(self.counts(),(0,0));self.assertIn("CONFIRM OFFICIAL POP STRIKE",item.callback_query.edit_message_text.await_args.args[0])
        nonce=self.ctx.user_data["missing_pop_strike_confirm"]["nonce"];cancel=update(f"mpconfirm:{nonce}:no")
        await workflow.missing_pop_confirm_callback(cancel,self.ctx);self.assertEqual(self.counts(),(0,0));self.assertEqual(self.current()["status"],"pending")

    async def test_malformed_confirmation_is_rejected_without_consuming_state(self):
        item=update(workflow.case_callback(dict(self.current()),"s"));await workflow.missing_pop_case_callback(item,self.ctx)
        nonce=self.ctx.user_data["missing_pop_strike_confirm"]["nonce"]
        malformed=update(f"mpconfirm:{nonce}:invalid");await workflow.missing_pop_confirm_callback(malformed,self.ctx)
        self.assertEqual(malformed.callback_query.answer.await_count,1)
        self.assertTrue(malformed.callback_query.answer.await_args.kwargs["show_alert"])
        self.assertIn("missing_pop_strike_confirm",self.ctx.user_data);self.assertEqual(self.counts(),(0,0))

    async def test_confirm_issues_once_delivers_and_closes_card(self):
        item=update(workflow.case_callback(dict(self.current()),"s"));await workflow.missing_pop_case_callback(item,self.ctx)
        nonce=self.ctx.user_data["missing_pop_strike_confirm"]["nonce"];confirm=update(f"mpconfirm:{nonce}:yes")
        with patch("missing_pop_workflow.db.issue_missing_pop_strike",wraps=db.issue_missing_pop_strike) as issue:
            await workflow.missing_pop_confirm_callback(confirm,self.ctx)
        issue.assert_called_once_with(self.case["id"],9);self.assertEqual(self.counts(),(1,1))
        row=self.current();self.assertEqual((row["status"],row["notification_status"],row["creator_notified"]),("strike_issued","delivered",1))
        self.assertTrue(any("OFFICIAL STRIKE" in call.args[1] for call in self.bot.send_message.await_args_list));self.assertIn("First POP strike",workflow.render_case(row))

    async def test_two_concurrent_admins_create_one_official_strike(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda actor:db.issue_missing_pop_strike(self.case["id"],actor,self.path),(9,10)))
        self.assertEqual(sum(result["ok"] for result in results),1);self.assertEqual(self.counts(),(1,1))

    async def test_evidence_before_confirmation_blocks_strike_and_reconciles_card(self):
        item=update(workflow.case_callback(dict(self.current()),"s"));await workflow.missing_pop_case_callback(item,self.ctx)
        nonce=self.ctx.user_data["missing_pop_strike_confirm"]["nonce"]
        db.record_pop_evidence(1,WEEK,101,-200,44,"photo","late",source_message_at="2026-07-24T18:00:00-04:00",path=self.path)
        confirm=update(f"mpconfirm:{nonce}:yes");await workflow.missing_pop_confirm_callback(confirm,self.ctx)
        self.assertEqual(self.counts(),(0,0));self.assertEqual(self.current()["status"],"resolved")
        self.assertIn("Qualifying POP evidence",confirm.callback_query.edit_message_text.await_args.args[0])

    async def test_failed_delivery_preserves_strike_and_alerts_admin(self):
        item=update(workflow.case_callback(dict(self.current()),"s"));await workflow.missing_pop_case_callback(item,self.ctx)
        nonce=self.ctx.user_data["missing_pop_strike_confirm"]["nonce"];self.bot.send_message.side_effect=RuntimeError("private detail")
        with patch("missing_pop_workflow.send_routed",AsyncMock(return_value=(True,None))) as routed:
            await workflow.missing_pop_confirm_callback(update(f"mpconfirm:{nonce}:yes"),self.ctx)
        row=self.current();self.assertEqual(self.counts(),(1,1));self.assertEqual((row["creator_notified"],row["notification_status"]),(0,"failed"))
        self.assertNotIn("private detail",row["notification_error"]);routed.assert_awaited_once()

    async def test_retry_sends_notice_only_and_never_duplicates_strike(self):
        db.issue_missing_pop_strike(self.case["id"],9,self.path);db.record_missing_pop_notification(self.case["id"],False,"REF",self.path)
        row=self.current();item=update(workflow.case_callback(row,"r"));await workflow.missing_pop_case_callback(item,self.ctx)
        self.assertEqual(self.counts(),(1,1));self.assertEqual(self.current()["notification_status"],"delivered")
        repeat=update(workflow.case_callback(self.current(),"r"));await workflow.missing_pop_case_callback(repeat,self.ctx)
        self.assertEqual(self.counts(),(1,1));self.assertTrue(repeat.callback_query.answer.await_args.kwargs["show_alert"])

    async def test_retry_race_answers_callback_once_and_does_not_send(self):
        db.issue_missing_pop_strike(self.case["id"],9,self.path);db.record_missing_pop_notification(self.case["id"],False,"REF",self.path)
        item=update(workflow.case_callback(self.current(),"r"))
        with patch("missing_pop_workflow.db.retry_missing_pop_notification",return_value={"ok":False,"reason":"not_retryable"}):
            await workflow.missing_pop_case_callback(item,self.ctx)
        self.assertEqual(item.callback_query.answer.await_count,1);self.assertTrue(item.callback_query.answer.await_args.kwargs["show_alert"])
        self.bot.send_message.assert_not_awaited();self.assertEqual(self.counts(),(1,1))

    async def test_excuse_reason_is_actor_bound_confirmed_and_resolved(self):
        item=update(workflow.case_callback(dict(self.current()),"e"),10);await workflow.missing_pop_case_callback(item,self.ctx)
        wrong=SimpleNamespace(effective_user=SimpleNamespace(id=9),effective_message=SimpleNamespace(text="Reason",reply_text=AsyncMock()))
        await workflow.handle_missing_pop_excuse_text(wrong,self.ctx);self.assertEqual(self.current()["status"],"pending")
        self.ctx.user_data={};item=update(workflow.case_callback(dict(self.current()),"e"),10);await workflow.missing_pop_case_callback(item,self.ctx)
        message=SimpleNamespace(effective_user=SimpleNamespace(id=10),effective_message=SimpleNamespace(text="Approved exception",reply_text=AsyncMock()))
        await workflow.handle_missing_pop_excuse_text(message,self.ctx);nonce=self.ctx.user_data["missing_pop_excuse_confirm"]["nonce"]
        await workflow.missing_pop_excuse_confirm_callback(update(f"mpexcuse:{nonce}:yes",10),self.ctx)
        row=self.current();self.assertEqual((row["status"],row["excusal_reason"],row["resolved_by"]),("excused","Approved exception",10));self.assertEqual(self.counts(),(0,0))

    async def test_leave_pending_records_reviewer_and_keeps_actions(self):
        item=update(workflow.case_callback(dict(self.current()),"p"),10);await workflow.missing_pop_case_callback(item,self.ctx)
        row=self.current();self.assertEqual((row["status"],row["reviewed_by"]),("pending",10));self.assertIsNotNone(workflow.case_markup(row))

    async def test_report_counts_change_immediately_after_resolution(self):
        self.assertEqual(db.missing_pop_case_counts(WEEK,self.path)["pending_review"],1)
        db.resolve_missing_pop_case(self.case["id"],"excused",9,"Approved",self.path)
        counts=db.missing_pop_case_counts(WEEK,self.path)
        self.assertEqual((counts["pending_review"],counts["resolved"]),(0,1))

    async def test_history_and_contact_are_read_only(self):
        before=dict(self.current())
        history=update(workflow.case_callback(before,"h"));await workflow.missing_pop_case_callback(history,self.ctx)
        contact=update(workflow.case_callback(before,"c"));await workflow.missing_pop_case_callback(contact,self.ctx)
        after=dict(self.current());self.assertEqual((after["status"],after["reviewed_by"]),(before["status"],before["reviewed_by"]))
        self.assertIn("POP History",self.bot.send_message.await_args.args[1]);self.assertIn("does not change",contact.callback_query.answer.await_args.args[0])

    async def test_resolved_case_action_is_stale_and_cannot_mutate(self):
        db.resolve_missing_pop_case(self.case["id"],"excused",9,"Reason",self.path)
        item=update(workflow.case_callback(self.current(),"p"));await workflow.missing_pop_case_callback(item,self.ctx)
        self.assertEqual(self.current()["status"],"excused");self.assertTrue(item.callback_query.answer.await_args.kwargs["show_alert"])

    async def test_deleted_card_is_replaced_once_and_identifiers_change(self):
        db.record_missing_pop_case_card(self.case["id"],-1001,77,111,self.path)
        self.bot.edit_message_text.side_effect=RuntimeError("deleted");self.bot.send_message.return_value=SimpleNamespace(message_id=222)
        self.assertTrue(await workflow.refresh_case_card(self.bot,cfg(),self.current()))
        self.assertEqual(self.current()["review_message_id"],222);self.assertEqual(self.bot.send_message.await_count,1)
        self.bot.edit_message_text.side_effect=None
        self.assertTrue(await workflow.refresh_case_card(self.bot,cfg(),self.current()));self.assertEqual(self.bot.send_message.await_count,1)

    async def test_strike_level_counts_only_official_pop_strikes(self):
        db.add_warning(1,"strike","Unrelated moderation",9,self.path)
        self.assertEqual(workflow.strike_level(db.official_pop_strike_count(1,self.path)),"Additional POP strike")
        db.issue_missing_pop_strike(self.case["id"],9,self.path)
        self.assertEqual(workflow.strike_level(db.official_pop_strike_count(1,self.path)),"First POP strike")

    async def test_callback_data_is_compact_and_uses_immutable_identity(self):
        value=workflow.case_callback(dict(self.current()),"s")
        self.assertLessEqual(len(value.encode()),64);self.assertEqual(value,f"mpop:{self.case['id']}:1:{WEEK}:s")

    async def test_external_strike_is_owner_only_and_requires_confirmation(self):
        data=workflow.case_callback(dict(self.current()),"x")
        denied=update(data,10);await workflow.missing_pop_case_callback(denied,self.ctx)
        self.assertTrue(denied.callback_query.answer.await_args.kwargs["show_alert"]);self.assertEqual(self.counts(),(0,0))
        opened=update(data,9);await workflow.missing_pop_case_callback(opened,self.ctx)
        self.assertEqual(self.counts(),(0,0));self.assertIn("RECORD EXISTING MANUAL",opened.callback_query.edit_message_text.await_args.args[0])
        nonce=self.ctx.user_data["missing_pop_external_strike"]["nonce"]
        await workflow.missing_pop_external_callback(update(f"mpmanual:{nonce}:begin"),self.ctx)
        issuer=SimpleNamespace(effective_user=SimpleNamespace(id=9),effective_message=SimpleNamespace(text="Alex",reply_text=AsyncMock()))
        await workflow.handle_missing_pop_external_text(issuer,self.ctx)
        stamp=SimpleNamespace(effective_user=SimpleNamespace(id=9),effective_message=SimpleNamespace(text="2026-07-31 09:30",reply_text=AsyncMock()))
        await workflow.handle_missing_pop_external_text(stamp,self.ctx)
        await workflow.missing_pop_external_callback(update(f"mpmanual:{nonce}:proof_yes"),self.ctx)
        note=SimpleNamespace(effective_user=SimpleNamespace(id=9),effective_message=SimpleNamespace(text="Owner reviewed screenshot",reply_text=AsyncMock()))
        await workflow.handle_missing_pop_external_text(note,self.ctx)
        self.assertEqual(self.counts(),(0,0))
        with patch("missing_pop_workflow.refresh_case_card",AsyncMock(return_value=True)):
            await workflow.missing_pop_external_callback(update(f"mpmanual:{nonce}:record"),self.ctx)
        row=dict(self.current())
        self.assertEqual((row["resolution_type"],row["external_issued_by"],row["recorded_by"],row["external_proof_reviewed"]),
            ("strike_issued_external","Alex",9,1))
        self.assertEqual(self.counts(),(1,1));self.bot.send_message.assert_not_awaited()
        self.assertNotIn("missing_pop_external_strike",self.ctx.user_data)

    async def test_external_strike_second_or_stale_attempt_is_blocked_without_notice(self):
        case=dict(self.current())
        first=db.record_external_missing_pop_strike(case["id"],1,WEEK,9,"Alex","2026-07-31T09:30:00-04:00",path=self.path)
        second=db.record_external_missing_pop_strike(case["id"],1,WEEK,9,"Alex","2026-07-31T09:30:00-04:00",path=self.path)
        self.assertTrue(first["ok"]);self.assertEqual(second["reason"],"official_strike_exists")
        stale=update(workflow.case_callback(self.current(),"x"));await workflow.missing_pop_case_callback(stale,self.ctx)
        self.assertTrue(stale.callback_query.answer.await_args.kwargs["show_alert"]);self.bot.send_message.assert_not_awaited()
        self.assertIn("Existing manual POP strike recorded",workflow.render_case(dict(self.current())))


if __name__=="__main__":unittest.main()
