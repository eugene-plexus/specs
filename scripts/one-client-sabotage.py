"""R1.1 sabotage pass: every check must fail when its defect is put back.

Run it after `one-client-acceptance.sh`, and before believing either.
Roadmap §2.1; record `docs/acceptance/one-client-run.md` §3.


Every check in this slice must fail when the defect it names is put
back. Restores from a COPY taken before anything is touched, never
`git checkout --`: that reverts uncommitted work, which in this repo
means deleting the change under test, after which every later result
reads *caught* for the wrong reason.

Opens with a baseline: the gate passes unsabotaged. Without it, a
sabotage that "fails" proves nothing about the sabotage.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")

SABOTAGES = [
    # (label, repo, file, old, new, test selector)
    (
        "driver: a client per call again",
        "inference-driver",
        "src/eugene_plexus_inference_driver/engines/openai_compat_http.py",
        "        if self._http_client is None:\n            self._http_client = client_for(",
        "        if True:\n            self._http_client = client_for(",
        "tests/test_http_client_reuse.py::test_three_completions_build_one_client",
    ),
    (
        "driver: latency measured by response.elapsed again",
        "inference-driver",
        "src/eugene_plexus_inference_driver/engines/openai_compat_http.py",
        "            latencyMs=int((time.perf_counter() - started) * 1000),\n        )\n\n    async def stream(",
        "            latencyMs=int(response.elapsed.total_seconds() * 1000),\n        )\n\n    async def stream(",
        "tests/test_http_client_reuse.py::test_latency_brackets_the_whole_call_not_just_the_socket",
    ),
    (
        "driver: trust_env on for everything (httpx's default)",
        "inference-driver",
        "src/eugene_plexus_inference_driver/_http.py",
        '    kwargs.setdefault("trust_env", not is_internal(url))\n    kwargs.setdefault("verify", ssl_context())\n    return httpx.AsyncClient(**kwargs)',
        '    kwargs.setdefault("trust_env", True)\n    kwargs.setdefault("verify", ssl_context())\n    return httpx.AsyncClient(**kwargs)',
        "tests/test_http_client_reuse.py::test_a_loopback_engine_declines_an_ambient_proxy",
    ),
    (
        "driver: trust_env off for everything (the review's blanket rule)",
        "inference-driver",
        "src/eugene_plexus_inference_driver/_http.py",
        '    kwargs.setdefault("trust_env", not is_internal(url))\n    kwargs.setdefault("verify", ssl_context())\n    return httpx.AsyncClient(**kwargs)',
        '    kwargs.setdefault("trust_env", False)\n    kwargs.setdefault("verify", ssl_context())\n    return httpx.AsyncClient(**kwargs)',
        "tests/test_http_client_reuse.py::test_a_cloud_backend_still_honours_the_proxy",
    ),
    (
        # **Both guards, not one.** Disabling either half of a
        # double-checked lock changes nothing, because the other half
        # still guards -- two single-line attempts at this escaped, and
        # each time it was the sabotage that was wrong rather than the
        # check. Two checks catch the whole-guard version.
        "driver: the SSL context is rebuilt on every call",
        "inference-driver",
        "src/eugene_plexus_inference_driver/_http.py",
        "    global _CONTEXT\n    if _CONTEXT is None:\n        with _LOCK:\n"
        "            if _CONTEXT is None:\n                _CONTEXT = httpx.create_ssl_context()\n"
        "    return _CONTEXT",
        "    global _CONTEXT\n    _CONTEXT = httpx.create_ssl_context()\n    return _CONTEXT",
        "tests/test_http_client_reuse.py",
    ),
    (
        "gateway: a client per topology read again",
        "gateway",
        "src/eugene_plexus_gateway/routing.py",
        "            response = await self._json_client.get(url, headers=self._headers())",
        "            async with internal_client(timeout=_TOPOLOGY_TIMEOUT) as c:\n                response = await c.get(url, headers=self._headers())",
        "tests/test_http_client_reuse.py::test_a_routing_refresh_builds_no_clients_for_its_reads",
    ),
    (
        "gateway: one duration back on monotonic",
        "gateway",
        "src/eugene_plexus_gateway/routes/inference.py",
        "    arrived = time.perf_counter()",
        "    arrived = time.monotonic()",
        "tests/test_http_client_reuse.py::test_no_duration_in_this_component_is_measured_with_monotonic",
    ),
    (
        "gateway: the topology client outlives its table",
        "gateway",
        "src/eugene_plexus_gateway/routing.py",
        "        with contextlib.suppress(BaseException):\n            await self._json_client.aclose()",
        "        pass",
        "tests/test_http_client_reuse.py::test_the_topology_client_is_closed_with_the_table",
    ),
    (
        "agent: a client per readiness probe again",
        "agent",
        "src/eugene_plexus_agent/engines/base.py",
        '    return shared_internal_client("engine-probe")',
        "    from .._http import internal_client\n\n    return internal_client()",
        "tests/test_http_client_reuse.py::test_ten_readiness_probes_build_one_client",
    ),
    (
        "agent: the reentrant lock back to a plain one (the cold-start deadlock)",
        "agent",
        "src/eugene_plexus_agent/_http.py",
        "_LOCK = threading.RLock()",
        "_LOCK = threading.Lock()",
        "tests/test_http_client_reuse.py::test_a_cold_process_can_build_its_first_shared_client",
    ),
    (
        "agent: the browser proxy takes the user's proxy",
        "agent",
        "src/eugene_plexus_agent/routes/proxy.py",
        "        client = internal_client(timeout=_TIMEOUT, follow_redirects=False)",
        "        client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)",
        "tests/test_http_client_reuse.py::test_the_browser_proxy_client_declines_an_ambient_proxy",
    ),
    (
        "library: the hub loses the user's proxy",
        "library",
        "src/eugene_plexus_library/hub.py",
        "        self._client = client or egress_client(",
        "        self._client = client or internal_client(",
        "tests/test_http_client_reuse.py::test_the_hub_client_keeps_the_users_proxy",
    ),
]


def run(repo: str, selector: str) -> tuple[int, str]:
    py = ROOT / repo / ".venv" / "Scripts" / "python.exe"
    done = subprocess.run(
        [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", selector],
        cwd=ROOT / repo,
        capture_output=True,
        text=True,
        timeout=600,
    )
    return done.returncode, done.stdout[-1500:] + done.stderr[-500:]


def main() -> int:
    backup = Path(tempfile.mkdtemp(prefix="r11-sabotage-"))
    touched = {(repo, rel) for _, repo, rel, _, _, _ in SABOTAGES}
    for repo, rel in touched:
        dst = backup / repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / repo / rel, dst)
    print(f"copies in {backup}\n")

    # --- baseline: the gates pass unsabotaged -------------------------
    failures: list[str] = []
    for repo in sorted({r for _, r, _, _, _, _ in SABOTAGES}):
        code, out = run(repo, "tests/test_http_client_reuse.py")
        mark = "PASS" if code == 0 else "FAIL"
        print(f"[baseline] {repo}: {mark}")
        if code != 0:
            failures.append(f"baseline {repo}\n{out}")
    if failures:
        print("\nBASELINE FAILED - a sabotage result would mean nothing.")
        print("\n".join(failures))
        return 1
    print()

    caught = escaped = 0
    for label, repo, rel, old, new, selector in SABOTAGES:
        path = ROOT / repo / rel
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run(repo, selector)
        finally:
            shutil.copy2(backup / repo / rel, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}\n{out}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")

    # --- and the gates still pass after every restore -----------------
    for repo in sorted({r for _, r, _, _, _, _ in SABOTAGES}):
        code, out = run(repo, "tests/test_http_client_reuse.py")
        print(f"[restored] {repo}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
