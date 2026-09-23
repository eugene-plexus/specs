"""Sabotage pass: Anthropic's count_tokens, counted by the backend's own tokenizer.

2026-09-23. Restores from a COPY, never `git checkout --`, and opens with
a baseline on both gates (feedback memory: a restore that reverts
uncommitted work deletes the change under test, and every later result
reads *caught* for the wrong reason).

Two repos: the driver counts (llama.cpp's /apply-template + /tokenize),
the gateway decides who counts and what a refusal looks like.

The over-corrections this change invites:

* count a different prompt than a generation would send (no thinking
  directive, no tools), or drop the BOS the completion path adds;
* count an image from its template marker;
* call a healthy backend without a template endpoint "broken", or call a
  request the template rejects "cannot count";
* wake a sleeping model to count, or cross to a fallback tier's model;
* answer "cannot count" with a 5xx, which Claude Code retries first;
* admit (reserve, rate-charge) rather than check a key, or ignore its
  model scope or local-only policy.

An escape means the check set cannot tell the fix from its opposite.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")
UNIT_TIMEOUT = 900

GATEWAY = "gateway"
INFERENCE = "src/eugene_plexus_gateway/routes/inference.py"
DRIVER_CLIENT = "src/eugene_plexus_gateway/driver_client.py"
ADMISSION = "src/eugene_plexus_gateway/admission.py"

DRIVER = "inference-driver"
OPENAI_HTTP = "src/eugene_plexus_inference_driver/engines/openai_compat_http.py"
ROUTE = "src/eugene_plexus_inference_driver/routes/generate.py"

FILES = {GATEWAY: (INFERENCE, DRIVER_CLIENT, ADMISSION), DRIVER: (OPENAI_HTTP, ROUTE)}

GATES = {
    GATEWAY: (
        "tests/test_anthropic_count_tokens.py",
        "tests/test_anthropic_messages.py",
        "tests/test_admission.py",
        "tests/test_local_only.py",
    ),
    DRIVER: (
        "tests/test_token_count.py",
        "tests/test_generate_route.py",
        "tests/test_local_only.py",
    ),
}


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
    # --------------------------------------------------------------- #
    # driver
    # --------------------------------------------------------------- #
    (
        "the count drops the BOS the completion path adds",
        DRIVER,
        OPENAI_HTTP,
        'json={"content": prompt, "add_special": True},',
        'json={"content": prompt, "add_special": False},',
    ),
    (
        "the template is given a bare prompt, not what a generation sends",
        DRIVER,
        OPENAI_HTTP,
        "        payload = self._payload_for(request)\n        client = self._client()\n"
        "        try:\n            rendered = await client.post(\n",
        '        payload = {"messages": [m.model_dump(mode="json", exclude_none=True)'
        " for m in request.messages]}\n        client = self._client()\n"
        "        try:\n            rendered = await client.post(\n",
    ),
    (
        "an image counted from its template marker",
        DRIVER,
        OPENAI_HTTP,
        "        if has_images(request.messages):\n            raise TokenCountUnsupported(\n",
        "        if False:\n            raise TokenCountUnsupported(\n",
    ),
    (
        "OpenAI's own endpoint asked to render a template",
        DRIVER,
        OPENAI_HTTP,
        "        if _is_openai_endpoint(self._base_url):\n"
        "            raise TokenCountUnsupported(",
        "        if False:\n            raise TokenCountUnsupported(",
    ),
    (
        "a backend with no template endpoint reported as broken",
        DRIVER,
        OPENAI_HTTP,
        "            if rendered.status_code in (404, 405, 501):\n",
        "            if False:\n",
    ),
    (
        "a request the template rejects reported as cannot-count",
        DRIVER,
        OPENAI_HTTP,
        "            if rendered.status_code in (404, 405, 501):\n",
        "            if rendered.status_code >= 400:\n",
    ),
    (
        "an unreachable backend reported as cannot-count",
        DRIVER,
        OPENAI_HTTP,
        '            raise CliError(f"openai_compat_http token count failed: {e!r}") from e\n',
        '            raise TokenCountUnsupported(f"unreachable: {e!r}") from e\n',
    ),
    (
        "cannot-count answered as a backend failure",
        DRIVER,
        ROUTE,
        "        raise _cannot_count(str(e), kind_label) from e\n",
        "        raise _backend_error(CliError(str(e)), kind_label) from e\n",
    ),
    (
        "local-only not enforced before the count",
        DRIVER,
        ROUTE,
        "    _refuse_non_chat(engine)\n    enforce(engine, body.localOnly)\n"
        "    _refuse_unsupported_tools(engine, body)\n    kind_label = getattr(",
        "    _refuse_non_chat(engine)\n"
        "    _refuse_unsupported_tools(engine, body)\n    kind_label = getattr(",
    ),
    # --------------------------------------------------------------- #
    # gateway
    # --------------------------------------------------------------- #
    (
        "THE FINDING: the door counts nothing",
        GATEWAY,
        INFERENCE,
        '    return JSONResponse(content={"input_tokens": counted})\n',
        '    return _cannot_count(body.model, "not built")\n',
    ),
    (
        "a sleeping model woken to count",
        GATEWAY,
        INFERENCE,
        "    if client is None:\n        # Deliberately no wake.",
        "    lifecycle = _lifecycle(request)\n"
        "    if client is None and lifecycle is not None:\n"
        "        await lifecycle.wake(resolution)\n"
        "    if client is None:\n        # Deliberately no wake.",
    ),
    (
        "cannot-count answered with a 5xx, which Claude Code retries",
        GATEWAY,
        INFERENCE,
        '    return anthropic.error_response(\n        400,\n        f"Cannot count tokens',
        '    return anthropic.error_response(\n        503,\n        f"Cannot count tokens',
    ),
    (
        "a key admitted (reserved, rate-charged) instead of checked",
        GATEWAY,
        INFERENCE,
        "    await admission.authorize(request, None)\n",
        "    await admission.authorize(request, body.model)\n",
    ),
    (
        "a key's model scope ignored",
        GATEWAY,
        INFERENCE,
        "    resolution = await admission.permitted(table.resolve(body.model), "
        "requirements=generate)\n    if not resolution.has_backends():\n",
        "    resolution = table.resolve(body.model)\n    if not resolution.has_backends():\n",
    ),
    (
        "the count path left out of client admission",
        GATEWAY,
        ADMISSION,
        '        "/v1/messages/count_tokens",\n',
        "",
    ),
    (
        "an image sent to be counted",
        GATEWAY,
        INFERENCE,
        "    if has_images(body.messages):\n        return _cannot_count(",
        "    if False:\n        return _cannot_count(",
    ),
    (
        "the count crosses to a fallback tier's model",
        GATEWAY,
        DRIVER_CLIENT,
        "        tier = next((t for t in self._tiers if t), [])\n",
        "        tier = self.candidates\n",
    ),
    (
        "a replica that cannot count ends the search",
        GATEWAY,
        DRIVER_CLIENT,
        "                if exc.status_code == 400:\n                    raise\n"
        "                last = exc\n                continue\n",
        "                raise\n",
    ),
    (
        "a backend's 400 asked again of every replica",
        GATEWAY,
        DRIVER_CLIENT,
        "                if exc.status_code == 400:\n                    raise\n"
        "                last = exc\n",
        "                last = exc\n",
    ),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    backup = Path(tempfile.mkdtemp(prefix="count-tokens-sabotage-"))
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

    wanted = [s for s in SABOTAGES if not sys.argv[1:] or any(a in s[0] for a in sys.argv[1:])]
    caught = escaped = 0
    for label, repo, relative, old, new in wanted:
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

    print(f"\n{caught} caught, {escaped} escaped, {len(wanted)} sabotages")
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
