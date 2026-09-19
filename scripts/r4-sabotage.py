"""R4 sabotage pass: every check must fail when its defect is put back.

Roadmap §5; records `docs/acceptance/anthropic-messages-measurement.md`
and `docs/acceptance/anthropic-messages-run.md`.

Restores from a COPY taken before anything is touched, never
`git checkout --`: that reverts uncommitted work, which in this repo
means deleting the change under test, after which every later result
reads *caught* for the wrong reason.

Opens with a baseline -- the gates pass unsabotaged -- because a
sabotage that "fails" against an already-red gate proves nothing.

**The first group puts back the design R4 was written with before the
measurement corrected it.** Refusing `thinking`, refusing an unknown
field, answering 401 for a bad key, answering 404 for an unknown model:
each was the plan, each would have passed a test suite written from the
documentation, and each breaks a real client. If a sabotage here escapes
it means the measurement is recorded in prose and nowhere a regression
can trip over it.

The second group takes the translation apart one property at a time --
the recursion into a `tool_result`, the `tool` role, the inbound
`tool_use` mapping, the stateful block indexing, the missing `[DONE]`.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")

GW_ANTHROPIC = "src/eugene_plexus_gateway/anthropic.py"
GW_ROUTE = "src/eugene_plexus_gateway/routes/inference.py"
GW_CORS = "src/eugene_plexus_gateway/cors.py"
UI_KEYS = "src/lib/clientKeys.ts"

GATEWAY = "gateway"
UI = "ui"

GATE_FILES = {
    GATEWAY: [
        "tests/test_anthropic_messages.py",
        # The OpenAI door is in the gate deliberately: R4's refactor
        # moved the routing phase out from under it, and a sabotage that
        # only the Anthropic tests can see would not notice the shared
        # half regressing.
        "tests/test_inference.py",
        "tests/test_tool_calling.py",
        "tests/test_client_keys.py",
    ],
}

UNIT_TIMEOUT = 300


def run_gate(gate: str) -> tuple[int, str]:
    try:
        if gate == UI:
            # **Through bash, and that is not a style choice.** Vitest
            # started from `cmd` -- as `shell=True`, as `cmd /c npx …`
            # and as `cmd /c npm run test` -- fails with *"Vitest failed
            # to find the current suite"* inside its own setup file,
            # while the identical command from bash passes 22 tests.
            # Three invocations reported a healthy gate as broken, which
            # would have made every sabotage below read "caught" for the
            # wrong reason. An instrument that reports a working product
            # as broken is this project's most expensive recurring
            # shape, and the baseline assertion is what caught it.
            done = subprocess.run(
                ["bash", "-c", "cd /d/py/eugene-plexus/ui && npx vitest run src/lib/clientKeys.test.ts"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=UNIT_TIMEOUT,
            )
        else:
            py = ROOT / gate / ".venv" / "Scripts" / "python.exe"
            done = subprocess.run(
                [
                    str(py), "-m", "pytest", "-q", "--no-header",
                    "-p", "no:cacheprovider", "-p", "no:randomly",
                    *GATE_FILES[gate],
                ],
                cwd=ROOT / gate,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=UNIT_TIMEOUT,
            )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-2500:] + (done.stderr or "")[-800:]


SABOTAGES: list[tuple[str, str, str, str, str, str]] = [
    # ---- R4 as designed, before the measurement corrected it -----------
    (
        "refuse `thinking` with a 400 naming the field (the design; breaks every real request)",
        GATEWAY, GW_ANTHROPIC,
        '    for name in _REFUSED_TOP_LEVEL:\n        if raw.get(name):',
        '    for name in (*_REFUSED_TOP_LEVEL, "thinking"):\n        if raw.get(name):',
        GATEWAY,
    ),
    (
        "refuse `thinking` by PRESENCE, which still breaks MAX_THINKING_TOKENS=0",
        GATEWAY, GW_ANTHROPIC,
        '    for name in _REFUSED_TOP_LEVEL:\n        if raw.get(name):',
        '    for name in (*_REFUSED_TOP_LEVEL, "thinking"):\n        if name in raw:',
        GATEWAY,
    ),
    (
        "a bad credential answers 401 again -- the status Claude Code retries for ever",
        GATEWAY, GW_ANTHROPIC,
        '            status=403,\n            kind="authentication_error",\n        ) from e',
        '            status=401,\n            kind="authentication_error",\n        ) from e',
        GATEWAY,
    ),
    (
        "no credential answers 401 again",
        GATEWAY, GW_ANTHROPIC,
        '            status=403,\n            kind="authentication_error",\n        )\n\n    assert',
        '            status=401,\n            kind="authentication_error",\n        )\n\n    assert',
        GATEWAY,
    ),
    (
        "an unknown model goes back to 404, whose body the client discards",
        GATEWAY, GW_ANTHROPIC,
        "    return 400 if openai_status == 404 else openai_status",
        "    return openai_status",
        GATEWAY,
    ),
    (
        "read only `Authorization`, so ANTHROPIC_API_KEY sees no credential at all",
        GATEWAY, GW_ANTHROPIC,
        '    api_key = request.headers.get("x-api-key")\n    if api_key:\n        return api_key.strip()',
        '    api_key = None\n    if api_key:\n        return api_key.strip()',
        GATEWAY,
    ),
    (
        "read only `x-api-key`, so ANTHROPIC_AUTH_TOKEN sees no credential at all",
        GATEWAY, GW_ANTHROPIC,
        '    header = request.headers.get("authorization")\n    if not header:\n        return None',
        '    header = None\n    if not header:\n        return None',
        GATEWAY,
    ),
    # ---- the translation, one property at a time -----------------------
    (
        "an image inside a tool_result stops being refused (the top-level-only walk)",
        GATEWAY, GW_ANTHROPIC,
        '        nested = _field(block, "content")\n'
        "        if isinstance(nested, list):\n"
        '            _refuse_unsupported_blocks(nested, where=f"{where} -> tool_result")',
        '        nested = None\n'
        "        if isinstance(nested, list):\n"
        '            _refuse_unsupported_blocks(nested, where=f"{where} -> tool_result")',
        GATEWAY,
    ),
    (
        "an image block is dropped rather than refused",
        GATEWAY, GW_ANTHROPIC,
        "        if kind in _REFUSED_BLOCK_TYPES:",
        "        if kind in set():",
        GATEWAY,
    ),
    (
        "a tool_result becomes the human speaking (step 6's defect, one protocol over)",
        GATEWAY, GW_ANTHROPIC,
        "                        role=Role1.tool,",
        "                        role=Role1.user,",
        GATEWAY,
    ),
    (
        "an assistant tool_use block is dropped, so a tool loop cannot continue",
        GATEWAY, GW_ANTHROPIC,
        '            elif kind == "tool_use":',
        '            elif kind == "tool_use_never":',
        GATEWAY,
    ),
    (
        "`is_error` is dropped, so a harness cannot see its own tool failed",
        GATEWAY, GW_ANTHROPIC,
        '    if _field(block, "is_error"):',
        "    if False:",
        GATEWAY,
    ),
    (
        "only the first system block is carried, so the real prompt is lost behind the billing header",
        GATEWAY, GW_ANTHROPIC,
        '    parts = [b.text for b in system if getattr(b, "text", None)]',
        '    parts = [b.text for b in system[:1] if getattr(b, "text", None)]',
        GATEWAY,
    ),
    (
        "a fifth stop_sequence is silently truncated instead of refused",
        GATEWAY, GW_ANTHROPIC,
        "    if body.stop_sequences and len(body.stop_sequences) > _MAX_STOP_SEQUENCES:",
        "    if False:",
        GATEWAY,
    ),
    (
        "a server-side tool is accepted, and fails when the model chooses it",
        GATEWAY, GW_ANTHROPIC,
        '        server_side = getattr(definition, "type", None)\n        if server_side:',
        "        server_side = None\n        if server_side:",
        GATEWAY,
    ),
    (
        "`any` maps to auto, so tool_choice stops meaning 'you must call one'",
        GATEWAY, GW_ANTHROPIC,
        '"any": ToolChoice.required',
        '"any": ToolChoice.auto',
        GATEWAY,
    ),
    # ---- the stream ----------------------------------------------------
    (
        "the stream carries OpenAI's [DONE] sentinel, which a strict client rejects",
        GATEWAY, GW_ANTHROPIC,
        '        out.append(frame("message_stop", {"type": "message_stop"}))\n        return out\n\n    def failed',
        '        out.append(frame("message_stop", {"type": "message_stop"}))\n'
        '        out.append("data: [DONE]\\n\\n")\n        return out\n\n    def failed',
        GATEWAY,
    ),
    (
        # Escaped the first pass, and it named a MISSING CHECK rather
        # than a weak fix. One streaming test streams only text and the
        # other only tool calls, so the nesting assertion never met a
        # second block and the index assertion never met an open text
        # one: each was correct about its own case and neither covered
        # the seam. `test_text_then_a_tool_call_closes_the_text_block_first`
        # drives the translator across it.
        "a text block is left open when a tool block opens (two open blocks at once)",
        GATEWAY, GW_ANTHROPIC,
        "                out.extend(self._close_text())\n                out.extend(self._close_tool_except(call_index))",
        "                out.extend(self._close_tool_except(call_index))",
        GATEWAY,
    ),
    (
        "every content block gets index 0, so two tool calls merge into one",
        GATEWAY, GW_ANTHROPIC,
        "                index = self._next_index\n                self._next_index += 1\n                self._tool_index[call_index] = index",
        "                index = 0\n                self._tool_index[call_index] = index",
        GATEWAY,
    ),
    (
        "message_start is emitted on acceptance, committing a model the cascade can still change",
        GATEWAY, GW_ROUTE,
        "                if not translator.started:\n"
        "                    # On the first DRIVER event, never on acceptance:",
        "                if translator.started:\n"
        "                    # On the first DRIVER event, never on acceptance:",
        GATEWAY,
    ),
    (
        "a mid-stream failure ends the stream with no error event and no message_stop",
        GATEWAY, GW_ROUTE,
        "            for chunk in translator.failed(str(e) or type(e).__name__):\n                yield chunk\n            return",
        "            return",
        GATEWAY,
    ),
    (
        "stop_reason tool_calls maps to end_turn, so an agent loop stops instead of dispatching",
        GATEWAY, GW_ANTHROPIC,
        '    "tool_calls": "tool_use",',
        '    "tool_calls": "end_turn",',
        GATEWAY,
    ),
    # ---- the envelope, the shared path, and CORS -----------------------
    (
        # The first version of this one was `headers={} or
        # envelope_headers(...)`, which is a NO-OP -- `{}` is falsy, so
        # `or` returns the right-hand side and the headers were set
        # exactly as before. It escaped because it sabotaged nothing.
        "the envelope headers are dropped, so nothing says which backend answered",
        GATEWAY, GW_ROUTE,
        "            headers=anthropic.envelope_headers(",
        "            headers={} if True else anthropic.envelope_headers(",
        GATEWAY,
    ),
    (
        "the Anthropic door stops recording, so GET /v1/metrics is blind to it (M8, again)",
        GATEWAY, GW_ROUTE,
        "        _record(\n"
        "            prepared.rec,\n"
        "            body,\n"
        "            tries,\n"
        "            served_model=served_model,",
        "        _noop = (\n"
        "            prepared.rec,\n"
        "            body,\n"
        "            tries,\n"
        "            served_model:=served_model,",
        GATEWAY,
    ),
    (
        "the OpenAI door starts answering 403 too, harmonising away the deliberate divergence",
        GATEWAY, "src/eugene_plexus_gateway/dependencies.py",
        '            status.HTTP_401_UNAUTHORIZED,\n            "Missing token",',
        '            status.HTTP_403_FORBIDDEN,\n            "Missing token",',
        GATEWAY,
    ),
    (
        "x-api-key drops out of the CORS allow-list, so a browser preflight passes and the request fails",
        GATEWAY, GW_CORS,
        '_DEFAULT_ALLOW_HEADERS = '
        '"authorization, content-type, x-api-key, anthropic-version, anthropic-beta"',
        '_DEFAULT_ALLOW_HEADERS = "authorization, content-type"',
        GATEWAY,
    ),
    (
        "/v1/messages leaves the CORS front door",
        GATEWAY, GW_CORS,
        '    {"/v1/models", "/v1/chat/completions", "/v1/embeddings", "/v1/messages"}',
        '    {"/v1/models", "/v1/chat/completions", "/v1/embeddings"}',
        GATEWAY,
    ),
    # ---- the recipe ----------------------------------------------------
    (
        "the recipe keeps the /v1, so Claude Code asks for /v1/v1/messages",
        UI, UI_KEYS,
        '  return s.baseUrl.replace(/\\/v1\\/?$/, "");',
        "  return s.baseUrl;",
        UI,
    ),
    (
        "the recipe names ANTHROPIC_API_KEY, which needs approval and loses to a subscription login",
        UI, UI_KEYS,
        "        `ANTHROPIC_AUTH_TOKEN=${s.key}`,",
        "        `ANTHROPIC_API_KEY=${s.key}`,",
        UI,
    ),
    (
        "the Claude Code recipe disappears again",
        UI, UI_KEYS,
        '      name: "Claude Code",',
        '      name: "Claude Code (hidden)",',
        UI,
    ),
]


def main() -> int:
    # A gate's own output carries box-drawing characters, and this box's
    # stdout is cp1252 by default -- so printing a failure crashed the
    # harness on the one path that matters.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    backup = Path(tempfile.mkdtemp(prefix="r4-sabotage-"))
    touched = {(repo, rel) for _, repo, rel, _, _, _ in SABOTAGES}
    for repo, rel in touched:
        dst = backup / repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / repo / rel, dst)
    print(f"copies in {backup}\n")

    gates = sorted({g for *_, g in SABOTAGES})
    failures = []
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[baseline] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            failures.append(f"baseline {gate}\n{out}")
    if failures:
        print("\nBASELINE FAILED - a sabotage result would mean nothing.")
        print("\n".join(failures))
        return 1
    print()

    caught = escaped = 0
    for label, repo, rel, old, new, gate in SABOTAGES:
        path = ROOT / repo / rel
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run_gate(gate)
        finally:
            shutil.copy2(backup / repo / rel, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}\n{out[-900:]}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")

    for gate in gates:
        code, out = run_gate(gate)
        print(f"[restored] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
