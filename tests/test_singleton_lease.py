import logging
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))

import database as db
import main as bot_main


LEASE = "telegram_bot_api_poller"


class ProcessLeaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "lease.db"
        db.initialize_database(self.path)
        self.now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_process_acquires_and_second_live_process_is_rejected(self):
        self.assertTrue(db.acquire_process_lease(LEASE,"first",90,"test-host",self.path,self.now))
        self.assertFalse(db.acquire_process_lease(LEASE,"second",90,"test-host",self.path,self.now))
        row=db.get_process_lease(LEASE,self.path)
        self.assertEqual(row["instance_id"],"first")
        self.assertEqual(row["startup_source"],"test-host")

    def test_near_simultaneous_acquisition_has_exactly_one_winner(self):
        barrier=Barrier(2)

        def acquire(instance_id):
            barrier.wait()
            return db.acquire_process_lease(LEASE,instance_id,90,"race",self.path,self.now)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(acquire,("one","two")))
        self.assertEqual(results.count(True),1)
        self.assertEqual(results.count(False),1)

    def test_heartbeat_extends_only_an_active_owned_lease(self):
        db.acquire_process_lease(LEASE,"owner",90,"test",self.path,self.now)
        later=self.now+timedelta(seconds=30)
        self.assertTrue(db.heartbeat_process_lease(LEASE,"owner",90,self.path,later))
        row=db.get_process_lease(LEASE,self.path)
        self.assertEqual(datetime.fromisoformat(row["heartbeat_at"]),later)
        self.assertEqual(datetime.fromisoformat(row["expires_at"]),later+timedelta(seconds=90))
        self.assertFalse(db.heartbeat_process_lease(LEASE,"intruder",90,self.path,later))

    def test_clean_shutdown_releases_only_its_own_lease(self):
        db.acquire_process_lease(LEASE,"owner",90,"test",self.path,self.now)
        self.assertFalse(db.release_process_lease(LEASE,"other",self.path))
        self.assertIsNotNone(db.get_process_lease(LEASE,self.path))
        self.assertTrue(db.release_process_lease(LEASE,"owner",self.path))
        self.assertIsNone(db.get_process_lease(LEASE,self.path))

    def test_expired_lease_can_be_taken_over_and_old_process_cannot_mutate_it(self):
        db.acquire_process_lease(LEASE,"old",30,"old-host",self.path,self.now)
        takeover=self.now+timedelta(seconds=31)
        self.assertTrue(db.acquire_process_lease(LEASE,"new",90,"new-host",self.path,takeover))
        self.assertFalse(db.heartbeat_process_lease(LEASE,"old",90,self.path,takeover))
        self.assertFalse(db.release_process_lease(LEASE,"old",self.path))
        self.assertEqual(db.get_process_lease(LEASE,self.path)["instance_id"],"new")

    def test_expired_owner_cannot_resurrect_its_lease(self):
        db.acquire_process_lease(LEASE,"old",30,"old-host",self.path,self.now)
        self.assertFalse(db.heartbeat_process_lease(
            LEASE,"old",90,self.path,self.now+timedelta(seconds=31)))

    def test_stale_clear_requires_expiry_and_the_inspected_instance(self):
        db.acquire_process_lease(LEASE,"owner",30,"old-host",self.path,self.now)
        self.assertFalse(db.clear_expired_process_lease(LEASE,"owner",self.path,self.now))
        expired=self.now+timedelta(seconds=31)
        self.assertFalse(db.clear_expired_process_lease(LEASE,"other",self.path,expired))
        self.assertTrue(db.clear_expired_process_lease(LEASE,"owner",self.path,expired))
        self.assertIsNone(db.get_process_lease(LEASE,self.path))

    def test_migration_is_additive_and_idempotent(self):
        with db.get_connection(self.path) as connection:
            connection.execute("INSERT INTO creators(telegram_id,display_name,status,registered_at) VALUES(?,?,?,?)",
                (77,"Preserved Creator","active",self.now.isoformat()))
            connection.execute("DROP TABLE process_leases")
            connection.execute("UPDATE schema_version SET version=12")
        db.initialize_database(self.path)
        db.initialize_database(self.path)
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0],14)
            self.assertEqual(connection.execute("SELECT display_name FROM creators WHERE telegram_id=77").fetchone()[0],
                "Preserved Creator")
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='process_leases'").fetchone()[0],1)


