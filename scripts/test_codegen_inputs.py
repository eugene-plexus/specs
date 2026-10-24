"""Tests for scripts/codegen-inputs.py. Offline: no test reads the network.

Run `python scripts/test_codegen_inputs.py`, or pytest on this file.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "codegen_inputs", Path(__file__).with_name("codegen-inputs.py")
)
codegen_inputs = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["codegen_inputs"] = codegen_inputs
_spec.loader.exec_module(codegen_inputs)  # type: ignore[union-attr]

Document = codegen_inputs.Document
SPECS = Path(__file__).resolve().parent.parent

UI_CONFIG = """\
// control.yaml joined at M5; this comment names openapi/control.yaml and must not count.
const SPECS = [
  { input: "openapi/gateway.yaml", output: "gateway.ts" },
%s];
"""
PY_CONFIG = """\
# openapi/agent.yaml was renamed once; this comment must not count either.
SPECS_TO_GENERATE: list[tuple[str, str]] = [
    ("openapi/gateway.yaml", "models.py"),
%s]
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit(repo: Path, message: str, **files: str) -> str:
    for name, text in files.items():
        path = repo / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def consumer(root: Path, repo: str, ref: str, config: str, text: str) -> None:
    (root / repo / Path(config).parent).mkdir(parents=True, exist_ok=True)
    (root / repo / "SPECS_REF").write_text(ref + "\n", encoding="utf-8", newline="\n")
    (root / repo / config).write_text(text, encoding="utf-8", newline="\n")


def two_document_specs(base: Path) -> tuple[Path, str, str]:
    """A specs repo whose first commit has gateway.yaml and whose second adds
    control.yaml. Returns it and both commits."""
    specs = base / "specs"
    specs.mkdir()
    git(specs, "init", "-q")
    before = commit(specs, "gateway", **{"openapi__gateway.yaml": "openapi: 3.1.0\n"})
    after = commit(specs, "control", **{"openapi__control.yaml": "openapi: 3.1.0\n"})
    return specs, before, after


UI_TABLE = {
    "openapi/gateway.yaml": Document(consumers=("ui",)),
    "openapi/control.yaml": Document(consumers=("ui",)),
}
UI_ONLY = {"ui": "scripts/codegen.mjs"}


# --------------------------------------------------------------------------- #
# Rule A
# --------------------------------------------------------------------------- #


def test_every_openapi_document_has_a_row() -> None:
    """The real tree: a new document with no row fails here, and in CI."""
    assert codegen_inputs.rule_a(SPECS) == []


def test_a_document_without_a_row_fails_and_so_does_a_row_without_a_document() -> None:
    with tempfile.TemporaryDirectory() as directory:
        specs, _, _ = two_document_specs(Path(directory))
        table = {
            "openapi/gateway.yaml": Document(consumers=("ui",)),
            "openapi/gone.yaml": Document(why_not="removed"),
        }
        problems = codegen_inputs.rule_a(specs, table, UI_ONLY)
    assert any("openapi/control.yaml has no row" in p for p in problems), problems
    assert any("row for openapi/gone.yaml, which does not exist" in p for p in problems), problems


def test_a_row_that_says_nothing_fails() -> None:
    with tempfile.TemporaryDirectory() as directory:
        specs, _, _ = two_document_specs(Path(directory))
        table = {
            "openapi/gateway.yaml": Document(),
            "openapi/control.yaml": Document(consumers=("nobody",)),
        }
        problems = codegen_inputs.rule_a(specs, table, UI_ONLY)
    assert any("gateway.yaml: its row names no consumer" in p for p in problems), problems
    assert any("control.yaml: its row names nobody, which is not a consumer" in p for p in problems)


