"""The token module is one module in five places, and nothing of HS256 is left.

Per-node token keys (2026-09-25; `docs/design/per-node-token-keys.md`) put
one module, `tokens.py`, into every component that mints or verifies a
token. Components share schemas and not code, so it is copied on purpose,
and a copy that drifts is the defect: two verifiers that disagree about a
token are a hole in whichever one is looser. D11 deleted HS256 and the
shared install key outright. Three checks:

(a) `src/<package>/tokens.py` is byte-identical in agent, control, gateway,
    library and inference-driver, and the five `tests/test_tokens.py` are
    identical except for the one line importing that repo's own package.
(b) No component `src/` (outside `_generated/`) names `HS256`,
    `AUTH_SIGNING_KEY`, `AUTH_VERIFY_KEY`, `auth_signing_key`,
    `auth_verify_key`, or a string starting `service:` (the old audience
    prefix). Read as text. In Python files, comments and docstrings are
    blanked first, because prose saying HS256 was removed -- as `tokens.py`'s
    own docstring does -- is history, not code; every string literal, name and
    f-string is still read.
(c) Each repo's `tests/test_tokens.py` passes, run against that repo's own
    `src/` (`PYTHONPATH`) with the repo's `.venv` interpreter when it has one,
    else with this interpreter when it can import the package (CI installs
    all five into one environment and makes no `.venv`), else it is skipped
    with the reason printed.

`--sabotage` then proves (a) and (b) can fail: in a temporary copy of the
five trees it flips one byte of a `tokens.py`, one of a `test_tokens.py`,
points one test's import at another repo's package, and adds an `HS256`
literal and an f-string `service:` audience to a source file. Each must be
caught, and each is restored from the bytes held in memory before the next;
the copy passes before the first and after the last.

Run from the directory holding `specs/`, `agent/`, ... as siblings, or pass
`--polyrepo`. Removed with the code it tested: the per-repo mutations of
`security.py`'s HS256/EdDSA selection, `auth_state.py`'s verify-key
bootstrap, the supervisor's verify-key hand-off and `node_identity.py`'s
key-downgrade guard -- none of that code exists any more, and HS256 cannot
come back without (b) failing.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path

REPOS = ("agent", "control", "gateway", "library", "inference-driver")
REFERENCE = "agent"

FORBIDDEN = (
    ("HS256", re.compile(r"HS256", re.IGNORECASE)),
    ("the shared-key settings", re.compile(r"auth_(signing|verify)_key", re.IGNORECASE)),
    ("a service: audience", re.compile(r"""["']service:""")),
)
TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".toml", ".txt", ".cfg", ".ini", ".md"}


def package(repo: str) -> str:
    return "eugene_plexus_" + repo.replace("-", "_")


def import_line(repo: str) -> str:
    return f"from {package(repo)} import tokens"


def tokens_path(root: Path, repo: str) -> Path:
    return root / repo / "src" / package(repo) / "tokens.py"


def test_path(root: Path, repo: str) -> Path:
    return root / repo / "tests" / "test_tokens.py"


def first_difference(a: bytes, b: bytes) -> int:
    """1-based line number of the first line where two files differ."""
    left, right = a.splitlines(), b.splitlines()
    for number, (x, y) in enumerate(zip(left, right, strict=False), start=1):
        if x != y:
            return number
    return min(len(left), len(right)) + 1


# --------------------------------------------------------------------------- #
# (a) one module, five copies
# --------------------------------------------------------------------------- #


def normalized_test(root: Path, repo: str) -> tuple[bytes | None, str | None]:
    """The test file with its own package's import replaced, or why it cannot be."""
    path = test_path(root, repo)
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{path}: {exc}"
    own = import_line(repo)
    count = sum(1 for line in text.splitlines() if line.strip() == own)
    if count != 1:
        return None, f"{path}: expected exactly one line {own!r}, found {count}"
    return text.replace(own, "from <package> import tokens").encode("utf-8"), None


def check_copies(root: Path) -> list[str]:
    problems: list[str] = []
    try:
        reference = tokens_path(root, REFERENCE).read_bytes()
    except OSError as exc:
        return [f"cannot read the reference tokens.py: {exc}"]
    for repo in REPOS:
        path = tokens_path(root, repo)
        try:
            data = path.read_bytes()
        except OSError as exc:
            problems.append(f"{path}: {exc}")
            continue
        if data != reference:
            line = first_difference(reference, data)
            problems.append(f"{path} differs from {REFERENCE}'s copy at line {line}")
    ref_test, why = normalized_test(root, REFERENCE)
    if ref_test is None:
        return problems + [why or "unreadable reference test"]
    for repo in REPOS:
        data, why = normalized_test(root, repo)
        if data is None:
            problems.append(why or f"{repo}: unreadable test")
        elif data != ref_test:
            line = first_difference(ref_test, data)
            problems.append(
                f"{test_path(root, repo)} differs from {REFERENCE}'s copy at line {line} "
                "(beyond the one import line)"
            )
    return problems


