"""CX9: models already in Ollama are listed in place, read-only, and run, on a real disposable install.

A fresh isolated install from this checkout's installer (the pinned UI wheel),
on claimed ports with every ambient `EUGENE_PLEXUS_*` variable cleared. No
Ollama is needed: this script writes a FAKE store the way Ollama v0.40 writes
one, in its own temp folder under --output: `blobs/sha256-<hex of the GGUF>`
holding a real ~20 MB GGUF (hard-linked, else copied), a v2 manifest
`manifests-v2/ollama.com/library/tiny/q4`, a legacy manifest
`manifests/registry.ollama.ai/library/tiny/q5` for a second tag of the same
blob, and a manifest list whose only child is an `mlx` / `safetensors` model.

How the store reaches the Library: `OLLAMA_MODELS` is set in the `spawn.env`
of the Library's entry in the agent's `agent.yaml`, so only the Library
process sees it (and nothing else of the calling shell's `EUGENE_PLEXUS_*`
does). The isolated install's `HOME`/`USERPROFILE` is its own folder, so the
default `~/.ollama/models` is empty and nothing on this PC's account is read.

Proved over HTTP through the agent's proxy:
1. `GET library /v1/folders` lists the store with `kind: ollama`, `found: true`;
   `PATCH /v1/config {findOllama: false}` removes it (and a rescan no longer
   shows the model as present); `true` restores both.
2. `GET /v1/models` lists ONE model for the blob, named `tiny:q4`, with
   `ollama.tags == [tiny:q4, tiny:q5]`; the mlx / safetensors manifest is not
   offered, and `GET /v1/scan` names it in `skipped` as "not for llama.cpp".
3. Read-only: `DELETE /v1/models/{id}` answers 409 "Ollama manages this model";
   `POST /v1/downloads` naming the store as `root` answers 4xx; the store tree
   (every entry, hidden ones included, with size, mtime and SHA-256 of every
   file) is identical before the install starts and after the agent has
   stopped.
4. Run: a run operation for the model (`modelId`, `installEngine: llama_cpp`)
   reaches `ready`; the gateway lists model id `tiny:q4` and one chat answer
   comes back.

The browser half (`cx9-ollama-models-browser.mjs`) sets the install up, waits
for this script's HTTP half, then checks that Library lists `tiny:q4` with the
"Ollama" badge, that the opened model says "Ollama manages this model." and
has no Delete button, and that Folders says "Ollama's models (read-only) ·
found on this machine".

Hand-off between the halves: the browser writes `ready.flag` when the Library
answers, this script writes `http.json` when its steps are done (or failed),
and the browser waits for it.

Downloads `ggml-org/models` `tinyllamas/stories15M-q4_0.gguf` (about 20 MB)
from Hugging Face and one llama.cpp build into the disposable folder.
Requires httpx and PyYAML, Node and Chrome, the sibling UI's Node
dependencies, and the internet. Windows only. Never run on the default ports
on Amish_Station: it claims its own.

Not checked, and recorded as such in `result.json` under `notChecked`: Ollama
itself (the store is a stand-in, so Ollama's own delete, prune and migration
are not exercised); a store on another machine (CX9-C3); a manifest list whose
`llamacpp` child is a blob reference (unit-tested in the Library only); the
"may not load in llama.cpp" warning for a family Ollama migrates (the
stand-in's architecture is not one).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PASSPHRASE = "cx9-disposable-passphrase"
GGUF_URL = "https://huggingface.co/ggml-org/models/resolve/main/tinyllamas/stories15M-q4_0.gguf"
TINY = {"repo": "ggml-org/models", "files": ["tinyllamas/stories15M-q4_0.gguf"]}
NAME = "tiny:q4"
TAGS = ["tiny:q4", "tiny:q5"]

MODEL = "application/vnd.ollama.image.model"
TENSOR = "application/vnd.ollama.image.tensor"
LIST = "application/vnd.ollama.manifest.list.v2+json"
MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"

_spec = importlib.util.spec_from_file_location("cx2", HERE / "cx2-setup-resume-acceptance.py")
assert _spec and _spec.loader
cx2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cx2)

CHECKS = (
    "storeListedAsOllamaFolder",
    "findOllamaOffRemovesFolder",
    "findOllamaOffHidesModel",
    "findOllamaOnRestoresBoth",
    "oneModelForTheBlob",
    "nameIsFirstTag",
    "bothTagsListed",
    "safetensorsNotOffered",
    "safetensorsSkippedWithReason",
    "deleteRefused409",
    "deleteNamesOllama",
    "downloadIntoStoreRefused",
    "storeTreeUnchanged",
    "runReady",
    "gatewayListsTagName",
    "chatAnswered",
    "libraryShowsOllamaBadge",
    "libraryManagesNoteInPlaceOfDelete",
    "foldersLineReadOnlyFound",
)

NOT_CHECKED = [
    "Ollama itself: the store is a stand-in, so Ollama's own delete, prune and migration are not exercised",
    "a store on another machine (CX9-C3 leaves it for later)",
    "a manifest list whose llamacpp child is a blob reference (unit-tested in the Library only)",
    "the 'may not load in llama.cpp' warning for a migrated family (the stand-in's architecture is not one)",
]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_tree(root: Path) -> dict[str, list]:
    """Every entry under `root`, hidden ones included: kind, size, mtime, and a SHA-256 for files."""
    found: dict[str, list] = {}
    entries = [root, *sorted(root.rglob("*"))]
    for path in entries:
        stat = path.lstat()
        relative = "." if path == root else path.relative_to(root).as_posix()
        if path.is_dir() and not path.is_symlink():
            found[relative] = ["dir", stat.st_mtime_ns]
        else:
            found[relative] = ["file", stat.st_size, stat.st_mtime_ns, sha256_of(path)]
    return found


def download_gguf(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        with client.stream("GET", GGUF_URL) as response:
            response.raise_for_status()
            with target.open("wb") as out:
                for chunk in response.iter_bytes(1 << 20):
                    out.write(chunk)
    assert target.stat().st_size > 1_000_000, "the GGUF download is too small"
    assert target.read_bytes()[:4] == b"GGUF", "the download is not a GGUF"


def layer(media: str, digest: str, size: int) -> dict:
    return {"mediaType": media, "digest": f"sha256:{digest}", "size": size}


def manifest(*layers: dict) -> dict:
    config = layer("application/vnd.docker.container.image.v1+json", "0" * 64, 2)
    return {"schemaVersion": 2, "mediaType": MANIFEST, "config": config, "layers": list(layers)}


def write_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8", newline="\n")


def build_store(store: Path, gguf: Path) -> str:
    """The fake Ollama store; returns the GGUF's SHA-256."""
    digest = sha256_of(gguf)
    blob = store / "blobs" / f"sha256-{digest}"
    blob.parent.mkdir(parents=True)
    try:
        os.link(gguf, blob)
    except OSError:
        shutil.copyfile(gguf, blob)
    size = blob.stat().st_size
    model = manifest(layer(MODEL, digest, size))
    write_json(store / "manifests-v2" / "ollama.com" / "library" / "tiny" / "q4", model)
    write_json(store / "manifests" / "registry.ollama.ai" / "library" / "tiny" / "q5", model)
    # A model llama.cpp cannot load: a list whose only child is mlx / safetensors.
    tensor = "1" * 64
    (store / "blobs" / f"sha256-{tensor}").write_bytes(b"safetensors stand-in")
    child = {"runner": "mlx", "format": "safetensors", **manifest(layer(TENSOR, tensor, 20))}
    write_json(
        store / "manifests-v2" / "ollama.com" / "library" / "mlxthing" / "latest",
        {"schemaVersion": 2, "mediaType": LIST, "manifests": [child]},
    )
    return digest


