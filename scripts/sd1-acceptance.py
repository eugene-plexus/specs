"""SD1 acceptance: speculative decoding for llama.cpp, Library -> agent -> engine.

docs/design/speculative-decoding.md, Troy's calls S1-S5. Real files and a real
llama-server on this machine's GPU, an agent and Library of its own on free
ports, and nothing of the live install touched:

* S1 the Library says what each model can draft with: a model with its own MTP
  head (`mtpHead`), and a separate MTP file beside another (`draftFiles`, role
  `draft`, skipped as a model with the reason `draft`).
* S2 a companion file outside the model's folder is refused at declaration.
* S3 a runtime declared with no speculation flags speculates anyway, with
  `ngram-mod` (S3: on everywhere), and shows it on the run.
* S4 "Draft with: the model's own head" starts as `ngram-mod,draft-mtp`, drafts,
  and the run shows the drafted and kept counts read from llama-server.
* S5 "Draft with: companion file" starts with `--spec-draft-model`, drafts, and
  shows the file.
* S6 admission reserves at least what the GPU measured while each ran (S4), and
  the numbers are printed.

Usage:
    python scripts/sd1-acceptance.py --server C:/sd1-acceptance/engine/b11719/llama-server.exe \
        --models C:/sd1-acceptance/models

`--models` must hold unsloth/Qwen3.5-9B-MTP-GGUF/Qwen3.5-9B-Q4_K_M.gguf and
ggml-org/Qwen3.6-27B-GGUF/{Qwen3.6-27B-Q4_K_M,mtp-Qwen3.6-27B-Q4_0}.gguf.
Clears every ambient EUGENE_PLEXUS_* variable, so it is safe beside a live agent.

`--from-discover` (library#13) gives the Library hard links to the two models
without the companion, and fetches the companion the way Discover does before
S1: D1 the catalogue offers ggml-org's MTP files as companions (and its DFlash
drafters as neither companions nor versions), and says where the owned 27B
sits; D2 the companion downloads alone into that folder. The links and the
download live in the run's temporary directory, so `--models` is only read.
"""

from __future__ import annotations

import argparse
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

HEAD_MODEL = "Qwen3.5-9B-Q4_K_M"
PLAIN_MODEL = "Qwen3.6-27B-Q4_K_M"
SIDECAR = "mtp-Qwen3.6-27B-Q4_0.gguf"
PLAIN_REPO = "ggml-org/Qwen3.6-27B-GGUF"
MODEL_FILES = (
    "unsloth/Qwen3.5-9B-MTP-GGUF/Qwen3.5-9B-Q4_K_M.gguf",
    f"{PLAIN_REPO}/Qwen3.6-27B-Q4_K_M.gguf",
)
EDIT_PROMPT = (
    "Add type hints to every function in this file and return the whole file, unchanged "
    "otherwise, in one code block.\n\n```python\n"
    + "\n\n".join(
        f"def step_{n}(items, limit):\n    out = []\n    for item in items:\n"
        f"        if len(out) >= limit:\n            break\n        out.append(item * {n})\n"
        "    return out\n"
        for n in range(1, 9)
    )
    + "```"
)
CONTEXT = 32768
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""), flush=True)
    if not ok:
        FAILURES.append(label)


def free_ports(count: int) -> list[int]:
    sockets = [socket.socket() for _ in range(count)]
    try:
        for s in sockets:
            s.bind(("127.0.0.1", 0))
        return [s.getsockname()[1] for s in sockets]
    finally:
        for s in sockets:
            s.close()


def gpu_used_bytes() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return int(out.strip().splitlines()[0]) * 1024**2


def gib(n: int | None) -> str:
    return "unknown" if n is None else f"{n / 1024**3:.2f} GiB"


