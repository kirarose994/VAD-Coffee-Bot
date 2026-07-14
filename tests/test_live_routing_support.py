import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).parents[1]/"bot"))

import database as db
from routing import destination, send_routed


class CentralRoutingTests(unittest.IsolatedAsyncioTestCase):
    def cfg(self):
        return SimpleNamespace(admin_chat_id=-100,registration_thread_id=1,away_thread_id=2,
            pop_review_thread_id=3,reports_thread_id=4,moderation_thread_id=5,
            support_thread_id=6,owner_review_thread_id=7,health_thread_id=8)

    async def test_forum_delivery_uses_chat_and_thread(self):
        bot=SimpleNamespace(send_message=AsyncMock())
        with patch("routing.db.set_system_state"),patch("routing.db.record_audit"):
            ok,ref=await send_routed(bot,self.cfg(),"support","Private support card")
        self.assertTrue(ok);self.assertIsNone(ref)
        bot.send_message.assert_awaited_once_with(-100,"Private support card",message_thread_id=6,reply_markup=None)

    def test_routes_are_category_specific(self):
        cfg=self.cfg()
        self.assertEqual(destination(cfg,"registration"),(-100,1))
        self.assertEqual(destination(cfg,"away_notice"),(-100,2))
        self.assertEqual(destination(cfg,"pop_review"),(-100,3))
        self.assertEqual(destination(cfg,"participation_alert"),(-100,4))
        self.assertEqual(destination(cfg,"moderation"),(-100,5))
        self.assertEqual(destination(cfg,"support"),(-100,6))


class SupportAndIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"support.db"
        db.initialize_database(self.path)
        for user,name in ((10,"Kira"),(11,"Eve")):
            db.register_creator(user,name.casefold(),name,self.path);db.set_status(user,"active",1,self.path)

    def tearDown(self): self.tmp.cleanup()

    def test_creator_identity_never_falls_back_to_another_record(self):
        self.assertEqual(db.get_creator(10,self.path)["display_name"],"Kira")
        self.assertEqual(db.get_creator(11,self.path)["display_name"],"Eve")
        self.assertIsNone(db.get_creator(12,self.path))

    def test_duplicate_numeric_identity_refreshes_instead_of_duplicating(self):
        db.register_creator(10,"new_username","Kira Rose",self.path)
        with db.get_connection(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM creators WHERE telegram_id=10").fetchone()[0],1)

    def test_support_requests_are_private_and_durable(self):
        first=db.create_support_request(10,"Participation","Please help",self.path)
        second=db.create_support_request(11,"POP","Question",self.path)
        self.assertEqual([r["id"] for r in db.support_requests_for(10,self.path)],[first])
        self.assertEqual([r["id"] for r in db.support_requests_for(11,self.path)],[second])
        self.assertTrue(db.update_support_request(first,"assign",99,path=self.path))
        self.assertTrue(db.update_support_request(first,"resolve",99,"Answered",self.path))
        self.assertFalse(db.update_support_request(first,"resolve",99,path=self.path))


if __name__=="__main__": unittest.main()
