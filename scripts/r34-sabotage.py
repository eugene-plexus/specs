"""R3.4 sabotage pass: three contract sentences, across two repos.

Roadmap §4 item 4, review §6.2 #22. Restores from a COPY, never
`git checkout --`, and opens with a baseline on both gates.

Two repos, because the fix is two repos: the gateway has to put `topP`
and `seed` on the request and render a finish reason in each door's own
vocabulary, and the driver has to put them on the wire and stop folding
`content_filter` into `error`. A sabotage in one must be caught by that
repo's own gate -- a cross-repo fix whose only evidence is an end-to-end
run is one nobody can maintain.

**Every entry has a pair somewhere in the check set**, because each of
these three fixes has an over-correction that looks exactly like it from
one side:

* drop `top_p` for every model, not just the fixed-temperature ones;
* map every driver finish reason onto its vendor's nearest value,
  including `error`, for which no vendor has one;
* move every driver 4xx out of the caller's range, not the two that are
  about OUR credential.

So the sabotages come in kinds: put the finding back, put the
over-correction in, and take the discriminator apart. An escape means
the check set cannot tell the fix from its opposite, which is the defect
R3.3 found one slice ago and R1.6 found before that.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")

GATEWAY = "gateway"
INFERENCE = "src/eugene_plexus_gateway/routes/inference.py"
ANTHROPIC = "src/eugene_plexus_gateway/anthropic.py"

DRIVER = "inference-driver"
OPENAI_HTTP = "src/eugene_plexus_inference_driver/engines/openai_compat_http.py"
BASE = "src/eugene_plexus_inference_driver/engines/base.py"

FILES = {
    GATEWAY: (INFERENCE, ANTHROPIC),
    DRIVER: (OPENAI_HTTP, BASE),
}

# The gate per repo. Deliberately more than the new file in each: the
# 401's non-cascade lives in `test_failover.py` and `test_inference.py`,
# and a change to `_payload_for` is a change to every adapter test.
GATES = {
    GATEWAY: (
        "tests/test_request_path_contract.py",
        "tests/test_inference.py",
        "tests/test_failover.py",
        "tests/test_anthropic_messages.py",
        "tests/test_tool_calling.py",
    ),
    DRIVER: (
        "tests/test_sampling_and_filter.py",
        "tests/test_openai_api_adapter.py",
        "tests/test_adapters.py",
        "tests/test_generate_route.py",
    ),
}

UNIT_TIMEOUT = 900


def run_gate(repo: str) -> tuple[int, str]:
    py = ROOT / repo / ".venv" / "Scripts" / "python.exe"
    try:
        done = subprocess.run(
            [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", *GATES[repo]],
            cwd=ROOT / repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=UNIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:]


# (label, repo, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # ----------------------------------------------------------------- #
    # top_p and seed
    # ----------------------------------------------------------------- #
    (
        "THE FINDING: the gateway accepts top_p and puts it nowhere",
        GATEWAY,
        INFERENCE,
        "        topP=body.top_p,\n",
        "",
    ),
    (
        "THE FINDING: the gateway accepts seed and puts it nowhere",
        GATEWAY,
        INFERENCE,
        "        seed=body.seed,\n",
        "",
    ),
    (
        "the gateway invents an install default for top_p where none exists",
        GATEWAY,
        INFERENCE,
        "        topP=body.top_p,",
        "        topP=body.top_p if body.top_p is not None else 0.95,",
    ),
    (
        "THE FINDING one layer down: the driver takes topP and never sends it",
        DRIVER,
        OPENAI_HTTP,
        '            payload["top_p"] = float(request.topP)',
        "            pass",
    ),
    (
        "THE FINDING one layer down: the driver takes seed and never sends it",
        DRIVER,
        OPENAI_HTTP,
        '            payload["seed"] = int(request.seed)',
        "            pass",
    ),
    (
        "seed=0 is dropped, because the guard is truthiness rather than `is not None`",
        DRIVER,
        OPENAI_HTTP,
        "        if request.seed is not None:",
        "        if request.seed:",
    ),
    (
        "THE OVER-CORRECTION: top_p is dropped for every model, not the fixed ones",
        DRIVER,
        OPENAI_HTTP,
        "        if request.topP is not None and not self._temperature_is_fixed:",
        "        if False:",
    ),
    (
        "THE OVER-CORRECTION: a reasoning model loses its seed along with its sampler",
        DRIVER,
        OPENAI_HTTP,
        "        if request.seed is not None:",
        "        if request.seed is not None and not self._temperature_is_fixed:",
    ),
    (
        "a fixed-temperature model drops top_p and says nothing about it",
        DRIVER,
        OPENAI_HTTP,
        '            self._warn_dropped("top_p")',
        "            pass",
    ),
    (
        "the CLI drop-warning fires on every request instead of once per field",
        DRIVER,
        BASE,
        "        if value is None or field in warned:",
        "        if value is None:",
    ),
    (
        "the CLI drop-warning fires whether or not the caller asked for anything",
        DRIVER,
        BASE,
        "        if value is None or field in warned:",
        "        if field in warned:",
    ),
    # ----------------------------------------------------------------- #
    # content_filter
    # ----------------------------------------------------------------- #
    (
        "THE FINDING: the driver folds content_filter back into error",
        DRIVER,
        OPENAI_HTTP,
        '    "content_filter": FinishReason.content_filter,',
        '    "content_filter": FinishReason.error,',
    ),
    (
        "THE FINDING: the gateway flattens content_filter to a natural stop",
        GATEWAY,
        INFERENCE,
        '    "content_filter": FinishReason.content_filter,',
        '    "content_filter": FinishReason.stop,',
    ),
    (
        "THE OVER-CORRECTION: a broken backend is reported as a content filter",
        GATEWAY,
        INFERENCE,
        '    "error": FinishReason.stop,',
        '    "error": FinishReason.content_filter,',
    ),
    (
        "the Anthropic door reports a refusal as a natural end",
        GATEWAY,
        ANTHROPIC,
        '    "content_filter": "refusal",',
        '    "content_filter": "end_turn",',
    ),
    (
        "THE OVER-CORRECTION on the Anthropic door: a broken backend is a refusal",
        GATEWAY,
        ANTHROPIC,
        '    "error": "end_turn",',
        '    "error": "refusal",',
    ),
    (
        "an unknown finish reason stops falling back to `stop`",
        DRIVER,
        OPENAI_HTTP,
        'str(first.get("finish_reason") or "stop"), FinishReason.stop',
        'str(first.get("finish_reason") or "stop"), FinishReason.content_filter',
    ),
    # ----------------------------------------------------------------- #
    # a driver 401 is not the caller's bad request
    # ----------------------------------------------------------------- #
    (
        "THE FINDING: a driver 401 is blamed on the caller again",
        GATEWAY,
        INFERENCE,
        "    if upstream in (401, 403):",
        "    if False:",
    ),
    (
        "THE OVER-CORRECTION: every driver 4xx becomes an upstream auth failure",
        GATEWAY,
        INFERENCE,
        "    if upstream in (401, 403):",
        "    if 400 <= upstream < 500:",
    ),
    (
        "403 is left behind, so a wrong-audience token is still the caller's fault",
        GATEWAY,
        INFERENCE,
        "    if upstream in (401, 403):",
        "    if upstream == 401:",
    ),
    (
        "the refusal stops naming the driver whose credential was refused",
        GATEWAY,
        INFERENCE,
        "f\"The driver {e.driver_name!r} at {e.driver_url} refused the gateway's \"",
        'f"A driver refused the gateway\'s "',
    ),
    (
        "the error type goes back to the caller's vocabulary while the status stays 502",
        GATEWAY,
        INFERENCE,
        '            error_type="upstream_auth_error",\n        )\n    if 400 <= upstream < 500:',
        '            error_type="invalid_request_error",\n        )\n    if 400 <= upstream < 500:',
    ),
    (
        # The first version of this entry inserted `upstream = 400`
        # INSIDE the branch, which is dead code -- the branch had
        # already been taken and still returned 502. It escaped, and
        # what escaped was a no-op rather than a defect: the same
        # mistake R2.4's second pass made. A sabotage has to change an
        # answer, not a variable nobody reads again.
        "the status goes back to 400 while the error type stays honest",
        GATEWAY,
        INFERENCE,
        '        return _Failure(\n            code=502,\n            message=(\n'
        '                f"The driver {e.driver_name!r}',
        '        return _Failure(\n            code=400,\n            message=(\n'
        '                f"The driver {e.driver_name!r}',
    ),
    (
        "REGRESSION GUARD: a driver 401 starts cascading to the next backend",
        GATEWAY,
        INFERENCE,
        "    if upstream in (401, 403):",
        "    if upstream in (401, 403) and False:",
    ),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    backup = Path(tempfile.mkdtemp(prefix="r34-sabotage-"))
    for repo, relatives in FILES.items():
        for relative in relatives:
            destination = backup / repo / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / repo / relative, destination)
    print(f"copy in {backup}\n")

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
            print(f"[SKIP   ] {repo}: {label}: anchor matched {source.count(old)} times")
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
    if not ok:
        return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
