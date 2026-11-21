"""vendored-source-check.py compares each consumer's copy with the source, offline (specs#135)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import sys
import unittest
import urllib.error
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

    def test_a_ref_then_a_branch_replace_the_pin_each_as_a_commit(self) -> None:
        heads = {("agent", "feature"): "e" * 40, ("ui", "feature"): "f" * 40}
        store = agent_files("e" * 40, workbench="c" * 40, site_host="d" * 40)
        said: dict[str, str] = {}
        chosen = check.resolve(
            set(EXPECTED),
            {"library": "1" * 40, "control": ""},
            installer=INSTALLER,
            fetch=fetcher(store),
            lookup=lambda repository, branch: heads.get((repository, branch)),
            branch="feature",
            said=said,
        )
        self.assertEqual("1" * 40, chosen["library"])
        self.assertEqual("f" * 40, chosen["ui"])
        self.assertEqual("e" * 40, chosen["agent"])
        self.assertEqual("branch feature", said["ui"])
        # site-host and Workbench at the pins of the agent in use, read by commit.
        self.assertEqual("c" * 40, chosen["workbench"])
        self.assertEqual("d" * 40, chosen["site-host"])
        self.assertEqual(
            re.search(r"(?m)^PIN_GATEWAY=([0-9a-f]{40})", INSTALLER).group(1), chosen["gateway"]
        )
        for repository, commit in chosen.items():
            self.assertRegex(commit, r"^[0-9a-f]{40}$", repository)

    def test_the_merge_gate_reads_each_main_at_its_commit(self) -> None:
        """specs#135 review S1: a branch name read through the raw host may be
        five minutes old; every name becomes the commit GitHub names now."""
        mains = {repository: format(i, "x") * 40 for i, repository in enumerate(sorted(EXPECTED))}
        heads = {**{(r, "main"): c for r, c in mains.items()}, ("ui", "feature"): "f" * 40}
        asked: list[tuple[str, str]] = []

        def lookup(repository: str, branch: str) -> str | None:
            asked.append((repository, branch))
            return heads.get((repository, branch))

        chosen = check.resolve(
            set(EXPECTED),
            {"store": "2" * 40, "gateway": "my-branch"},
            installer=INSTALLER,
            fetch=fetcher({}),  # nothing read from the agent: no pins needed
            lookup=lambda r, b: lookup(r, b) or ("9" * 40 if b == "my-branch" else None),
            branch="feature",
            at="main",
        )
        self.assertEqual("2" * 40, chosen["store"])
        self.assertEqual("9" * 40, chosen["gateway"])
        self.assertEqual("f" * 40, chosen["ui"])
        for repository in set(EXPECTED) - {"store", "ui", "gateway"}:
            self.assertEqual(mains[repository], chosen[repository], repository)
            self.assertIn((repository, "main"), asked)

    def test_a_branch_github_does_not_have_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "GitHub has no branch 'gone'"):
            check.resolve(
                set(EXPECTED), {"library": "gone"}, installer=INSTALLER, fetch=fetcher({})
            )

    def test_a_ref_that_names_no_consumer_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "names no consumer.*librray"):
            check.resolve(set(EXPECTED), {"librray": ""}, installer=INSTALLER, fetch=fetcher({}))

    def test_a_consumer_with_no_known_pin_names_a_remedy_that_works(self) -> None:
        repositories = set(EXPECTED) | {"newcomer"}
        with self.assertRaisesRegex(ValueError, "newcomer: this check knows no pin.*--at main"):
            check.resolve(
                repositories, {}, installer=INSTALLER, fetch=fetcher(agent_files(AGENT_PIN))
            )
        # The remedies named: a ref, or the merge gate's main.
        chosen = check.resolve(
            repositories,
            {"newcomer": "3" * 40},
            installer=INSTALLER,
            fetch=fetcher(agent_files(AGENT_PIN)),
        )
        self.assertEqual("3" * 40, chosen["newcomer"])
        chosen = check.resolve(
            repositories,
            {},
            installer=INSTALLER,
            fetch=fetcher({}),
            lookup=lambda repository, branch: "4" * 40 if branch == "main" else None,
            at="main",
        )
        self.assertEqual("4" * 40, chosen["newcomer"])

    def test_an_unreadable_agent_pin_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "Workbench pin"):
            check.resolve({"agent", "workbench"}, {}, installer=INSTALLER, fetch=fetcher({}))


class _Answer:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _opener(*outcomes: object):
    """urlopen that answers with each outcome in turn: bytes, or an exception."""
    calls: list[str] = []
    queue = list(outcomes)

    def urlopen(url: str, timeout: float) -> _Answer:
        calls.append(url)
        outcome = queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return _Answer(outcome)  # type: ignore[arg-type]

    return urlopen, calls


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "said so", None, None)  # type: ignore[arg-type]


COMMIT = "a" * 40


class FetchTests(unittest.TestCase):
    """specs#135 review: bounded retries, fail closed, by commit only (no network)."""

    def fetch(self, *outcomes: object):
        urlopen, calls = _opener(*outcomes)
        waits: list[float] = []
        try:
            got = check.fetch_raw(
                "library", COMMIT, "VENDORED.json", urlopen=urlopen, sleep=waits.append
            )
        except check.FetchError as error:
            got = error
        return got, calls, waits

    def test_a_429_a_503_and_a_timeout_are_tried_again(self) -> None:
        got, calls, waits = self.fetch(_http_error(429), _http_error(503), TimeoutError(), b"ok")
        self.assertEqual(b"ok", got)
        self.assertEqual(4, len(calls))
        self.assertEqual(list(check.BACKOFF_SECONDS), waits)
        self.assertIn(f"/library/{COMMIT}/VENDORED.json", calls[0])

    def test_after_the_last_try_it_fails_closed_naming_the_url_and_status(self) -> None:
        got, calls, _ = self.fetch(*[_http_error(502)] * check.ATTEMPTS)
        self.assertIsInstance(got, check.FetchError)
        self.assertEqual(check.ATTEMPTS, len(calls))
        self.assertIn(calls[0], str(got))
        self.assertIn("HTTP 502", str(got))

    def test_a_timeout_inside_urlerror_counts_as_a_timeout(self) -> None:
        reason = urllib.error.URLError(TimeoutError("timed out"))
        got, calls, _ = self.fetch(reason, b"ok")
        self.assertEqual((b"ok", 2), (got, len(calls)))

    def test_a_404_is_missing_and_not_tried_again(self) -> None:
        got, calls, waits = self.fetch(_http_error(404))
        self.assertIsNone(got)
        self.assertEqual((1, []), (len(calls), waits))

    def test_a_403_fails_at_once(self) -> None:
        got, calls, _ = self.fetch(_http_error(403), b"never")
        self.assertIsInstance(got, check.FetchError)
        self.assertIn("HTTP 403", str(got))
        self.assertEqual(1, len(calls))

    def test_a_branch_name_is_never_fetched(self) -> None:
        urlopen, calls = _opener(b"stale")
        with self.assertRaisesRegex(ValueError, "not a commit"):
            check.fetch_raw("library", "main", "VENDORED.json", urlopen=urlopen)
        self.assertEqual([], calls)


class MainTests(unittest.TestCase):
    def test_a_misspelt_ref_name_fails_without_a_traceback(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = check.main(["--root", str(SCRIPTS), "--ref", "tool_driver="])
        self.assertEqual(1, code)
        self.assertIn("names no consumer in platform/manifest.json: tool_driver", err.getvalue())


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
