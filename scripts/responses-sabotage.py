"""Sabotage pass: the Responses door (slice 4) and the image limit, 2026-09-23.

Restores from a COPY, never `git checkout --`, and opens with a baseline on
every gate (feedback memory: a restore that reverts uncommitted work deletes
the change under test, and every later result reads *caught* for the wrong
reason).

Each sabotage is a way this door could be wrong about the client it exists
for, most of them measured against a real Codex CLI 0.130
(`docs/acceptance/responses-measurement.md`):

* refuse the `web_search` tool on every request, or drop it silently;
* refuse `detail: "high"`, which is on every image Codex sends;
* keep the 404 Codex retries five times, or keep the install's output cap
  whose `incomplete` Codex regenerates five times -- or drop the cap on
  every door, which is the over-correction;
* open the stream only at the first token, keep it alive with an SSE
  comment, or end a failure with a bare `error` event -- each measured to
  lose the stream or its message in Codex;
* code a failure so Codex retries what cannot succeed, or stops on what can;
* drop the reasoning or read someone else's; send `encrypted_content`
  unasked; lose a call id or a picture on the way in;
* refuse the stored-state fields silently, or accept an unknown field;
* leave the door out of admission, the body limit, CORS, or the pump
  running when the client has gone;
* and for the image limit: ignore the operator's setting on any door, or
  leave the driver's ceiling at four.

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
RESPONSES = "src/eugene_plexus_gateway/responses.py"
INFERENCE = "src/eugene_plexus_gateway/routes/inference.py"
ADMISSION = "src/eugene_plexus_gateway/admission.py"
IMAGES = "src/eugene_plexus_gateway/images.py"
APP = "src/eugene_plexus_gateway/app.py"
CORS = "src/eugene_plexus_gateway/cors.py"

DRIVER = "inference-driver"
DRIVER_IMAGES = "src/eugene_plexus_inference_driver/images.py"

FILES = {
    GATEWAY: (RESPONSES, INFERENCE, ADMISSION, IMAGES, APP, CORS),
    DRIVER: (DRIVER_IMAGES,),
}

GATES = {
    GATEWAY: (
        "tests/test_responses.py",
        "tests/test_images.py",
        "tests/test_anthropic_images.py",
        "tests/test_profile_defaults.py",
    ),
    DRIVER: ("tests/test_images.py",),
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


SABOTAGES: list[tuple[str, str, str, str, str]] = [
    (
        "web_search refused like any other server-side tool",
        GATEWAY,
        RESPONSES,
        '        if isinstance(kind, str) and kind.startswith("web_search"):\n',
        "        if False:\n",
    ),
    (
        "web_search removed silently, not named",
        GATEWAY,
        RESPONSES,
        '            ignored.append("tools.web_search")\n',
        "            pass\n",
    ),
    (
        "detail: high refused, as the chat door refuses it",
        GATEWAY,
        RESPONSES,
        '        ignored.append("input_image.detail")\n',
        '        raise Refusal(f"{where}.detail: only auto is supported.", param="input")\n',
    ),
    (
        "a model nothing serves stays a 404, which Codex retries five times",
        GATEWAY,
        RESPONSES,
        "    return 400 if status == 404 else status\n",
        "    return status\n",
    ),
    (
        "the model_not_found code dropped",
        GATEWAY,
        RESPONSES,
        '    if status == 404 or error_type == "model_not_found":\n        return "model_not_found"\n',
        "",
    ),
    (
        "a rejected key answered 400 rather than the OpenAI door's 401",
        GATEWAY,
        RESPONSES,
        "            status=e.status_code,\n",
        "            status=400,\n",
    ),
    (
        "the install cap applied on this door, whose incomplete Codex regenerates",
        GATEWAY,
        INFERENCE,
        '        request, body, surface="chat", instead="/v1/embeddings", install_max_tokens=False\n',
        '        request, body, surface="chat", instead="/v1/embeddings", install_max_tokens=True\n',
    ),
    (
        "the over-correction: the install cap dropped on every door",
        GATEWAY,
        INFERENCE,
        "        if max_tokens is None and install_max_tokens:\n",
        "        if max_tokens is None and False:\n",
    ),
    (
        "no keepalive while the backend is silent",
        GATEWAY,
        INFERENCE,
        "                if event is None:\n                    yield translator.keepalive()\n",
        "                if event is None:\n",
    ),
    (
        "the keepalive is an SSE comment, which Codex's idle timer ignores",
        GATEWAY,
        RESPONSES,
        '        return self.frame("response.in_progress", {"response": self._lean()})\n',
        '        return ": keepalive\\n\\n"\n',
    ),
    (
        "the stream says nothing until the first token",
        GATEWAY,
        INFERENCE,
        "    for chunk in translator.start():\n        yield chunk\n"
        "    with collect_attempts() as tries:\n",
        "    with collect_attempts() as tries:\n",
    ),
    (
        "a failure after the stream opened is a bare error event",
        GATEWAY,
        RESPONSES,
        '        events.append(self.frame("response.failed", {"response": response}))\n',
        '        events.append(self.frame("error", {"code": code, "message": message}))\n',
    ),
    (
        "an over-long prompt coded as retryable",
        GATEWAY,
        RESPONSES,
        '    if is_context_overflow(message):\n        return "context_length_exceeded"\n'
        '    if status in (502, 503) and error_type != "upstream_auth_error":\n',
        '    if status in (502, 503) and error_type != "upstream_auth_error":\n',
    ),
    (
        "every in-stream failure coded server_error, so Codex retries a fired deadline",
        GATEWAY,
        RESPONSES,
        '    if status in (502, 503) and error_type != "upstream_auth_error":\n'
        '        return "server_error"\n    return "invalid_prompt"\n',
        '    return "server_error"\n',
    ),
    (
        "the over-correction: every in-stream failure fatal, even a dead backend",
        GATEWAY,
        RESPONSES,
        '    if status in (502, 503) and error_type != "upstream_auth_error":\n'
        '        return "server_error"\n',
        "",
    ),
    (
        "the middleware's mid-stream refusal is the chat door's bare data frame",
        GATEWAY,
        ADMISSION,
        '                if scope["path"] == "/v1/responses":\n',
        "                if False:\n",
    ),
    (
        "the middleware's fired deadline coded server_error",
        GATEWAY,
        RESPONSES,
        "    if status in (401, 403, 504, 400):\n",
        "    if False:\n",
    ),
    (
        "sequence numbers never advance",
        GATEWAY,
        RESPONSES,
        "        self._sequence += 1\n",
        "",
    ),
    (
        "a streamed tool call's argument deltas dropped",
        GATEWAY,
        RESPONSES,
        "            if arguments:\n                call[\"arguments\"].append(arguments)\n",
        "            if False:\n                call[\"arguments\"].append(arguments)\n",
    ),
    (
        "an answer cut at the cap streamed as response.completed",
        GATEWAY,
        RESPONSES,
        '        name = "response.incomplete" if status == "incomplete" else "response.completed"\n',
        '        name = "response.completed"\n',
    ),
    (
        "items in a cut answer marked completed (batch)",
        GATEWAY,
        RESPONSES,
        '    item_status = "incomplete" if status == "incomplete" else "completed"\n    items',
        '    item_status = "completed"\n    items',
    ),
    (
        "adjacent user messages kept apart",
        GATEWAY,
        RESPONSES,
        "            and role in (Role1.user, Role1.system)\n",
        "            and role in ()\n",
    ),
    (
        "the over-correction: a later developer message hoisted into the system prompt",
        GATEWAY,
        RESPONSES,
        "            self._flush_hoisted()\n            self._append(Role1.system, parts)\n",
        "            self._flush_hoisted()\n"
        "            if self.messages and self.messages[0].role == Role1.system:\n"
        "                self.messages[0] = ChatCompletionMessage(\n"
        "                    role=Role1.system,\n"
        "                    content=_joined(_as_parts(self.messages[0].content) + parts),\n"
        "                )\n"
        "            else:\n"
        "                self._append(Role1.system, parts)\n",
    ),
    (
        "reasoning items dropped on the way in",
        GATEWAY,
        RESPONSES,
        "            conversation.reasoning(item)\n",
        "            pass\n",
    ),
    (
        "our encrypted_content not read back",
        GATEWAY,
        RESPONSES,
        '    return decode_signature(item.get("encrypted_content"))\n',
        "    return None\n",
    ),
    (
        "someone else's encrypted_content read as reasoning",
        GATEWAY,
        RESPONSES,
        '    return decode_signature(item.get("encrypted_content"))\n',
        '    return item.get("encrypted_content") or None\n',
    ),
    (
        "encrypted_content sent though include did not ask",
        GATEWAY,
        RESPONSES,
        "    if include_encrypted:\n",
        "    if True:\n",
    ),
    (
        "a call id replaced on the way in",
        GATEWAY,
        RESPONSES,
        '                id=call_id, type="function", function=FunctionCall(name=name, '
        "arguments=arguments)\n",
        '                id="call_x", type="function", function=FunctionCall(name=name, '
        "arguments=arguments)\n",
    ),
    (
        "view_image's picture dropped from the tool output",
        GATEWAY,
        RESPONSES,
        "                    pictures.append(_image_part(part, at, self.budget, self.ignored))\n",
        "                    pass\n",
    ),
    (
        "stored-state fields ignored rather than refused",
        GATEWAY,
        RESPONSES,
        "    for name, why in _STATEFUL.items():\n        if raw.get(name) is not None:\n",
        "    for name, why in _STATEFUL.items():\n        if False:\n",
    ),
    (
        "an unknown top-level field accepted",
        GATEWAY,
        RESPONSES,
        "        if name not in _TOP_LEVEL:\n",
        "        if False:\n",
    ),
    (
        "the keepalive pump left running when the client leaves",
        GATEWAY,
        RESPONSES,
        "        task.cancel()\n        await asyncio.gather(task, return_exceptions=True)\n",
        "        pass\n",
    ),
    (
        "the door left out of client admission",
        GATEWAY,
        ADMISSION,
        '        "/v1/responses",\n',
        "",
    ),
    (
        "the door left out of the body limit",
        GATEWAY,
        APP,
        '            "/v1/systemone",\n            "/v1/responses",\n',
        '            "/v1/systemone",\n',
    ),
    (
        "the door left out of CORS",
        GATEWAY,
        CORS,
        ', "/v1/messages", "/v1/responses"}',
        ', "/v1/messages"}',
    ),
    (
        "the operator's image limit ignored everywhere",
        GATEWAY,
        IMAGES,
        '        value = int(store.get("maxImagesPerRequest")) if store is not None '
        "else DEFAULT_MAX_IMAGES\n",
        "        value = DEFAULT_MAX_IMAGES\n",
    ),
    (
        "the chat door ignores the image setting",
        GATEWAY,
        INFERENCE,
        "            lambda: chat_contract.parse_request(raw, max_images=max_images(_store(request)))\n",
        "            lambda: chat_contract.parse_request(raw)\n",
    ),
    (
        "the Anthropic door ignores the image setting",
        GATEWAY,
        INFERENCE,
        "        body = anthropic.translate_request(raw, max_images=max_images(_store(request)))\n",
        "        body = anthropic.translate_request(raw)\n",
    ),
    (
        "the default image limit left at four",
        GATEWAY,
        IMAGES,
        "DEFAULT_MAX_IMAGES = 12\n",
        "DEFAULT_MAX_IMAGES = 4\n",
    ),
    (
        "the driver's image ceiling left at four",
        DRIVER,
        DRIVER_IMAGES,
        "MAX_IMAGES = 64\n",
        "MAX_IMAGES = 4\n",
    ),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    backup = Path(tempfile.mkdtemp(prefix="responses-sabotage-"))
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
