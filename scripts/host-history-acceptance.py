"""Host history, live: two nodes, a real load on the GPU, a node stopped.

`docs/design/host-history.md` (H1-H6). Real processes from the installed
packages: a control root, agent A on the root's machine and agent B, both
enrolled, both recording every 2 s. A runs a real llama-server on a real
model; B runs nothing. Temporary state only, loopback ports the OS picks
(never a default port), and no `EUGENE_PLEXUS_*` variable from the calling
shell reaches any process.

Needs this machine's GPU, so it runs here and not in CI:

    agent/.venv/Scripts/python.exe scripts/host-history-acceptance.py \\
        --server C:/sd1-acceptance/engine/b11719/llama-server.exe \\
        --model C:/sd1-acceptance/models/unsloth/Qwen3.5-9B-MTP-GGUF/Qwen3.5-9B-Q4_K_M.gguf

Checks, in order:

1.  Both agents record, and the console reads both through A's proxy
    (`node:<name>`): GPU memory, CPU, RAM and disk series with fresh
    readings, and every series that cannot be read says why.
2.  A model loaded on A: A's "held by Eugene" rises to at least 80% of the
    model file and `runtimesRunning` reads 1; B, on the same card, sees the
    card's memory rise and holds nothing itself.
3.  The model unloaded: A's share falls back under 256 MiB and the window
    shows the rise and the fall.
4.  B stopped: A's proxy says B is not answering; B started again records
    again, and B's window shows the stop as empty buckets (a gap) whose
    series are null, between recorded ones.
5.  Recording turned off on B: no new sample, the record still readable
    with `enabled: false`; DELETE empties it; turned on, it records again.
6.  Settings: an interval under 2 s is refused; the retention fields carry
    the store's size on disk.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

NODE_A = "hh-a"
NODE_B = "hh-b"
PROCESSES = ("control", "agent-a", "agent-b")
SAMPLE_SECONDS = 2
MiB = 1024**2

for _key in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
    del os.environ[_key]


def serve(kind: str, directory: Path, port: int, host: str) -> None:
    """One control root or one agent, until `directory/stop` appears."""
    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(
            Settings(config_file=directory / "control.yaml", state_dir=directory / "state")
        )
    else:
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings

        app = create_app(
            settings=Settings(
                config_file=directory / "agent.yaml", bind_port=port, default_topology=False
            )
        )
    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
    )

    async def run() -> None:
        task = asyncio.create_task(server.serve())
        while not task.done() and not (directory / "stop").exists():
            await asyncio.sleep(0.1)
        server.should_exit = True
        await task

    asyncio.run(run())


def routable_address() -> str:
    """The address this host would use to reach another; no packet is sent."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return str(probe.getsockname()[0])
    finally:
        probe.close()


def free_ports() -> dict[str, int]:
    sockets = []
    try:
        for _ in PROCESSES:
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return {n: s.getsockname()[1] for n, s in zip(PROCESSES, sockets, strict=True)}
    finally:
        for sock in sockets:
            sock.close()


def latest(history: dict[str, Any], metric: str, *, gpu: bool | None = None) -> float | None:
    for s in history["series"]:
        if s["metric"] == metric and (gpu is None or s["key"].startswith("gpu:cuda:")):
            return s.get("latest")
    return None


def series_of(history: dict[str, Any], metric: str) -> dict[str, Any] | None:
    return next(
        (s for s in history["series"] if s["metric"] == metric and s["key"].startswith("gpu:cuda:"))
        if metric.startswith("gpu")
        else (s for s in history["series"] if s["metric"] == metric),
        None,
    )