class PollerStartupTests(unittest.TestCase):
    def config(self):
        return SimpleNamespace(token="synthetic-test-token",log_level="CRITICAL")

    def test_rejected_startup_never_builds_or_contacts_telegram(self):
        with patch.object(bot_main.Config,"from_env",return_value=self.config()), \
             patch.object(bot_main,"initialize_database"), \
             patch.object(bot_main,"acquire_process_lease",return_value=False), \
             patch.object(bot_main,"commit_identifier",return_value="abc123"), \
             patch.object(bot_main,"startup_source",return_value="test-host"), \
             patch.object(bot_main.Application,"builder") as builder:
            with self.assertLogs("main",level=logging.INFO) as captured:
                self.assertEqual(bot_main.main(),2)
                self.assertEqual(bot_main.main(),2)
        builder.assert_not_called()
        identities=[line for line in captured.output if "startup_identity" in line]
        self.assertEqual(len(identities),2)
        self.assertTrue(all("lease_acquired=false" in line and "polling_start_et=not-started" in line
            for line in identities))

    def test_database_error_fails_closed_before_polling(self):
        with patch.object(bot_main.Config,"from_env",return_value=self.config()), \
             patch.object(bot_main,"initialize_database"), \
             patch.object(bot_main,"acquire_process_lease",side_effect=sqlite3.OperationalError("locked")), \
             patch.object(bot_main.Application,"builder") as builder:
            self.assertEqual(bot_main.main(),2)
        builder.assert_not_called()

    def test_successful_start_verifies_lease_before_polling_and_releases(self):
        app=Mock();app.bot_data={};app.job_queue=Mock()
        builder=Mock();builder.token.return_value=builder;builder.post_init.return_value=builder;builder.build.return_value=app
        calls=[]

        def acquire(*args,**kwargs):calls.append("acquire");return True
        def heartbeat(*args,**kwargs):calls.append("verify");return True
        def polling(*args,**kwargs):calls.append("poll")
        app.run_polling.side_effect=polling
        with patch.object(bot_main.Config,"from_env",return_value=self.config()), \
             patch.object(bot_main,"initialize_database"), \
             patch.object(bot_main,"acquire_process_lease",side_effect=acquire), \
             patch.object(bot_main,"heartbeat_process_lease",side_effect=heartbeat), \
             patch.object(bot_main,"release_process_lease",return_value=True) as release, \
             patch.object(bot_main,"begin_recovery_run",return_value=1), \
             patch.object(bot_main,"apply_persisted_settings"), \
             patch.object(bot_main,"synchronize_role_memberships"), \
             patch.object(bot_main,"set_system_state"), \
             patch.object(bot_main,"register_application_handlers"), \
             patch.object(bot_main.Application,"builder",return_value=builder), \
             patch.object(bot_main,"commit_identifier",return_value="abc123"), \
             patch.object(bot_main,"startup_source",return_value="test-host"):
            self.assertEqual(bot_main.main(),0)
        self.assertEqual(calls,["acquire","verify","poll"])
        release.assert_called_once()
        app.job_queue.run_repeating.assert_called_once()


class PollerHeartbeatJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_lost_lease_stops_polling_without_telegram_alert(self):
        app=SimpleNamespace(bot_data={"process_instance_id":"one"},stop_running=Mock())
        ctx=SimpleNamespace(application=app)
        with patch.object(bot_main,"heartbeat_process_lease",return_value=False):
            await bot_main.poller_lease_heartbeat_job(ctx)
            await bot_main.poller_lease_heartbeat_job(ctx)
        app.stop_running.assert_called_once_with()
        self.assertTrue(app.bot_data["poller_lease_lost"])

    async def test_heartbeat_database_error_stops_polling(self):
        app=SimpleNamespace(bot_data={"process_instance_id":"one"},stop_running=Mock())
        ctx=SimpleNamespace(application=app)
        with patch.object(bot_main,"heartbeat_process_lease",side_effect=sqlite3.OperationalError("locked")):
            await bot_main.poller_lease_heartbeat_job(ctx)
        app.stop_running.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
