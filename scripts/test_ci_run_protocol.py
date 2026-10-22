"""Offline regression tests for pinned and candidate run protocol checks."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run_protocol

AHEAD = "specs main is ahead of the pinned library's run protocol; the next ship moves the pins"


def write(path, protocol):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(protocol, ensure_ascii=False), encoding="utf-8")


def changed(protocol, section):
    result = deepcopy(protocol)
    result[section]["new"] = {}
    return result


class RunProtocolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ep-run-protocol-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.actual = {
            "paths": {"/v1/run-operations": {"get": {}}},
            "components": {"schemas": {"Model": {"description": "Modèle"}}},
        }
        # Installed sources need not be siblings of the specs checkout.
        self.specs = self.root / "specs/openapi/run-operations.json"
        self.library = self.root / "installed/library/contracts/run-operations.json"
        self.agent = self.root / "installed/agent/contracts/run-operations.json"
        for path in (self.specs, self.library, self.agent):
            write(path, self.actual)
        self.sources = {
            "eugene_plexus_library.run_operations": SimpleNamespace(
                origin=str(self.library.parents[1] / "src/eugene_plexus_library/run_operations.py")
            ),
            "eugene_plexus_agent.run_worker": SimpleNamespace(
                origin=str(self.agent.parents[1] / "src/eugene_plexus_agent/run_worker.py")
            ),
        }
        finder = patch.object(run_protocol, "find_spec", self.sources.__getitem__)
        finder.start()
        self.addCleanup(finder.stop)
        self.output = io.StringIO()

    def verify(self, actual=None, library_ref=""):
        with redirect_stdout(self.output):
            run_protocol.verify_run_protocol(
                self.actual if actual is None else actual,
                self.specs,
                library_ref=library_ref,
            )

    def test_pins_allow_specs_ahead(self):
        for section in ("paths", "components"):
            with self.subTest(section=section):
                write(self.specs, changed(self.actual, section))
                self.output = io.StringIO()

                self.verify()

                self.assertEqual(self.output.getvalue().splitlines(), [AHEAD])

    def test_pins_reject_router_drift_even_when_specs_match(self):
        for section in ("paths", "components"):
            with self.subTest(section=section):
                actual = changed(self.actual, section)
                write(self.specs, actual)

                with self.assertRaisesRegex(AssertionError, "run protocol .* drifted"):
                    self.verify(actual)

                self.assertEqual(self.output.getvalue(), "")

    def test_pins_reject_agent_drift(self):
        for section in ("paths", "components"):
            with self.subTest(section=section):
                write(self.agent, changed(self.actual, section))

                with self.assertRaisesRegex(AssertionError, "agent.*vendored run protocol"):
                    self.verify()

                self.assertEqual(self.output.getvalue(), "")

    def test_pins_require_library_contract(self):
        self.library.unlink()

        with self.assertRaisesRegex(FileNotFoundError, "run-operations.json"):
            self.verify()

    def test_pins_require_agent_checkout_contract(self):
        self.agent.unlink()

        with self.assertRaisesRegex(FileNotFoundError, "run-operations.json"):
            self.verify()

    def test_pins_require_library_source_checkout(self):
        self.sources["eugene_plexus_library.run_operations"].origin = str(
            self.root / "site-packages/eugene_plexus_library/run_operations.py"
        )

        with self.assertRaisesRegex(AssertionError, "pinned library.*source checkout"):
            self.verify()

    def test_pins_allow_packaged_agent_without_checkout_contract(self):
        self.sources["eugene_plexus_agent.run_worker"].origin = str(
            self.root / "site-packages/eugene_plexus_agent/run_worker.py"
        )
        self.agent.unlink()
        write(self.specs, changed(self.actual, "components"))

        self.verify()

        self.assertEqual(self.output.getvalue().splitlines(), [AHEAD])

    def test_aligned_pins_are_silent(self):
        self.verify()

        self.assertEqual(self.output.getvalue(), "")

    def test_candidates_use_specs_without_requiring_vendored_copies(self):
        self.library.unlink()
        self.agent.unlink()
        for library_ref in ("same-named-branch", "a" * 40):
            with self.subTest(library_ref=library_ref):
                self.verify(library_ref=library_ref)

                self.assertEqual(self.output.getvalue(), "")

    def test_candidates_reject_specs_drift_even_when_vendored_copies_match(self):
        for library_ref in ("same-named-branch", "a" * 40):
            for section in ("paths", "components"):
                with self.subTest(library_ref=library_ref, section=section):
                    write(self.specs, changed(self.actual, section))

                    with self.assertRaisesRegex(AssertionError, "run protocol .* drifted"):
                        self.verify(library_ref=library_ref)

                    self.assertEqual(self.output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
