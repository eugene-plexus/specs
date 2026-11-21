"""vendored-source-check.py compares each consumer's copy with the source, offline (specs#135)."""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check = _load("vendored-source-check")
vendor = _load("vendor-platform")
EXPECTED = vendor.planned(SCRIPTS.parent)
INSTALLER = (SCRIPTS / "install.sh").read_text(encoding="utf-8")
SHA = re.compile(r"[0-9a-f]{64}")


def store_from_source() -> dict[tuple[str, str, str], bytes]:
    """Every consumer holding exactly what vendoring writes, at ref `pin`."""
    return {
        (repository, "pin", relative): data
        for repository, files in EXPECTED.items()
        for relative, (_, data) in files.items()
    }


def fetcher(store: dict[tuple[str, str, str], bytes]):
    def fetch(repository: str, ref: str, path: str) -> bytes | None:
        return store.get((repository, ref, path))

    return fetch


REFS = dict.fromkeys(EXPECTED, "pin")


class CompareTests(unittest.TestCase):
    def test_copies_equal_to_the_source_pass(self) -> None:
        self.assertEqual([], check.compare(EXPECTED, REFS, fetcher(store_from_source())))

    def test_a_copy_one_byte_off_is_named_with_both_digests(self) -> None:
        store = store_from_source()
        key = ("library", "pin", "src/eugene_plexus_library/_http.py")
        store[key] = store[key].replace(b"def ", b"def  ", 1)
        problems = check.compare(EXPECTED, REFS, fetcher(store))
        # Only the copy differs here; the lock still records the source's digest.
        self.assertEqual(1, len(problems), problems)
        line = problems[0]
        self.assertIn("library src/eugene_plexus_library/_http.py", line)
        self.assertIn("platform/1.0.0/_http.py", line)
        self.assertEqual(2, len(SHA.findall(line)), line)

    def test_a_stale_copy_with_its_own_lock_still_differs(self) -> None:
        """The specs#135 shape: copy and VENDORED.json agree with each other, not with specs."""
        store = store_from_source()
        old = b"# an older _http.py\n"
        for repository in ("library", "inference-driver", "tool-driver", "store", "site-host"):
            rel = vendor_rel(repository, "_http.py")
            store[(repository, "pin", rel)] = old
            lock = store[(repository, "pin", "VENDORED.json")].decode()
            new = check.digest(EXPECTED[repository][rel][1])
            lock = lock.replace(new, check.digest(old))
            store[(repository, "pin", "VENDORED.json")] = lock.encode()
        problems = check.compare(EXPECTED, REFS, fetcher(store))
        named = {(line.split()[0], line.split()[1].rstrip(":")) for line in problems}
        for repository in ("library", "inference-driver", "tool-driver", "store", "site-host"):
            self.assertIn((repository, vendor_rel(repository, "_http.py")), named)
            self.assertIn((repository, "VENDORED.json"), named)
        self.assertEqual(10, len(problems), problems)

    def test_a_missing_copy_fails(self) -> None:
        store = store_from_source()
        del store[("ui", "pin", "contracts/run-operations.json")]
        problems = check.compare(EXPECTED, REFS, fetcher(store))
        self.assertEqual(1, len(problems), problems)
        self.assertIn("ui contracts/run-operations.json: missing at pin", problems[0])
        self.assertIn("openapi/run-operations.json", problems[0])

    def test_line_endings_are_not_drift(self) -> None:
        store = store_from_source()
        key = ("gateway", "pin", "src/eugene_plexus_gateway/_http.py")
        store[key] = store[key].replace(b"\n", b"\r\n")
        self.assertEqual([], check.compare(EXPECTED, REFS, fetcher(store)))


def vendor_rel(repository: str, module: str) -> str:
    return next(
        rel for rel, (source, _) in EXPECTED[repository].items() if source.endswith("/" + module)
    )


AGENT_PIN = re.search(r"(?m)^PIN_AGENT=([0-9a-f]{40})", INSTALLER).group(1)
WB = "a" * 40
SH = "b" * 40


def agent_files(ref: str, workbench: str = WB, site_host: str = SH):
    return {
        ("agent", ref, check.CATALOGUE): (
            f"  url: https://github.com/eugene-plexus/workbench/archive/{workbench}.tar.gz\n"
            f"  version: {workbench}\n"
        ).encode(),
        ("agent", ref, check.SITE_HOST_PY): f'SITE_HOST_COMMIT = "{site_host}"\n'.encode(),
    }


class ResolveTests(unittest.TestCase):
    def test_pins_are_what_ships(self) -> None:
        chosen = check.resolve(
            set(EXPECTED), {}, installer=INSTALLER, fetch=fetcher(agent_files(AGENT_PIN))
        )
        self.assertEqual(AGENT_PIN, chosen["agent"])
        self.assertEqual(WB, chosen["workbench"])
        self.assertEqual(SH, chosen["site-host"])
        for repository, name in check.INSTALLER_PINS.items():
            pin = re.search(rf"(?m)^PIN_{name}=([0-9a-f]{{40}})", INSTALLER).group(1)
            self.assertEqual(pin, chosen[repository], repository)

    def test_a_ref_then_a_branch_replace_the_pin(self) -> None:
        store = agent_files("feature", workbench="c" * 40, site_host="d" * 40)
        chosen = check.resolve(
            set(EXPECTED),
            {"library": "1" * 40},
            installer=INSTALLER,
            fetch=fetcher(store),
            has_branch=lambda repository: repository in {"agent", "ui", "library"},
            branch="feature",
        )
        self.assertEqual("1" * 40, chosen["library"])
        self.assertEqual("feature", chosen["ui"])
        self.assertEqual("feature", chosen["agent"])
        # site-host and Workbench at the pins of the agent in use.
        self.assertEqual("c" * 40, chosen["workbench"])
        self.assertEqual("d" * 40, chosen["site-host"])
        self.assertEqual(
            re.search(r"(?m)^PIN_GATEWAY=([0-9a-f]{40})", INSTALLER).group(1), chosen["gateway"]
        )

    def test_the_merge_gate_reads_main_where_no_candidate_exists(self) -> None:
        chosen = check.resolve(
            set(EXPECTED),
            {"store": "2" * 40},
            installer=INSTALLER,
            fetch=fetcher({}),  # nothing read from the agent: no pins needed
            has_branch=lambda repository: repository == "ui",
            branch="feature",
            at="main",
        )
        self.assertEqual("2" * 40, chosen["store"])
        self.assertEqual("feature", chosen["ui"])
        for repository in set(EXPECTED) - {"store", "ui"}:
            self.assertEqual("main", chosen[repository], repository)

    def test_an_unreadable_agent_pin_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "Workbench pin"):
            check.resolve({"agent", "workbench"}, {}, installer=INSTALLER, fetch=fetcher({}))


class VendorTests(unittest.TestCase):
    def test_vendoring_writes_what_the_check_expects(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ep-vendored-source-") as directory:
            root = Path(directory)
            vendor.vendor(root, check=False)
            store = {
                (repository, "pin", relative): (root / repository / relative).read_bytes()
                for repository, files in EXPECTED.items()
                for relative in files
            }
        self.assertEqual([], check.compare(EXPECTED, REFS, fetcher(store)))


if __name__ == "__main__":
    unittest.main()