def same_path(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(str(b)))


def poll(check, seconds: float, what: str, every: float = 0.5):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        value = check()
        if value:
            return value
        time.sleep(every)
    raise AssertionError(f"timed out after {seconds:.0f}s: {what}")


def wait_for(client: httpx.Client, url: str, agent: subprocess.Popen | None = None) -> None:
    for _ in range(300):
        try:
            if client.get(url + "/healthz").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        assert agent is None or agent.poll() is None, "agent exited"
        time.sleep(0.2)
    raise AssertionError(f"{url} did not answer")


def http_half(client: httpx.Client, url: str, store: Path, digest: str, seen: dict, checks: dict) -> None:
    """Steps 1-4 over HTTP through the agent's proxy, filling `checks` as each is observed."""
    login = client.post(url + "/v1/auth/login", json={"passphrase": PASSPHRASE})
    assert login.status_code == 200, login.text[:300]
    auth = {"Authorization": f"Bearer {login.json()['sessionToken']}"}
    library = url + "/api/proxy/library"
    gateway = url + "/api/proxy/gateway"

    def folders() -> list[dict]:
        answer = client.get(library + "/v1/folders", headers=auth)
        assert answer.status_code == 200, answer.text[:300]
        return answer.json().get("folders", [])

    def store_folder() -> dict | None:
        return next((f for f in folders() if f.get("kind") == "ollama" and same_path(f["path"], store)), None)

    def rescan() -> dict:
        started = client.post(library + "/v1/scan", headers=auth, json={})
        assert started.status_code in (202, 409), started.text[:300]

        def finished() -> dict | None:
            scan = client.get(library + "/v1/scan", headers=auth).json()
            return scan if scan.get("state") not in ("scanning", "idle") else None

        time.sleep(0.5)
        return poll(finished, 120, "the scan to finish")

    def listed() -> list[dict]:
        answer = client.get(library + "/v1/models", headers=auth)
        assert answer.status_code == 200, answer.text[:300]
        return [m for m in answer.json().get("models", []) if m.get("ollama") is not None]

    def toggle(value: bool) -> None:
        patched = client.patch(library + "/v1/config", headers=auth, json={"findOllama": value})
        assert patched.status_code == 200 and not patched.json().get("rejected"), patched.text[:300]

    # 1. The store as a folder, and the setting that removes and restores it.
    rescan()
    folder = store_folder()
    seen["folder"] = folder
    checks["storeListedAsOllamaFolder"] = folder is not None and folder.get("found") is True
    toggle(False)
    checks["findOllamaOffRemovesFolder"] = store_folder() is None
    rescan()
    checks["findOllamaOffHidesModel"] = not any(m.get("status") == "present" for m in listed())
    toggle(True)
    restored_folder = store_folder() is not None
    scan = rescan()
    models = listed()
    checks["findOllamaOnRestoresBoth"] = restored_folder and any(m.get("status") == "present" for m in models)

    # 2. One model for the blob, named by the first tag; the mlx model is not offered.
    seen["models"] = [{k: m.get(k) for k in ("id", "name", "path", "status", "ollama")} for m in models]
    checks["oneModelForTheBlob"] = len(models) == 1 and digest in models[0].get("path", "").lower()
    model = models[0]
    checks["nameIsFirstTag"] = model.get("name") == NAME
    checks["bothTagsListed"] = (model.get("ollama") or {}).get("tags") == TAGS
    all_models = client.get(library + "/v1/models", headers=auth).json().get("models", [])
    checks["safetensorsNotOffered"] = not any("mlxthing" in json.dumps(m) for m in all_models)
    skipped = scan.get("skipped") or []
    seen["skipped"] = skipped
    checks["safetensorsSkippedWithReason"] = any(
        "mlxthing" in json.dumps(s) and "not for llama.cpp" in json.dumps(s) for s in skipped
    )

    # 3. Read-only: Delete is refused, a download cannot name the store.
    refused = client.request("DELETE", library + f"/v1/models/{model['id']}", headers=auth, json={})
    seen["delete"] = {"status": refused.status_code, "body": refused.text[:400]}
    checks["deleteRefused409"] = refused.status_code == 409
    checks["deleteNamesOllama"] = "Ollama manages this model" in refused.text
    download = client.post(library + "/v1/downloads", headers=auth, json={**TINY, "root": str(store)})
    seen["downloadIntoStore"] = {"status": download.status_code, "body": download.text[:400]}
    checks["downloadIntoStoreRefused"] = 400 <= download.status_code < 500

    # 4. Run it as the console does: the run operation, with the engine agreed up front.
    node = client.get(url + "/v1/node", headers=auth).json().get("name")
    run_id = f"run_cx9-{uuid.uuid4().hex[:8]}"
    intent = {"node": node, "modelId": model["id"], "installEngine": "llama_cpp"}
    submitted = client.put(library + f"/v1/run-operations/{run_id}", headers=auth, json=intent)
    assert submitted.status_code == 202, submitted.text[:300]
    steps: list[str] = []
    record: dict = {}
    deadline = time.perf_counter() + 1800
    while time.perf_counter() < deadline:
        record = client.get(library + f"/v1/run-operations/{run_id}", headers=auth).json()
        if not steps or steps[-1] != record.get("step"):
            steps.append(record.get("step"))
        if record.get("step") in {"ready", "failed", "cancelled", "skipped"}:
            break
        time.sleep(0.5)
    seen["steps"] = steps
    seen["run"] = {k: record.get(k) for k in ("step", "answer", "engine", "error")}
    checks["runReady"] = record.get("step") == "ready"
    assert checks["runReady"], f"the run did not reach ready: {seen['run']}"

    def gateway_ids() -> list[str]:
        answer = client.get(gateway + "/v1/models", headers=auth)
        return [m.get("id") for m in answer.json().get("data", [])] if answer.status_code == 200 else []

    poll(lambda: NAME in gateway_ids(), 300, f"the gateway to list {NAME}", every=2)
    seen["gatewayIds"] = gateway_ids()
    checks["gatewayListsTagName"] = NAME in seen["gatewayIds"]
    chat = client.post(
        gateway + "/v1/chat/completions",
        headers=auth,
        timeout=120,
        json={"model": NAME, "max_tokens": 8, "messages": [{"role": "user", "content": "Once upon a time"}]},
    )
    seen["chat"] = {"status": chat.status_code, "body": chat.text[:300]}
    checks["chatAnswered"] = chat.status_code == 200 and bool(chat.json().get("choices"))


