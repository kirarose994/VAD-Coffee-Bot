import sys
import tempfile
import unittest
import httpcore
import httpx
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch

sys.path.insert(0,str(Path(__file__).parents[1]/"bot"))
import database as db
from telegram.error import NetworkError
from telegram_io import is_transient_network_error,retry_telegram
from tracker import telegram_recovery_job
from handlers.error import error_handler
from routing import send_routed


class RetryPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_read_retries_with_bounded_backoff(self):
        operation=AsyncMock(side_effect=[NetworkError("read"),NetworkError("read"),"ok"]);sleep=AsyncMock()
        result=await retry_telegram(operation,attempts=3,base_delay=.5,sleep=sleep)
        self.assertEqual(result,"ok");self.assertEqual(operation.await_count,3)
        self.assertEqual([c.args[0] for c in sleep.await_args_list],[.5,1.0])

    async def test_non_network_error_fails_immediately(self):
        operation=AsyncMock(side_effect=ValueError("bad data"));sleep=AsyncMock()
        with self.assertRaises(ValueError):await retry_telegram(operation,sleep=sleep)
        self.assertEqual(operation.await_count,1);sleep.assert_not_awaited()

    def test_wrapped_network_error_is_transient(self):
        try:
            try:raise OSError("socket read")
            except OSError as cause:raise NetworkError("Telegram read failed") from cause
        except NetworkError as error:self.assertTrue(is_transient_network_error(error))

    def test_httpcore_and_httpx_read_errors_are_transient(self):
        self.assertTrue(is_transient_network_error(httpcore.ReadError("read")))
        self.assertTrue(is_transient_network_error(httpx.ReadError("read")))


class IncidentDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"test.db";db.initialize_database(self.path)
        self.details={"exception_type":"NetworkError","message":"read failed","traceback":"trace","source":"telegram_polling"}
    def tearDown(self):self.tmp.cleanup()

    def test_duplicate_occurrences_survive_restart_without_duplicate_incident(self):
        first,created=db.record_system_incident("transient_network:telegram","ERR-ONE","transient_network","telegram_polling",self.details,self.path)
        second,created_again=db.record_system_incident("transient_network:telegram","ERR-TWO","transient_network","telegram_polling",self.details,self.path)
        self.assertTrue(created);self.assertFalse(created_again);self.assertEqual(first["id"],second["id"])
        self.assertEqual(second["error_reference"],"ERR-ONE");self.assertEqual(second["occurrence_count"],2)
        with db.get_connection(self.path) as connection:self.assertEqual(connection.execute("SELECT COUNT(*) FROM system_incidents").fetchone()[0],1)

    def test_success_auto_resolves_open_transient_incident_idempotently(self):
        incident,_=db.record_system_incident("transient_network:telegram","ERR-ONE","transient_network","telegram_polling",self.details,self.path)
        self.assertEqual(db.resolve_transient_incidents(self.path),1);self.assertEqual(db.resolve_transient_incidents(self.path),0)
        self.assertEqual(db.get_system_incident(incident["id"],self.path)["status"],"resolved")
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_events WHERE action='system_incident_resolved'").fetchone()[0],1)


class RecoveryJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_probe_resolves_incident(self):
        bot=SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(id=1)));ctx=SimpleNamespace(bot=bot)
        with patch("tracker.db.resolve_transient_incidents") as resolved:
            await telegram_recovery_job(ctx)
        resolved.assert_called_once_with()

    async def test_failed_probe_stays_quiet(self):
        bot=SimpleNamespace(get_me=AsyncMock(side_effect=NetworkError("read")));ctx=SimpleNamespace(bot=bot)
        with patch("tracker.db.resolve_transient_incidents") as resolved:
            await telegram_recovery_job(ctx)
        resolved.assert_not_called()


class ErrorHandlerIncidentTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_transient_error_has_one_audit_and_owner_notice(self):
        incident={"id":9,"error_reference":"ERR-STABLE"};bot=SimpleNamespace(send_message=AsyncMock())
        cfg=SimpleNamespace(owner_user_ids=frozenset({1}),admin_chat_id=-100,health_thread_id=7)
        ctx=SimpleNamespace(error=NetworkError("read failed"),bot_data={"config":cfg},bot=bot,job=None)
        with patch("handlers.error.db.record_system_incident",side_effect=[(incident,True),(incident,False)]) as recorded, \
             patch("handlers.error.db.record_audit") as audit:
            await error_handler(None,ctx);await error_handler(None,ctx)
        self.assertEqual(recorded.call_count,2);self.assertEqual(audit.call_count,1)
        self.assertEqual(bot.send_message.await_count,2)  # one Owner DM and one Health-topic post


class RoutedSendRetryTests(unittest.IsolatedAsyncioTestCase):
    def cfg(self):return SimpleNamespace(admin_chat_id=-100,reports_thread_id=7,owner_user_ids=frozenset())

    async def test_routed_send_retries_transient_read_then_succeeds(self):
        bot=SimpleNamespace(send_message=AsyncMock(side_effect=[NetworkError("read"),None]))
        with patch("routing.db.resolve_transient_incidents") as resolved, \
             patch("routing.db.set_system_state"),patch("routing.db.record_audit"):
            ok,ref=await send_routed(bot,self.cfg(),"participation_alert","alert")
        self.assertTrue(ok);self.assertIsNone(ref);self.assertEqual(bot.send_message.await_count,2);resolved.assert_called_once()

    async def test_non_network_send_failure_is_not_retried(self):
        bot=SimpleNamespace(send_message=AsyncMock(side_effect=ValueError("bad request construction")))
        with patch("routing.db.record_delivery_failure") as failed,patch("routing.db.set_system_state"),patch("routing.db.record_audit"), \
             patch("routing._notify_owners_once",new=AsyncMock()):
            ok,ref=await send_routed(bot,self.cfg(),"participation_alert","alert")
        self.assertFalse(ok);self.assertTrue(ref.startswith("DEL-"));self.assertEqual(bot.send_message.await_count,1);failed.assert_called_once()
