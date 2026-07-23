import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))

import database as db
from engagement import classify as classify_participation
from pop_reliability import classify_pop_candidate
from recovery_contract import (AdapterMessage, HISTORY_RECOVERY_LEASE_NAME,
    MediaIndicators, classify_message)


NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
BOT_API_LEASE = "telegram_bot_api_poller"


class NormalizedMessageContractTests(unittest.TestCase):
    def fixture(self, **changes):
        values = dict(canonical_chat_id=-100300, message_id=90, thread_id=11,
            sender_telegram_id=20, original_timestamp=NOW, text=None, caption=None,
            media=MediaIndicators())
        values.update(changes)
        return AdapterMessage(**values)

    @staticmethod
    def existing_pop_message(message):
        media = message.media
        document = (SimpleNamespace(mime_type=media.document_mime_type,
            file_name=f"proof{media.document_extension or ''}") if media.document else None)
        entities = (SimpleNamespace(type="url"),) if media.has_url_entity else ()
        return SimpleNamespace(text=message.text, caption=message.caption, entities=entities,
            caption_entities=entities, photo=[object()] if media.photo else None,
            document=document, animation=object() if media.animation else None,
            video=object() if media.video else None, voice=object() if media.voice else None,
            audio=object() if media.audio else None, sticker=object() if media.sticker else None,
            story=object() if media.forwarded_story else None)

    def test_fixture_decisions_match_existing_participation_and_pop_classifiers(self):
        fixtures = (
            self.fixture(text="This conversation has a thoughtful and useful answer."),
            self.fixture(message_id=91, text="hello"),
            self.fixture(message_id=92, media=MediaIndicators(photo=True)),
            self.fixture(message_id=93, caption="Weekly story proof",
                media=MediaIndicators(document=True, document_mime_type="image/png",
                    document_extension="PNG")),
            self.fixture(message_id=94, text="represented Telegram link",
                media=MediaIndicators(has_url_entity=True)),
            self.fixture(message_id=95, text="I posted my weekly POP to my story"),
            self.fixture(message_id=96, media=MediaIndicators(forwarded_story=True)),
        )
        for fixture in fixtures:
            with self.subTest(message_id=fixture.message_id):
                envelope = classify_message(fixture, now=NOW)
                participation = classify_participation(fixture.text,
                    media=fixture.media.any_media, now=NOW)
                pop = classify_pop_candidate(self.existing_pop_message(fixture))
                self.assertEqual(envelope.derived.participation_decision,
                    "accepted" if participation.accepted else "rejected")
                self.assertEqual(envelope.derived.participation_reason, participation.reason)
                self.assertEqual(envelope.derived.participation_digest,
                    participation.digest or None)
                self.assertEqual(envelope.derived.pop_proof_type, pop.proof_type)
                self.assertEqual(envelope.derived.pop_reason, pop.reason)
                self.assertEqual(envelope.derived.pop_decision,
                    "qualified" if pop.proof_type else "needs_review" if pop.needs_review else "unqualified")

    def test_envelope_contains_required_metadata_without_raw_content(self):
        edited = NOW.replace(hour=13)
        source = self.fixture(text="A thoughtful normalized participation message",
            edit_timestamp=edited, media=MediaIndicators(has_url_entity=True))
        envelope = classify_message(source, now=NOW)
        self.assertEqual((envelope.canonical_chat_id,envelope.message_id,envelope.thread_id,
            envelope.sender_telegram_id),(-100300,90,11,20))
        self.assertEqual(envelope.original_timestamp,NOW)
        self.assertEqual(envelope.edit_timestamp,edited)
        self.assertEqual(envelope.message_type,"text")
        self.assertEqual(len(envelope.normalized_text_hash),64)
        self.assertFalse(hasattr(envelope,"text"))
        self.assertFalse(hasattr(envelope,"caption"))
        self.assertFalse(hasattr(envelope,"raw_media"))

    def test_audio_fixtures_match_existing_live_participation_rules(self):
        digest="b"*64
        accepted=classify_message(self.fixture(media=MediaIndicators(
            voice=True,duration_seconds=6,identity_hash=digest)),now=NOW)
        short=classify_message(self.fixture(message_id=91,media=MediaIndicators(
            audio=True,duration_seconds=4,identity_hash=digest)),now=NOW)
        duplicate=classify_message(self.fixture(message_id=92,media=MediaIndicators(
            audio=True,duration_seconds=6,identity_hash=digest)),now=NOW,
            is_repeat=lambda value,since:True)
        promotional=classify_message(self.fixture(message_id=93,caption="buy now",
            media=MediaIndicators(audio=True,duration_seconds=6,identity_hash=digest)),now=NOW)
        self.assertEqual((accepted.derived.participation_decision,
            accepted.derived.participation_reason),("accepted","voice_message"))
        self.assertEqual(short.derived.participation_reason,"audio_too_short")
        self.assertEqual(duplicate.derived.participation_reason,"duplicate_audio")
        self.assertEqual(promotional.derived.participation_reason,"promotional_spam")

    def test_contract_rejects_ambiguous_ids_and_naive_timestamps(self):
        with self.assertRaises(TypeError):
            self.fixture(message_id="90")
        with self.assertRaises(ValueError):
            self.fixture(original_timestamp=datetime(2026,7,17,12,0))


class HistoryRecoverySchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "history.db"
        db.initialize_database(self.path)
        self.now = NOW.isoformat()

    def tearDown(self):
        self.tmp.cleanup()

    def insert_source(self, connection, key="participation-main", kind="participation",
                      peer=-300, chat=-100300, thread=None):
        return connection.execute("""INSERT INTO history_recovery_sources
          (source_key,source_kind,peer_id,canonical_chat_id,thread_id,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?)""",(key,kind,peer,chat,thread,self.now,self.now)).lastrowid

    def insert_run(self, connection, source_id, status="discovering", instance="worker-1"):
        return connection.execute("""INSERT INTO history_recovery_runs
          (source_id,instance_id,status,started_at,starting_checkpoint_message_id,
           fixed_boundary_message_id,fixed_boundary_message_at)
          VALUES(?,?,?,?,?,?,?)""",(source_id,instance,status,self.now,0,100,self.now)).lastrowid

    def insert_item(self, connection, run_id, source_id, peer=-300, message=90):
        return connection.execute("""INSERT INTO history_recovery_items
          (run_id,source_id,source_peer_id,canonical_chat_id,message_id,thread_id,
           sender_telegram_id,source_message_at,message_type,normalized_text_hash,
           classification_version,participation_decision,participation_reason,
           pop_decision,pop_reason,discovered_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (run_id,source_id,peer,-100300,message,None,20,self.now,"text","a"*64,
           "bot-api-parity-v1","accepted","meaningful","unqualified",
           "unqualified_text",self.now)).lastrowid

    def test_schema_fourteen_is_additive_and_privacy_minimal(self):
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0],14)
            tables={row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"history_recovery_sources","history_recovery_runs",
                "history_recovery_items"}.issubset(tables))
            columns={row[1] for row in connection.execute(
                "PRAGMA table_info(history_recovery_items)")}
        self.assertFalse({"text","caption","url","raw_message","raw_media","media_blob"}&columns)
        self.assertTrue({"canonical_chat_id","message_id","thread_id","sender_telegram_id",
            "source_message_at","edit_at","message_type","normalized_text_hash",
            "media_duration_seconds","media_identity_hash","participation_decision",
            "pop_decision"}.issubset(columns))

    def test_repeat_migration_preserves_old_records_audit_and_recovery_rows(self):
        with db.get_connection(self.path) as connection:
            connection.execute("INSERT INTO creators(telegram_id,display_name,status,registered_at) VALUES(?,?,?,?)",
                (77,"Preserved Creator","active",self.now))
            connection.execute("""INSERT INTO audit_events
              (occurred_at,actor_role,action,result) VALUES(?,'system','preserved_audit','success')""",
              (self.now,))
            source=self.insert_source(connection)
            run=self.insert_run(connection,source,status="complete")
            self.insert_item(connection,run,source)
        db.initialize_database(self.path);db.initialize_database(self.path)
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT display_name FROM creators WHERE telegram_id=77").fetchone()[0],
                "Preserved Creator")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_events WHERE action='preserved_audit'").fetchone()[0],1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM history_recovery_sources").fetchone()[0],1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM history_recovery_runs").fetchone()[0],1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM history_recovery_items").fetchone()[0],1)

    def test_uniqueness_and_active_run_constraints_are_fail_closed(self):
        with db.get_connection(self.path) as connection:
            source=self.insert_source(connection)
            run=self.insert_run(connection,source)
            with self.assertRaises(sqlite3.IntegrityError):
                self.insert_source(connection,key="duplicate-location")
            with self.assertRaises(sqlite3.IntegrityError):
                self.insert_run(connection,source,instance="worker-2")
            self.insert_item(connection,run,source)
            with self.assertRaises(sqlite3.IntegrityError):
                self.insert_item(connection,run,source)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE history_recovery_runs SET error_reference=? WHERE id=?",
                    ("x"*65,run))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE history_recovery_runs SET error_reference=? WHERE id=?",
                    ("unsafe reference",run))

    def test_version_thirteen_database_upgrades_without_operational_loss(self):
        with db.get_connection(self.path) as connection:
            connection.execute("DROP TABLE history_recovery_items")
            connection.execute("DROP TABLE history_recovery_runs")
            connection.execute("DROP TABLE history_recovery_sources")
            connection.execute("UPDATE schema_version SET version=13")
            connection.execute("INSERT INTO creators(telegram_id,display_name,status,registered_at) VALUES(?,?,?,?)",
                (88,"Version Thirteen Creator","active",self.now))
            connection.execute("""INSERT INTO audit_events
              (occurred_at,actor_role,action,result) VALUES(?,'system','v13_audit','success')""",
              (self.now,))
        db.initialize_database(self.path)
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0],14)
            self.assertEqual(connection.execute("SELECT display_name FROM creators WHERE telegram_id=88").fetchone()[0],
                "Version Thirteen Creator")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_events WHERE action='v13_audit'").fetchone()[0],1)

    def test_mtproto_and_bot_api_leases_are_independent(self):
        self.assertTrue(db.acquire_process_lease(BOT_API_LEASE,"bot",90,"test",self.path,NOW))
        self.assertTrue(db.acquire_process_lease(HISTORY_RECOVERY_LEASE_NAME,"history",90,"test",self.path,NOW))
        self.assertFalse(db.acquire_process_lease(BOT_API_LEASE,"bot-2",90,"test",self.path,NOW))
        self.assertFalse(db.acquire_process_lease(HISTORY_RECOVERY_LEASE_NAME,"history-2",90,"test",self.path,NOW))
        self.assertTrue(db.release_process_lease(HISTORY_RECOVERY_LEASE_NAME,"history",self.path))
        self.assertIsNotNone(db.get_process_lease(BOT_API_LEASE,self.path))


if __name__ == "__main__":
    unittest.main()
