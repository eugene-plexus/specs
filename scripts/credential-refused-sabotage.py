"""Sabotage pass: a provider refusing a DRIVER's own key, across two repos.

Found 2026-09-28 by `b2-hosted-jev-check.py`: OpenRouter's 401 for an
invalid key reached the caller as a 400 `invalid_request_error`. The fix
is two repos — the driver classifies the refusal (`#backend-credential-
refused`, 502, terminal) and the gateway reports it as `upstream_auth_error`
naming the driver — so a sabotage in one must be caught by that repo's
own gate. Restores from a COPY, never `git checkout --`, and opens with a
baseline on both gates.

The kinds, as in R3.4: put the finding back; put the over-correction in
(every 4xx treated as ours, a flagged-content 403 treated as ours, the
cascade widened, the breaker tripped); and take away what makes the
message worth having (the provider's words, the next step, the driver's
name). An escape means the checks cannot tell the fix from its opposite.

Usage: python scripts/credential-refused-sabotage.py
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")

DRIVER = "inference-driver"
FAILURES = "src/eugene_plexus_inference_driver/failures.py"
GENERATE = "src/eugene_plexus_inference_driver/routes/generate.py"

GATEWAY = "gateway"
INFERENCE = "src/eugene_plexus_gateway/routes/inference.py"
CLIENT = "src/eugene_plexus_gateway/driver_client.py"

FILES = {DRIVER: (FAILURES, GENERATE), GATEWAY: (INFERENCE, CLIENT)}

GATES = {
    DRIVER: (
        "tests/test_credential_refused.py",
        "tests/test_failover_safety.py",
        "tests/test_context_window.py",
        "tests/test_decisions.py",
    ),
    GATEWAY: (
        "tests/test_request_path_contract.py",
        "tests/test_inference.py",
        "tests/test_failover.py",
        "tests/test_decisions.py",
    ),
}

NEW_BRANCH_TAIL = (
    "                f\"{detail} That driver's key is under Config -> {e.driver_name}.\"\n"
    "            ),\n"
    '            error_type="upstream_auth_error",\n'
)

SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # --- the finding back ---------------------------------------------------
    ("driver: the refusal is the caller's 400 again", DRIVER, GENERATE,
     "    refused = credential_refused(e)\n", "    refused = None\n"),
    ("gateway: the driver's new type is not recognised", GATEWAY, INFERENCE,
     'if e.problem is not None and str(e.problem.type or "").endswith("#backend-credential-refused"):',
     "if False:"),
    # --- the over-corrections -------------------------------------------------
    ("driver: every 4xx is our credential", DRIVER, FAILURES,
     "    if status in (401, 402):\n",
     "    if 400 <= status < 500 and status not in (408, 409, 425, 429):\n"),
    ("driver: a flagged-content 403 is our credential", DRIVER, FAILURES,
     "    if status == 403 and not _CONTENT_REFUSAL.search(str(error)):\n",
     "    if status == 403:\n"),
    ("driver: the refusal is cascade-safe", DRIVER, GENERATE,
     "                retryDisposition=RetryDisposition.terminal,\n                retryAfterSeconds=wait,",
     "                retryDisposition=RetryDisposition.safe,\n                retryAfterSeconds=wait,"),
    ("gateway: the refusal cascades", GATEWAY, CLIENT,
     '    return retry_disposition(exc) == "safe"\n',
     '    return retry_disposition(exc) == "safe" or "credential-refused" in str(\n'
     '        getattr(getattr(exc, "problem", None), "type", "")\n    )\n'),
    ("gateway: the refusal trips the breaker", GATEWAY, CLIENT,
     'failed=error is not None and retry_disposition(error) != "terminal",',
     "failed=error is not None,"),
    # --- the message worth having ---------------------------------------------
    ("driver: 402 is not a credential refusal", DRIVER, FAILURES,
     "    if status in (401, 402):\n", "    if status in (401,):\n"),
    ("driver: the provider's words are dropped", DRIVER, GENERATE,
     '({what}; HTTP {refused}): {e} "', '({what}; HTTP {refused}). "'),
    ("driver: the next step is dropped", DRIVER, GENERATE,
     'f"Nothing is wrong with the request. {step} a working API key on this driver."',
     'f""'),
    ("driver: a 402 reads as a bad key", DRIVER, GENERATE,
     'what = "the account behind its API key has no credit" if refused == 402 else "its API key"',
     'what = "its API key"'),
    ("driver: the retry hint is dropped", DRIVER, GENERATE,
     '            headers={"Retry-After": str(int(wait + 0.999))} if wait is not None else None,\n',
     "            headers=None,\n"),
    ("gateway: the driver is not named", GATEWAY, INFERENCE,
     'f"The driver {e.driver_name!r} at {e.driver_url} could not use its provider: "',
     'f"A driver could not use its provider: "'),
    ("gateway: the refusal is a generic upstream error", GATEWAY, INFERENCE,
     NEW_BRANCH_TAIL, NEW_BRANCH_TAIL.replace("upstream_auth_error", "upstream_error")),
    ("gateway: 'Outcome unknown' said twice again", GATEWAY, INFERENCE,
     'if retry_disposition(e) == "indeterminate" and "Outcome unknown" not in failure.message:',
     'if retry_disposition(e) == "indeterminate":'),
]

UNIT_TIMEOUT = 900


def run_gate(repo: str) -> tuple[int, str]:
    py = ROOT / repo / ".venv" / "Scripts" / "python.exe"
    try:
        done = subprocess.run(
            [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", *GATES[repo]],
            cwd=ROOT / repo, capture_output=True, text=True, timeout=UNIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, f"{repo}: gate timed out after {UNIT_TIMEOUT}s"
    return done.returncode, (done.stdout + done.stderr)[-3000:]


def main() -> int:
    backup = Path(tempfile.mkdtemp(prefix="ep-credential-sabotage-"))
    for repo, files in FILES.items():
        for relative in files:
            target = backup / repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / repo / relative, target)
    for repo in FILES:
        code, out = run_gate(repo)
        print(f"[baseline] {repo}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    print()
    caught = escaped = 0
    for label, repo, relative, old, new in SABOTAGES:
        path = ROOT / repo / relative
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[NO-OP  ] {repo}: {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run_gate(repo)
        finally:
            shutil.copy2(backup / repo / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {repo}: {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {repo}: {label}")
            escaped += 1
    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")
    ok = True
    for repo in FILES:
        code, out = run_gate(repo)
        print(f"[restored] {repo}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            ok = False
    shutil.rmtree(backup, ignore_errors=True)
    return 0 if ok and escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
