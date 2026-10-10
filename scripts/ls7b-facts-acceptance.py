"""LS7b acceptance: the Library says what is known of a prepared model.

library-sources-and-engines.md §6.8 and §6.10 (B22 replaced, B26, B30, the
source list's order). A throwaway standalone agent on free loopback ports
supervises its own Library over one folder laid out as LS5's preparation
leaves it (LS7a's layout: a two-shard Flash-Next GGUF in its publisher's
folder, `Strata-data` beside it), with the provenance file taken away so the
model is added the way the console adds it. A fake managed Strata install
says it is v0.1.37. One fake hub on loopback (LS4's) stands for a company's
own hub; nothing reaches the internet.

  F1  the agent reads Strata's configuration back (`inspectPreparedModel`):
      its list entry's title, architecture and size, the context it was
      prepared for, how it runs, the source GGUF as the Library spells it,
      and every file beside the source, the MTP helper's marked shared and
      setup's unnamed intermediates left out;
  F2  added with that draft, the Library lists it with its title and
      context, its files measured on disk, its source linked and the source's
      architecture inherited, and nothing missing;
  F3  a provenance file that records none of it is listed with each missing
      fact named, with why;
  F4  the agent refuses a file Strata did not write (422, naming why) and a
      file outside the Library's folders;
  F5  B30: the node's Strata v0.1.37 is older than UD-IQ4_XS needs
      (v0.1.38, setup's own floor): the list entry says so, others do not;
  F6  a search answers in the source list's order, whatever a source's kind:
      the company hub first when it is first, the engines' lists first when
      they are.

Clears every ambient EUGENE_PLEXUS_* variable, so it is safe beside a live
install. Run with the agent and library installed (editable is fine).
"""

from __future__ import annotations

import importlib.util
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import yaml

HERE = Path(__file__).resolve().parent


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ls7 = _load("ls7", "ls7-copy-acceptance.py")
ls4 = _load("ls4", "ls4-sources-acceptance.py")
ls3 = ls7.ls3

FAILURES: list[str] = []
REPO, FIRST, SECOND = ls7.REPO, ls7.FIRST, ls7.SECOND


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  -- {detail}"), flush=True)
    if not ok:
        FAILURES.append(label)


