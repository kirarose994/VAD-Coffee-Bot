import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))
from permissions import (
    Membership, Role, can_manage_sensitive, can_mutate, can_read, can_view_audit, has_permission, role_for, roles_for,
)


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            owner_user_ids=frozenset({0}),
            lead_admin_user_ids=frozenset({1}),
            admin_user_ids=frozenset({1, 2}),
        )

    def test_owner_has_every_permission(self):
        self.assertEqual(role_for(0, self.config), Role.OWNER)
        self.assertTrue(can_read(0, self.config))
        self.assertTrue(can_mutate(0, self.config))
        self.assertTrue(can_view_audit(0, self.config))
        self.assertTrue(can_manage_sensitive(0, self.config))
        self.assertEqual(roles_for(0,self.config),frozenset({Membership.CREATOR,Membership.ADMIN,Membership.OWNER}))

    def test_lead_admin_has_operational_permissions_only(self):
        self.assertEqual(role_for(1, self.config), Role.LEAD_ADMIN)
        self.assertTrue(can_read(1, self.config))
        self.assertTrue(can_mutate(1, self.config))
        self.assertFalse(can_view_audit(1, self.config))
        self.assertFalse(can_manage_sensitive(1, self.config))

    def test_admin_has_moderation_permissions_without_audit_access(self):
        self.assertEqual(role_for(2, self.config), Role.ADMIN)
        self.assertTrue(can_read(2, self.config))
        self.assertTrue(can_mutate(2, self.config))
        self.assertFalse(can_view_audit(2, self.config))
        self.assertTrue(has_permission(2,self.config,"adjust_warnings"))
        self.assertFalse(has_permission(2,self.config,"review_registrations"))
        self.assertEqual(roles_for(2,self.config),frozenset({Membership.CREATOR,Membership.ADMIN}))

    def test_creator_membership_is_independent_of_admin_membership(self):
        self.assertEqual(roles_for(50,self.config,has_creator_profile=True),frozenset({Membership.CREATOR}))

    def test_lead_admin_receives_review_tools_but_not_owner_setup(self):
        self.assertTrue(has_permission(1,self.config,"review_registrations"))
        self.assertTrue(has_permission(1,self.config,"review_pop"))
        self.assertFalse(has_permission(1,self.config,"change_settings"))

    def test_unknown_user_has_no_permissions(self):
        self.assertEqual(role_for(3, self.config), Role.NONE)
        self.assertFalse(can_read(3, self.config))
        self.assertFalse(can_mutate(3, self.config))


if __name__ == "__main__": unittest.main()