def test_a_fragment_must_be_referenced_by_the_document_that_reaches_it() -> None:
    with tempfile.TemporaryDirectory() as directory:
        specs = Path(directory) / "specs"
        specs.mkdir()
        git(specs, "init", "-q")
        commit(
            specs,
            "tree",
            **{
                "openapi__control.yaml": "a:\n  $ref: './components/sign-in.yaml#/x'\n",
                "openapi__components__sign-in.yaml": "x: 1\n",
                "openapi__components__sites.yaml": "x: 1\n",
            },
        )
        table = {
            "openapi/control.yaml": Document(consumers=("ui",)),
            "openapi/components/sign-in.yaml": Document(reached_through=("openapi/control.yaml",)),
            "openapi/components/sites.yaml": Document(reached_through=("openapi/control.yaml",)),
        }
        problems = codegen_inputs.rule_a(specs, table, UI_ONLY)
    assert problems == ["openapi/components/sites.yaml: openapi/control.yaml does not $ref it."]


# --------------------------------------------------------------------------- #
# Rule B
# --------------------------------------------------------------------------- #


def test_a_consumer_pinned_past_a_document_it_does_not_generate_fails() -> None:
    """The ui and control.yaml case: ui's pin has the document and its codegen does not name it."""
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        specs, _, after = two_document_specs(base)
        consumer(base / "root", "ui", after, "scripts/codegen.mjs", UI_CONFIG % "")
        problems = codegen_inputs.rule_b(
            specs, codegen_inputs.Checkouts(base / "root"), UI_TABLE, UI_ONLY
        )
    assert problems == [
        f"ui pins specs {after[:7]}, which has openapi/control.yaml; "
        "ui/scripts/codegen.mjs does not generate it."
    ]


def test_a_consumer_that_generates_it_passes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        specs, _, after = two_document_specs(base)
        extra = '  { input: "openapi/control.yaml", output: "control.ts" },\n'
        consumer(base / "root", "ui", after, "scripts/codegen.mjs", UI_CONFIG % extra)
        problems = codegen_inputs.rule_b(
            specs, codegen_inputs.Checkouts(base / "root"), UI_TABLE, UI_ONLY
        )
    assert problems == []


def test_a_consumer_not_yet_re_pinned_is_not_checked_against_a_newer_document() -> None:
    """The specs-first order: the document lands, the consumer re-pins later."""
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        specs, before, _ = two_document_specs(base)
        consumer(base / "root", "ui", before, "scripts/codegen.mjs", UI_CONFIG % "")
        problems = codegen_inputs.rule_b(
            specs, codegen_inputs.Checkouts(base / "root"), UI_TABLE, UI_ONLY
        )
    assert problems == []


def test_a_config_that_names_a_document_the_table_does_not_give_it_fails() -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        specs, before, _ = two_document_specs(base)
        table = {
            "openapi/gateway.yaml": Document(consumers=("ui",)),
            "openapi/control.yaml": Document(consumers=("control",)),
        }
        extra = '  { input: "openapi/control.yaml", output: "control.ts" },\n'
        consumer(base / "root", "ui", before, "scripts/codegen.mjs", UI_CONFIG % extra)
        problems = codegen_inputs.rule_b(
            specs, codegen_inputs.Checkouts(base / "root"), table, UI_ONLY
        )
    assert len(problems) == 1, problems
    assert "ui/scripts/codegen.mjs generates openapi/control.yaml" in problems[0]
    assert "does not give ui" in problems[0]


def test_a_python_config_is_read_from_its_list_and_not_its_comments() -> None:
    named = codegen_inputs.documents_named(
        "scripts/codegen.py", PY_CONFIG % '    ("openapi/components/common.yaml", "c.py"),\n'
    )
    assert named == {"openapi/gateway.yaml", "openapi/components/common.yaml"}
    assert codegen_inputs.documents_named("scripts/codegen.mjs", UI_CONFIG % "") == {
        "openapi/gateway.yaml"
    }
    assert codegen_inputs.documents_named("scripts/codegen.py", "X = 1\n") is None
    assert codegen_inputs.documents_named("scripts/codegen.mjs", "const A = [];\n") is None


