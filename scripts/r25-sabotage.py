"""R2.5 sabotage pass: every check must fail when its defect is put back.

Run it after `still-computing-acceptance.sh`, and before believing
either. Roadmap §3.5; record `docs/acceptance/still-computing-run.md` §5.

Restores from a COPY taken before anything is touched, never
`git checkout --`: that reverts uncommitted work, which in this repo
means deleting the change under test, after which every later result
reads *caught* for the wrong reason.

Opens with a baseline -- all four gates pass unsabotaged -- because a
sabotage that "fails" against an already-red gate proves nothing.

**The first five entries are the findings themselves**, each put back the
way the repo actually had it, and each driven against the LIVE
processes: a real gateway cascading a real read timeout onto a real
second replica, a real driver reporting a real deadline as an anonymous
transport error, a real killed client leaving a real engine computing,
and a real agent restart eating a real operator's setting. The entries
after them take each fix apart one property at a time, on whichever gate
can see them.

**A gate that HANGS counts as caught, and one sabotage is there for
exactly that.** `Request.is_disconnected()` wedges when it is called
from a raw `asyncio.Task`, which is how this slice's first version was
written and how the driver's whole suite came to hang; putting it back
must be caught, and the only symptom is that the gate never returns.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")
SPECS = ROOT / "specs"

DRV_ENGINE = "src/eugene_plexus_inference_driver/engines/openai_compat_http.py"
DRV_ROUTE = "src/eugene_plexus_inference_driver/routes/generate.py"
DRV_SUB = "src/eugene_plexus_inference_driver/engines/_subprocess.py"
DRV_BASE = "src/eugene_plexus_inference_driver/engines/base.py"
DRV_CONF = "src/eugene_plexus_inference_driver/config.py"
DRV_DISC = "src/eugene_plexus_inference_driver/disconnect.py"

GW_CLIENT = "src/eugene_plexus_gateway/driver_client.py"
GW_ROUTE = "src/eugene_plexus_gateway/routes/inference.py"
GW_CONF = "src/eugene_plexus_gateway/config.py"
GW_ROUTING = "src/eugene_plexus_gateway/routing.py"
GW_DISC = "src/eugene_plexus_gateway/disconnect.py"

AG_COMP = "src/eugene_plexus_agent/companions.py"

DRIVER = "inference-driver"
GATEWAY = "gateway"
AGENT = "agent"
LIVE = "live"

GATE_FILES = {
    DRIVER: [
        "tests/test_backend_timeout.py",
        "tests/test_client_disconnect.py",
        # `test_embeddings.py` is here because it is the file the
        # `is_disconnected()` wedge actually hung on, and a gate that
        # cannot reproduce the trap cannot catch the sabotage that puts
        # it back. The wedge is order-dependent -- anyio cancel-scope
        # bookkeeping -- so the answer is more route tests, not a
        # cleverer one.
        "tests/test_embeddings.py",
        "tests/test_generate_route.py",
    ],
    GATEWAY: [
        "tests/test_timeout_is_not_a_failure.py",
        "tests/test_client_disconnect.py",
        "tests/test_failover.py",
    ],
    AGENT: [
        "tests/test_companion_config_is_the_operators.py",
        "tests/test_companions.py",
    ],
}

# A wedged gate is a caught sabotage, not a broken harness -- see the
# module docstring. 300 s is ~40x the slowest healthy unit gate here.
UNIT_TIMEOUT = 300
LIVE_TIMEOUT = 1800


def run_gate(gate: str) -> tuple[int, str]:
    try:
        if gate in GATE_FILES:
            py = ROOT / gate / ".venv" / "Scripts" / "python.exe"
            done = subprocess.run(
                [str(py), "-m", "pytest", "-q", "--no-header",
                 "-p", "no:cacheprovider", "-p", "no:randomly", *GATE_FILES[gate]],
                cwd=ROOT / gate,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=UNIT_TIMEOUT,
            )
        else:
            done = subprocess.run(
                ["bash", str(SPECS / "scripts" / "still-computing-acceptance.sh")],
                cwd=SPECS,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=LIVE_TIMEOUT,
            )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-2500:] + (done.stderr or "")[-800:]


SABOTAGES: list[tuple[str, str, str, str, str, str]] = [
    # ---- the findings, put back, against the live processes ------------
    (
        "gateway: a read timeout cascades again, so the prompt is recomputed (#13, THE finding)",
        GATEWAY, GW_CLIENT,
        "    if isinstance(exc, httpx.TimeoutException):\n        return False",
        "    if isinstance(exc, httpx.TimeoutException):\n        return True",
        LIVE,
    ),
    (
        "driver: a read timeout goes back to an anonymous transport error (#13's other half)",
        DRIVER, DRV_ENGINE,
        "        except httpx.TimeoutException as e:\n"
        "            raise _timed_out(e, self._timeout_seconds, \"the completion\") from e",
        "        except httpx.TimeoutException as e:\n"
        "            raise CliError(f\"openai_compat_http request failed: {e}\") from e",
        LIVE,
    ),
    (
        "gateway: a closed tab leaves the backend computing again (#16, THE finding)",
        GATEWAY, GW_ROUTE,
        "            response = await serve_while_connected(\n"
        "                request, client.generate(generate), what=\"a chat completion\"\n"
        "            )",
        "            response = await client.generate(generate)",
        LIVE,
    ),
    (
        "driver: the driver keeps the engine running for a caller that left (#16's other half)",
        DRIVER, DRV_ROUTE,
        "        return await serve_while_connected(request, engine.generate(body), "
        "what=\"a generation\")",
        "        return await engine.generate(body)",
        LIVE,
    ),
    (
        "agent: the boot reconcile overwrites the companion's config again (#13, durability)",
        AGENT, AG_COMP,
        "    document = _read_config(path) if path.exists() else {}",
        "    document = {}",
        LIVE,
    ),
    # ---- taking each fix apart, on the gate that can see it ------------
    (
        "gateway: a 504 from the driver cascades again",
        GATEWAY, GW_CLIENT,
        "        if exc.status_code == 504:\n            return False",
        "        if exc.status_code == 504:\n            return exc.status_code >= 500",
        GATEWAY,
    ),
    (
        # The over-correction: refusing to cascade a CONNECT timeout
        # turns a dead host into a dead slot, which is the one case
        # failover was built for.
        "gateway: a connect timeout stops cascading, so a dead host kills the slot",
        GATEWAY, GW_CLIENT,
        "    if isinstance(exc, httpx.ConnectTimeout):\n        return True",
        "    if isinstance(exc, httpx.ConnectTimeout):\n        return False",
        GATEWAY,
    ),
    (
        "gateway: the embeddings cascade recomputes a timeout too",
        GATEWAY, GW_CLIENT,
        "    if isinstance(exc, httpx.TimeoutException):\n        return False",
        "    if isinstance(exc, httpx.TimeoutException):\n        return True",
        GATEWAY,
    ),
    (
        "driver: BackendTimeout stops being a CliError, so every route handler misses it",
        DRIVER, DRV_SUB,
        "class BackendTimeout(CliError):",
        "class BackendTimeout(RuntimeError):",
        DRIVER,
    ),
    (
        "driver: a fired deadline answers 502 again, so the gateway cascades it",
        DRIVER, DRV_ROUTE,
        "            status_code=status.HTTP_504_GATEWAY_TIMEOUT,",
        "            status_code=status.HTTP_502_BAD_GATEWAY,",
        DRIVER,
    ),
    (
        # The measured symptom: `str(httpx.ReadTimeout(""))` is empty,
        # so the message was "openai_compat_http request failed: " and
        # stopped. Naming the exception class is not naming the knob.
        "driver: the timeout message drops the deadline and the setting",
        DRIVER, DRV_ENGINE,
        'f"openai_compat_http {what} did not answer within {limit_seconds:g}s "',
        'f"openai_compat_http {what} failed "',
        DRIVER,
    ),
    (
        "driver: a connect timeout becomes a BackendTimeout, so a dead host stops cascading",
        DRIVER, DRV_ENGINE,
        "        except httpx.ConnectTimeout as e:\n"
        "            # A host that never accepted the connection is a DEAD host,",
        "        except NotImplementedError as e:\n"
        "            # A host that never accepted the connection is a DEAD host,",
        DRIVER,
    ),
    (
        "driver: the streamed path loses the timeout identity",
        DRIVER, DRV_ENGINE,
        '            raise _timed_out(e, self._timeout_seconds, "the stream") from e',
        '            raise CliError(f"openai_compat_http stream failed: {e}") from e',
        DRIVER,
    ),
    (
        "driver: the embeddings path loses it too",
        DRIVER, DRV_ENGINE,
        '            raise _timed_out(e, self._timeout_seconds, "the embeddings request") from e',
        '            raise CliError(f"openai_compat_http embeddings failed: {e}") from e',
        DRIVER,
    ),
    # ---- the ORDER of the two deadlines --------------------------------
    (
        "driver: the deadline goes back below the gateway's, so the knob is inert again",
        DRIVER, DRV_BASE,
        "DEFAULT_REQUEST_TIMEOUT_SECONDS = 660.0",
        "DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0",
        DRIVER,
    ),
    (
        "gateway: the deadline goes back to 180 s, above the driver's",
        GATEWAY, GW_CONF,
        "DEFAULT_REQUEST_TIMEOUT_SECONDS = 600.0",
        "DEFAULT_REQUEST_TIMEOUT_SECONDS = 700.0",
        GATEWAY,
    ),
    (
        "gateway: RoutingTable types the number again instead of reading it",
        GATEWAY, GW_ROUTING,
        "        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,",
        "        request_timeout_seconds: float = 180.0,",
        GATEWAY,
    ),
    (
        "driver: one engine types the number again instead of reading it",
        DRIVER, DRV_ENGINE,
        "        timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,",
        "        timeout_seconds: float = 120.0,",
        DRIVER,
    ),
    (
        "driver: the schema default drifts from the constant",
        DRIVER, DRV_CONF,
        "            default=DEFAULT_REQUEST_TIMEOUT_SECONDS,",
        "            default=900,",
        DRIVER,
    ),
    # ---- the disconnect watcher ----------------------------------------
    (
        # Abandoning the task is not cancelling it. This is the version
        # that passes a check asserting only that the route came back,
        # which is why the checks assert what the BACKEND did.
        "gateway: the backend call is abandoned rather than cancelled",
        GATEWAY, GW_DISC,
        "    task.cancel()\n    # Awaited, not merely cancelled",
        "    # task.cancel()\n    # Awaited, not merely cancelled",
        GATEWAY,
    ),
    (
        "gateway: the cancellation is never awaited, so the socket may not have closed yet",
        GATEWAY, GW_DISC,
        "    with contextlib.suppress(asyncio.CancelledError, Exception):\n        await task",
        "    if False:\n        await task",
        LIVE,
    ),
    (
        # The false positive: a watcher that reports every request as
        # disconnected cancels live work. The control tests exist for it.
        "gateway: the watcher reports every request as gone",
        GATEWAY, GW_DISC,
        "            if message[\"type\"] == \"http.disconnect\":\n                return",
        "            if True:\n                return",
        GATEWAY,
    ),
    (
        # The trap this slice actually hit, and the only symptom is a
        # gate that never returns.
        "driver: the watcher goes back to Request.is_disconnected() and wedges",
        DRIVER, DRV_DISC,
        "        await request.body()\n        while True:\n"
        "            message = await request.receive()\n"
        "            if message[\"type\"] == \"http.disconnect\":\n                return",
        "        while True:\n            if await request.is_disconnected():\n"
        "                return\n            await asyncio.sleep(0.25)",
        DRIVER,
    ),
    (
        "driver: the streamed prefill is awaited unwatched again",
        DRIVER, DRV_ROUTE,
        "        first = await serve_while_connected(request, anext(stream), "
        "what=\"a streamed prefill\")",
        "        first = await anext(stream)",
        DRIVER,
    ),
    (
        "driver: the embeddings path is awaited unwatched",
        DRIVER, DRV_ROUTE,
        "        return await serve_while_connected(\n"
        "            request, engine.embed(list(body.input)), what=\"an embedding\"\n        )",
        "        return await engine.embed(list(body.input))",
        DRIVER,
    ),
    (
        "gateway: the embeddings path is awaited unwatched",
        GATEWAY, GW_ROUTE,
        "        result = await serve_while_connected(\n"
        "            request, client.embed(EmbedRequest(input=inputs)), "
        "what=\"an embeddings request\"\n        )",
        "        result = await client.embed(EmbedRequest(input=inputs))",
        GATEWAY,
    ),
    # ---- the companion config ------------------------------------------
    (
        "agent: `changed` goes back to meaning the bytes moved, so every boot restarts everything",
        AGENT, AG_COMP,
        "    changed = any(document.get(key) != value for key, value in managed.items())",
        "    changed = document != {**document, **managed} or True",
        AGENT,
    ),
    (
        "agent: an unreadable companion config takes the runtime down instead of degrading",
        AGENT, AG_COMP,
        "    except (OSError, yaml.YAMLError):\n        return {}",
        "    except NotImplementedError:\n        return {}",
        AGENT,
    ),
    (
        "agent: the managed keys stop being written, so a re-target never reaches the driver",
        AGENT, AG_COMP,
        "    document.update(managed)",
        "    document.update({})",
        AGENT,
    ),
]


def main() -> int:
    backup = Path(tempfile.mkdtemp(prefix="r25-sabotage-"))
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
            print(f"[ESCAPED] {label}\n{out}")
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