# --------------------------------------------------------------------------- #
# (b) nothing of the shared key is left
# --------------------------------------------------------------------------- #


_SKIPPED = {tokenize.NL, tokenize.COMMENT}
_STATEMENT_START = {tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING}


def code_only(text: str) -> str:
    """The source with comments and bare string statements blanked, lines kept.

    A bare string statement is a docstring, or the attribute docstrings the
    settings classes carry under each field. Everything else, including
    every string literal that is an argument, a value or part of an
    expression, and every f-string, is left as it is.
    """
    toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    spans = []
    before: tokenize.TokenInfo | None = None
    for index, tok in enumerate(toks):
        if tok.type == tokenize.COMMENT:
            spans.append((tok.start, tok.end))
        elif tok.type == tokenize.STRING and (before is None or before.type in _STATEMENT_START):
            ahead = index + 1
            while ahead < len(toks) and toks[ahead].type in _SKIPPED:
                ahead += 1
            if ahead == len(toks) or toks[ahead].type in (tokenize.NEWLINE, tokenize.ENDMARKER):
                spans.append((tok.start, tok.end))
        if tok.type not in _SKIPPED:
            before = tok
    lines = [list(line) for line in text.splitlines(keepends=True)]
    for (start_row, start_col), (end_row, end_col) in spans:
        for row in range(start_row, end_row + 1):
            line = lines[row - 1]
            first = start_col if row == start_row else 0
            last = end_col if row == end_row else len(line)
            for col in range(first, min(last, len(line))):
                if line[col] not in "\r\n":
                    line[col] = " "
    return "".join("".join(line) for line in lines)


def residue(root: Path, repo: str) -> list[str]:
    """Every forbidden name in one repo's `src/`, as `repo/src/...:line: what: text`."""
    findings: list[str] = []
    src = root / repo / "src"
    if not src.is_dir():
        return [f"{repo}/src: no src directory"]
    for path in sorted(src.rglob("*")):
        parts = set(path.relative_to(src).parts)
        if not path.is_file() or "_generated" in parts or "__pycache__" in parts:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        where = path.relative_to(root).as_posix()
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(f"{where}: unreadable ({exc})")
            continue
        text = original
        if path.suffix == ".py":
            try:
                text = code_only(original)
            except (tokenize.TokenError, SyntaxError, IndentationError) as exc:
                findings.append(f"{where}: does not tokenize ({exc})")
                continue
        shown = original.splitlines()
        for number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in FORBIDDEN:
                if pattern.search(line):
                    findings.append(f"{where}:{number}: {label}: {shown[number - 1].strip()}")
    return findings


# --------------------------------------------------------------------------- #
# (c) each copy's own tests
# --------------------------------------------------------------------------- #