def test_a_pin_the_checkout_does_not_have_says_to_fetch_history() -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        specs, _, _ = two_document_specs(base)
        consumer(base / "root", "ui", "a" * 40, "scripts/codegen.mjs", UI_CONFIG % "")
        problems = codegen_inputs.rule_b(
            specs, codegen_inputs.Checkouts(base / "root"), UI_TABLE, UI_ONLY
        )
    assert len(problems) == 1 and "aaaaaaa, which this checkout does not have" in problems[0]
    assert "git fetch --unshallow" in problems[0]


def test_a_file_that_cannot_be_read_fails_naming_where() -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        specs, _, _ = two_document_specs(base)
        problems = codegen_inputs.rule_b(
            specs, codegen_inputs.Checkouts(base / "root"), UI_TABLE, UI_ONLY
        )
    assert len(problems) == 1
    assert problems[0].startswith("cannot read ") and "SPECS_REF" in problems[0]


def test_a_network_failure_names_the_url_and_the_status() -> None:
    url = "https://raw.githubusercontent.com/eugene-plexus/ui/abc/SPECS_REF"
    calls: list[str] = []

    def refused(request, timeout=None):  # type: ignore[no-untyped-def]
        calls.append(request)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]

    real = urllib.request.urlopen
    urllib.request.urlopen = refused  # type: ignore[assignment]
    try:
        try:
            codegen_inputs.fetch(url, pause=0)
        except codegen_inputs.Unreadable as e:
            message = str(e)
        else:
            raise AssertionError("a 404 must not read as a file")
    finally:
        urllib.request.urlopen = real  # type: ignore[assignment]
    assert message == f"cannot read {url}: HTTP 404"
    assert len(calls) == 1, "a 404 is the answer; it is not asked again"


def test_a_server_error_is_asked_again_and_then_fails_naming_the_status() -> None:
    url = "https://raw.githubusercontent.com/eugene-plexus/ui/abc/SPECS_REF"
    calls: list[str] = []

    def down(request, timeout=None):  # type: ignore[no-untyped-def]
        calls.append(request)
        raise urllib.error.HTTPError(url, 503, "Unavailable", {}, None)  # type: ignore[arg-type]

    real = urllib.request.urlopen
    urllib.request.urlopen = down  # type: ignore[assignment]
    try:
        try:
            codegen_inputs.fetch(url, attempts=3, pause=0)
        except codegen_inputs.Unreadable as e:
            message = str(e)
        else:
            raise AssertionError("a 503 must not read as a file")
    finally:
        urllib.request.urlopen = real  # type: ignore[assignment]
    assert message == f"cannot read {url}: HTTP 503"
    assert len(calls) == 3


# --------------------------------------------------------------------------- #
# The pins
# --------------------------------------------------------------------------- #


def test_the_installer_pins_are_read_for_every_consumer_it_carries() -> None:
    pins = codegen_inputs.installer_pins(
        (SPECS / "scripts" / "install.sh").read_text(encoding="utf-8")
    )
    assert set(pins) == {
        "agent",
        "control",
        "gateway",
        "inference-driver",
        "library",
        "store",
        "tool-driver",
        "ui",
    }
    assert all(len(sha) == 40 for sha in pins.values())


def test_the_agents_workbench_and_site_host_pins_are_read() -> None:
    wb, sh = "1" * 40, "2" * 40
    files = {
        codegen_inputs.AGENT_CATALOGUE: (
            f"  source: https://github.com/eugene-plexus/workbench/archive/{wb}.tar.gz\n"
        ),
        codegen_inputs.AGENT_SITE_HOST: f'x = 1\nSITE_HOST_COMMIT = "{sh}"\n',
    }
    assert codegen_inputs.agent_pins(files.__getitem__) == {"workbench": wb, "site-host": sh}


def test_every_consumer_has_a_pin_one_way_or_the_other() -> None:
    from_installer = set(codegen_inputs.INSTALLER_PINS)
    from_agent = {"workbench", "site-host"}
    assert from_installer | from_agent == set(codegen_inputs.CONSUMERS)


if __name__ == "__main__":
    failed = 0
    for name, test in list(globals().items()):
        if not name.startswith("test_") or not callable(test):
            continue
        try:
            test()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
        else:
            print(f"ok   {name}")
    sys.exit(1 if failed else 0)