def run(root: Path) -> None:
    assert sys.platform == "win32", "Windows only"
    root.mkdir(parents=True, exist_ok=False)
    prefix = root / "install"
    store = root / "ollama-store" / "models"
    before = cx2.snapshot_windows()
    base = cx2.claim_ports()
    agent_port = base + 1
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env.update(
        {
            "NO_PROXY": "localhost,127.0.0.1,::1",
            "PYTHONUTF8": "1",
            "EUGENE_PLEXUS_AGENT_BIND_PORT": str(agent_port),
        }
    )
    # The agent's own environment never carries it; only the Library's `spawn.env` does.
    env.pop("OLLAMA_MODELS", None)
    result: dict = {"ports": {"agent": agent_port}, "checks": {}, "notChecked": NOT_CHECKED, "store": str(store)}
    checks = result["checks"]
    agent = None
    logs = []
    browser = None
    handoff: dict = {}
    tree_before: dict | None = None
    try:
        download_gguf(root / "download" / "stories15M-q4_0.gguf")
        digest = build_store(store, root / "download" / "stories15M-q4_0.gguf")
        tree_before = snapshot_tree(store)
        result["storeEntries"] = len(tree_before)

        wrapper = root / "install-wrapper.ps1"
        wrapper.write_text(
            "& '"
            + str(HERE / "install.ps1").replace("'", "''")
            + "' -Prefix '"
            + str(prefix).replace("'", "''")
            + "' -NoService -NoStart -Isolated\n",
            encoding="utf-8",
        )
        with (root / "installer.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                env=env,
                cwd=root,
                stdout=log,
                stderr=log,
                check=True,
                timeout=900,
            )
        python = prefix / "venv/Scripts/python.exe"
        components = []
        for name, offset in (("control", 2), ("gateway", 3), ("library", 4)):
            spawn: dict = {"configFile": str(prefix / f"{name}.yaml")}
            if name == "library":
                spawn["env"] = {"OLLAMA_MODELS": str(store)}
            components.append({"name": name, "kind": name, "url": f"http://127.0.0.1:{base + offset}", "spawn": spawn})
        (prefix / "agent.yaml").write_text(yaml.safe_dump({"components": components}), encoding="utf-8")
        env.update(
            {
                "HOME": str(prefix),
                "USERPROFILE": str(prefix),
                "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(prefix / "engines"),
                "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(prefix / "agent.yaml"),
                "EUGENE_PLEXUS_AGENT_BIND_HOST": "127.0.0.1",
                # The machine port is off until agent#27 is fixed: with it on, the wizard joins the root at
                # control's moved URL, which is plain HTTP, and the join token expects TLS.
                "EUGENE_PLEXUS_AGENT_MACHINE_PORT_ENABLED": "0",
            }
        )
        log = (root / "agent.log").open("w", encoding="utf-8")
        logs.append(log)
        agent = subprocess.Popen(
            [str(python), str(HERE / "s8-ui-acceptance.py"), "--serve", str(prefix), "--port", str(agent_port)],
            cwd=prefix,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=FLAGS,
        )
        url = f"http://127.0.0.1:{agent_port}"
        with httpx.Client(trust_env=False, timeout=30) as client:
            wait_for(client, url, agent)
            settings = root / "browser-settings.json"
            settings.write_text(
                json.dumps({"url": url, "output": str(root), "passphrase": PASSPHRASE, "modelName": NAME}),
                encoding="utf-8",
            )
            with (root / "browser.log").open("w", encoding="utf-8") as blog:
                browser = subprocess.Popen(
                    ["node", str(HERE / "cx9-ollama-models-browser.mjs"), str(settings)], stdout=blog, stderr=blog
                )
                try:
                    # The browser sets the install up, then waits for the HTTP half.
                    until = time.perf_counter() + 900
                    while not (root / "ready.flag").exists():
                        assert browser.poll() is None, "browser exited before the install was ready"
                        assert time.perf_counter() < until, "the install was not ready in 15 minutes"
                        time.sleep(0.5)
                    try:
                        http_half(client, url, store, digest, result, checks)
                    except Exception as error:  # the browser must be told, or it waits for the full timeout
                        handoff = {"error": repr(error)}
                        result["httpError"] = repr(error)
                    (root / "http.json").write_text(json.dumps(handoff), encoding="utf-8")
                    browser.wait(timeout=1800)
                finally:
                    if browser.poll() is None:
                        browser.kill()
            report = root / "browser.json"
            if report.exists():
                result["browser"] = json.loads(report.read_text(encoding="utf-8"))
            assert "error" not in handoff, f"the HTTP half failed: {handoff['error']}"
            assert browser.returncode == 0, "browser failed; see browser.log and failure.png"
            seen = result["browser"]
            checks["libraryShowsOllamaBadge"] = "Ollama" in str(seen.get("badgeText", ""))
            checks["libraryManagesNoteInPlaceOfDelete"] = (
                seen.get("managesText") == "Ollama manages this model." and seen.get("deleteButtons") == 0
            )
            checks["foldersLineReadOnlyFound"] = (
                seen.get("folderLine") == "Ollama's models (read-only) · found on this machine"
            )
    finally:
        try:
            if agent:
                (prefix / "stop").touch()
                try:
                    agent.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    # A stop takes at most 5 s plus the children's own stops since
                    # agent#20 (a connection Windows reset kept uvicorn waiting for
                    # ever). Past 45 s that fix has failed: say so, and the tree goes.
                    print("the agent did not stop in 45 s (agent#20 again?); killing its process tree",
                          flush=True)
                    subprocess.run(["taskkill", "/PID", str(agent.pid), "/T", "/F"],
                                   capture_output=True, check=False)
        finally:
            for log in logs:
                log.close()
            # After every process of the install is gone: nothing of Ollama's was touched.
            if tree_before is not None:
                tree_after = snapshot_tree(store)
                names = set(tree_before) | set(tree_after)
                changed = sorted(k for k in names if tree_before.get(k) != tree_after.get(k))
                result["storeChanges"] = changed
                checks["storeTreeUnchanged"] = not changed
            result["passed"] = all(checks.get(name) is True for name in CHECKS) and set(checks) <= set(CHECKS)
            result["liveInstallUnchanged"] = cx2.snapshot_windows() == before
            (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            lines = ["# CX9 acceptance", "", f"Passed: {result['passed']}", "", "## Checks", ""]
            lines += [f"- {name}: {checks.get(name, 'not run')}" for name in CHECKS]
            lines += ["", "## Not checked", ""] + [f"- {item}" for item in NOT_CHECKED]
            (root / "result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    assert result["liveInstallUnchanged"], "live service/account environment changed"
    assert result["passed"], "a CX9 check failed; see result.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True, help="A new disposable directory")
    run(parser.parse_args().output.resolve())
