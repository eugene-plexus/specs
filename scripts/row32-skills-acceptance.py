"""Row 32 acceptance: skills reach the model through its tools, and nothing else.

Design: `docs/design/rows/row-32.md` section 5. CI only, on Linux and Windows: a control root,
row 2's shared agent harness with its gateway and an inference-driver, a fixture backend that
calls tools as scripted, and Workbench installed by the agent as the shipped catalogue entry,
pointed at the candidate's archive. Every port is the OS's (never 8079-8083) and every
`EUGENE_PLEXUS_*` variable is cleared. The owner and two people, Ada and Bo.

1. Ada uploads a skill ZIP with `references/style.md` and a script, reads its SKILL.md and turns
   it on. The fixture, scripted to call `use_skill` then `read_skill_file`, receives the body and
   the file; the tool definition lists the skill; the system message is byte-identical with and
   without skills, and names none.
2. The script line says no Job Site allows commands.
3. Bo sees nothing of Ada's, by list or by id; the owner's skill given to everyone reaches both;
   Bo turns it off and it leaves his next chat.
4. Each hostile archive is refused with its cause, and nothing is written: Workbench's data
   folder is the same tree before and after, and no escape name exists anywhere.
5. Ada is removed from Eugene and the owner deletes her data now: her skill folder and her rows
   are gone, and the skill given to everyone stays.

    python specs/scripts/row32-skills-acceptance.py [--workbench REF] [--output DIR]

`--workbench` (or `R32_WORKBENCH_REF`): a commit, or a branch of eugene-plexus/workbench (a
branch it does not have is `main`). Run in an environment holding every Python component (CI's
pinned integration does).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import secrets
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent
APP = "workbench"
MODEL = "skills"
BODY_MARK = "kqzvr32bodymark"
STYLE_MARK = "kqzvr32stylemark"
RESULTS: list[tuple[str, str, bool, str]] = []


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


def key_of(sub: str) -> str:
    """Workbench's name for a person's folders (`files.person_key`)."""
    return hashlib.sha256(sub.encode("utf-8")).hexdigest()[:32]


# --------------------------------------------------------------------------- #
# skills, good and hostile
# --------------------------------------------------------------------------- #


def skill_md(name: str = "pdf-forms") -> bytes:
    return (
        f"---\nname: {name}\ndescription: Fill in PDF forms.\nlicense: Apache-2.0\n---\n\n"
        f"# Filling PDF forms\n\nRead references/style.md first. {BODY_MARK}\n"
    ).encode()


def archive(*entries, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=compression) as made:
        for name, data in entries:
            made.writestr(name, data)
    return out.getvalue()


def good_zip() -> bytes:
    return archive(
        ("pdf-forms/SKILL.md", skill_md()),
        ("pdf-forms/references/style.md", f"Headings in sentence case. {STYLE_MARK}".encode()),
        ("pdf-forms/scripts/fill.py", b"print('filled')\n"),
    )


def link(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info


#: An escape a refused archive would have made: none may exist anywhere afterwards.
ESCAPE = "r32-escape-kqzv.sh"


def hostile() -> list[tuple[str, bytes, list[str]]]:
    md = ("SKILL.md", skill_md())
    absolute = f"C:/{ESCAPE}" if os.name == "nt" else f"/tmp/{ESCAPE}"
    return [
        ("traversal", archive(md, (f"../{ESCAPE}", b"x")), [f"`../{ESCAPE}`", "leaves"]),
        (
            "deep traversal",
            archive(md, ("../" * 8 + ESCAPE, b"x")),
            ["leaves the skill's folder"],
        ),
        ("absolute path", archive(md, (absolute, b"x")), [f"`{absolute}`", "leaves"]),
        ("link", archive(md, (link("references/notes.md"), b"../../../../etc/passwd")),
         ["`references/notes.md`", "is a link"]),
        ("513 entries", archive(md, *((f"r/{i}.md", b"x") for i in range(512))),
         ["more than 512"]),
        ("a 1,000-to-1 entry", archive(md, ("assets/zeros.bin", b"\0" * (1 << 20))),
         ["`assets/zeros.bin`", "more than 100 times"]),
        ("no SKILL.md", archive(("a/README.md", b"x"), ("b/SKILL.md", skill_md())),
         ["no `SKILL.md`"]),
        ("bad name", archive(("SKILL.md", skill_md("Bad Name"))), ["`Bad Name`"]),
        ("a Windows device name", archive(md, ("references/NUL.md", b"x")),
         ["`references/NUL.md`", "Windows"]),
        ("a trailing dot", archive(md, ("notes./a.md", b"x")), ["`notes./a.md`", "dot"]),
        ("names only case tells apart", archive(md, ("Notes.md", b"a"), ("notes.md", b"b")),
         ["same file"]),
        ("bzip2", archive(md, compression=zipfile.ZIP_BZIP2), ["Deflate"]),
    ]


# --------------------------------------------------------------------------- #
# the processes this run starts
# --------------------------------------------------------------------------- #


def fixture_app():
    """An OpenRouter-shaped backend. A user message `row32 use` is answered by calling
    `use_skill`, then `read_skill_file`, then words; anything else by words. Every request it
    receives is kept, in order."""
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse

    app = FastAPI()
    seen: list[dict] = []

    @app.get("/healthz")
    async def health():
        return {}

    @app.get("/seen")
    async def received():
        return seen

    @app.get("/v1/models/user")
    async def models():
        return {
            "data": [
                {
                    "id": MODEL,
                    "name": MODEL,
                    "context_length": 32768,
                    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                    "supported_parameters": ["tools", "tool_choice", "temperature", "max_tokens"],
                }
            ]
        }

    @app.post("/v1/chat/completions")
    async def complete(body: dict):
        seen.append(body)
        messages = body["messages"]
        last = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=-1)
        asked = json.dumps(messages[last].get("content")) if last >= 0 else ""
        done = sum(m["role"] == "tool" for m in messages[last + 1 :])
        offered = {t["function"]["name"] for t in body.get("tools") or []}
        script = [
            ("use_skill", {"name": "pdf-forms"}),
            ("read_skill_file", {"name": "pdf-forms", "path": "references/style.md"}),
        ]
        delta: dict = {"content": "R32 answer."}
        finish = "stop"
        if "row32 use" in asked and done < len(script) and script[done][0] in offered:
            name, arguments = script[done]
            delta = {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": f"row32-{done}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ]
            }
            finish = "tool_calls"
        usage = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
        if not body.get("stream"):
            message = {"role": "assistant", **delta}
            for call in message.get("tool_calls", []):
                call.pop("index", None)
            return {
                "model": body["model"],
                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                "usage": usage,
            }

        async def frames():
            for event in [
                {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage},
            ]:
                yield "data: " + json.dumps({"model": body["model"], **event}) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(frames(), media_type="text/event-stream")

    return app


def workbench_catalogue(directory: Path, commit: str) -> None:
    """The shipped catalogue with Workbench's entry pointed at the candidate's archive."""
    from eugene_plexus_agent import apps

    catalogue = [m.model_dump(mode="json", exclude_none=True) for m in apps.load_catalogue()]
    next(m for m in catalogue if m["id"] == APP).update(
        version=commit,
        source=f"https://github.com/eugene-plexus/workbench/archive/{commit}.tar.gz",
    )
    (directory / "catalogue.yaml").write_text(yaml.safe_dump(catalogue), encoding="utf-8")


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "agent":
        from eugene_plexus_agent import apps

        catalogue = apps.load_catalogue((directory / "catalogue.yaml").read_text(encoding="utf-8"))
        apps.load_catalogue = lambda: catalogue
        load("row32_harness", "s8-ui-acceptance.py").serve(directory, port)
        return
    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(
            Settings(config_file=directory / "control.yaml", state_dir=directory / "state")
        )
    elif kind == "fixture":
        app = fixture_app()
    else:
        raise ValueError(f"Unknown process: {kind}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def tree(root: Path) -> list[str]:
    """Every path under `root`, but the SQLite files any request or background index sync may
    write (the store, and each person's index under `knowledge/`)."""
    return sorted(
        str(p.relative_to(root))
        for p in root.rglob("*")
        if ".sqlite3" not in p.name and p.relative_to(root).parts[0] != "knowledge"
    )


def exercise(work: Path, workbench_ref: str) -> None:
    harness = load("row32_ports", "s8-ui-acceptance.py")
    c3 = load("row32_browser", "c3-workbench-acceptance.py")
    r7 = load("row32_archive", "row7-person-removal-acceptance.py")
    commit = r7.resolve(workbench_ref)
    ports: dict[str, int] = {}
    for name in ("control", "agent", "gateway", "model", "fixture"):
        ports[name] = harness.free_port(*ports.values())
    assert not set(ports.values()) & set(range(8079, 8084))
    urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
    processes: dict[str, subprocess.Popen] = {}
    logs = []
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env.update(
        OPENAI_API_KEY="row32-fixture",  # gitleaks:allow (a fake)
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
    )
    password = secrets.token_urlsafe(24)
    client = httpx.Client(timeout=60, trust_env=False)

    def wait(probe, label: str, seconds: float = 90):
        deadline, last = time.perf_counter() + seconds, None
        while time.perf_counter() < deadline:
            for name, process in processes.items():
                if process.poll() is not None:
                    raise Abort(f"{name} exited with code {process.returncode}")
            try:
                value = probe()
                if value:
                    return value
            except (httpx.HTTPError, KeyError, ValueError, IndexError, StopIteration) as exc:
                last = str(exc)[:400]
            time.sleep(0.2)
        raise Abort(f"timed out waiting for {label}: {last}")

    def call(name: str, method: str, path: str, token: str | None = None, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        result = client.request(method, urls[name] + path, headers=headers, **kwargs)
        result.raise_for_status()
        return result.json() if result.content else None

    def start(name: str) -> None:
        directory = work / name
        directory.mkdir(exist_ok=True)
        log = (directory / "process.log").open("ab")
        logs.append(log)
        processes[name] = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve", name, "--directory",
             str(directory), "--port", str(ports[name])],
            cwd=directory, env=env, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait(lambda: client.get(urls[name] + "/healthz").status_code == 200, name)

    def seen() -> list[dict]:
        return call("fixture", "GET", "/seen")

    try:
        say("an install: a root, an agent with a gateway and a model, Workbench")
        start("fixture")
        start("control")
        call("control", "POST", "/v1/auth/initialize", json={"passphrase": password})
        root = call("control", "POST", "/v1/auth/login", json={"passphrase": password})[
            "sessionToken"
        ]
        agent_dir = work / "agent"
        agent_dir.mkdir()
        (agent_dir / "gateway.yaml").write_text(
            yaml.safe_dump({"routingRefreshSeconds": 1}), encoding="utf-8"
        )
        (agent_dir / "model.yaml").write_text(
            yaml.safe_dump({"provider": "openrouter", "baseUrl": urls["fixture"]}),
            encoding="utf-8",
        )
        (agent_dir / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "securityMode": "prompt_on_startup",
                    "uvBinary": c3.uv_binary(),
                    "components": [
                        {"name": name, "kind": kind, "url": urls[name],
                         "spawn": {"configFile": str(agent_dir / f"{name}.yaml")}}
                        for name, kind in (("gateway", "gateway"), ("model", "inference-driver"))
                    ],
                }
            ),
            encoding="utf-8",
        )
        workbench_catalogue(agent_dir, commit)
        start("agent")
        local = call("agent", "POST", "/v1/auth/initialize", json={"passphrase": password})[
            "sessionToken"
        ]
        join = call("control", "POST", "/v1/nodes/join-token", root,
                    json={"nodeName": "row32", "grants": ["gateway"]})["token"]
        call("agent", "POST", "/v1/node/enroll", local, timeout=90,
             json={"controlUrl": urls["control"], "token": join, "name": "row32"})
        wait(lambda: client.get(urls["agent"] + "/healthz").status_code == 200, "the agent")
        operator = call("agent", "POST", "/v1/auth/login", json={"passphrase": password})[
            "sessionToken"
        ]
        entry = next(
            e["manifest"] for e in call("agent", "GET", "/v1/app-catalogue", operator)["apps"]
            if e["manifest"]["id"] == APP
        )
        must("0a", f"the Workbench under test is the catalogue entry ({commit[:12]})",
             entry["version"] == commit, entry)
        call("agent", "POST", f"/v1/apps/{APP}/install", operator)

        def installed() -> bool:
            state = call("agent", "GET", f"/v1/apps/{APP}/install", operator)
            if state["state"] == "failed":
                raise Abort("the install failed: " + str(state.get("error"))[-1500:])
            return state["state"] == "done"

        wait(installed, "the install", 900)
        app = wait(
            lambda: a if (a := call("agent", "GET", f"/v1/apps/{APP}", operator))["status"]
            == "running" else None,
            "Workbench running", 120,
        )
        ui = app["uiUrl"].rstrip("/")
        data = agent_dir / "apps" / APP / "data"
        if not (data / "workbench.sqlite3").is_file():
            data = next(agent_dir.rglob("workbench.sqlite3")).parent
        owner = c3.Browser(ui)
        must("0b", "the owner signs in", owner.sign_in(password).startswith("/#signin="))
        people = {}
        for name in ("ada", "bo"):
            made = call("control", "POST", "/v1/people", root,
                        json={"name": name, "displayName": name.title(),
                              "password": f"{name}-password-32"})
            people[name] = made["id"]
        ada, bo = c3.Browser(ui), c3.Browser(ui)
        must("0c", "Ada and Bo sign in",
             ada.sign_in("ada-password-32", "ada").startswith("/#signin=")
             and bo.sign_in("bo-password-32", "bo").startswith("/#signin="))
        model = wait(
            lambda: next(m["id"] for m in ada.get("/api/models").json()["models"]
                         if m["id"].endswith(MODEL)),
            "the model is listed", 90,
        )

        def chat(person, instructions: str | None = "Be brief.") -> str:
            made = person.post("/api/chats", json={"model": model})
            made.raise_for_status()
            chat_id = made.json()["id"]
            if instructions:
                person.patch(f"/api/chats/{chat_id}",
                             json={"settings": {"instructions": instructions}}).raise_for_status()
            return chat_id

        def ask(person, chat_id: str, words: str) -> tuple[dict, list[dict]]:
            """The answer, and the requests the fixture had for it: streamed, and asking
            `words` last (a background call Workbench makes is not one of them)."""
            before = len(seen())
            answer = person.ask(chat_id, words)
            if answer["status"] != "done":
                raise Abort(f"the answer {answer['status']}: {answer.get('error')}")

            def asking(request: dict) -> bool:
                users = [m for m in request["messages"] if m["role"] == "user"]
                return bool(users) and words in json.dumps(users[-1].get("content"))

            return answer, [r for r in seen()[before:] if r.get("stream") and asking(r)]

        def tool(request: dict, name: str) -> dict | None:
            return next((t["function"] for t in request.get("tools") or []
                         if t["function"]["name"] == name), None)

        def system(request: dict) -> str | None:
            found = [m["content"] for m in request["messages"] if m["role"] == "system"]
            return found[0] if found else None

        say("1. Ada adds a skill, reads it, turns it on, and the model uses it")
        ada_chat = chat(ada)
        _, plain = ask(ada, ada_chat, "row32 plain")
        check("1a", "with no skills, no skill tool is offered", tool(plain[-1], "use_skill") is None)
        added = ada.post("/api/skills", files={"file": ("pdf-forms.zip", good_zip(),
                                                         "application/zip")})
        must("1b", "Ada's skill ZIP is added, off", added.status_code == 201
             and added.json()["on"] is False, added.text[:300])
        skill = added.json()
        whole = ada.get(f"/api/skills/{skill['id']}").json()
        check("1c", "the page shows the whole SKILL.md, other keys kept and not used",
              whole["skillMd"] == skill_md().decode()
              and [o["key"] for o in whole["others"]] == ["license"], whole.get("others"))
        ada.patch(f"/api/skills/{skill['id']}", json={"on": True}).raise_for_status()
        _, rounds = ask(ada, ada_chat, "row32 use")
        must("1d", "the model asked three times: use_skill, read_skill_file, then its answer",
             len(rounds) == 3, [len(r["messages"]) for r in rounds])
        listing = tool(rounds[0], "use_skill") or {}
        check("1e", "the tool definition lists the skill as name: description",
              "- pdf-forms: Fill in PDF forms." in listing.get("description", ""), listing)
        check("1f", "the system message is byte-identical with and without skills",
              system(rounds[0]) == system(plain[-1]) and system(plain[-1]) is not None,
              [system(plain[-1]), system(rounds[0])])
        check("1g", "no message the model is sent names a skill before it calls one",
              "pdf-forms" not in json.dumps(rounds[0]["messages"]))
        used = [m["content"] for m in rounds[1]["messages"] if m["role"] == "tool"]
        read = [m["content"] for m in rounds[2]["messages"] if m["role"] == "tool"]
        check("1h", "use_skill returns the body and the file list",
              len(used) == 1 and BODY_MARK in used[0] and "references/style.md" in used[0]
              and "scripts/fill.py" in used[0] and "name: pdf-forms" not in used[0], used)
        check("1i", "read_skill_file returns the file", len(read) == 2 and STYLE_MARK in read[1],
              read[-1:])

        say("2. scripts")
        check("2", "the script line says no Job Site allows commands",
              bool(used) and "This skill has scripts. They run only on a Job Site that allows "
              "commands; this chat has none." in used[0], used)

        say("3. Bo, and a skill the owner gives everyone")
        listed = bo.get("/api/skills").json()["skills"]
        by_id = bo.get(f"/api/skills/{skill['id']}")
        bo_chat = chat(bo)
        picked = bo.patch(f"/api/chats/{bo_chat}", json={"settings": {"skills": [skill["id"]]}})
        check("3a", "Bo sees nothing of Ada's: not listed, 404 by id, refused for a chat",
              listed == [] and by_id.status_code == 404 and picked.status_code == 400,
              {"listed": listed, "byId": by_id.status_code, "picked": picked.status_code})
        written = owner.post("/api/skills/written", json={
            "name": "house-style", "description": "The house style.", "instructions": "Be kind."})
        must("3b", "the owner writes a skill", written.status_code == 201, written.text[:300])
        shared = owner.patch(f"/api/skills/{written.json()['id']}", json={"everyone": True})
        must("3c", "and gives it to everyone", shared.status_code == 200
             and shared.json()["everyone"] is True, shared.text[:300])
        seen_by = {
            who: [(s["name"], s["fromEugene"], s["on"])
                  for s in person.get("/api/skills").json()["skills"] if s["everyone"]]
            for who, person in (("ada", ada), ("bo", bo))
        }
        check("3d", "both see it, marked From Eugene, on",
              all(v == [("house-style", True, True)] for v in seen_by.values()), seen_by)
        _, ada_rounds = ask(ada, chat(ada), "row32 plain")
        _, bo_rounds = ask(bo, chat(bo), "row32 plain")
        check("3e", "it reaches both people's chats",
              "house-style" in (tool(ada_rounds[0], "use_skill") or {}).get("description", "")
              and "house-style" in (tool(bo_rounds[0], "use_skill") or {}).get("description", ""))
        check("3f", "Bo cannot change or delete it",
              bo.patch(f"/api/skills/{written.json()['id']}",
                       json={"instructions": "Be rude."}).status_code == 403
              and bo.http.delete(f"{ui}/api/skills/{written.json()['id']}",
                                 headers=bo._headers()).status_code == 403)
        off = bo.patch(f"/api/skills/{written.json()['id']}", json={"on": False})
        _, bo_after = ask(bo, chat(bo), "row32 plain")
        check("3g", "Bo turns it off, and it leaves his next chat",
              off.status_code == 200 and off.json()["on"] is False
              and tool(bo_after[0], "use_skill") is None, off.text[:200])
        _, ada_after = ask(ada, chat(ada), "row32 plain")
        check("3h", "and only his", "house-style" in (tool(ada_after[0], "use_skill") or {})
              .get("description", ""))
        # Ada turns it off too, so her removal has a row of hers in skill_off to delete.
        ada.patch(f"/api/skills/{written.json()['id']}", json={"on": False}).raise_for_status()

        say("4. hostile archives")
        before = tree(data)
        refusals = {}
        for label, payload, words in hostile():
            answer = ada.post("/api/skills", files={"file": ("skill.zip", payload,
                                                             "application/zip")})
            message = (answer.json().get("detail") or {}).get("message", "")
            refusals[label] = (answer.status_code, message)
            check(f"4 {label}", f"{label}: refused with its cause",
                  answer.status_code in (400, 413, 415) and message.startswith("Not added: ")
                  and all(w in message for w in words), (answer.status_code, message))
        after = tree(data)
        escaped = [str(p) for p in work.rglob(ESCAPE)]
        for candidate in (Path(f"C:/{ESCAPE}"), Path(f"/tmp/{ESCAPE}"),
                          Path(tempfile.gettempdir()) / ESCAPE):
            if candidate.exists():
                escaped.append(str(candidate))
        check("4z", "nothing was written: Workbench's data folder is the same tree, and no "
              "escape exists", after == before and escaped == [],
              {"new": sorted(set(after) - set(before)), "escaped": escaped})
        check("4y", "Ada's skills are as they were",
              [s["name"] for s in ada.get("/api/skills").json()["skills"]]
              == ["house-style", "pdf-forms"])

        say("5. Ada is removed")
        folder = data / "skills" / key_of(people["ada"])
        must("5a", "her skill folder is there before", (folder / skill["id"] / "SKILL.md").is_file())
        client.delete(urls["control"] + f"/v1/people/{people['ada']}",
                      headers={"Authorization": f"Bearer {root}"}).raise_for_status()
        checked = owner.post("/api/removed-people/check").json()
        row = next((p for p in checked["people"] if p["sub"] == people["ada"]), None)
        must("5b", "the owner's check hides her", row is not None and row["state"] == "hidden",
             checked)
        started = owner.post(f"/api/removed-people/{people['ada']}/delete")
        must("5c", "Delete now starts", started.status_code == 202, started.text[:200])

        def purged():
            listed = owner.get("/api/removed-people").json()["people"]
            return next((p for p in listed
                         if p["sub"] == people["ada"] and p["state"] == "purged"), None)

        done = wait(purged, "her purge", 180)
        check("5d", "the purge finishes cleanly", not done["problem"], done)
        with contextlib.closing(
            sqlite3.connect(f"{(data / 'workbench.sqlite3').as_uri()}?mode=ro", uri=True)
        ) as db:
            rows = (
                db.execute("SELECT COUNT(*) FROM skills WHERE owner = ?",
                           (people["ada"],)).fetchone()[0],
                db.execute("SELECT COUNT(*) FROM skill_off WHERE sub = ?",
                           (people["ada"],)).fetchone()[0],
            )
            kept = [r[0] for r in db.execute("SELECT name FROM skills WHERE owner = 'install'")]
        check("5e", "her skill folder and rows are gone", not folder.exists() and rows == (0, 0),
              {"folder": folder.exists(), "rows": rows})
        check("5f", "the skill given to everyone stays, and Bo still has it",
              kept == ["house-style"]
              and [s["name"] for s in bo.get("/api/skills").json()["skills"]] == ["house-style"],
              kept)
    except Abort as exc:
        print(f"\nABORTED: {exc}", flush=True)
        for name in ("agent", "control"):
            log = work / name / "process.log"
            if log.exists():
                tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
                print(f"---- {name} log (last 60 lines) ----", *tail, sep="\n", flush=True)
    finally:
        (work / "agent" / "stop").touch()
        import psutil

        for process in reversed(list(processes.values())):
            with contextlib.suppress(psutil.NoSuchProcess):
                top = psutil.Process(process.pid)
                for child in top.children(recursive=True):
                    with contextlib.suppress(psutil.NoSuchProcess):
                        child.kill()
                with contextlib.suppress(psutil.NoSuchProcess):
                    top.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=20)
        client.close()
        for log in logs:
            log.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve", choices=["agent", "control", "fixture"])
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--workbench", default=os.getenv("R32_WORKBENCH_REF") or "main")
    parser.add_argument("--output", type=Path, help="keep the working folder here")
    args = parser.parse_args()
    for name in list(os.environ):
        if name.upper().startswith("EUGENE_PLEXUS_"):
            del os.environ[name]
    if args.serve:
        assert args.port and args.port not in set(range(8079, 8084))
        serve(args.serve, args.directory, args.port)
        return
    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)
        exercise(args.output.resolve(), args.workbench)
    else:
        with tempfile.TemporaryDirectory(prefix="row32-", ignore_cleanup_errors=True) as directory:
            exercise(Path(directory), args.workbench)
    failed = [r for r in RESULTS if not r[2]]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    finished = any(r[0] == "5f" for r in RESULTS)
    sys.exit(1 if failed or not finished else 0)


if __name__ == "__main__":
    main()
