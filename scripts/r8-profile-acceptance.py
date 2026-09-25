"""R8/A2: real gateway + Library processes; fixture agent/drivers at the HTTP seam.

Uses disposable state and dynamically allocated loopback ports. No engines,
external providers, installed node state, or operator profiles are touched.
Run with a Python environment containing agent, gateway and library (editable
or pinned); the agent is imported for its token code and is not started.

Per-node token keys (2026-09-25, `docs/design/per-node-token-keys.md`). R8 has
never had a control root, and gains nothing from one: every claim here is about
a gateway reading one model's profile from the Library beside it. So the
authority is the smallest one the product has, a standalone agent, which is its
own authority as `node:local`. The script is that agent's key holder and runs
the agent's own code for it: `NodeIdentityStore.ensure_keypair` and
`NodeTrust.load`, the two calls the agent makes at boot, write `node.yaml` and a
self-signed `trust_bundle.json`; the gateway's and Library's service tokens are
`NodeTrust.mint_service` for this machine, as the supervisor mints them; the
operator session is `NodeTrust.mint_local_session`, the call a standalone
agent's login makes once the passphrase checks out. No agent process runs
because the fixture must stay the agent's HTTP surface (a real agent cannot
report a ready runtime without a real engine behind it), and a real login would
add only the passphrase check in front of that same call. Both real processes
are handed the four trust settings and verify every token against that bundle;
the new check proves it by refusing no bearer and a session signed by a key the
bundle does not list. The old `service:gateway` and `operator` audiences were
retired with the shared key, so no token here is hand-encoded any more.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

import httpx
import yaml


def serve(kind: str, root: Path, port: int, agent_url: str) -> None:
    import uvicorn

    if kind == "gateway":
        from eugene_plexus_gateway.app import create_app
        from eugene_plexus_gateway.settings import Settings
        app = create_app(Settings(config_file=root / "gateway.yaml", agent_url=agent_url))
    else:
        from eugene_plexus_library.app import create_app
        from eugene_plexus_library.settings import Settings
        app = create_app(Settings(config_file=root / "library.yaml", state_file=root / "state.json"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False))

    async def run() -> None:
        task = asyncio.create_task(server.serve())
        while not task.done() and not (root / f"{kind}.stop").exists():
            await asyncio.sleep(0.1)
        server.should_exit = True
        await task

    asyncio.run(run())


def standalone(directory: Path):
    """A standalone agent's trust, built by the agent's own boot sequence."""
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust

    directory.mkdir()
    identity = NodeIdentityStore(directory / "node.yaml")
    identity.load()
    identity.ensure_keypair()
    trust = NodeTrust(identity, directory / BUNDLE_FILE)
    trust.load()
    assert not trust.enrolled and trust.recipient == "node:local", trust.recipient
    assert trust.bundle_path.is_file(), "a standalone agent keeps its own bundle"
    return trust


def main() -> None:
    from eugene_plexus_library._generated.models import LibraryModel
    from eugene_plexus_library.store import StateStore

    with tempfile.TemporaryDirectory(prefix="ep-r8-") as directory:
        root = Path(directory)
        trust = standalone(root / "agent")
        service = {kind: trust.mint_service(sub=kind, audience=trust.recipient)[0]
                   for kind in ("gateway", "library")}
        operator, _ = trust.mint_local_session()
        # Well formed and correctly addressed, from a standalone agent this
        # install's bundle does not list: verification must refuse it.
        stranger, _ = standalone(root / "stranger").mint_local_session()
        model_path = str(root / "model.gguf")
        store = StateStore(root / "state.json")
        store.replace_models([LibraryModel(id="opaque-model", name="fixture", path=model_path,
            format="gguf", status="present", sizeBytes=0, files=[])], scanned_at=datetime.now(UTC))
        (root / "library.yaml").write_text("modelRoots: []\nscanOnStartup: false\n")
        (root / "gateway.yaml").write_text(yaml.safe_dump({"profileCacheSeconds": 0,
            "routingRefreshSeconds": 3600, "defaultMaxTokens": 2048, "defaultTemperature": 0.7,
            "modelSlots": [{"model": "fallback-test", "targets": ["friendly-alias", "fallback-alias"]}]}))
        sockets = [socket.socket() for _ in range(2)]
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        gateway_port, library_port = [sock.getsockname()[1] for sock in sockets]
        library_url = f"http://127.0.0.1:{library_port}"
        gateway_url = f"http://127.0.0.1:{gateway_port}"
        calls: list[dict] = []
        reads: list[str] = []
        state = {"outage": False, "fail_first": False}

        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def reply(self, data: object, code: int = 200, content_type: str = "application/json") -> None:
                body = json.dumps(data).encode() if content_type == "application/json" else str(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path.startswith("/api/proxy/library/"):
                    assert self.headers.get("Authorization") == f"Bearer {service['gateway']}"
                    reads.append(self.path)
                    if state["outage"]:
                        self.reply({"error": "fixture Library unavailable"}, 503)
                        return
                    response = httpx.get(library_url + self.path.removeprefix("/api/proxy/library"),
                        headers={"Authorization": self.headers["Authorization"]}, trust_env=False)
                    self.reply(response.json(), response.status_code)
                elif self.path == "/v1/components":
                    self.reply({"components": [{"name": "fixture-driver", "kind": "inference-driver",
                                                "url": agent_url + "/driver"},
                        {"name": "fallback-driver", "kind": "inference-driver",
                         "url": agent_url + "/fallback"}]})
                elif self.path == "/v1/runtimes":
                    self.reply({"runtimes": [{"name": "fixture-runtime", "modelAlias": "friendly-alias",
                        "modelPath": model_path, "localPath": "/wrong/local-copy.gguf", "status": "ready",
                        "engine": "llama_cpp", "host": "127.0.0.1", "port": 1}]})
                elif self.path.endswith("/v1/info"):
                    self.reply({"backend": "openai_compat_http", "modelId":
                                "fallback-alias" if self.path.startswith("/fallback/") else "friendly-alias",
                                "runtime": "fixture-runtime", "capabilities": {"supportedSettings": ["maxTokens", "temperature", "topP", "seed", "stop", "tools", "toolChoice", "responseFormat"]}})
                elif self.path == "/v1/node":
                    self.reply({"enrolled": False})
                else:
                    self.reply({}, 404)

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(body)
                if state["fail_first"] and self.path.startswith("/driver/"):
                    self.reply({"type": "about:blank", "title": "Fixture refused before work", "status": 503, "retryDisposition": "safe"}, 503)
                    return
                result = {"content": "profile-ok", "modelId": "friendly-alias",
                          "backend": "openai_compat_http", "finishReason": "stop"}
                if self.path.endswith("/stream"):
                    self.reply('event: token\ndata: {"text":"profile-ok"}\n\nevent: done\ndata: '
                               + json.dumps(result) + '\n\n', content_type="text/event-stream")
                else:
                    self.reply(result)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        agent_url = f"http://127.0.0.1:{server.server_port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        processes: dict[str, subprocess.Popen] = {}
        logs = []
        try:
            for sock in sockets:
                sock.close()
            for kind, port in (("library", library_port), ("gateway", gateway_port)):
                env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
                prefix = f"EUGENE_PLEXUS_{kind.upper()}_"
                # All four, exactly as the agent's supervisor hands a child.
                env[prefix + "TRUST_BUNDLE_FILE"] = str(trust.bundle_path)
                env[prefix + "TRUST_AUTHORITY"] = trust.authority
                env[prefix + "AUTH_RECIPIENT"] = trust.recipient
                env[prefix + "SERVICE_TOKEN"] = service[kind]
                log = (root / f"{kind}.log").open("w", encoding="utf-8")
                logs.append(log)
                processes[kind] = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                    "--serve", kind, "--directory", str(root), "--port", str(port),
                    "--agent-url", agent_url], env=env, cwd=root, stdout=log, stderr=subprocess.STDOUT)
                deadline = time.perf_counter() + 30
                while time.perf_counter() < deadline:
                    try:
                        if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1, trust_env=False).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise AssertionError(f"{kind} did not start")
            # Real verification, against the standalone bundle and nothing
            # else: a missing bearer and a stranger's session are refused by
            # both processes, and the bundle's own session is accepted.
            for target in (library_url + "/v1/models/opaque-model/profiles",
                           gateway_url + "/v1/models"):
                for label, bearer in (("no bearer", None), ("unlisted key", stranger),
                                      ("standalone session", operator)):
                    got = httpx.get(target, trust_env=False, timeout=15,
                                    headers={"Authorization": f"Bearer {bearer}"} if bearer else {})
                    expected = 200 if bearer == operator else 401
                    assert got.status_code == expected, (target, label, got.status_code, got.text)
            print("PASS gateway and Library verify against the node:local bundle: "
                  "no bearer and an unlisted key refused, its own session accepted", flush=True)
            with httpx.Client(headers={"Authorization": f"Bearer {operator}"}, trust_env=False, timeout=15) as client:
                url = library_url + "/v1/models/opaque-model/profiles"
                spec = {"name": "tuned", "engine": "llama_cpp", "maxTokens": 111,
                        "temperature": 0, "topP": 0.2}
                response = client.post(url, json=spec)
                response.raise_for_status()
                profile_id = response.json()["id"]

                def generate(endpoint="/v1/chat/completions", stream=False, **extra):
                    body = {"model": "friendly-alias", "messages": [{"role": "user", "content": "hi"}],
                            "stream": stream, **extra}
                    response = client.post(gateway_url + endpoint, json=body)
                    assert response.status_code == 200, response.text
                    assert "profile-ok" in response.text, response.text
                    return calls[-1]

                # A2 regression: actual HTTP and persisted profile, not a helper.
                client.put(url + "/" + profile_id, json={**spec, "maxTokens": 2048}).raise_for_status()
                evidence = []
                for field in ("max_completion_tokens", "max_tokens"):
                    for stream in (False, True):
                        for fallback in (False, True):
                            state["fail_first"] = fallback
                            before = len(calls)
                            generate(stream=stream, model="fallback-test" if fallback else "friendly-alias",
                                     **{field: 25})
                            forwarded = calls[before:]
                            assert len(forwarded) == (2 if fallback else 1), forwarded
                            assert all(call["maxTokens"] == 25 for call in forwarded), forwarded
                            assert all(call["callerSettings"] == ["maxTokens"] for call in forwarded), forwarded
                            evidence.append({"field": field, "stream": stream, "fallback": fallback,
                                             "driverLimits": [call["maxTokens"] for call in forwarded]})
                            if fallback:
                                # A6b keeps a failed primary cooling across requests.
                                # Restore it through both controlled probes before
                                # the next independent wire-shaping scenario.
                                state["fail_first"] = False
                                for _ in range(2):
                                    time.sleep(1.1)
                                    generate()

                state["fail_first"] = False
                print("PASS A2 persisted profile=2048; HTTP driver captures " + json.dumps(evidence), flush=True)
                schema = {"type": "json_schema", "json_schema": {"name": "answer", "strict": True,
                          "schema": {"type": "object", "properties": {"x": {"type": "integer"}},
                                     "required": ["x"], "additionalProperties": False}}}
                for stream in (False, True):
                    got = generate(stream=stream, response_format=schema, max_completion_tokens=25)
                    assert got["responseFormat"] == schema, got
                before = len(calls)
                for extra in ({"max_tokens": 25, "max_completion_tokens": 26},
                              {"max_completion_tokens": True}, {"reasoning_effort": "high"}):
                    refused = client.post(gateway_url + "/v1/chat/completions", json={
                        "model": "friendly-alias", "messages": [{"role": "user", "content": "SECRET"}], **extra})
                    assert refused.status_code == 400, refused.text
                    assert refused.json()["error"]["param"] in extra, refused.text
                    assert "SECRET" not in refused.text
                assert len(calls) == before
                print("PASS A2 structured-output wire and safe refusals before generation", flush=True)
                client.put(url + "/" + profile_id, json=spec).raise_for_status()

                for endpoint in ("/v1/chat/completions", "/v1/messages"):
                    for stream in (False, True):
                        extra = {"max_tokens": 37} if endpoint.endswith("messages") else {}
                        got = generate(endpoint, stream, **extra)
                        assert (got["maxTokens"], got["temperature"], got["topP"]) == (extra.get("max_tokens", 111), 0, 0.2), got
                print("PASS both protocols and streaming use persisted model defaults", flush=True)
                count = len(reads)
                got = generate(max_tokens=19, temperature=0, top_p=0, seed=0)
                assert (got["maxTokens"], got["temperature"], got["topP"], got["seed"]) == (19, 0, 0, 0)
                assert len(reads) == count
                print("PASS explicit values bypass Library and preserve zeroes", flush=True)
                spec.update(maxTokens=222, temperature=0.5)
                client.put(url + "/" + profile_id, json=spec).raise_for_status()
                assert generate()["maxTokens"] == 222
                # Leave enough time to observe stale reuse on a loaded Windows
                # runner. A one-second stale window could expire during the HTTP
                # request itself, correctly returning defaults and failing this
                # timing fixture. Still explicitly test expiry after the bound.
                client.patch(gateway_url + "/v1/config", json={"profileCacheSeconds": 1, "profileMaxStaleSeconds": 5}).raise_for_status()
                generate()
                state["outage"] = True
                time.sleep(1.1)
                assert generate()["maxTokens"] == 222
                time.sleep(5.1)
                assert generate()["maxTokens"] == 2048
                print("PASS edits, bounded stale reuse, and outage fallback", flush=True)
                state["outage"] = False
                time.sleep(5.1)  # finish the full backoff after the most recent failed read
                assert generate()["maxTokens"] == 222
                client.patch(gateway_url + "/v1/config", json={"profileCacheSeconds": 0}).raise_for_status()
                second = client.post(url, json={"name": "second", "engine": "llama_cpp",
                    "default": True, "maxTokens": 333})
                second.raise_for_status()
                assert generate()["maxTokens"] == 333
                client.delete(url + "/" + second.json()["id"]).raise_for_status()
                assert generate()["maxTokens"] == 222
                client.delete(url + "/" + profile_id).raise_for_status()
                assert generate()["maxTokens"] == 2048
                print("PASS recovery, default selection/promotion, and deletion", flush=True)
        except BaseException:
            for path in root.glob("*.log"):
                print(path.name, path.read_text(errors="replace")[-5000:])
            raise
        finally:
            for kind in processes:
                (root / f"{kind}.stop").touch()
            for proc in processes.values():
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            for log in logs:
                log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", choices=["gateway", "library"])
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--agent-url")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port, args.agent_url)
    else:
        main()
