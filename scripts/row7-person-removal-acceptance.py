"""Row 7 acceptance: a removed person's data is hidden, then deleted from every copy.

Design: `docs/design/rows/row-07.md` section 5. Real processes on free ports (never
8079-8083), every `EUGENE_PLEXUS_*` variable cleared: a control root, an enrolled agent that
supervises a gateway and a model's inference-driver, a stand-in engine, Eugene's reference
memory server (`m-memory-server.py`, whose forget can be held open), and Workbench, installed
by the agent as the shipped catalogue entry, pointed at its archive at the commit under test.

**Which Workbench.** `--workbench` (or `R7_WORKBENCH_REF`): a commit, or a branch of
`eugene-plexus/workbench`; a branch it does not have is `main`. CI passes a candidate commit,
or the same-named branch on a branch push, else `main`: the agent's catalogue pin is the last
Workbench shipped, and between a merge and the next ship it is older than what this checks.

What it checks, in order:

1. Owner, Ann and Ben each make a chat with a unique mark; Ann also keeps a note and a
   document, makes a connection to another app, and connects her memory server, which is
   sent her chat. A copy of the store is kept beside it, as a migration keeps one.
2. Ann's own download holds her chat, her note and her document.
3. Ann is removed at the root and the owner presses Check now: her connection gets 401, her
   sign-in ends, her data is still on the disk, her delete date shows, and Ben works.
4. Delete now while her memory server holds its forget open; Workbench is killed hard, the
   agent starts it again, the forget is let go, and the purge finishes.
5. Ann has no row in any table (the store opened read-only) and no folder; her mark is in no
   file of Workbench's data folder (the store, its log, the copy, downloads, indexes) or of
   the agent's logs. Her server was asked to forget her exchange only, and never cleared.
   Ben's chat is as it was, and the copy is kept for him.
6. Ann made again at the root gets a new id and an empty Workbench.
7. The owner's download of Ben is refused while `ownerReadsChats` is off; with it on, it has
   his chats and no notes.
8. With `removedPeopleRetention` "Not at all", removing Ben deletes his data at once.
9. Removing three people at once hides nobody; the owner is asked.

    python specs/scripts/row7-person-removal-acceptance.py [--workbench REF] [--keep]

Run in an environment holding every Python component (CI's pinned integration does).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import closing
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent
MODEL = "r7-local"
ANSWER = "R7-ANSWER: noted."
APP = "workbench"
#: Marks no index or model knows, with first letters no other word here starts with.
MARK = {"owner": "jqzvowner7mark", "ann": "kqzvannmark7", "ben": "xqzvbenmark7"}
RESULTS: list[tuple[str, str, bool, str]] = []
DAY = 86_400.0


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def check(number: str, claim: str, passed: bool, detail: object = "") -> bool:
    RESULTS.append((number, claim, bool(passed), str(detail)))
    tail = f"  -- {str(detail)[:600]}" if detail not in ("", None) else ""
    print(f"  {'PASS' if passed else 'FAIL'}  {number}. {claim}{tail}", flush=True)
    return bool(passed)


class Abort(Exception):
    pass


def must(number: str, claim: str, passed: bool, detail: object = "") -> None:
    if not check(number, claim, passed, detail):
        raise Abort(f"{number}: {claim}")


def say(text: str) -> None:
    print(f"\n== {text}", flush=True)


def resolve(ref: str) -> str:
    """A commit of eugene-plexus/workbench: `ref` itself, or the head of that branch, or of
    `main` when there is no such branch."""
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref
    for branch in (ref, "main"):
        listing = subprocess.run(
            ["git", "ls-remote", "https://github.com/eugene-plexus/workbench", f"refs/heads/{branch}"],
            capture_output=True, text=True, check=True, timeout=120,
        ).stdout.split()
        if listing:
            if branch != ref:
                print(f"workbench has no branch {ref!r}: testing main", flush=True)
            return listing[0]
    raise SystemExit("workbench has no main branch to test")


def key_of(sub: str) -> str:
    """Workbench's name for a person's folders (`files.person_key`)."""
    return hashlib.sha256(sub.encode("utf-8")).hexdigest()[:32]


def holds(data: bytes, needle: bytes) -> bool:
    """Whether these bytes hold `needle`, inside a ZIP's members too: a download is
    compressed, so its raw bytes never show a word it keeps."""
    if needle in data:
        return True
    if data[:4] != b"PK\x03\x04":
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return any(holds(archive.read(name), needle) for name in archive.namelist())
    except zipfile.BadZipFile:
        return False


def holding(directory: Path, mark: str) -> list[str]:
    """Every file under `directory` that holds `mark`, a ZIP's members included."""
    needle = mark.encode()
    found = []
    for path in directory.rglob("*"):
        try:
            if path.is_file() and holds(path.read_bytes(), needle):
                found.append(str(path.relative_to(directory)))
        except OSError:
            continue
    return sorted(found)