def fetch_companion_through_discover(client: httpx.Client, proxy: str, wait: Any) -> None:
    """D1 and D2: what Discover shows for ggml-org's 27B, and its download."""
    listing = client.get(f"{proxy}/v1/catalogue/model", params={"repo": PLAIN_REPO})
    listing.raise_for_status()
    body = listing.json()
    drafts = {f["path"]: f for f in body.get("draftFiles") or []}
    labels = [c["label"] for c in body.get("candidates") or []]
    plain = next((c for c in body.get("candidates") or [] if c["label"] == "Q4_K_M"), {})
    owned = plain.get("alreadyOwned") or {}
    check(
        "D1 Discover offers the MTP files as companions, not the DFlash files as versions, "
        "and says where the owned 27B sits",
        SIDECAR in drafts
        and all(f["role"] == "draft" for f in drafts.values())
        and not any("dflash" in label.lower() for label in labels)
        and owned.get("root") is not None
        and owned.get("folder") == PLAIN_REPO,
        f"companions {sorted(drafts)}; versions {labels}; owned {owned}",
    )
    started = client.post(
        f"{proxy}/v1/downloads",
        json={
            "repo": PLAIN_REPO,
            "revision": body.get("resolvedCommit") or "main",
            "files": [SIDECAR],
            "root": owned.get("root"),
            "subdirectory": owned.get("folder"),
        },
    )
    if started.status_code >= 300:
        raise AssertionError(f"the companion download: {started.status_code} {started.text[:400]}")
    download_id = started.json()["id"]
    done = wait(
        lambda: (lambda d: d if d["state"] in ("done", "failed", "cancelled") else None)(
            client.get(f"{proxy}/v1/downloads/{download_id}").json()
        ),
        "the companion downloads",
        3600,
    )
    files = done.get("files") or []
    check(
        "D2 the companion downloads alone into the 27B's folder",
        done["state"] == "done"
        and len(files) == 1
        and Path(files[0]["destinationPath"]).parent.as_posix().endswith(PLAIN_REPO),
        f"{done['state']}: {[f.get('destinationPath') for f in files]} {done.get('error') or ''}",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--from-discover", action="store_true")
    args = parser.parse_args()
    server: Path = args.server.resolve()
    models: Path = args.models.resolve()

    with tempfile.TemporaryDirectory(prefix="ep-sd1-", ignore_cleanup_errors=True) as raw:
        directory = Path(raw)
        if args.from_discover:
            # Hard links: no copy of 21 GB, and the source folder is never written.
            linked = directory / "models"
            for relative in MODEL_FILES:
                (linked / relative).parent.mkdir(parents=True, exist_ok=True)
                os.link(models / relative, linked / relative)
            models = linked
        agent_port, library_port = free_ports(2)
        (directory / "engines").mkdir()
        (directory / "library.yaml").write_text(
            yaml.safe_dump({"logLevel": "INFO", "modelRoots": [str(models)]}), encoding="utf-8"
        )
        (directory / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "securityMode": "prompt_on_startup",
                    "engineBinaryRoots": [str(server.parent)],
                    "components": [
                        {
                            "name": "library",
                            "kind": "library",
                            "url": f"http://127.0.0.1:{library_port}",
                            "spawn": {"configFile": str(directory / "library.yaml")},
                        }
                    ],
                    "runtimes": [],
                }
            ),
            encoding="utf-8",
        )
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
        env.update(
            {
                "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(directory / "agent.yaml"),
                "EUGENE_PLEXUS_AGENT_BIND_HOST": "127.0.0.1",
                "EUGENE_PLEXUS_AGENT_BIND_PORT": str(agent_port),
                "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(directory / "engines"),
                "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
                "PYTHONUNBUFFERED": "1",
            }
        )
        log = (directory / "agent.log").open("wb")
        agent = subprocess.Popen(
            [sys.executable, "-m", "eugene_plexus_agent", "--unattended"],
            cwd=directory,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{agent_port}",
            timeout=120,
            trust_env=False,
            limits=httpx.Limits(keepalive_expiry=2.0),
        )

        def wait(fn, label: str, seconds: float = 120):  # type: ignore[no-untyped-def]
            deadline = time.perf_counter() + seconds
            last: object = None
            while time.perf_counter() < deadline:
                try:
                    got = fn()
                    last = got
                    if got:
                        return got
                except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError) as e:
                    last = e
                time.sleep(0.5)
            raise AssertionError(f"timed out: {label} ({last!r})")

        try:
            wait(lambda: client.get("/healthz").status_code == 200, "the agent answers")
            token = client.post(
                "/v1/auth/initialize", json={"passphrase": secrets.token_urlsafe(24)}
            ).json()["sessionToken"]
            client.headers["Authorization"] = f"Bearer {token}"
            proxy = "/api/proxy/library"
            wait(lambda: client.get(f"{proxy}/healthz").status_code == 200, "the library answers")

            def scan() -> None:
                client.post(f"{proxy}/v1/scan", json={"full": True})
                wait(
                    lambda: client.get(f"{proxy}/v1/scan").json()["state"] != "scanning",
                    "the scan finishes",
                    600,
                )

            scan()
            if args.from_discover:
                fetch_companion_through_discover(client, proxy, wait)
                scan()
            listed = {m["name"]: m for m in client.get(f"{proxy}/v1/models").json()["models"]}
            skipped = client.get(f"{proxy}/v1/scan").json().get("skipped") or []

            # S1 -------------------------------------------------------------
            head = listed[HEAD_MODEL]
            plain = listed[PLAIN_MODEL]
            head_spec = (head.get("gguf") or {}).get("speculation") or {}
            plain_spec = (plain.get("gguf") or {}).get("speculation") or {}
            draft = (plain_spec.get("draftFiles") or [{}])[0]
            check(
                "S1 the Library says what each model can draft with",
                head_spec.get("mtpHead") is True
                and head_spec.get("draftFiles") == []
                and plain_spec.get("mtpHead") is False
                and Path(draft.get("path", "")).name == SIDECAR
                and draft.get("kind") == "mtp"
                and any(f.get("role") == "draft" for f in plain.get("files") or [])
                and SIDECAR not in {Path(m["path"]).name for m in listed.values()}
                and any(
                    s.get("reason") == "draft" and Path(s["path"]).name == SIDECAR for s in skipped
                ),
                f"{HEAD_MODEL}: {head_spec}; {PLAIN_MODEL}: {plain_spec}",
            )

            def spec(name: str, model: dict[str, Any], flags: dict[str, Any]) -> dict[str, Any]:
                return {
                    "name": name,
                    "engine": "llama_cpp",
                    "modelPath": model["path"],
                    "binary": str(server),
                    "autoDriver": False,
                    "flags": {"contextSize": CONTEXT, **flags},
                }

            # S2 -------------------------------------------------------------
            elsewhere = str(Path(head["path"]).parent / SIDECAR)
            refused = client.post(
                "/v1/runtimes",
                json=spec(
                    "sd1-elsewhere",
                    plain,
                    {"draftWith": "companion", "draftModelPath": elsewhere},
                ),
            )
            check(
                "S2 a companion outside the model's folder is refused at declaration",
                refused.status_code == 400 and "model's own folder" in refused.text,
                f"{refused.status_code} {refused.text[:200]}",
            )

            def run(name: str, model: dict[str, Any], flags: dict[str, Any]) -> dict[str, Any]:
                body = spec(name, model, flags)
                admission = client.post("/v1/runtimes/admission", json=body).json()
                before = gpu_used_bytes()
                created = client.post("/v1/runtimes", json=body)
                if created.status_code != 201:
                    raise AssertionError(f"{name}: {created.status_code} {created.text[:400]}")
                runtime = wait(
                    lambda: (lambda r: r if r["status"] == "ready" else None)(
                        client.get(f"/v1/runtimes/{name}").json()
                    ),
                    f"{name} is ready",
                    900,
                )
                time.sleep(3)
                after = gpu_used_bytes()
                engine = httpx.Client(base_url=runtime["url"], timeout=600, trust_env=False)
                # A file asked back with a small change: the answer repeats it,
                # so the n-gram has something to propose. Thinking off, or the
                # tokens go to reasoning that repeats nothing.
                reply = engine.post(
                    "/v1/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": EDIT_PROMPT}],
                        "max_tokens": 512,
                        "seed": 7,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                ).json()
                timings = reply.get("timings") or {}
                # The agent reads the counters every 10 s: wait until it has
                # read them since the request, then judge the numbers.
                drafted_now = timings.get("draft_n") or 0
                shown = wait(
                    lambda: (
                        lambda s: (
                            s
                            if s
                            and s.get("draftedTokens") is not None
                            and s["draftedTokens"] >= drafted_now
                            else None
                        )
                    )(client.get(f"/v1/runtimes/{name}").json().get("speculation")),
                    f"{name} shows its drafting counts",
                    60,
                )
                final = client.get(f"/v1/runtimes/{name}").json()
                client.delete(f"/v1/runtimes/{name}")
                wait(
                    lambda: client.get(f"/v1/runtimes/{name}").status_code == 404,
                    f"{name} is removed",
                    60,
                )
                time.sleep(3)
                used = after - before if after is not None and before is not None else None
                print(
                    f"      {name}: admission requires {gib(admission.get('requiredBytes'))} "
                    f"({admission.get('basis')}), the GPU measured {gib(used)}; decode "
                    f"{timings.get('predicted_per_second', 0):.1f} tok/s; "
                    f"drafted {shown.get('draftedTokens')}, kept {shown.get('acceptedTokens')}",
                    flush=True,
                )
                return {
                    "argv": final.get("argv") or [],
                    "speculation": shown,
                    "admission": admission,
                    "used": used,
                }

            def spec_type(argv: list[str]) -> str | None:
                return argv[argv.index("--spec-type") + 1] if "--spec-type" in argv else None

            # S3 -------------------------------------------------------------
            default = run("sd1-default", head, {})
            check(
                "S3 a runtime with no speculation flags reuses repeated text, and says so",
                spec_type(default["argv"]) == "ngram-mod"
                and "--metrics" in default["argv"]
                and default["speculation"].get("types") == ["ngram-mod"]
                and (default["speculation"].get("draftedTokens") or 0) > 0,
                f"{spec_type(default['argv'])}, {default['speculation']}",
            )

            # S4 -------------------------------------------------------------
            own = run("sd1-own-head", head, {"draftWith": "mtpHead"})
            s = own["speculation"]
            check(
                "S4 the model's own head drafts, and the run shows how much it kept",
                spec_type(own["argv"]) == "ngram-mod,draft-mtp"
                and "--spec-draft-model" not in own["argv"]
                and s.get("types") == ["ngram-mod", "draft-mtp"]
                and (s.get("draftedTokens") or 0) > 0
                and 0 < (s.get("acceptedTokens") or 0) <= s["draftedTokens"],
                s,
            )

            # S5 -------------------------------------------------------------
            companion = run(
                "sd1-companion",
                plain,
                {"draftWith": "companion", "draftModelPath": draft["path"]},
            )
            s = companion["speculation"]
            check(
                "S5 a companion file drafts with --spec-draft-model, and the run names it",
                spec_type(companion["argv"]) == "ngram-mod,draft-mtp"
                and "--spec-draft-model" in companion["argv"]
                and Path(s.get("draftModelPath") or "").name == SIDECAR
                and (s.get("draftedTokens") or 0) > 0,
                s,
            )

            # S6 -------------------------------------------------------------
            for label, outcome in (("own head", own), ("companion", companion)):
                required = outcome["admission"].get("requiredBytes")
                used = outcome["used"]
                check(
                    f"S6 admission reserves at least what the GPU used drafting with the {label}",
                    required is not None and used is not None and required >= used,
                    f"required {gib(required)}, used {gib(used)}",
                )
        except Exception as exc:
            FAILURES.append(f"aborted: {type(exc).__name__}: {exc}")
            print(f"FAIL  aborted: {exc}", flush=True)
        finally:
            client.close()
            if os.name == "nt":
                agent.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                agent.terminate()
            try:
                agent.wait(timeout=60)
            except subprocess.TimeoutExpired:
                agent.kill()
            log.close()
            if FAILURES:
                print((directory / "agent.log").read_text(errors="replace")[-4000:])

    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
