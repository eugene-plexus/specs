"""Accept delivery guards against isolated Git repositories and simulated GitHub.

Runs in CI. All shipping roots/remotes are temporary fixtures. No live install,
real branch, port, or release is touched. Each fixture is also a focused local test.
"""

import sys
import unittest


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        ["test_ship", "test_branch_ci"]
    )
    sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
