import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0,str(Path(__file__).parents[1]/"bot"))

import database as db
from pop_history_report import build_owner_report,render_owner_report


def message(message_id,sender,decision,at="2026-07-16T20:33:00+00:00",proof="photo",reason=None):
    return {"message_id":message_id,"sender_telegram_id":sender,
        "original_timestamp":at,"edit_timestamp":None,"media_type":proof,
        "pop_decision":decision,"pop_proof_type":proof if decision=="qualified" else None,
        "pop_reason":reason or decision}


class PopHistoryOwnerReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"report.db"
        db.initialize_database(self.path)
        for user_id,username,name,status in (
            (10,"same_username","Approved Name","active"),
            (11,"same_username","Different Immutable ID","active"),
            (20,"inactive_user","Inactive Name","inactive"),
            (30,"archived_user","Archived Name","active"),
            (50,"unqualified_user","Unqualified Name","active"),
            (60,"review_user","Review Name","active"),
        ):
            db.register_creator(user_id,username,name,self.path);db.set_status(user_id,status,1,self.path)
        with db.get_connection(self.path) as connection:
            connection.execute("UPDATE creators SET deleted_at=? WHERE telegram_id=30",
                ("2026-07-17T00:00:00-04:00",))
        db.set_system_state("config:timezone_name",json.dumps("America/New_York"),self.path)

    def tearDown(self):self.tmp.cleanup()

    def scan(self):
        return {"messages":[
            message(1,10,"qualified"),
            message(2,10,"unqualified","2026-07-16T21:00:00+00:00","text","unqualified_text"),
            message(3,20,"qualified"),message(4,30,"qualified"),message(5,40,"qualified"),
            message(6,50,"unqualified",proof="other",reason="unqualified_text"),
            message(7,60,"needs_review",proof="text",reason="ambiguous_text"),
        ]}

    def test_grouped_report_uses_immutable_identity_and_owner_sections(self):
        report=build_owner_report(self.scan(),creator_database=self.path,environ={"TIMEZONE":"UTC"})
        self.assertEqual(report["timezone"],"America/New_York")
        self.assertEqual(report["message_totals"],
            {"total":7,"qualified":4,"needs_review":1,"unqualified":2})
        self.assertEqual(report["creator_totals"],{"total":6,"ready_to_recover":1,
            "already_credited_skipped":0,"needs_owner_review":1,
            "not_eligible_unqualified":1,"unmatched_inactive":3})
        ready=report["sections"]["ready_to_recover"][0]
        self.assertEqual(ready["identity_label"],"Approved Name (@same_username)")
        self.assertEqual(ready["telegram_id"],10)
        self.assertEqual(ready["primary_evidence"]["message_id"],1)
        self.assertEqual(ready["earliest_qualifying_timestamp_display"],
            "Thursday, July 16, 2026 at 4:33 PM ET")
        self.assertEqual(ready["additional_messages_found"],1)
        self.assertEqual(ready["additional_messages"][0]["reason"],"unqualified_text")
        # A colliding mutable username never changes the immutable-ID match.
        self.assertNotEqual(ready["creator_name"],"Different Immutable ID")

    def test_existing_weekly_credit_is_an_explicit_readonly_skip(self):
        db.submit_pop(10,"2026-W29",900,-100,7,"photo",self.path,
            submitted_at="2026-07-16T15:00:00-04:00")
        report=build_owner_report(self.scan(),creator_database=self.path)
        self.assertEqual(report["creator_totals"]["ready_to_recover"],0)
        self.assertEqual(report["creator_totals"]["already_credited_skipped"],1)
        skipped=report["sections"]["already_credited_skipped"][0]
        self.assertEqual(skipped["telegram_id"],10)
        self.assertEqual(skipped["primary_evidence"]["message_id"],1)
        self.assertEqual(skipped["primary_evidence"]["original_timestamp_display"],
            "Thursday, July 16, 2026 at 4:33 PM ET")
        self.assertEqual(skipped["eligibility_reason"],"existing_weekly_credit")
        self.assertEqual(skipped["recovery_status"],"already_credited")
        self.assertFalse(skipped["include_in_future_write_set"])
        self.assertEqual(skipped["existing_credit"]["message_id"],900)
        self.assertIsNone(skipped["selected_recovery_evidence"])
        self.assertEqual(skipped["comparison_evidence"]["message_id"],1)
        self.assertEqual(report["recovery_candidates"],[])

    def test_repeated_previews_are_idempotent_and_do_not_write(self):
        db.submit_pop(10,"2026-W29",900,-100,7,"photo",self.path,
            submitted_at="2026-07-16T15:00:00-04:00")
        with db.get_readonly_connection(self.path) as connection:
            before={table:connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("pop_submissions","pop_evidence","audit_events")}
        first=build_owner_report(self.scan(),creator_database=self.path)
        second=build_owner_report(self.scan(),creator_database=self.path)
        self.assertEqual(first,second)
        with db.get_readonly_connection(self.path) as connection:
            after={table:connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in before}
        self.assertEqual(after,before)

    def test_duplicate_source_evidence_does_not_change_creator_outcome(self):
        scan=self.scan();scan["messages"].append(dict(scan["messages"][0]))
        report=build_owner_report(scan,creator_database=self.path)
        self.assertEqual(report["creator_totals"]["ready_to_recover"],1)
        self.assertEqual(len(report["sections"]["ready_to_recover"]),1)
        self.assertEqual(len(report["recovery_candidates"]),1)
        self.assertEqual(report["recovery_candidates"][0]["message_id"],1)
        self.assertEqual(report["message_totals"]["total"],7)

    def test_earliest_qualifying_evidence_is_selected_only_without_weekly_credit(self):
        scan=self.scan();scan["messages"].append(message(
            8,10,"qualified","2026-07-16T20:00:00+00:00","video"))
        ready=build_owner_report(scan,creator_database=self.path)
        self.assertEqual(ready["recovery_candidates"][0]["message_id"],8)
        self.assertTrue(ready["sections"]["ready_to_recover"][0]
            ["include_in_future_write_set"])
        self.assertEqual(ready["sections"]["ready_to_recover"][0]
            ["selected_recovery_evidence"]["message_id"],8)
        db.submit_pop(10,"2026-W29",900,-100,7,"photo",self.path,
            submitted_at="2026-07-16T15:00:00-04:00")
        skipped=build_owner_report(scan,creator_database=self.path)
        row=skipped["sections"]["already_credited_skipped"][0]
        self.assertEqual(row["comparison_evidence"]["message_id"],8)
        self.assertIsNone(row["selected_recovery_evidence"])
        self.assertEqual(skipped["recovery_candidates"],[])

    def test_other_unqualified_text_stays_inspectable_and_never_ready(self):
        report=build_owner_report(self.scan(),creator_database=self.path)
        row=report["sections"]["not_eligible_unqualified"][0]
        self.assertEqual(row["telegram_id"],50)
        self.assertEqual(row["primary_evidence"]["proof_type"],"other")
        self.assertEqual(row["primary_evidence"]["status"],"unqualified")
        self.assertEqual(row["primary_evidence"]["reason"],"unqualified_text")
        self.assertIsNone(row["existing_credit"])

    def test_unmatched_resolution_checks_every_source_by_telegram_id_only(self):
        db.register_member(40,"same_username","Known Non-Creator","buyer",self.path)
        db.record_bot_user(40,"same_username","Known Bot User",self.path)
        with db.get_connection(self.path) as connection:
            connection.execute("""INSERT INTO user_roles
              (telegram_id,role,active,assigned_at,assigned_by)
              VALUES(40,'admin',1,'2026-07-01T12:00:00-04:00',1)""")
            db.audit_event(connection,1,"creator_registration_reviewed","creator",
                target_telegram_id=40)
            connection.execute("""INSERT INTO audit_history
              (actor_id,target_id,action,details,created_at)
              VALUES(1,40,'creator_registered','historical','2026-06-01T12:00:00-04:00')""")
        report=build_owner_report(self.scan(),creator_database=self.path,
            environ={"OWNER_USER_IDS":"40","TIMEZONE":"America/New_York"})
        resolution=report["unmatched_identity_resolution"][0]
        self.assertEqual(resolution["telegram_id"],40)
        self.assertFalse(resolution["safe_match_found"])
        self.assertFalse(resolution["automatic_credit_eligible"])
        self.assertEqual(resolution["exact_reason"],
            "staff_identity_exists_but_canonical_creator_profile_is_missing")
        checks={row["source"]:row for row in resolution["source_checks"]}
        for source in ("active_creators","inactive_creators","archived_creators",
                "other_creator_registration_states","staff_inherited_creator_profiles"):
            self.assertFalse(checks[source]["found"])
        for source in ("community_members","bot_users","user_roles",
                "configured_staff_roles","historical_registration_audit"):
            self.assertTrue(checks[source]["found"])
        # A mutable username collision with creator 10/11 never creates a match.
        self.assertNotEqual(resolution["telegram_id"],10)
        self.assertNotEqual(resolution["telegram_id"],11)

    def test_unmatched_resolution_explains_absence_and_action_is_nonexecuting(self):
        report=build_owner_report(self.scan(),creator_database=self.path)
        resolution=report["unmatched_identity_resolution"][0]
        self.assertEqual(resolution["exact_reason"],
            "telegram_id_absent_from_all_available_identity_sources")
        action=resolution["identify_creator_action"]
        self.assertEqual(action["label"],"Identify Creator")
        self.assertTrue(action["owner_only"])
        self.assertFalse(action["enabled"])
        self.assertTrue(action["requires_explicit_confirmation"])
        self.assertTrue(action["requires_audit_logging"])
        self.assertFalse(action["write_performed"])
        self.assertEqual(report["recovery_candidates"][0]["telegram_id"],10)

    def test_inactive_archived_and_unmatched_are_explicitly_ineligible(self):
        report=build_owner_report(self.scan(),creator_database=self.path)
        rows={row["telegram_id"]:row for row in report["sections"]["unmatched_inactive"]}
        self.assertEqual(rows[20]["final_outcome"],"Not Eligible — Inactive Creator")
        self.assertEqual(rows[30]["final_outcome"],"Not Eligible — Archived Creator")
        self.assertEqual(rows[40]["final_outcome"],"Not Eligible — Unmatched Telegram ID")
        self.assertFalse(any(row["eligible_for_recovery"] for row in rows.values()))
        self.assertIn("Unmatched Telegram ID 40",rows[40]["identity_label"])

    def test_render_is_grouped_and_includes_creator_and_message_totals(self):
        rendered=render_owner_report(build_owner_report(self.scan(),creator_database=self.path))
        for title in ("Ready to Recover","Already Credited / Skipped","Needs Owner Review","Not Eligible / Unqualified",
                "Unmatched or Inactive Creators"):
            self.assertIn(title,rendered)
        self.assertIn("Creator totals: 6 total",rendered)
        self.assertIn("Message totals: 7 total",rendered)
        self.assertIn("Unmatched Identity Resolution",rendered)
        self.assertIn("Exact reason: telegram_id_absent_from_all_available_identity_sources",rendered)
        self.assertIn("Owner review action: Identify Creator (not enabled)",rendered)
        self.assertEqual(rendered.count("Approved Name (@same_username)"),1)
        self.assertNotIn("raw",rendered.casefold())

    def test_readonly_connection_refuses_writes(self):
        with db.get_readonly_connection(self.path) as connection:
            with self.assertRaisesRegex(sqlite3.OperationalError,"readonly"):
                connection.execute("INSERT INTO creators(telegram_id,display_name,status,registered_at) VALUES(1,'x','active','x')")


if __name__=="__main__":unittest.main()