def exercise(root: Path, server: Path, model: Path) -> int:
    ports = free_ports()
    dirs = {"control": root / "root", "agent-a": root / "a", "agent-b": root / "b"}
    for directory in dirs.values():
        directory.mkdir()
    passphrase = secrets.token_urlsafe(24)
    model_bytes = model.stat().st_size
    # A's proxy refuses a node that advertises loopback (reachable only from
    # itself), so B listens on this machine's LAN address -- that address
    # only, not every interface -- and advertises it.
    lan = routable_address()
    hosts = {"control": "127.0.0.1", "agent-a": "127.0.0.1", "agent-b": lan}

    def base(name: str) -> str:
        return f"http://{hosts[name]}:{ports[name]}"

    for name, components in (
        ("agent-a", [{"name": "control", "kind": "control", "url": base("control")}]),
        ("agent-b", []),
    ):
        (dirs[name] / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "advertiseUrl": base(name),
                    "securityMode": "prompt_on_startup",
                    "hostHistorySampleSeconds": SAMPLE_SECONDS,
                    # The real llama-server lives outside the managed store.
                    "engineBinaryRoots": [str(server.parent)],
                    "components": components,
                }
            ),
            encoding="utf-8",
        )

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["EUGENE_PLEXUS_AGENT_ENGINE_ROOT"] = str(root / "engines")
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    processes: dict[str, subprocess.Popen] = {}
    logs: dict[str, Any] = {}
    passed: list[str] = []

    def start(name: str) -> None:
        directory = dirs[name]
        (directory / "stop").unlink(missing_ok=True)
        logs[name] = (root / f"{name}.log").open("a", encoding="utf-8")
        processes[name] = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                "control" if name == "control" else "agent",
                "--directory",
                str(directory),
                "--port",
                str(ports[name]),
                "--host",
                hosts[name],
            ],
            cwd=directory,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=logs[name],
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def stop(name: str) -> None:
        proc = processes.pop(name)
        (dirs[name] / "stop").touch()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False
                )
            else:
                proc.kill()
            proc.wait(timeout=10)
            raise AssertionError(f"{name} did not stop") from None
        finally:
            logs.pop(name).close()

    def ok(message: str) -> None:
        passed.append(message)
        print(f"PASS {message}", flush=True)

    with httpx.Client(trust_env=False, timeout=30) as client:

        def call(name: str, method: str, path: str, token: str | None = None, **kwargs: Any):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            return client.request(method, base(name) + path, headers=headers, **kwargs)

        def wait_for(check: Any, label: str, timeout: float = 60.0) -> Any:
            deadline = time.perf_counter() + timeout
            last: object = None
            while time.perf_counter() < deadline:
                try:
                    last = check()
                    if last:
                        return last
                except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                    last = exc
                dead = [n for n, p in processes.items() if p.poll() is not None]
                if dead:
                    raise AssertionError(f"{dead} exited while waiting for {label}")
                time.sleep(0.5)
            raise AssertionError(f"timed out after {timeout:.0f} s waiting for {label} ({last!r})")

        def login(name: str) -> str:
            response = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
            assert response.status_code == 200, f"{name} login: {response.status_code}"
            return response.json()["sessionToken"]

        def dump_logs() -> None:
            for name in PROCESSES:
                handle = logs.get(name)
                if handle is not None:
                    handle.flush()
                path = root / f"{name}.log"
                if path.exists():
                    tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
                    print(f"{name} log tail:\n" + "\n".join(tail), file=sys.stderr)

        try:
            # ---- setup: a root, A on its machine, B ---------------------------
            start("control")
            wait_for(lambda: call("control", "GET", "/healthz").status_code == 200, "root health")
            assert (
                call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
            ).status_code == 204
            session_root = login("control")
            call("control", "PATCH", "/v1/config", session_root, json={"nodePollIntervalSeconds": 2})
            joins = {}
            for name in ("agent-a", "agent-b"):
                response = call("control", "POST", "/v1/nodes/join-token", session_root, json={})
                assert response.status_code == 201, f"join token: {response.status_code}"
                joins[name] = response.json()["token"]
            for name, node in (("agent-a", NODE_A), ("agent-b", NODE_B)):
                start(name)
                wait_for(lambda n=name: call(n, "GET", "/healthz").status_code == 200, f"{name} health")
                response = call(name, "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
                assert response.status_code == 200, f"{name} initialize: {response.status_code}"
                response = call(
                    name,
                    "POST",
                    "/v1/node/enroll",
                    response.json()["sessionToken"],
                    json={"controlUrl": base("control"), "token": joins[name], "name": node},
                )
                assert response.status_code == 200, f"{name} enroll: {response.text}"
            session_a = login("agent-a")
            session_b = login("agent-b")
            wait_for(
                lambda: all(
                    n.get("reachable")
                    for n in call("control", "GET", "/v1/nodes", session_root).json()["nodes"]
                )
                and len(call("control", "GET", "/v1/nodes", session_root).json()["nodes"]) == 2,
                "the root's first probe of both nodes",
            )

            def history_a(**params: Any) -> dict[str, Any]:
                response = call("agent-a", "GET", "/v1/node/history", session_a, params=params)
                assert response.status_code == 200, f"A history: {response.status_code} {response.text}"
                return response.json()

            def via_proxy_b(**params: Any) -> httpx.Response:
                return call(
                    "agent-a", "GET", f"/api/proxy/node:{NODE_B}/v1/node/history", session_a,
                    params=params,
                )  # fmt: skip

            def history_b(**params: Any) -> dict[str, Any]:
                response = via_proxy_b(**params)
                assert response.status_code == 200, f"B via proxy: {response.status_code} {response.text[:600]}"
                return response.json()

            def fresh(history: dict[str, Any]) -> bool:
                at = history.get("latestAt")
                if not at:
                    return False
                age = time.time() - _parse(at)
                return age < 4 * SAMPLE_SECONDS

            # ---- 1. both record; the console reads both through A ------------
            a = wait_for(lambda: (lambda h: h if fresh(h) else None)(history_a()), "A's first samples")
            b = wait_for(lambda: (lambda h: h if fresh(h) else None)(history_b()), "B's first samples via A")
            for label, h in (("A", a), ("B", b)):
                metrics = {s["metric"] for s in h["series"]}
                need = {"gpuMemoryUsed", "gpuMemoryTotal", "gpuMemoryEugene", "cpuUtilization",
                        "ramUsed", "diskFree", "runtimesRunning"}  # fmt: skip
                assert need <= metrics, f"{label} lacks {need - metrics}"
                assert (latest(h, "gpuMemoryTotal", gpu=True) or 0) > 1024 * MiB, label
                assert h["sampleSeconds"] == SAMPLE_SECONDS and h["enabled"] is True, label
                silent = [s["key"] for s in h["series"] if s.get("latest") is None and not s.get("unavailable")]
                assert not silent, f"{label}: series with no reading and no reason: {silent}"
            unread = sorted({f"{s['metric']}: {s['unavailable']}" for s in a["series"] if s.get("unavailable")})
            ok(
                "both agents record every 2 s and the console reads both through A's proxy; "
                f"what A cannot read says why ({len(unread)}: {'; '.join(unread) or 'none'})"
            )

            # ---- 2. a model loaded on A ---------------------------------------
            spec = {
                "name": "hh-load",
                "engine": "llama_cpp",
                "modelPath": str(model),
                "binary": str(server),
                "autoDriver": False,
                "flags": {"contextSize": 4096},
            }
            before_b_used = latest(history_b(), "gpuMemoryUsed", gpu=True) or 0
            created = call("agent-a", "POST", "/v1/runtimes", session_a, json=spec)
            assert created.status_code == 201, f"create: {created.status_code} {created.text[:400]}"
            wait_for(
                lambda: call("agent-a", "GET", "/v1/runtimes/hh-load", session_a).json()["status"] == "ready",
                "the model is ready",
                600,
            )
            loaded = wait_for(
                lambda: (lambda h: h if (latest(h, "gpuMemoryEugene", gpu=True) or 0) >= 0.8 * model_bytes
                         and latest(h, "runtimesRunning") == 1 else None)(history_a()),
                "A's share follows the load",
            )  # fmt: skip
            share = latest(loaded, "gpuMemoryEugene", gpu=True) or 0
            b_loaded = wait_for(
                lambda: (lambda h: h if (latest(h, "gpuMemoryUsed", gpu=True) or 0) - before_b_used
                         >= 0.8 * model_bytes else None)(history_b()),
                "B sees the card fill",
            )  # fmt: skip
            assert (latest(b_loaded, "gpuMemoryEugene", gpu=True) or 0) < 256 * MiB, "B holds memory"
            ok(
                f"a model loaded on A: A holds {share / 1024**3:.1f} GiB of a "
                f"{model_bytes / 1024**3:.1f} GiB file and runs 1 runtime; B sees the card rise "
                f"by {((latest(b_loaded, 'gpuMemoryUsed', gpu=True) or 0) - before_b_used) / 1024**3:.1f} GiB "
                "and holds nothing"
            )

            # ---- 3. unloaded --------------------------------------------------
            loaded_at = time.time()
            assert call("agent-a", "DELETE", "/v1/runtimes/hh-load", session_a).status_code in (200, 204)
            wait_for(
                lambda: (lambda h: (latest(h, "gpuMemoryEugene", gpu=True) or 0) < 256 * MiB
                         and latest(h, "runtimesRunning") == 0)(history_a()),
                "A's share follows the unload",
            )  # fmt: skip
            window = history_a(**{"from": _iso(loaded_at - 120), "step": "raw"})
            eugene = series_of(window, "gpuMemoryEugene")
            assert eugene is not None
            values = [v for v in eugene["max"] if v is not None]
            assert max(values) >= 0.8 * model_bytes and values[-1] < 256 * MiB, values[-5:]
            ok(
                f"unloaded: A's share fell back to {values[-1] / MiB:.0f} MiB, and the window "
                f"shows the rise to {max(values) / 1024**3:.1f} GiB and the fall"
            )

            # ---- 4. B stopped: not answering, then a gap ----------------------
            stop("agent-b")
            stopped_at = time.time()
            refused = wait_for(
                lambda: (lambda r: r if r.status_code != 200 else None)(via_proxy_b()),
                "A's proxy to say B is not answering",
            )
            time.sleep(6 * SAMPLE_SECONDS)
            start("agent-b")
            wait_for(lambda: call("agent-b", "GET", "/healthz").status_code == 200, "B health again")
            session_b = login("agent-b")
            after = wait_for(
                lambda: (lambda h: h if fresh(h) else None)(history_b(**{"from": _iso(stopped_at - 20), "step": "raw"})),
                "B records again",
            )  # fmt: skip
            samples = [bucket["samples"] for bucket in after["buckets"]]
            used = series_of(after, "gpuMemoryUsed")
            assert used is not None
            gap = _longest_gap(samples)
            assert gap is not None and gap[1] - gap[0] >= 3, samples
            assert all(used["mean"][i] is None for i in range(*gap)), "a gap drew values"
            assert samples[gap[0] - 1] > 0 and samples[gap[1]] > 0, samples
            ok(
                f"B stopped: A's proxy answered {refused.status_code} "
                f"({_detail(refused)}); restarted, B's window shows the stop as "
                f"{gap[1] - gap[0]} empty buckets with null values between recorded ones"
            )

            # ---- 5. recording off, deleted, on --------------------------------
            patched = call("agent-b", "PATCH", "/v1/config", session_b, json={"hostHistoryEnabled": False})
            assert "hostHistoryEnabled" in patched.json().get("applied", []), patched.text
            frozen = history_b()["latestAt"]
            time.sleep(4 * SAMPLE_SECONDS)
            off = history_b()
            assert off["enabled"] is False and off["latestAt"] == frozen and off["series"], off["latestAt"]
            assert call("agent-b", "DELETE", "/v1/node/history", session_b).status_code == 204
            emptied = history_b()
            assert emptied["series"] == [] and emptied.get("latestAt") is None, emptied.get("latestAt")
            call("agent-b", "PATCH", "/v1/config", session_b, json={"hostHistoryEnabled": True})
            wait_for(lambda: fresh(history_b()), "B records again after being turned on")
            ok(
                "recording off on B: no new sample and the record still readable; DELETE "
                "emptied it; turned on, B records again"
            )

            # ---- 6. settings --------------------------------------------------
            refused_patch = call("agent-a", "PATCH", "/v1/config", session_a,
                                 json={"hostHistorySampleSeconds": 1}).json()  # fmt: skip
            assert any(r["key"] == "hostHistorySampleSeconds" for r in refused_patch["rejected"])
            fields = {
                f["key"]: f
                for f in call("agent-a", "GET", "/v1/config/schema", session_a).json()["fields"]
            }
            status = fields["hostHistoryHourDays"].get("status") or {}
            assert "MB on disk" in status.get("text", ""), status
            ok(f"settings: 1 s refused; the retention fields say \"{status['text']}\"")
        except BaseException:
            dump_logs()
            raise
        finally:
            for name in ("agent-b", "agent-a", "control"):
                if name in processes:
                    stop(name)
    return len(passed)


def _parse(iso: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _iso(ts: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


def _longest_gap(samples: list[int]) -> tuple[int, int] | None:
    """`(start, end)` of the longest run of empty buckets with a recorded
    bucket on each side."""
    best: tuple[int, int] | None = None
    i = 0
    while i < len(samples):
        if samples[i] == 0:
            j = i
            while j < len(samples) and samples[j] == 0:
                j += 1
            if i > 0 and j < len(samples) and (best is None or j - i > best[1] - best[0]):
                best = (i, j)
            i = j
        else:
            i += 1
    return best


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:120]
    detail = body.get("detail", body)
    if isinstance(detail, dict):
        detail = detail.get("detail") or detail.get("title") or detail
    return str(detail)[:160]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve", choices=("agent", "control"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--server", type=Path, help="llama-server binary")
    parser.add_argument("--model", type=Path, help="a GGUF the card can hold")
    args = parser.parse_args()
    if args.serve:
        assert args.directory is not None and args.port is not None
        serve(args.serve, args.directory, args.port, args.host)
        return
    if args.server is None or args.model is None:
        parser.error("--server and --model are required")
    with tempfile.TemporaryDirectory(prefix="ep-host-history-", ignore_cleanup_errors=True) as directory:
        count = exercise(Path(directory), args.server, args.model)
    print(f"{count}/{count} checks passed", flush=True)


if __name__ == "__main__":
    main()
