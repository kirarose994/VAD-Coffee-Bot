import sys, tempfile, unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).parents[1]/"bot"))
import database as db
from operations import admin_away_authorized, admin_away_notification

class AdminAwayTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"db.sqlite";db.initialize_database(self.path);db.register_creator(10,"creator","Creator",self.path);db.set_status(10,"active",1,self.path)
 def tearDown(self):self.tmp.cleanup()
 def create(self,start="2026-07-16",end="2026-07-31"):return db.create_admin_absence_notice(10,"vacation",start,end,"Private note","vacation_trip",99,self.path)
 def test_immediate_approval_and_private_audit(self):
  request=self.create();self.assertEqual(db.get_absence_request(request,self.path)["status"],"approved");event=next(r for r in db.history(20,self.path) if r["action"]=="absence_entered_on_behalf");self.assertNotIn("Private note",event["new_value"] or "")
 def test_overlapping_and_repeat_are_rejected(self):
  self.create()
  with self.assertRaises(ValueError):self.create("2026-07-20","2026-07-21")
 def test_cancel_preserves_started_thursday_and_removes_future(self):
  request=self.create();self.assertTrue(db.cancel_approved_absence(request,99,"Returned",self.path,today=date(2026,7,16)));self.assertEqual(db.creator_pop_status(10,"2026-W29",self.path),"excused");self.assertEqual(db.creator_pop_status(10,"2026-W30",self.path),"not submitted")
 def test_cancel_restores_availability(self):
  today=datetime.now(ZoneInfo("America/New_York")).date();request=self.create(today.isoformat(),(today+timedelta(days=14)).isoformat());self.assertTrue(db.cancel_approved_absence(request,99,"Returned",self.path,today=today));self.assertEqual(db.get_creator(10,self.path)["availability"],"unavailable")
 def test_type_specific_permission_and_notification(self):
  cfg=SimpleNamespace(owner_user_ids=frozenset(),lead_admin_user_ids=frozenset(),admin_user_ids=frozenset({2}),admin_permissions={2:frozenset({"review_vacations"})});self.assertTrue(admin_away_authorized(2,cfg,"vacation_trip"));self.assertFalse(admin_away_authorized(2,cfg,"personal_day"));self.assertNotIn("note",admin_away_notification("2026-07-16","2026-07-18").casefold())