# --------------------------------------------------------------------------- #
# the processes this run starts
# --------------------------------------------------------------------------- #


def fixture_app():
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse

    app = FastAPI()

    @app.get("/healthz")
    async def health():
        return {}

    @app.get("/model/props")
    async def props():
        return {"default_generation_settings": {"n_ctx": 32768}, "modalities": {"vision": False}}

    @app.get("/model/v1/models")
    async def models():
        return {"data": [{"id": MODEL, "object": "model"}]}

    @app.post("/model/v1/chat/completions")
    async def complete(body: dict):
        usage = {"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23}
        if not body.get("stream"):
            return {"model": MODEL, "usage": usage, "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": ANSWER}}]}

        async def frames():
            yield "data: " + json.dumps({"model": MODEL, "choices": [
                {"index": 0, "delta": {"content": ANSWER}, "finish_reason": None}]}) + "\n\n"
            yield "data: " + json.dumps({"model": MODEL, "choices": [
                {"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage}) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(frames(), media_type="text/event-stream")

    return app


def workbench_catalogue(directory: Path, *, version: str, source: str) -> None:
    """The shipped catalogue with Workbench's entry pointed at the candidate: only a
    shipped entry may use the memory-server link (row 72), so not a custom entry."""
    from eugene_plexus_agent import apps

    catalogue = [m.model_dump(mode="json", exclude_none=True) for m in apps.load_catalogue()]
    next(m for m in catalogue if m["id"] == "workbench").update(version=version, source=source)
    (directory / "catalogue.yaml").write_text(yaml.safe_dump(catalogue), encoding="utf-8")


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    host = "127.0.0.1"
    if kind == "fixture":
        app = fixture_app()
    elif kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(Settings(config_file=directory / "control.yaml", state_dir=directory / "state"))
    elif kind == "agent":
        from eugene_plexus_agent import apps
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.console_logging import install_console_capture
        from eugene_plexus_agent.settings import Settings

        catalogue = apps.load_catalogue((directory / "catalogue.yaml").read_text(encoding="utf-8"))
        apps.load_catalogue = lambda: catalogue
        host = "0.0.0.0"
        install_console_capture(log_dir=directory / "logs")
        app = create_app(settings=Settings(config_file=directory / "agent.yaml", default_topology=False,
                                           bind_port=port))
    else:
        raise SystemExit(f"unknown kind {kind!r}")
    uvicorn.run(app, host=host, port=port, log_level="error", access_log=False)


def kill_hard(pid: int) -> None:
    """End a process and every process under it at once, as a crash does."""
    import psutil

    try:
        top = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    for process in [*top.children(recursive=True), top]:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass


def exercise(work: Path, commit: str) -> None:
    c3 = load("c3", "c3-workbench-acceptance.py")
    Browser = c3.Browser
    for name in [k for k in os.environ if k.startswith("EUGENE_PLEXUS_")]:
        del os.environ[name]
    ports = c3.free_ports(["control", "agent", "fixture", "gateway", "model", "memory"])
    assert not set(ports.values()) & set(range(8079, 8084))
    url = {k: f"http://127.0.0.1:{v}" for k, v in ports.items()}
    lan = c3.routable_address()
    client = httpx.Client(timeout=120, trust_env=False)
    processes: list[subprocess.Popen] = []
    passphrase = secrets.token_urlsafe(24)

    def call(name: str, method: str, path: str, token: str | None = None, **kw):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return client.request(method, url[name] + path, headers=headers, **kw)

    def wait(fn, label: str, seconds: float = 60):
        deadline = time.perf_counter() + seconds
        last = None
        while time.perf_counter() < deadline:
            try:
                found = fn()
                if found:
                    return found
            except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError, StopIteration) as e:
                last = e
            time.sleep(0.25)
        raise Abort(f"timed out: {label} ({last!r})")

    def spawn(name: str, command: list[str], directory: Path) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        env.pop("OPENAI_API_KEY", None)
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        processes.append(subprocess.Popen(
            command, cwd=directory, env=env, stdin=subprocess.DEVNULL,
            stdout=(directory / f"{name}.log").open("ab"), stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ))

    def start(name: str) -> None:
        directory = work / name
        directory.mkdir(exist_ok=True)
        spawn(name, [sys.executable, str(Path(__file__).resolve()), "--serve", name, "--directory",
                     str(directory), "--port", str(ports[name])], directory)
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name)

    try:
        say("an install: a root, an agent with a gateway and a model, a memory server")
        start("fixture")
        start("control")
        call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).raise_for_status()
        root = call("control", "POST", "/v1/auth/login", json={"passphrase": passphrase}).json()["sessionToken"]
        agent_dir = work / "agent"
        agent_dir.mkdir()
        (agent_dir / "gateway.yaml").write_text(yaml.safe_dump({"routingRefreshSeconds": 2}), encoding="utf-8")
        (agent_dir / "model.yaml").write_text(yaml.safe_dump({
            "provider": "openai_compat_custom", "baseUrl": url["fixture"] + "/model",
            "modelId": MODEL, "backendLocality": "local"}), encoding="utf-8")
        (agent_dir / "agent.yaml").write_text(yaml.safe_dump({
            "firstRunComplete": True,
            "updateChecks": False,
            "advertiseUrl": f"http://{lan}:{ports['agent']}",
            "securityMode": "prompt_on_startup",
            "uvBinary": c3.uv_binary(),
            "components": [
                {"name": "gateway", "kind": "gateway", "url": url["gateway"],
                 "spawn": {"configFile": str(agent_dir / "gateway.yaml")}},
                {"name": "model", "kind": "inference-driver", "url": url["model"],
                 "spawn": {"configFile": str(agent_dir / "model.yaml")}},
            ],
        }), encoding="utf-8")
        archive = f"https://github.com/eugene-plexus/workbench/archive/{commit}.tar.gz"
        workbench_catalogue(agent_dir, version=commit, source=archive)
        start("agent")
        local = call("agent", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).json()["sessionToken"]
        join = call("control", "POST", "/v1/nodes/join-token", root,
                    json={"nodeName": "r7-node", "grants": ["gateway"]}).json()["token"]
        enrolled = call("agent", "POST", "/v1/node/enroll", local, timeout=90,
                        json={"controlUrl": url["control"], "token": join, "name": "r7-node"})
        must("0a", "the agent enrolls with the root", enrolled.status_code == 200, enrolled.text[:200])
        wait(lambda: call("agent", "GET", "/healthz").status_code == 200, "agent after enrolment")
        operator = call("agent", "POST", "/v1/auth/login", json={"passphrase": passphrase}).json()["sessionToken"]
        memory_dir = work / "memory"
        memory_dir.mkdir()
        spawn("memory", [sys.executable, str(HERE / "m-memory-server.py"), "--port", str(ports["memory"])],
              memory_dir)
        wait(lambda: call("memory", "GET", "/state").status_code == 200, "the memory server")

        say(f"Workbench {commit[:12]}, installed by the agent from its archive")
        catalogue = call("agent", "GET", "/v1/app-catalogue", operator).json()
        entry = next(e for e in catalogue["apps"] if e["manifest"]["id"] == APP)
        must("0b", "the Workbench under test is a catalogue entry",
             entry["origin"] == "catalogue" and entry["manifest"]["version"] == commit
             and entry["manifest"]["source"] == archive, entry)
        began = call("agent", "POST", f"/v1/apps/{APP}/install", operator)
        must("0c", "its install starts", began.status_code == 202, began.text[:300])

        def installed() -> bool:
            progress = call("agent", "GET", f"/v1/apps/{APP}/install", operator).json()
            if progress["state"] == "failed":
                raise Abort("the install failed: " + str(progress.get("error"))[-1500:])
            return progress["state"] == "done"

        wait(installed, "the install", 900)
        wait(lambda: call("agent", "GET", f"/v1/apps/{APP}", operator).json()["status"] == "running",
             "Workbench running", 120)
        app = call("agent", "GET", f"/v1/apps/{APP}", operator).json()
        ui = app["uiUrl"].rstrip("/")
        data = agent_dir / "apps" / APP / "data"
        configured = call("agent", "PATCH", f"/v1/apps/{APP}/config", operator,
                          json={"memoryServers": "any"})
        must("0d", "Workbench takes a memory server on this host", configured.status_code == 200
             and not configured.json().get("rejected"), configured.text[:300])

        def settings(**values) -> None:
            answer = call("agent", "PATCH", f"/v1/apps/{APP}/config", operator, json=values)
            if answer.status_code != 200 or answer.json().get("rejected"):
                raise Abort(f"Workbench refused {values}: {answer.text[:300]}")

        say("1. owner, Ann and Ben each keep something")
        owner = Browser(ui)
        must("1a", "the owner signs in", owner.sign_in(passphrase).startswith("/#signin="))
        wait(lambda: any(m["id"] == MODEL for m in owner.get("/api/models").json()["models"]),
             "the model is listed", 90)
        made = {}
        for name in ("ann", "ben"):
            answer = call("control", "POST", "/v1/people", root,
                          json={"name": name, "displayName": name.title(), "password": f"{name}-password-12"})
            must("1b", f"{name.title()} is made at the root", answer.status_code == 201, answer.text[:200])
            made[name] = answer.json()["id"]
        ann, ben = Browser(ui), Browser(ui)
        must("1c", "Ann and Ben sign in", ann.sign_in("ann-password-12", "ann").startswith("/#signin=")
             and ben.sign_in("ben-password-12", "ben").startswith("/#signin="))
        server = ann.http.put(ui + "/api/memory/server", headers=ann._headers(),
                              json={"url": url["memory"] + "/mcp", "token": ""})
        must("1d", "Ann connects her memory server", server.status_code == 200, server.text[:300])
        chats = {}
        for who, person in (("owner", owner), ("ann", ann), ("ben", ben)):
            chat = person.post("/api/chats", json={"model": MODEL}).json()["id"]
            done = person.ask(chat, f"My favourite word is {MARK[who]}")
            must("1e", f"{who}'s chat is answered", done["status"] == "done", done.get("error"))
            chats[who] = chat
        note = ann.post("/api/memory/notes", json={"text": f"Remember {MARK['ann']}"})
        must("1f", "Ann keeps a note", note.status_code == 201, note.text[:200])
        kept = ann.post("/api/documents", files=[("files", ("plans.md", f"# Plans\n\nThe word is {MARK['ann']}.\n".encode(), "text/markdown"))])
        must("1g", "Ann keeps a document", kept.status_code == 201, kept.text[:200])
        wait(lambda: all(d["state"] in ("ready", "skipped", "failed")
                         for d in ann.get("/api/documents").json()["documents"]), "her document is read", 90)
        connection = ann.post("/api/connections", json={"name": "Her app", "rights": {"notes": True}})
        must("1h", "Ann connects another app", connection.status_code == 201, connection.text[:200])
        token = connection.json()["token"]

        def mcp_status() -> int:
            return client.post(ui + "/mcp", headers={
                "Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json"}, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "r7", "version": "1"}}}).status_code

        check("1i", "her connection works", mcp_status() != 401)
        retained = wait(lambda: [r for r in call("memory", "GET", "/state").json()["retained"]
                                 if MARK["ann"] in r["content"]], "her chat reaches her memory server", 90)
        sent = {r["document_id"] for r in retained}
        database = data / "workbench.sqlite3"
        with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as live, \
                closing(sqlite3.connect(data / "workbench.sqlite3.schema-27.bak")) as copy:
            live.backup(copy)
        check("1j", "a copy of the store is kept beside it, as a migration keeps one",
              MARK["ann"].encode() in (data / "workbench.sqlite3.schema-27.bak").read_bytes())

        say("2. Ann downloads her own data")
        mine = ann.post("/api/me/export").json()["export"]
        mine = wait(lambda: next(e for e in ann.get("/api/exports").json()["exports"]
                                 if e["id"] == mine["id"] and e["state"] != "making"), "her download", 120)
        got = ann.get(f"/api/exports/{mine['id']}")
        archive = zipfile.ZipFile(io.BytesIO(got.content)) if got.status_code == 200 else None
        names = archive.namelist() if archive else []
        check("2", "her download holds her chat, her note and her document",
              archive is not None and MARK["ann"] in archive.read("chats.json").decode()
              and MARK["ann"] in archive.read("memory.json").decode()
              and any(n.startswith("documents/") and MARK["ann"].encode() in archive.read(n) for n in names),
              names)

        say("3. Ann is removed; the owner presses Check now")
        gone = call("control", "DELETE", f"/v1/people/{made['ann']}", root)
        must("3a", "the root deletes Ann", gone.status_code == 204, gone.text[:200])
        checked = owner.post("/api/removed-people/check").json()
        row = next((p for p in checked["people"] if p["sub"] == made["ann"]), None)
        check("3b", "her delete date shows, 30 days on",
              row is not None and row["state"] == "hidden"
              and abs(row["deleteAt"] - row["removedAt"] - 30 * DAY) < 5, row)
        check("3c", "her connection gets 401, and her sign-in has ended",
              mcp_status() == 401 and ann.get("/api/me").status_code == 401)
        check("3d", "her data is still on the disk", bool(holding(data, MARK["ann"])), holding(data, MARK["ann"]))
        check("3e", "Ben works", ben.get(f"/api/chats/{chats['ben']}").status_code == 200)

        say("4. Delete now, with her memory server's forget held open; Workbench is killed")
        call("memory", "POST", "/control", json={"hold": True}).raise_for_status()
        started = owner.post(f"/api/removed-people/{made['ann']}/delete")
        must("4a", "Delete now starts", started.status_code == 202, started.text[:200])
        wait(lambda: call("memory", "GET", "/state").json()["holding"] > 0, "the forget is held open", 60)
        before = call("agent", "GET", f"/v1/apps/{APP}", operator).json()
        kill_hard(int(before["pid"]))
        call("memory", "POST", "/control", json={"hold": False}).raise_for_status()

        def again():
            now = call("agent", "GET", f"/v1/apps/{APP}", operator).json()
            return now.get("status") == "running" and now.get("pid") and now["pid"] != before["pid"] \
                and client.get(ui + "/healthz").status_code == 200

        must("4b", "the agent starts Workbench again", bool(wait(again, "Workbench restarted", 120)))

        def purged():
            listed = owner.get("/api/removed-people").json()["people"]
            found = next((p for p in listed if p["sub"] == made["ann"]), None)
            return found if found and found["state"] == "purged" else None

        row = wait(purged, "the purge finishes after the restart", 180)
        must("4c", "the purge finishes after the restart", row["purgedAt"] is not None and not row["problem"], row)

        say("5. nothing of Ann is left")
        with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as db:
            rows = {}
            for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
                if table in ("removed_people", "exports"):
                    continue
                columns = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
                for column in ("owner", "sub", "subject"):
                    if column in columns:
                        n = db.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = ?",
                                       (made["ann"],)).fetchone()[0]
                        if n:
                            rows[f"{table}.{column}"] = n
        check("5a", "Ann has no row in any table", rows == {}, rows)
        folders = [p for p in (data / "knowledge" / key_of(made["ann"]), data / "files" / key_of(made["ann"]))
                   if p.exists()]
        check("5b", "and no folder", folders == [], folders)
        kept = [p.name for p in (data / "exports").glob(f"{mine['id']}*")]
        check("5b2", "her own download's file is gone", kept == [], kept)
        left = holding(data, MARK["ann"]) + holding(agent_dir / "logs", MARK["ann"])
        check("5c", "her mark is in no file, nor inside any download: the store, its log, the "
              "copy, downloads, indexes, logs", left == [], left)
        state = call("memory", "GET", "/state").json()
        check("5d", "her memory server was asked to forget her exchange only, and never cleared",
              set(state["forgotten"]) == sent and state["cleared"] == 0, {"forgotten": state["forgotten"], "sent": sorted(sent)})
        bens = ben.get(f"/api/chats/{chats['ben']}")
        check("5e", "Ben's chat is as it was, and the copy is kept for him",
              bens.status_code == 200 and MARK["ben"] in json.dumps(bens.json())
              and MARK["ben"].encode() in (data / "workbench.sqlite3.schema-27.bak").read_bytes())

        say("6. Ann made again")
        again_made = call("control", "POST", "/v1/people", root,
                          json={"name": "ann", "displayName": "Ann", "password": "ann-password-34"})
        new_ann = Browser(ui)
        signed = again_made.status_code == 201 and new_ann.sign_in("ann-password-34", "ann").startswith("/#signin=")
        check("6", "a re-created Ann gets a new id and an empty Workbench",
              signed and again_made.json()["id"] != made["ann"]
              and new_ann.get("/api/chats").json()["chats"] == []
              and new_ann.get("/api/memory/notes").json()["notes"] == [], again_made.text[:200])

        say("7. the owner's download of Ben")
        refused = owner.post(f"/api/people/{made['ben']}/export")
        settings(ownerReadsChats=True)
        made_export = owner.post(f"/api/people/{made['ben']}/export").json()["export"]
        done = wait(lambda: next(e for e in owner.get("/api/exports").json()["exports"]
                                 if e["id"] == made_export["id"] and e["state"] != "making"), "the owner's download", 120)
        got = owner.get(f"/api/exports/{done['id']}")
        names = zipfile.ZipFile(io.BytesIO(got.content)).namelist() if got.status_code == 200 else []
        check("7", "refused while ownerReadsChats is off; with it on, his chats and no notes",
              refused.status_code == 403 and "chats.json" in names and "memory.json" not in names,
              {"refused": refused.status_code, "names": names})
        settings(ownerReadsChats=None)

        say("8. removedPeopleRetention: Not at all")
        settings(removedPeopleRetention="none")
        call("control", "DELETE", f"/v1/people/{made['ben']}", root).raise_for_status()
        owner.post("/api/removed-people/check")

        def ben_purged():
            listed = owner.get("/api/removed-people").json()["people"]
            return next((p for p in listed if p["sub"] == made["ben"] and p["state"] == "purged"), None)

        wait(ben_purged, "Ben's data is deleted at once", 120)
        check("8", "removing Ben deletes his data at once", holding(data, MARK["ben"]) == [],
              holding(data, MARK["ben"]))
        settings(removedPeopleRetention=None)

        say("9. three removed at once")
        three = {}
        for name in ("cy", "di", "ed"):
            answer = call("control", "POST", "/v1/people", root,
                          json={"name": name, "displayName": name.title(), "password": f"{name}-password-12"})
            three[name] = (answer.json()["id"], Browser(ui))
            three[name][1].sign_in(f"{name}-password-12", name)
        for sub, _ in three.values():
            call("control", "DELETE", f"/v1/people/{sub}", root).raise_for_status()
        checked = owner.post("/api/removed-people/check").json()
        hidden = [p for p in checked["people"] if p["sub"] in {s for s, _ in three.values()}]
        check("9", "removing three at once hides nobody, and the owner is asked",
              hidden == [] and (checked["brake"] or {}).get("count") == 3
              and all(b.get("/api/me").status_code == 200 for _, b in three.values()), checked["brake"])
    except (Abort, c3.Abort) as exc:
        print(f"\nABORTED: {exc}", flush=True)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve")
    parser.add_argument("--directory")
    parser.add_argument("--port", type=int)
    parser.add_argument("--workbench", default=os.environ.get("R7_WORKBENCH_REF") or "main")
    parser.add_argument("--keep", action="store_true", help="keep the working directory")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, Path(args.directory), args.port)
        return
    commit = resolve(args.workbench)
    work = Path(tempfile.mkdtemp(prefix="ep-r7-"))
    print(f"working in {work}; Workbench {commit}", flush=True)
    try:
        exercise(work, commit)
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    failed = [r for r in RESULTS if not r[2]]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    finished = any(r[0] == "9" for r in RESULTS)
    sys.exit(1 if failed or not finished else 0)


if __name__ == "__main__":
    main()
