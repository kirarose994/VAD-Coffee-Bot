import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))
from permissions import Role, can_mutate, can_read, role_for


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            lead_admin_user_ids=frozenset({1}),
            admin_user_ids=frozenset({1, 2}),
        )

    def test_lead_admin_has_all_permissions(self):
        self.assertEqual(role_for(1, self.config), Role.LEAD_ADMIN)
        self.assertTrue(can_read(1, self.config))
        self.assertTrue(can_mutate(1, self.config))

    def test_admin_is_read_only(self):
        self.assertEqual(role_for(2, self.config), Role.ADMIN)
        self.assertTrue(can_read(2, self.config))
        self.assertFalse(can_mutate(2, self.config))

    def test_unknown_user_has_no_permissions(self):
        self.assertEqual(role_for(3, self.config), Role.NONE)
        self.assertFalse(can_read(3, self.config))
        self.assertFalse(can_mutate(3, self.config))


if __name__ == "__main__": unittest.main()