def clean_env(root: Path, repo: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env["PYTHONPATH"] = str(root / repo / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def interpreter_for(root: Path, repo: str) -> tuple[str | None, str]:
    """(python, why) -- the interpreter to run a repo's tests with, or None and why not."""
    venv = root / repo / ".venv"
    for candidate in (venv / "Scripts" / "python.exe", venv / "bin" / "python"):
        if candidate.is_file():
            return str(candidate), f"{repo}/.venv"
    probe = subprocess.run(
        [sys.executable, "-c", f"import {package(repo)}.tokens, pytest"],
        cwd=root / repo,
        env=clean_env(root, repo),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if probe.returncode == 0:
        return sys.executable, "this interpreter"
    reason = (probe.stderr.strip().splitlines() or ["import failed"])[-1]
    return None, f"no {repo}/.venv, and this interpreter cannot import {package(repo)}: {reason}"


def run_tests(root: Path, repo: str) -> tuple[str, str]:
    """('PASS' | 'FAIL' | 'SKIP', detail)."""
    python, where = interpreter_for(root, repo)
    if python is None:
        return "SKIP", where
    result = subprocess.run(
        [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_tokens.py"],
        cwd=root / repo,
        env=clean_env(root, repo),
        capture_output=True,
        text=True,
        timeout=300,
    )
    summary = (result.stdout.strip().splitlines() or [""])[-1]
    passed = re.search(r"(\d+) passed", summary)
    if result.returncode == 0 and passed and int(passed.group(1)) > 0:
        return "PASS", f"{summary} ({where})"
    return "FAIL", f"exit {result.returncode} ({where})\n{result.stdout}\n{result.stderr}"


# --------------------------------------------------------------------------- #
# the gate, and its sabotage
# --------------------------------------------------------------------------- #


def static_checks(root: Path) -> tuple[list[str], dict[str, list[str]]]:
    return check_copies(root), {repo: residue(root, repo) for repo in REPOS}


def sabotage(polyrepo: Path) -> int:
    """Prove (a) and (b) catch what they exist to catch. Returns the count caught."""
    with tempfile.TemporaryDirectory(prefix="ep-r7-tokens-") as temp:
        copy = Path(temp)
        for repo in REPOS:
            shutil.copytree(
                polyrepo / repo / "src",
                copy / repo / "src",
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            (copy / repo / "tests").mkdir(parents=True)
            shutil.copy2(test_path(polyrepo, repo), test_path(copy, repo))
        baseline_copies, baseline_residue = static_checks(copy)
        # The copy must read exactly as the real trees do before anything is broken:
        # (a) clean, and (b) finding what it finds there, no more and no less.
        if baseline_copies:
            raise SystemExit("sabotage needs a clean (a) baseline:\n" + "\n".join(baseline_copies))
        assert baseline_residue == static_checks(polyrepo)[1], "the copy reads unlike the trees"
        print("PASS sabotage baseline: the unbroken copy reads as the real trees do", flush=True)

        def flip(path: Path) -> None:
            data = bytearray(path.read_bytes())
            data[len(data) // 2] ^= 0x01
            path.write_bytes(bytes(data))

        def reimport(path: Path) -> None:
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace(import_line("inference-driver"), import_line("agent")),
                encoding="utf-8",
            )

        def append(line: str):
            def apply(path: Path) -> None:
                path.write_text(path.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")

            return apply

        victim = copy / "library" / "src" / package("library") / "settings.py"
        cases = [
            ("one byte of gateway's tokens.py", tokens_path(copy, "gateway"), flip, "copies"),
            ("one byte of library's test_tokens.py", test_path(copy, "library"), flip, "copies"),
            (
                "inference-driver's test importing the agent's tokens",
                test_path(copy, "inference-driver"),
                reimport,
                "copies",
            ),
            ("an HS256 literal in library/settings.py", victim, append('ALG = "HS256"'), "residue"),
            (
                "an f-string service: audience in library/settings.py",
                victim,
                append('AUD = f"service:{ALG}"'),
                "residue",
            ),
        ]
        caught = 0
        for label, path, apply, which in cases:
            original = path.read_bytes()
            try:
                apply(path)
                assert path.read_bytes() != original, f"sabotage {label} changed nothing"
                copies, found = static_checks(copy)
                if which == "copies":
                    hit = bool(copies)
                else:
                    added = [f for f in found["library"] if f not in baseline_residue["library"]]
                    hit = any(f.startswith(victim.relative_to(copy).as_posix()) for f in added)
                if not hit:
                    raise SystemExit(f"ESCAPED sabotage: {label}")
                caught += 1
                print(f"CAUGHT {label}", flush=True)
            finally:
                path.write_bytes(original)
        after_copies, after_residue = static_checks(copy)
        assert after_copies == [] and after_residue == baseline_residue, "restore left a change"
        print(f"PASS {caught}/{len(cases)} sabotages caught; the restored copy passes again")
        return caught


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--polyrepo",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="the directory holding specs/, agent/, control/, ... as siblings",
    )
    parser.add_argument(
        "--sabotage",
        action="store_true",
        help="also prove (a) and (b) catch a flipped byte and a reintroduced HS256",
    )
    args = parser.parse_args()
    root = args.polyrepo.resolve()
    failures: list[str] = []
    checks = 0

    copies, found = static_checks(root)
    checks += 1
    if copies:
        failures.append("(a)")
        print("FAIL (a) the token module or its tests drifted:", flush=True)
        for problem in copies:
            print(f"    {problem}", flush=True)
    else:
        print(
            f"PASS (a) tokens.py is byte-identical in all {len(REPOS)} repos, and the "
            f"{len(REPOS)} test_tokens.py differ only in the import line",
            flush=True,
        )

    for repo in REPOS:
        checks += 1
        if found[repo]:
            failures.append(f"(b) {repo}")
            print(f"FAIL (b) {repo}/src still names the shared-key model:", flush=True)
            for finding in found[repo]:
                print(f"    {finding}", flush=True)
        else:
            print(f"PASS (b) {repo}/src names no HS256, shared key setting or service: audience")

    skipped = 0
    for repo in REPOS:
        checks += 1
        verdict, detail = run_tests(root, repo)
        print(f"{verdict} (c) {repo} tests/test_tokens.py: {detail}", flush=True)
        if verdict == "FAIL":
            failures.append(f"(c) {repo}")
        elif verdict == "SKIP":
            skipped += 1

    if args.sabotage:
        checks += 1
        sabotage(root)

    if failures:
        raise SystemExit(f"{len(failures)} of {checks} checks failed: {', '.join(failures)}")
    print(
        f"{checks - skipped}/{checks} checks passed" + (f", {skipped} skipped" if skipped else "")
    )


if __name__ == "__main__":
    main()
