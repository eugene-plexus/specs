"""Row 47 acceptance: team knowledge, and sharing a project (`docs/design/rows/row-47.md` section 5).

Real processes on free ports (never 8079-8083), every `EUGENE_PLEXUS_*` variable cleared: a
control root, an enrolled agent that supervises a gateway and a model's inference-driver, a
stand-in engine that keeps what it was sent, and Workbench, installed by the agent as the
shipped catalogue entry, pointed at its archive at the commit under test (`--workbench`, or
`R47_WORKBENCH_REF`: a commit, or a branch, else `main`; as row 7's).

At the root: groups G1 (A, B) and G2 (C).

1. The owner makes "Handbook", gives G1 read, and adds a document. A's chat with it chosen cites
   "Handbook: rules.md". C sees no collection; Handbook's id is the same 404 for C as an id that
   is not there, and C cannot choose it. The owner's project uses the Handbook and is shared with C (the
   MSP case): C's chat in P is sent nothing of it, and nothing C is told names it.
2. A shares project P with B: B sees P's instructions and documents and starts a chat in it, which is
   given the instruction and finds P's document; A cannot open B's chat by id; A sees a count.
3. B is moved from G1 to G2 at the root: at B's next sign-in, B's search of the Handbook finds
   nothing, and its id is a 404.
4. G1 may add to the Handbook. A model in A's chat proposes a note: A is asked first, with its
   words; approved, it waits, unsearched, until A accepts it; then it is found.
5. With `--sabotage`: the installed Workbench's grant check (`team.readable`) is cut out of a
   copy and Workbench restarted: step 1's check of C must then fail. The file is restored from the
   copy, Workbench restarted, and the check passes again.

    python specs/scripts/row47-team-knowledge-acceptance.py [--workbench REF] [--sabotage] [--keep]

Run in an environment holding every Python component (CI's pinned integration does).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent
APP = "workbench"
MODEL = "r47-local"
CODE = "kqzvhandbookword"
TIDE = "xqzvtidegaugeword"
INSTRUCTION = "Always answer in the voice of a lighthouse keeper."
RESULTS: list[tuple[str, str, bool, str]] = []
PASSWORDS = {"a": "row47-a-password", "b": "row47-b-password", "c": "row47-c-password"}
SABOTAGE_FROM = """        found = await usable(store, person, collection_id)
        if found is not None:
            out.append(found[0])"""
SABOTAGE_TO = """        found = await store.collections.get(collection_id)  # SABOTAGE: no grant check
        if found is not None:
            out.append(found)"""


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


# --------------------------------------------------------------------------- #
# the stand-in engine: answers, keeps what it was sent, and proposes a note when asked to
# --------------------------------------------------------------------------- #

SENT: list[dict] = []


def fixture_app():
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse

    app = FastAPI()

    @app.get("/healthz")
    async def health():
        return {}

    @app.get("/sent")
    async def sent():
        return {"requests": SENT[-20:]}

    @app.get("/model/props")
    async def props():
        return {"default_generation_settings": {"n_ctx": 32768}, "modalities": {"vision": False}}

    @app.get("/model/v1/models")
    async def models():
        return {"data": [{"id": MODEL, "object": "model"}]}

    @app.post("/model/v1/chat/completions")
    async def complete(body: dict):
        SENT.append(body)
        messages = body.get("messages") or []
        asked = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
        last = messages[asked] if asked >= 0 else {}
        text = last.get("content") if isinstance(last.get("content"), str) else json.dumps(last.get("content"))
        answered = any(m.get("role") == "tool" for m in messages[asked + 1 :])
        tools = {t["function"]["name"] for t in body.get("tools") or []}
        usage = {"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23}
        propose = "PROPOSE:" in (text or "") and "suggest_team_note" in tools and not answered

        def frame(delta: dict, finish: str | None = None, **more) -> str:
            return "data: " + json.dumps({"model": MODEL, "choices": [
                {"index": 0, "delta": delta, "finish_reason": finish}], **more}) + "\n\n"

        async def frames():
            if propose:
                words = (text or "").split("PROPOSE:", 1)[1].split("\n", 1)[0].strip()
                arguments = json.dumps({"collection": "Handbook", "note": words})
                yield frame({"tool_calls": [{"index": 0, "id": "call-1", "type": "function",
                                             "function": {"name": "suggest_team_note",
                                                          "arguments": arguments}}]})
                yield frame({}, "tool_calls", usage=usage)
            else:
                yield frame({"content": "Noted."})
                yield frame({}, "stop", usage=usage)
            yield "data: [DONE]\n\n"

        return StreamingResponse(frames(), media_type="text/event-stream")

    return app


def serve(kind: str, directory: Path, port: int) -> None:
    if kind != "fixture":
        load("r7", "row7-person-removal-acceptance.py").serve(kind, directory, port)
        return
    import uvicorn

    uvicorn.run(fixture_app(), host="127.0.0.1", port=port, log_level="error", access_log=False)


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #


def exercise(work: Path, commit: str, *, sabotage: bool) -> None:
    c3 = load("c3", "c3-workbench-acceptance.py")
    r7 = load("r7", "row7-person-removal-acceptance.py")
    Browser = c3.Browser
    for name in [k for k in os.environ if k.startswith("EUGENE_PLEXUS_")]:
        del os.environ[name]
    ports = c3.free_ports(["control", "agent", "fixture", "gateway", "model"])
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

    def sent_last() -> str:
        return json.dumps(call("fixture", "GET", "/sent").json()["requests"][-1])

    try:
        say("an install: a root, an agent with a gateway and a model")
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
        r7.workbench_catalogue(agent_dir, version=commit, source=archive)
        start("agent")
        local = call("agent", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).json()["sessionToken"]
        join = call("control", "POST", "/v1/nodes/join-token", root,
                    json={"nodeName": "r47-node", "grants": ["gateway"]}).json()["token"]
        enrolled = call("agent", "POST", "/v1/node/enroll", local, timeout=90,
                        json={"controlUrl": url["control"], "token": join, "name": "r47-node"})
        must("0a", "the agent enrolls with the root", enrolled.status_code == 200, enrolled.text[:200])
        wait(lambda: call("agent", "GET", "/healthz").status_code == 200, "agent after enrolment")
        operator = call("agent", "POST", "/v1/auth/login", json={"passphrase": passphrase}).json()["sessionToken"]

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

        def running() -> str:
            wait(lambda: call("agent", "GET", f"/v1/apps/{APP}", operator).json()["status"] == "running",
                 "Workbench running", 120)
            ui_url = call("agent", "GET", f"/v1/apps/{APP}", operator).json()["uiUrl"].rstrip("/")
            wait(lambda: httpx.get(ui_url + "/healthz", trust_env=False, timeout=5).status_code == 200,
                 "Workbench answering", 120)
            return ui_url

        ui = running()

        say("groups G1 (A, B) and G2 (C), and everyone signs in")
        groups = {}
        for name in ("G1", "G2"):
            made = call("control", "POST", "/v1/permission-groups", root, json={"name": name, "apps": None})
            must("0d", f"{name} is made", made.status_code == 201, made.text[:200])
            groups[name] = made.json()["id"]
        people = {}
        for who, member_of in (("a", ["G1"]), ("b", ["G1"]), ("c", ["G2"])):
            made = call("control", "POST", "/v1/people", root, json={
                "name": who, "displayName": who.upper(), "password": PASSWORDS[who],
                "groups": [groups[g] for g in member_of]})
            must("0e", f"{who.upper()} is made in {member_of}", made.status_code == 201, made.text[:200])
            people[who] = made.json()["id"]
        owner, a, b, c = Browser(ui), Browser(ui), Browser(ui), Browser(ui)
        must("0f", "the owner signs in", owner.sign_in(passphrase, "operator").startswith("/#signin="))
        for who, person in (("a", a), ("b", b), ("c", c)):
            must("0g", f"{who.upper()} signs in", person.sign_in(PASSWORDS[who], who).startswith("/#signin="))

        def chat(person, collection: str | None = None, **body) -> str:
            made = person.post("/api/chats", json={"model": MODEL, **body})
            must("-", "a chat is made", made.status_code == 201, made.text[:300])
            chat_id = made.json()["id"]
            if collection is not None:
                linked = person.http.put(ui + f"/api/chats/{chat_id}/collections",
                                         headers=person._headers(), json={"ids": [collection]})
                must("-", "the collection is chosen for the chat", linked.status_code == 200, linked.text[:300])
            return chat_id

        def settled(person, collection: str) -> dict:
            def read():
                seen = person.get(f"/api/collections/{collection}").json()
                docs = seen["documentList"]
                return seen if docs and all(
                    d["document"]["state"] in ("ready", "searchable", "skipped", "failed") for d in docs
                ) else None

            return wait(read, "the collection's documents read", 120)

        say("1. the owner's Handbook, given to G1: A's chat cites it; C finds nothing")
        made = owner.post("/api/collections", json={"name": "Handbook"})
        must("1a", "the owner makes the Handbook", made.status_code == 201, made.text[:300])
        hid = made.json()["id"]
        rules = f"# Rules\n\nNew starters get a desk on day one. The front door code word is {CODE}.\n"
        added = owner.post(f"/api/collections/{hid}/documents",
                           files=[("files", ("rules.md", rules.encode(), "text/markdown"))])
        must("1b", "the owner adds rules.md", added.status_code == 201, added.text[:300])
        granted = owner.http.put(ui + f"/api/collections/{hid}/grants", headers=owner._headers(),
                                 json={"grants": [{"kind": "group", "id": groups["G1"], "role": "read"}]})
        must("1c", "the owner gives G1 read", granted.status_code == 200, granted.text[:300])
        settled(owner, hid)
        a_chat = chat(a, hid)
        answer = a.ask(a_chat, f"What is the front door code word {CODE}?")
        team = [s for s in answer.get("sources") or [] if s.get("scope") == "collection"]
        check("1d", "A's chat with the Handbook chosen cites Handbook: rules.md",
              team and team[0]["name"] == "Handbook: rules.md"
              and team[0]["collection"] == {"id": hid, "name": "Handbook"}
              and "desk on day one" in sent_last(), team)
        check("1e", "C sees no collection",
              c.get("/api/collections").json()["collections"] == [])
        same = c.get(f"/api/collections/{hid}")
        none = c.get("/api/collections/no-such-collection")
        check("1f", "the Handbook's id is the same 404 for C as an id that is not there",
              same.status_code == none.status_code == 404 and same.json() == none.json(),
              (same.text[:200], none.text[:200]))
        c_chat = chat(c)
        chosen = c.http.put(ui + f"/api/chats/{c_chat}/collections", headers=c._headers(),
                            json={"ids": [hid]})
        check("1g", "C cannot choose the Handbook for a chat",
              chosen.status_code == 404 and chosen.json() == none.json(), chosen.text[:200])
        # The owner's (an MSP's): only someone in a group with C, or the owner, shares with C.
        msp = owner.post("/api/projects", json={"name": "Client"}).json()["id"]
        linked = owner.http.put(ui + f"/api/projects/{msp}/collections", headers=owner._headers(),
                                json={"ids": [hid]})
        must("1h", "the owner's project uses the Handbook", linked.status_code == 200, linked.text[:300])
        shared = owner.http.put(ui + f"/api/projects/{msp}/sharing", headers=owner._headers(),
                                json={"shares": [{"kind": "person", "id": people["c"], "role": "read"}]})
        must("1i", "the owner shares the project with C", shared.status_code == 200, shared.text[:300])
        refused = a.http.put(ui + "/api/projects/" + a.post("/api/projects", json={"name": "Mine"}).json()["id"]
                             + "/sharing", headers=a._headers(),
                             json={"shares": [{"kind": "person", "id": people["c"], "role": "read"}]})
        check("1k", "A, in no group with C, cannot share with C", refused.status_code == 422, refused.text[:200])
        c_in_project = chat(c, projectId=msp)

        def c_finds_nothing(number: str) -> bool:
            told = c.ask(c_in_project, f"What is the front door code word {CODE}?")
            sent = sent_last()
            return check(number, "C's chat in the owner's project is sent nothing of the Handbook, and is told nothing of it",
                         "desk on day one" not in sent and "Handbook" not in sent
                         and "Handbook" not in json.dumps(told)
                         and "Handbook" not in c.get(f"/api/chats/{c_in_project}/collections").text,
                         {"retrieval": told.get("retrieval"), "sources": told.get("sources")})

        c_finds_nothing("1j")

        if sabotage:
            say("5. sabotage: the grant check cut out of the installed Workbench")
            # The installed package, not uv's caches of the archive.
            found = sorted(p for p in agent_dir.rglob("eugene_plexus_workbench/team.py")
                           if "site-packages" in p.parts)
            must("5a", "the installed team.py is found", len(found) == 1, found)
            module = found[0]
            copy = work / "team.py.original"
            shutil.copyfile(module, copy)
            source = copy.read_text(encoding="utf-8")
            must("5b", "the grant check is where the sabotage expects it", source.count(SABOTAGE_FROM) == 1)
            module.write_text(source.replace(SABOTAGE_FROM, SABOTAGE_TO), encoding="utf-8", newline="")
            restarted = call("agent", "POST", f"/v1/apps/{APP}/restart", operator)
            must("5c", "Workbench restarts with the sabotage", restarted.status_code == 200, restarted.text[:200])
            time.sleep(2)
            running()
            before = len(RESULTS)
            caught = not c_finds_nothing("5d (expected to FAIL under sabotage)")
            RESULTS[before:] = []  # the expected failure is this step's evidence, not a failure
            shutil.copyfile(copy, module)
            check("5e", "without the grant check, C's chat is sent the Handbook: the check catches it",
                  caught)
            restarted = call("agent", "POST", f"/v1/apps/{APP}/restart", operator)
            must("5f", "Workbench restarts restored", restarted.status_code == 200, restarted.text[:200])
            time.sleep(2)
            running()
            c_finds_nothing("5g")

        say("2. A shares a project with B: knowledge, not chats")
        project = a.post("/api/projects", json={"name": "Harbour"}).json()["id"]
        note = a.post("/api/memory/notes", json={"text": INSTRUCTION, "kind": "instruction",
                                                 "projectId": project})
        must("2a", "A keeps an instruction in the project", note.status_code in (200, 201), note.text[:300])
        tide = f"# Survey\n\nThe tide gauge code is {TIDE}.\n"
        added = a.post("/api/documents", data={"projectId": project},
                       files=[("files", ("survey.md", tide.encode(), "text/markdown"))])
        must("2b", "A adds a document to the project", added.status_code == 201, added.text[:300])
        a_own = chat(a, projectId=project)
        a.ask(a_own, "A private question about my garden.")
        shared = a.http.put(ui + f"/api/projects/{project}/sharing", headers=a._headers(), json={"shares": [
            {"kind": "person", "id": people["b"], "role": "read"}]})
        must("2c", "A shares the project with B", shared.status_code == 200, shared.text[:300])
        collection = shared.json()["collectionId"]
        settled(a, collection)
        page = b.get(f"/api/projects/{project}").json()
        check("2d", "B sees the project's instruction and its document, and no chat",
              [n["text"] for n in page.get("instructions", [])] == [INSTRUCTION]
              and page.get("documents") == 1 and page.get("chatList") == [], page)
        b_chat = chat(b, projectId=project)
        b.patch(f"/api/chats/{b_chat}", json={"settings": {"documents": "on"}})
        told = b.ask(b_chat, f"What is the tide gauge code {TIDE}?")
        sent = sent_last()
        names = [s.get("name") for s in told.get("sources") or []]
        check("2e", "B's chat is given the instruction and finds the project's document",
              INSTRUCTION in sent and "The tide gauge code is" in sent and "Harbour: survey.md" in names,
              names)
        check("2f", "A cannot open B's chat by id, nor B A's",
              a.get(f"/api/chats/{b_chat}").status_code == 404
              and b.get(f"/api/chats/{a_own}").status_code == 404)
        mine = a.get(f"/api/projects/{project}").json()
        check("2g", "A sees how many chats others have in it, and only A's own chats",
              mine["sharing"]["othersChats"] == 1 and [x["id"] for x in mine["chatList"]] == [a_own],
              {"others": mine["sharing"]["othersChats"], "chats": [x["id"] for x in mine["chatList"]]})

        say("3. B is taken out of G1: the Handbook is gone for B")
        b_hand = chat(b, hid)
        b.ask(b_hand, f"What is the front door code word {CODE}?")
        check("3a", "while in G1, B's chat finds the Handbook", "desk on day one" in sent_last())
        # Into G2: a person in no group may not be given Workbench at all.
        moved = call("control", "PATCH", f"/v1/people/{people['b']}", root,
                     json={"groups": [groups["G2"]]})
        must("3b", "B is moved from G1 to G2 at the root", moved.status_code == 200, moved.text[:200])
        b2 = Browser(ui)
        ended = b2.sign_in(PASSWORDS["b"], "b")
        must("3c", "B signs in again", ended.startswith("/#signin="), ended)
        told = b2.ask(b_hand, f"What is the front door code word {CODE}?")
        check("3d", "B's next search of the Handbook finds nothing, and says nothing of it",
              "desk on day one" not in sent_last() and "Handbook" not in json.dumps(told))
        check("3e", "the Handbook's id is a 404 for B now",
              b2.get(f"/api/collections/{hid}").status_code == 404)

        say("4. a model proposes a note: it waits for a person who adds to the Handbook")
        granted = owner.http.put(ui + f"/api/collections/{hid}/grants", headers=owner._headers(),
                                 json={"grants": [{"kind": "group", "id": groups["G1"], "role": "contribute"}]})
        must("4a", "G1 may add to the Handbook", granted.status_code == 200, granted.text[:300])
        a_note = chat(a, hid)
        posted = a.post(f"/api/chats/{a_note}/messages",
                        json={"content": "PROPOSE: Fire drills are on Fridays zqxdrillword."})
        must("4b", "A asks in a chat with the Handbook chosen", posted.status_code == 201, posted.text[:200])

        def asked():
            last = a.get(f"/api/chats/{a_note}").json()["messages"][-1]
            return last if last.get("toolRounds") else None

        asking = wait(asked, "the proposal to be asked about", 60)
        asked_call = asking["toolRounds"][0]["calls"][0]
        check("4c", "A is asked first, with the words, before anything leaves the chat",
              asked_call.get("ask") is True and asked_call.get("status") != "done"
              and a.get(f"/api/collections/{hid}").json()["inbox"] == [], asked_call)
        decided = a.post(f"/api/chats/{a_note}/messages/{asking['id']}/tools/decision",
                         json={"callId": asked_call["id"], "approve": True})
        must("4d", "A approves it", decided.status_code == 204, decided.text[:200])
        told = a.answer(a_note)
        calls = [x for r in told.get("toolRounds") or [] for x in r.get("calls") or []]
        check("4e", "the model's suggest_team_note ran", calls and calls[0].get("status") == "done", calls)
        seen = a.get(f"/api/collections/{hid}").json()
        check("4f", "the note waits in the Handbook's inbox, not among its notes",
              [i["title"] for i in seen["inbox"]] == ["Fire drills are on Fridays zqxdrillword."]
              and seen["noteList"] == [], {"inbox": seen["inbox"], "notes": seen["noteList"]})
        a.ask(chat(a, hid), "When are the zqxdrillword drills?")
        check("4g", "while it waits, it is not searched", "Fire drills are on Fridays" not in sent_last())
        accepted = a.post(f"/api/collections/{hid}/inbox/{seen['inbox'][0]['id']}/accept")
        check("4h", "A accepts it, as A", accepted.status_code == 200 and accepted.json()["addedBy"] == "A",
              accepted.text[:200])
        a.ask(chat(a, hid), "When are the zqxdrillword drills?")
        check("4i", "accepted, it is found", "Fire drills are on Fridays" in sent_last())
    finally:
        for process in processes:
            r7.kill_hard(process.pid)
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve")
    parser.add_argument("--directory")
    parser.add_argument("--port", type=int)
    parser.add_argument("--workbench", default=os.environ.get("R47_WORKBENCH_REF") or "main")
    parser.add_argument("--sabotage", action="store_true",
                        help="cut the grant check out of the installed Workbench once, and see step 1 catch it")
    parser.add_argument("--keep", action="store_true", help="keep the working directory")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, Path(args.directory), args.port)
        return
    r7 = load("r7", "row7-person-removal-acceptance.py")
    commit = r7.resolve(args.workbench)
    work = Path(tempfile.mkdtemp(prefix="ep-r47-"))
    print(f"working in {work}; Workbench {commit}", flush=True)
    try:
        exercise(work, commit, sabotage=args.sabotage)
    except BaseException:
        for log in sorted(work.rglob("*.log")):
            tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
            print(f"--- {log.relative_to(work)} ---", *tail, sep="\n")
        raise
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    failed = [r for r in RESULTS if not r[2]]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    finished = any(r[0] == "4i" for r in RESULTS) and (
        not args.sabotage or any(r[0] == "5g" for r in RESULTS))
    sys.exit(1 if failed or not finished else 0)


if __name__ == "__main__":
    main()
