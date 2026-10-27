"""Row 27a: past chats migrate, send once across a crash, yield to live work and stop.

Real control, agent, supervised gateway/driver, Workbench and reference memory server
processes, following row7-person-removal-acceptance.py. Only the model is a stand-in.
All state and the Workbench package COPY live under the worktree root's .codex-tmp.
Ports come from the OS; ambient EUGENE_PLEXUS_* variables are removed.

Run with CI's integration interpreter (all runtime dependencies installed):
    python specs/scripts/row27a-backfill-acceptance.py --workbench REF
    python specs/scripts/row27a-backfill-acceptance.py --source workbench --sabotage

--source copies a local candidate; otherwise resolve the candidate like row 7, using
the same-named component branch or main. No Workbench worktree file is ever patched.
--sabotage first disables the restart's exclusion of already-sent queue rows, in the
temporary store.py only. Step 3 must fail on duplicate document IDs. Restore the copy,
then run every normal check. CI deliberately does not enable sabotage.

The crash is between acknowledged deliveries: hold the next retain BEFORE the server
accepts it, kill Workbench, then discard that dead caller's unaccepted request. This
tests durable restart guards without claiming atomicity between two separate servers.
Stop instead releases an active retain normally, and watches for arrivals after DELETE.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import math
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent
SCRIPT = Path(__file__).resolve()
TEMP_ROOT = HERE.parents[1] / ".codex-tmp"
BACKFILL = "/api/memory/server/backfill"
MODEL = "r7-local"  # row 7's stand-in engine, reached through the real gateway
EXTRA_COLUMNS = {
    "memory_servers": ("backfill",),
    "projects": ("model",),
    "memory_tidy": ("model", "merged"),
    "document_folders": ("project_id",),
}
sys.dont_write_bytecode = True


class Failure(AssertionError):
    def __init__(self, step: str, observed: object):
        self.step = step
        self.observed = observed
        super().__init__(f"{step}: {observed}")


def check(step: str, claim: str, passed: bool, observed: object) -> None:
    print(f"{'PASS' if passed else 'FAIL'} {step}. {claim}: {observed}", flush=True)
    if not passed:
        raise Failure(step, observed)


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def wait(fn, label: str, seconds: float = 60):
    deadline = time.perf_counter() + seconds
    observed = None
    while time.perf_counter() < deadline:
        try:
            observed = fn()
            if observed:
                return observed
        except (httpx.HTTPError, KeyError) as exc:
            observed = str(exc)
        time.sleep(0.05)
    raise TimeoutError(f"{label}; last observation={observed!r}, waited {seconds}s")


def snapshot(path: Path, columns: dict | None = None) -> dict:
    """Compare every old value, including every message and its tree links, read-only."""
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        if columns is None:
            tables = (
                "people",
                "chats",
                "messages",
                "projects",
                "memory_servers",
                "document_folders",
                "memory_tidy",
                "settings",
            )
            columns = {
                t: [r[1] for r in db.execute(f"PRAGMA table_info({t})")] for t in tables
            }
        result = {}
        for table, names in columns.items():
            selected = ", ".join(f'"{name}"' for name in names)
            result[table] = {
                "columns": names,
                "rows": sorted(
                    [
                        list(row)
                        for row in db.execute(f'SELECT {selected} FROM "{table}"')
                    ],
                    key=repr,
                ),
            }
        return result


async def seed(directory: Path) -> None:
    """Build a populated schema-32 fixture, removing all five schema-33 columns.

    As in Workbench's migration unit test, use its schema builder, then undo 33's
    additive DDL. The acceptance takes the old-column snapshot BEFORE Workbench starts.
    """
    from eugene_plexus_workbench.store import Chat, Message, Person, Project, Store

    people = json.loads((directory / "people.json").read_text(encoding="utf-8"))
    store = Store(directory / "workbench.sqlite3")
    await store.open()
    expected: dict[str, str] = {}
    excluded = []
    try:
        for sub in ("operator", people["ben"]):
            await store.upsert_person(
                Person(sub, sub, "operator" if sub == "operator" else "member")
            )
        await store.put_setting("memoryServers", "any")
        await store.put_setting("memoryWritePolicy", "custom")
        await store.put_setting("memoryPolicySource", "own")
        await store.put_project(
            Project("private-project", "operator", "Private", 1, 2), limit=10
        )
        # Also exercise preservation in each table getting an additive column.
        await store.put_memory_server(
            "unused-person",
            "https://unused.invalid/mcp",
            "fixture-token",
            "Preserved server",
            {},
        )
        groups = [
            ("past-a", "operator", 18, {}),
            ("past-b", "operator", 18, {}),
            ("stop-chat", people["ben"], 24, {}),
            ("project-chat", "operator", 2, {"project_id": "private-project"}),
            ("memory-off", "operator", 2, {"settings": {"memory": "off"}}),
            ("key-chat", "operator", 1, {}),
        ]
        ordinal = 0
        for chat_id, sub, count, kwargs in groups:
            await store.create_chat(Chat(chat_id, sub, chat_id, MODEL, 1, 2, **kwargs))
            parent = None
            for i in range(count):
                stamp = 1_700_000_000 + ordinal
                ordinal += 1
                text = f"I grow beans in garden bed {chat_id} {i}."
                if chat_id == "key-chat":
                    text = "My API key is " + "sk-" + "a" * 48
                user_id, answer_id = f"{chat_id}-q{i:02}", f"{chat_id}-a{i:02}"
                await store.add_message(
                    Message(
                        user_id, chat_id, i * 2, "user", "done", stamp, content=text
                    ),
                    parent_id=parent,
                )
                await store.add_message(
                    Message(
                        answer_id,
                        chat_id,
                        i * 2 + 1,
                        "assistant",
                        "done",
                        stamp + 0.1,
                        content="Understood.",
                    ),
                    parent_id=user_id,
                )
                doc_id = f"{chat_id}:{answer_id}"
                if chat_id.startswith("past-"):
                    expected[doc_id] = text
                elif sub == "operator":
                    excluded.append(doc_id)
                parent = answer_id
    finally:
        await store.close()
    with closing(sqlite3.connect(directory / "workbench.sqlite3")) as db:
        db.execute(
            "INSERT INTO document_folders (owner, grant_id, name, added_at) "
            "VALUES ('operator', 'old-folder', 'Preserved folder', 2)"
        )
        db.execute("DROP INDEX document_folders_by_project")
        for table, names in EXTRA_COLUMNS.items():
            for name in names:
                db.execute(f"ALTER TABLE {table} DROP COLUMN {name}")
        db.execute("UPDATE meta SET value = '32' WHERE key = 'schema'")
        db.commit()
    (directory / "expected.json").write_text(
        json.dumps({"documents": expected, "excluded": excluded}), encoding="utf-8"
    )


def serve(directory: Path, port: int) -> None:
    import uvicorn
    from eugene_plexus_workbench.app import create_app
    from eugene_plexus_workbench.settings import Settings
    from eugene_plexus_workbench.store import Store

    if not (directory / "migration.json").exists():
        # Record migration before startup jobs refresh people or withdraw an old
        # folder without a real grant. Those jobs deliberately change rows.
        async def migrate():
            store = Store(directory / "workbench.sqlite3")
            await store.open()
            await store.close()

        asyncio.run(migrate())
        columns = json.loads(
            (directory / "old-columns.json").read_text(encoding="utf-8")
        )
        migrated = snapshot(directory / "workbench.sqlite3", columns)
        (directory / "migration.json").write_text(
            json.dumps(migrated), encoding="utf-8"
        )

    values = json.loads((directory / "settings.json").read_text(encoding="utf-8"))
    uvicorn.run(
        create_app(Settings(**values)),
        host="127.0.0.1",
        port=port,
        access_log=False,
        log_level="error",
    )


class Install:
    def __init__(self, work: Path, package: Path, commit: str):
        self.work, self.package, self.commit = work, package, commit
        self.r7 = load("row27a_row7", "row7-person-removal-acceptance.py")
        self.c3 = load("row27a_c3", "c3-workbench-acceptance.py")
        self.ports = self.c3.free_ports(
            ["control", "agent", "fixture", "gateway", "model", "memory", "workbench"]
        )
        assert not set(self.ports.values()) & set(range(8079, 8084)), self.ports
        self.http = httpx.Client(timeout=30, trust_env=False)
        self.processes: list[subprocess.Popen] = []
        self.browsers = []
        self.workbench = None
        self.current_step = "0"

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.ports[name]}"

    def call(self, name: str, method: str, path: str, token: str | None = None, **kw):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = self.http.request(
            method, self.url(name) + path, headers=headers, **kw
        )
        response.raise_for_status()
        return response

    def spawn(self, name: str, command: list[str], *, candidate: bool = False):
        directory = self.work / name
        directory.mkdir(exist_ok=True)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.upper().startswith("EUGENE_PLEXUS_")
        }
        env.pop("OPENAI_API_KEY", None)
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if candidate:
            env["PYTHONPATH"] = (
                str(self.package) + os.pathsep + env.get("PYTHONPATH", "")
            )
        for key in ("TEMP", "TMP", "TMPDIR"):
            env[key] = str(self.work / "tmp")
        with (directory / "process.log").open("ab") as log:
            process = subprocess.Popen(
                command,
                cwd=directory,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        self.processes.append(process)
        return process

    def start(self, name: str):
        self.spawn(
            name,
            [
                sys.executable,
                str(HERE / "row7-person-removal-acceptance.py"),
                "--serve",
                name,
                "--directory",
                str(self.work / name),
                "--port",
                str(self.ports[name]),
            ],
        )
        wait(
            lambda: self.call(name, "GET", "/healthz").status_code == 200,
            f"{name} healthy",
        )

    def start_workbench(self):
        self.workbench = self.spawn(
            "workbench",
            [
                sys.executable,
                str(SCRIPT),
                "--serve-workbench",
                "--directory",
                str(self.work / "workbench"),
                "--port",
                str(self.ports["workbench"]),
            ],
            candidate=True,
        )
        wait(
            lambda: self.call("workbench", "GET", "/healthz").status_code == 200,
            "Workbench healthy",
        )

    def state(self):
        return self.call("memory", "GET", "/state").json()

    def control(self, **values):
        self.call("memory", "POST", "/control", json=values)

    def gate(self, count: int):
        self.control(retain_limit=count)
        return wait(
            lambda: (
                (s if len(s["retained"]) == count and s["retain_waiting"] else None)
                if (s := self.state())
                else None
            ),
            f"server accepted {count} and holds next",
        )

    def browser(self, password: str, name: str | None = None):
        browser = self.c3.Browser(self.url("workbench"))
        self.browsers.append(browser)
        location = browser.sign_in(password, name)
        assert location.startswith("/#signin="), location
        return browser

    def delete(self, browser, path: str):
        return browser.http.delete(browser.base + path, headers=browser._headers())

    def setup(self):
        (self.work / "tmp").mkdir(parents=True)
        print(f"Processes in {self.work}; OS-assigned ports={self.ports}", flush=True)
        self.start("fixture")
        self.start("control")
        password = secrets.token_urlsafe(24)
        self.call(
            "control", "POST", "/v1/auth/initialize", json={"passphrase": password}
        )
        root = self.call(
            "control", "POST", "/v1/auth/login", json={"passphrase": password}
        ).json()["sessionToken"]
        agent_dir = self.work / "agent"
        agent_dir.mkdir()
        (agent_dir / "gateway.yaml").write_text(
            yaml.safe_dump({"routingRefreshSeconds": 1}), encoding="utf-8"
        )
        (agent_dir / "model.yaml").write_text(
            yaml.safe_dump(
                {
                    "provider": "openai_compat_custom",
                    "baseUrl": self.url("fixture") + "/model",
                    "modelId": MODEL,
                    "backendLocality": "local",
                }
            ),
            encoding="utf-8",
        )
        (agent_dir / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "advertiseUrl": f"http://{self.c3.routable_address()}:{self.ports['agent']}",
                    "securityMode": "prompt_on_startup",
                    "components": [
                        {
                            "name": name,
                            "kind": kind,
                            "url": self.url(name),
                            "spawn": {"configFile": str(agent_dir / f"{name}.yaml")},
                        }
                        for name, kind in (
                            ("gateway", "gateway"),
                            ("model", "inference-driver"),
                        )
                    ],
                }
            ),
            encoding="utf-8",
        )
        # The shipped catalogue, Workbench's entry at the candidate's archive, as rows 7 and 70c
        # do: the agent needs a catalogue file. This script runs Workbench itself, as a process
        # it can seed at schema 32, kill hard and restart, not as an app the agent installs.
        self.r7.workbench_catalogue(
            agent_dir,
            version=self.commit,
            source=f"https://github.com/eugene-plexus/workbench/archive/{self.commit}.tar.gz",
        )
        self.start("agent")
        local = self.call(
            "agent", "POST", "/v1/auth/initialize", json={"passphrase": password}
        ).json()["sessionToken"]
        join = self.call(
            "control",
            "POST",
            "/v1/nodes/join-token",
            root,
            json={"nodeName": "row27a", "grants": ["gateway"]},
        ).json()["token"]
        self.call(
            "agent",
            "POST",
            "/v1/node/enroll",
            local,
            json={"controlUrl": self.url("control"), "token": join, "name": "row27a"},
        )
        wait(
            lambda: self.call("agent", "GET", "/healthz").status_code == 200,
            "enrolled agent",
        )
        operator = self.call(
            "agent", "POST", "/v1/auth/login", json={"passphrase": password}
        ).json()["sessionToken"]
        key = self.call(
            "agent",
            "POST",
            "/v1/auth/client-keys",
            operator,
            json={"name": "app:workbench-row27a@row27a"},
        ).json()["token"]
        oidc = self.call(
            "control",
            "POST",
            "/v1/oidc/clients",
            root,
            json={
                "name": "Row 27a Workbench",
                "owner": "app:workbench-row27a@row27a",
                "redirectUris": [self.url("workbench") + "/oidc/callback"],
            },
        ).json()
        ben_password = "row27a-ben-password"
        ben = self.call(
            "control",
            "POST",
            "/v1/people",
            root,
            json={"name": "ben", "displayName": "Ben", "password": ben_password},
        ).json()["id"]
        data = self.work / "workbench"
        data.mkdir()
        (data / "key").write_text(key, encoding="utf-8")
        (data / "secret").write_text(oidc["clientSecret"], encoding="utf-8")
        (data / "people.json").write_text(json.dumps({"ben": ben}), encoding="utf-8")
        (data / "settings.json").write_text(
            json.dumps(
                {
                    "data_dir": str(data),
                    "bind_port": self.ports["workbench"],
                    "gateway_url": self.url("gateway"),
                    "key_file": str(data / "key"),
                    "oidc_issuer": self.url("agent") + "/oidc",
                    "oidc_client_id": oidc["client"]["clientId"],
                    "oidc_secret_file": str(data / "secret"),
                }
            ),
            encoding="utf-8",
        )
        seeded = self.spawn(
            "workbench",
            [sys.executable, str(SCRIPT), "--seed", "--directory", str(data)],
            candidate=True,
        )
        assert seeded.wait(timeout=60) == 0, (data / "process.log").read_text(
            encoding="utf-8"
        )[-2500:]
        expected = json.loads((data / "expected.json").read_text(encoding="utf-8"))
        before = snapshot(data / "workbench.sqlite3")
        (data / "old-columns.json").write_text(
            json.dumps({t: v["columns"] for t, v in before.items()}), encoding="utf-8"
        )
        with closing(sqlite3.connect(data / "workbench.sqlite3")) as db:
            old_version = db.execute(
                "SELECT value FROM meta WHERE key='schema'"
            ).fetchone()[0]
        self.spawn(
            "memory",
            [
                sys.executable,
                str(HERE / "m-memory-server.py"),
                "--port",
                str(self.ports["memory"]),
            ],
        )
        wait(lambda: self.state(), "memory server")
        self.current_step = "1"
        self.start_workbench()
        with closing(sqlite3.connect(data / "workbench.sqlite3")) as db:
            version = db.execute(
                "SELECT value FROM meta WHERE key='schema'"
            ).fetchone()[0]
            added = {
                t: {r[1]: r for r in db.execute(f"PRAGMA table_info({t})")}
                for t in EXTRA_COLUMNS
            }
        after = json.loads((data / "migration.json").read_text(encoding="utf-8"))
        backup = data / "workbench.sqlite3.schema-32.bak"
        intact = before == after and backup.is_file() and snapshot(backup) == before
        nullable = all(
            added[t].get(n, (None,) * 4)[3] == 0
            for t, names in EXTRA_COLUMNS.items()
            for n in names
        )
        # 33 is row 27a's own step; a later row's migration (34, row 32) runs on after it.
        check(
            "1",
            "populated schema 32 migrates to 33 and on, intact",
            old_version == "32" and int(version) >= 33 and intact and nullable,
            {
                "schema": f"{old_version}->{version}",
                "rows": {t: len(v["rows"]) for t, v in before.items()},
                "all_old_values_intact": intact,
                "new_columns_nullable": nullable,
            },
        )
        owner = self.browser(password, "operator")
        ben_browser = self.browser(ben_password, "ben")
        wait(
            lambda: any(
                m["id"] == MODEL for m in owner.get("/api/models").json()["models"]
            ),
            "gateway model",
            90,
        )
        return owner, ben_browser, expected

    def connect(self, browser):
        response = browser.http.put(
            browser.base + "/api/memory/server",
            headers=browser._headers(),
            json={"url": self.url("memory") + "/mcp", "token": ""},
        )
        response.raise_for_status()

    def close(self):
        for browser in self.browsers:
            browser.http.close()
        # Includes the gateway/driver supervised by the disposable agent; wait for death
        # before removing the temporary install (Windows can keep its modules locked).
        import psutil

        children = []
        for process in reversed(self.processes):
            try:
                top = psutil.Process(process.pid)
                if process.poll() is None:
                    children.extend(top.children(recursive=True))
                    children.append(top)
            except psutil.NoSuchProcess:
                pass
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(children, timeout=10)
        for process in self.processes:
            process.wait(timeout=10)
        self.http.close()


def exercise(work: Path, package: Path, commit: str, *, sabotage: bool):
    install = Install(work, package, commit)
    original = None
    module = package / "eugene_plexus_workbench" / "store.py"
    try:
        owner, ben, expected = install.setup()
        install.current_step = "2"
        install.connect(owner)
        preview = owner.get(BACKFILL).json()
        docs = expected["documents"]
        check(
            "2",
            "preview counts only eligible exchanges; consent sends nothing",
            preview["exchanges"] == len(docs)
            and preview["chats"] == 2
            and preview["skipped"] == 1
            and preview["tokens"] == sum(math.ceil(len(t) / 3) for t in docs.values())
            and preview["estimateSeconds"] is None
            and preview["backfill"] is None
            and install.state()["retained"] == [],
            preview,
        )
        install.current_step = "3"
        install.control(retain_limit=3, retain_delay=0.15)
        began = owner.post(BACKFILL, json={})
        began.raise_for_status()
        partial = install.gate(3)
        # The fourth call proves the three preceding calls have been acknowledged.
        progress = owner.get(BACKFILL).json()["backfill"]
        check(
            "3a",
            "POST sends some but not all before a hard process kill",
            began.json()["backfill"]["state"] == "running"
            and 0 < len(partial["retained"]) < len(docs)
            and progress["sent"] == 3,
            {
                "server_ids": [r["document_id"] for r in partial["retained"]],
                "holding": partial["retain_waiting"],
                "persisted_sent": progress["sent"],
                "total": len(docs),
            },
        )
        pid = install.workbench.pid
        install.r7.kill_hard(pid)
        install.workbench.wait(timeout=15)
        install.control(discard_retains=True)
        wait(
            lambda: not install.state()["retain_waiting"],
            "dead caller's unaccepted request discarded",
        )
        if sabotage:
            original = module.read_bytes()
            source = original.decode("utf-8")
            guard = "SELECT * FROM memory_server_sent WHERE state IN ('send','forget') "
            assert source.count(guard) == 1, (
                "restart guard changed; review sabotage anchor"
            )
            module.write_bytes(
                source.replace(
                    guard, guard.replace("'send','forget'", "'send','forget','sent'")
                ).encode("utf-8"),
            )
            print(f"SABOTAGE restart guard disabled in COPY {module}", flush=True)
        install.start_workbench()
        check(
            "3b",
            "a new Workbench process resumes saved consent",
            install.workbench.pid != pid
            and owner.get(BACKFILL).json()["backfill"]["state"] == "running",
            {"killed_pid": pid, "restart_pid": install.workbench.pid},
        )
        # One accepted backfill, then hold the next. Queue a real live answer behind
        # that active call. Only that call may finish before the live exchange.
        install.gate(4)
        install.current_step = "4"
        live = owner.post("/api/chats", json={"model": MODEL}).json()["id"]
        answer = owner.ask(live, "I prefer runner beans in my garden.")
        live_id = f"{live}:{answer['id']}"

        # Completion queues asynchronously; inspect the actual queue read-only so this
        # assertion tests priority for work that is due, without depending on scheduling.
        def live_queued():
            with closing(
                sqlite3.connect(
                    (work / "workbench/workbench.sqlite3").as_uri() + "?mode=ro",
                    uri=True,
                )
            ) as db:
                return db.execute(
                    "SELECT state FROM memory_server_sent WHERE document_id=?",
                    (live_id,),
                ).fetchone() == ("send",)

        wait(live_queued, "live exchange queued")
        install.control(retain_limit=6)
        state = install.gate(6)
        ids = [r["document_id"] for r in state["retained"]]
        running = owner.get(BACKFILL).json()["backfill"]
        check(
            "4",
            "live answer goes ahead of queued past chats during the backfill",
            answer["status"] == "done"
            and ids[5] == live_id
            and running["state"] == "running"
            and running["sent"] < len(docs),
            {
                "answer_status": answer["status"],
                "next_ids": ids[4:6],
                "live_id": live_id,
                "backfill": running["state"],
                "sent": running["sent"],
                "total": len(docs),
            },
        )
        install.current_step = "3"
        install.control(retain_limit=None, retain_delay=0.02)

        def finished_or_duplicate():
            # "done" first: Workbench marks a document sent only after the server kept it,
            # so arrivals read afterwards hold every document. Read the other way round, the
            # last document can land between the two reads and look missing.
            done = owner.get(BACKFILL).json()["backfill"]["state"] == "done"
            counts = Counter(r["document_id"] for r in install.state()["retained"])
            return (
                (counts, done) if done or any(n > 1 for n in counts.values()) else None
            )

        counts, done = wait(
            finished_or_duplicate, "backfill done or duplicate observed", 120
        )
        state = install.state()
        progress = owner.get(BACKFILL).json()["backfill"]
        duplicates = {k: n for k, n in counts.items() if n != 1}
        missing = sorted(set(docs) - counts.keys())
        unexpected = sorted(counts.keys() - set(docs) - {live_id})
        excluded = [
            r["document_id"]
            for r in state["retained"]
            if r["document_id"] in expected["excluded"]
            or "sk-" + "a" * 48 in r["content"]
        ]
        wrong_content = [
            r["document_id"]
            for r in state["retained"]
            if r["document_id"] in docs and r["content"] != docs[r["document_id"]]
        ]
        check(
            "3",
            "after restart every eligible document arrived exactly once; no key arrived",
            done
            and not duplicates
            and not missing
            and not unexpected
            and not excluded
            and not wrong_content
            and counts[live_id] == 1
            and progress["sent"] == len(docs)
            and progress["skipped"] == 1,
            {
                "arrivals": sum(counts.values()),
                "unique_ids": len(counts),
                "expected_past": len(docs),
                "duplicates": duplicates,
                "missing": missing,
                "unexpected": unexpected,
                "excluded": excluded,
                "wrong_content": wrong_content,
                "sent": progress["sent"],
                "skipped": progress["skipped"],
                "done": done,
            },
        )
        install.current_step = "5"
        install.delete(owner, "/api/chats/past-a").raise_for_status()
        forgotten = {d for d in docs if d.startswith("past-a:")}
        wait(
            lambda: forgotten <= set(install.state()["forgotten"]),
            "each deleted exchange forgotten",
        )
        state = install.state()
        check(
            "5",
            "deleting a chat forgets each exchange and leaves other chats",
            Counter(state["forgotten"]) == Counter(dict.fromkeys(forgotten, 1))
            and not forgotten.intersection(state["memories"])
            and set(state["memories"]) == (set(docs) - forgotten) | {live_id}
            and state["cleared"] == 0,
            {
                "forget_ids": state["forgotten"],
                "expected_forgets": len(forgotten),
                "remaining_memories": len(state["memories"]),
                "cleared": state["cleared"],
            },
        )
        install.current_step = "6"
        install.connect(ben)
        baseline = len(install.state()["retained"])
        install.control(retain_limit=baseline + 2, retain_delay=0.15)
        ben.post(BACKFILL, json={}).raise_for_status()
        install.gate(baseline + 2)
        # Issue Stop while a retain is held. A correct Stop waits for that retain;
        # release it after observing whether DELETE returned early, then measure arrivals.
        with ThreadPoolExecutor(max_workers=1) as pool:
            stopped = pool.submit(install.delete, ben, BACKFILL)
            time.sleep(0.3)
            returned_while_held = stopped.done()
            at_return = (
                len(install.state()["retained"]) if returned_while_held else None
            )
            install.control(retain_limit=None, retain_delay=0.15)
            response = stopped.result(timeout=15)
            response.raise_for_status()
            if at_return is None:
                at_return = len(install.state()["retained"])
        started = time.perf_counter()
        observed_counts = [len(install.state()["retained"])]
        while time.perf_counter() - started < 2.0:
            time.sleep(0.05)
            observed_counts.append(len(install.state()["retained"]))
        elapsed = time.perf_counter() - started
        after_stop = ben.get(BACKFILL).json()["backfill"]
        check(
            "6",
            "Stop permits no new arrivals after DELETE returns",
            after_stop["state"] == "stopped"
            and 0 < after_stop["sent"] < after_stop["total"]
            and all(n == at_return for n in observed_counts),
            {
                "returned_while_retain_held": returned_while_held,
                "arrivals_at_return": at_return,
                "arrivals_after_wait": observed_counts[-1],
                "observed_seconds": round(elapsed, 3),
                "samples": len(observed_counts),
                "state": after_stop["state"],
                "sent": after_stop["sent"],
                "total": after_stop["total"],
            },
        )
    except (Failure, KeyboardInterrupt):
        raise
    except Exception as exc:
        check(
            install.current_step,
            "acceptance completed this step",
            False,
            f"{type(exc).__name__}: {exc}; process logs: {work}",
        )
    finally:
        try:
            install.close()
        finally:
            if original is not None:
                module.write_bytes(original)
                print("SABOTAGE restored the temporary store.py", flush=True)


def candidate(work: Path, source: Path | None, ref: str) -> tuple[Path, str]:
    commit = "local"
    if source is None:
        r7 = load("row27a_resolve", "row7-person-removal-acceptance.py")
        commit = r7.resolve(ref)
        print(f"Workbench candidate {commit}", flush=True)
        with httpx.Client(timeout=120, follow_redirects=True) as http:
            response = http.get(
                f"https://github.com/eugene-plexus/workbench/archive/{commit}.tar.gz"
            )
            response.raise_for_status()
        archive = work / "workbench.tar.gz"
        archive.write_bytes(response.content)
        with tarfile.open(archive) as tar:
            tar.extractall(work / "archive", filter="data")
        source = next((work / "archive").iterdir())
    else:
        print(f"Workbench local candidate copied from {source}", flush=True)
    install = work / "install"
    shutil.copytree(
        source / "src/eugene_plexus_workbench",
        install / "eugene_plexus_workbench",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return install, commit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--workbench", default=os.environ.get("R27A_WORKBENCH_REF") or "main"
    )
    parser.add_argument("--source", type=Path, help="copy a local Workbench candidate")
    parser.add_argument(
        "--sabotage",
        action="store_true",
        help="prove step 3 fails, restore, run normally",
    )
    parser.add_argument(
        "--keep", action="store_true", help="keep temporary state and logs"
    )
    parser.add_argument(
        "--serve-workbench", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument("--seed", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--directory", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    for key in list(os.environ):
        if key.upper().startswith("EUGENE_PLEXUS_"):
            del os.environ[key]
    if args.seed:
        asyncio.run(seed(args.directory))
        return 0
    if args.serve_workbench:
        serve(args.directory, args.port)
        return 0
    TEMP_ROOT.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="row27a-", dir=TEMP_ROOT)).resolve()
    passed = False
    try:
        package, commit = candidate(
            work, args.source.resolve() if args.source else None, args.workbench
        )
        if args.sabotage:
            try:
                exercise(work / "sabotage", package, commit, sabotage=True)
            except Failure as exc:
                check(
                    "7",
                    "sabotage is detected specifically by step 3's document-ID counts",
                    exc.step == "3"
                    and isinstance(exc.observed, dict)
                    and bool(exc.observed.get("duplicates")),
                    str(exc),
                )
            else:
                check(
                    "7",
                    "sabotage must fail step 3",
                    False,
                    "broken restart guard passed",
                )
        exercise(work / "normal", package, commit, sabotage=False)
        passed = True
        print(
            "ALL PASS row 27a"
            + (
                " (sabotage caught; restored normal run passed)"
                if args.sabotage
                else ""
            ),
            flush=True,
        )
        return 0
    except Failure:
        return 1
    finally:
        if args.keep or not passed:
            print(f"Evidence kept in {work}", flush=True)
        else:
            shutil.rmtree(work)


if __name__ == "__main__":
    sys.exit(main())