def fake_managed_strata(engines: Path, version: str) -> None:
    """A managed install as the agent's store records one: the receipt and
    its executable (never run here)."""
    build = engines / "strata" / version
    build.mkdir(parents=True)
    binary = build / ("strata-server.exe" if os.name == "nt" else "strata-server")
    binary.write_bytes(b"")
    (build / "install.json").write_text(
        json.dumps({"version": version, "variant": "fake", "binary": binary.name}),
        encoding="utf-8",
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    corp_port, agent_port, library_port = ls4.free_ports(3)
    hub = ThreadingHTTPServer(("127.0.0.1", corp_port), ls4.hub_handler("corp"))
    threading.Thread(target=hub.serve_forever, daemon=True).start()
    corp = f"http://127.0.0.1:{corp_port}"
    with tempfile.TemporaryDirectory(prefix="ep-ls7b-", ignore_cleanup_errors=True) as raw:
        # Long names: a CI runner's temp folder is its 8.3 short name.
        directory = Path(raw).resolve()
        models = directory / "share"
        models.mkdir()
        made = ls7.lay_out(models)
        made.unlink()  # added below, as the console adds it
        data = models / "Strata-data"
        entry = data / "strata-iq2_xs.json"
        engines_root = directory / "engines"
        fake_managed_strata(engines_root, "v0.1.37")
        (directory / "library.yaml").write_text(
            yaml.safe_dump({"logLevel": "INFO", "modelRoots": [str(models)]}), encoding="utf-8"
        )
        (directory / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "securityMode": "prompt_on_startup",
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
                "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(engines_root),
                "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
                "PYTHONUNBUFFERED": "1",
                "NO_PROXY": "127.0.0.1,localhost",
            }
        )
        log_path = directory / "agent.log"
        log = log_path.open("wb")
        agent = subprocess.Popen(
            [sys.executable, "-m", "eugene_plexus_agent", "--unattended"],
            cwd=directory,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        client = httpx.Client(base_url=f"http://127.0.0.1:{agent_port}", timeout=60, trust_env=False)

        def wait(fn, label: str, seconds: float = 90):  # type: ignore[no-untyped-def]
            deadline = time.perf_counter() + seconds
            last: object = None
            while time.perf_counter() < deadline:
                try:
                    got = fn()
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

            def models_now() -> dict[str, dict[str, Any]]:
                client.post(f"{proxy}/v1/scan", json={"full": True})
                wait(
                    lambda: client.get(f"{proxy}/v1/scan").json()["state"] != "scanning",
                    "the scan finishes",
                )
                return {m["name"]: m for m in client.get(f"{proxy}/v1/models").json()["models"]}

            source = next(m for m in models_now().values() if m["path"].endswith(FIRST))

            # F1 -----------------------------------------------------------
            inspect = "/v1/engines/strata/prepared/inspect"
            answer = client.post(inspect, json={"entry": str(entry)})
            draft = answer.json() if answer.status_code == 200 else {}
            files = {f["path"]: f for f in draft.get("files") or []}
            wanted = {
                "strata-iq2_xs.json",
                "packs/iq2_xs/dense.bin",
                "packs/iq2_xs/expert-profile.bin",
                "packs/iq2_xs/tokenizer/merges.txt",
                "packs/iq2_xs/tokenizer/token_type.json",
                "packs/iq2_xs/tokenizer/vocab.json",
                "mtp/rt/experts.bin",
            }
            check(
                "F1 Strata's configuration read back: its list entry, context, mode and source",
                answer.status_code == 200
                and draft.get("title") == "Qwen3.8-Flash-Next IQ2_XS"
                and draft.get("architecture") == "qwen4exp"
                and draft.get("quantization") == "IQ2_XS"
                and draft.get("contextLength") == 8192
                and draft.get("mode") == "every expert in RAM"
                and Path(draft.get("source", {}).get("path", "")) == models / REPO / FIRST
                and draft.get("source", {}).get("repoId") == REPO,
                answer.text[:500],
            )
            check(
                "F1 every file beside the source, sized, the MTP helper shared, setup's "
                "intermediates and the GGUF shards left out",
                set(files) == wanted
                and files["mtp/rt/experts.bin"].get("shared") is True
                and not files["packs/iq2_xs/dense.bin"].get("shared")
                and files["packs/iq2_xs/dense.bin"].get("sizeBytes") == 4096,
                sorted(files),
            )

            # F2 -----------------------------------------------------------
            added = client.post(
                f"{proxy}/v1/models/prepared",
                json={"name": "flash-iq2", "provenance": draft},
            )
            model = added.json() if added.status_code == 201 else {}
            written = data / f"flash-iq2{ls3.SUFFIX}"
            on_disk = json.loads(written.read_text(encoding="utf-8")) if written.is_file() else {}
            detail = model.get("prepared") or {}
            own = sum((data / p).stat().st_size for p in wanted) + (
                written.stat().st_size if written.is_file() else 0
            )
            check(
                "F2 added with the draft: the provenance file records what Strata read",
                added.status_code == 201
                and on_disk.get("title") == "Qwen3.8-Flash-Next IQ2_XS"
                and on_disk.get("contextLength") == 8192
                and {f["path"] for f in on_disk.get("files") or []} == wanted,
                added.text[:400],
            )
            listed = models_now().get("flash-iq2") or {}
            listed_detail = listed.get("prepared") or {}
            check(
                "F2 the Library lists it with its title, context and measured files, its "
                "source linked and that model's architecture, nothing missing",
                listed.get("displayName") == "Qwen3.8-Flash-Next IQ2_XS"
                and listed.get("contextLength") == 8192
                and listed.get("architecture") == "qwen4exp"
                and listed_detail.get("diskBytes") == own == listed.get("sizeBytes")
                and listed_detail.get("sourceModelId") == source["id"]
                and listed_detail.get("mode") == "every expert in RAM"
                and not listed_detail.get("missing")
                and str(data / "packs" / "iq2_xs" / "dense.bin")
                in {f["path"] for f in listed.get("files") or []},
                {k: listed.get(k) for k in ("displayName", "contextLength", "architecture",
                                            "sizeBytes", "prepared")} | {"own": own, "detail": detail},
            )

            # F3 -----------------------------------------------------------
            (data / f"bare{ls3.SUFFIX}").write_text(
                json.dumps({"engine": "strata", "entry": "strata-iq2_xs.json"}), encoding="utf-8"
            )
            bare = (models_now().get("bare") or {}).get("prepared") or {}
            why = {m["fact"]: m["reason"] for m in bare.get("missing") or []}
            check(
                "F3 one that records nothing names each missing fact, with why",
                set(why) == {"files", "source", "architecture", "contextLength"}
                and "prepare it again" in why["files"]
                and "without naming the model it was made from" in why["source"],
                bare,
            )

            # F4 -----------------------------------------------------------
            notes = data / "notes.json"
            notes.write_text('{"hello": 1}', encoding="utf-8")
            refused = client.post(inspect, json={"entry": str(notes)})
            elsewhere = directory / "elsewhere"
            elsewhere.mkdir()
            outside = elsewhere / "strata-iq2_xs.json"
            outside.write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
            away = client.post(inspect, json={"entry": str(outside)})
            check(
                "F4 a file Strata did not write is refused, naming why; one outside the "
                "Library's folders is not read",
                refused.status_code == 422
                and "no `args` list" in refused.text
                and away.status_code == 400
                and "Not a Library model" in away.text,
                (refused.status_code, refused.text[:200], away.status_code, away.text[:200]),
            )

            # F5 -----------------------------------------------------------
            engines = client.get("/v1/engines").json()["engines"]
            strata = next(e for e in engines if e["engine"] == "strata")
            listed_models = {m["id"]: m for m in strata.get("supportedModels") or []}
            unsloth = (listed_models.get("unsloth-UD-IQ4_XS") or {}).get("preparation") or {}
            iq2 = (listed_models.get("IQ2_XS") or {}).get("preparation") or {}
            check(
                "F5 B30: Strata v0.1.37 here is older than UD-IQ4_XS needs (v0.1.38), and says "
                "so on that entry only",
                strata.get("version") == "v0.1.37"
                and unsloth.get("minEngineVersion") == "v0.1.38"
                and unsloth.get("engineTooOld") == "v0.1.37"
                and iq2.get("engineTooOld") is None
                and iq2.get("minEngineVersion") is None,
                (strata.get("version"), unsloth, iq2),
            )

            # F6 -----------------------------------------------------------
            lists = ls4.as_console_lists(engines)
            corp_source = {"id": "corp", "kind": "hf_hub", "label": "Corp", "address": corp}
            engine_source = {"id": "engines", "kind": "engine_list", "label": "Engines"}

            def order_with(sources: list[dict[str, Any]]) -> list[str]:
                patched = client.patch(f"{proxy}/v1/config", json={"catalogueSources": sources})
                if patched.status_code != 200:
                    raise AssertionError(f"sources refused: {patched.text[:300]}")
                page = client.post(
                    f"{proxy}/v1/catalogue/search", json={"limit": 30, "engines": lists}
                ).json()
                return [r.get("source") for r in page.get("results") or []]

            hub_first = order_with([corp_source, engine_source])
            lists_first = order_with([engine_source, corp_source])
            check(
                "F6 results come in the list's order, whatever a source's kind",
                hub_first == ["corp"] + ["engines"] * 9
                and lists_first == ["engines"] * 9 + ["corp"],
                (hub_first, lists_first),
            )
        finally:
            if os.name == "nt":
                agent.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                agent.terminate()
            try:
                agent.wait(timeout=60)
            except subprocess.TimeoutExpired:
                agent.kill()
                print("WARN  the agent did not stop in 60 s and was killed", flush=True)
            log.close()
            hub.shutdown()
            if FAILURES:
                print("--- agent log (last 60 lines) ---")
                print(
                    "\n".join(
                        log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
                    )
                )
    print(f"{'FAILED' if FAILURES else 'PASSED'}: {len(FAILURES)} failing check(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
