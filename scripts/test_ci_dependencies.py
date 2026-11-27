import unittest

from ci_dependencies import conflicts


class DependencyTests(unittest.TestCase):
    def test_dependabot_cannot_pin_a_different_authlib_than_the_release(self):
        errors = conflicts("authlib==1.9.10\n", "authlib==1.8.0\n")
        self.assertEqual(len(errors), 3)
        self.assertIn("authlib==1.9.10", errors[0])
        self.assertIn("authlib==1.8.0", errors[0])

    def test_runtime_dependency_can_take_its_version_from_constraints(self):
        self.assertEqual(conflicts("authlib\npytest==8.4.2\n", "authlib==1.8.0\n"), [])

    def test_names_are_normalized_and_extras_do_not_hide_conflicts(self):
        self.assertTrue(conflicts("Some_Package[extra]>=3\n", "some-package==2\n"))

    def test_windows_only_conflict_is_seen_on_linux_preflight(self):
        self.assertTrue(
            conflicts("authlib>=2; sys_platform == 'win32'\n", "authlib==1.8.0\n")
        )

    def test_matching_range_and_irrelevant_python_marker_pass(self):
        self.assertEqual(
            conflicts(
                "authlib>=1,<2\nauthlib>=3; python_version < '3.9'\n",
                "authlib==1.8.0\n",
            ),
            [],
        )

    def test_one_platform_constraint_does_not_hide_another(self):
        errors = conflicts(
            "authlib>=2\n",
            "authlib==1.8.0; sys_platform == 'linux'\n"
            "authlib==2.0; sys_platform == 'win32'\n",
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("linux", errors[0])


if __name__ == "__main__":
    unittest.main()
