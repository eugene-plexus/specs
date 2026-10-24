"""Row 70c acceptance: Workbench reads a person's groups and policies, and a group's memory
server is everyone's in the group (`docs/design/rows/row-70.md` section 5, steps 3 and 4).

Real processes on free ports (never 8079-8083), every `EUGENE_PLEXUS_*` variable cleared: a
control root, an enrolled agent that supervises a gateway and a model's inference-driver, a
stand-in engine, Eugene's reference memory server (`m-memory-server.py`), and Workbench,
installed by the agent as the shipped catalogue entry, pointed at its archive at the commit under test
(`--workbench`, or `R70C_WORKBENCH_REF`: a commit, or a branch, else `main`; as row 7's).

1. At the root: G1 (background, 70%) and G2 (interactive, 85%). A is in G1; B in G1 and G2;
   C in 40 groups with long names, past the ID token's 1024-byte cap.
2. (Row 70's step 3, Workbench's half.) A and B sign in to Workbench: its Settings say their
   groups, each value in effect (70% and background for A; 85% and interactive for B) and
   which group set it.
3. (Step 4.) The owner attaches the memory server to G1 in Workbench: A and B both see it as
   set by G1; neither can remove it, change it or attach one; a member cannot see the owner's
   list. A group id Eugene does not list gets none.
4. (Step 5, Workbench's half.) B is taken out of G2 at the root: at B's next sign-in Workbench
   says G1 only, 70% and background.
5. C's ID token is cut at the cap, so Workbench reads every group from userinfo: all 40 show.
6. G1 is deleted at the root: the owner sees its server as a deleted group's, and removes it.

    python specs/scripts/row70c-workbench-groups-acceptance.py [--workbench REF] [--keep]

Run in an environment holding every Python component (CI's pinned integration does).
"""

from __future__ import annotations

import argparse
import importlib.util
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
RESULTS: list[tuple[str, str, bool, str]] = []
PASSWORDS = {"a": "row70c-a-password", "b": "row70c-b-password", "c": "row70c-c-password"}


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


def exercise(work: Path, commit: str) -> None:
    c3 = load("c3", "c3-workbench-acceptance.py")
    r7 = load("r7", "row7-person-removal-acceptance.py")
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
            "modelId": r7.MODEL, "backendLocality": "local"}), encoding="utf-8")
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
                    json={"nodeName": "r70c-node", "grants": ["gateway"]}).json()["token"]
        enrolled = call("agent", "POST", "/v1/node/enroll", local, timeout=90,
                        json={"controlUrl": url["control"], "token": join, "name": "r70c-node"})
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
        ui = call("agent", "GET", f"/v1/apps/{APP}", operator).json()["uiUrl"].rstrip("/")
        configured = call("agent", "PATCH", f"/v1/apps/{APP}/config", operator,
                          json={"memoryServers": "any"})
        must("0d", "Workbench takes a memory server on this host", configured.status_code == 200
             and not configured.json().get("rejected"), configured.text[:300])

        say("1. two groups with policies, and three people in them")
        groups = {}
        for name, band, percent in (("G1", "background", 70), ("G2", "interactive", 85)):
            made = call("control", "POST", "/v1/permission-groups", root, json={
                "name": name, "apps": None,
                "policies": {"queueBand": band, "summaryContextPercent": percent}})
            must("1a", f"{name} is made with its policies", made.status_code == 201, made.text[:200])
            groups[name] = {"id": made.json()["id"], "name": name}
        many = []
        for n in range(40):
            made = call("control", "POST", "/v1/permission-groups", root, json={
                "name": f"Team {n:02d} " + "x" * 71, "apps": None,
                "policies": {"summaryContextPercent": 60}})
            must("1b", "a long-named group is made", made.status_code == 201, made.text[:200])
            many.append(made.json()["id"])
        people = {}
        for who, member_of in (("a", [groups["G1"]["id"]]),
                               ("b", [groups["G1"]["id"], groups["G2"]["id"]]),
                               ("c", many)):
            made = call("control", "POST", "/v1/people", root, json={
                "name": who, "displayName": who.upper(), "password": PASSWORDS[who],
                "groups": member_of})
            must("1c", f"{who.upper()} is made in their groups", made.status_code == 201, made.text[:200])
            people[who] = made.json()["id"]

        say("2. Workbench says each person's groups and what they set")
        a, b = Browser(ui), Browser(ui)
        must("2a", "A and B sign in to Workbench",
             a.sign_in(PASSWORDS["a"], "a").startswith("/#signin=")
             and b.sign_in(PASSWORDS["b"], "b").startswith("/#signin="))
        g1, g2 = groups["G1"], groups["G2"]
        seen_a = a.get("/api/groups").json()
        check("2b", "A: in G1; 70% and background, set by G1",
              seen_a["groups"] == [g1] and seen_a["policies"] == [
                  {"policy": "queueBand", "value": "background", "setBy": [g1]},
                  {"policy": "summaryContextPercent", "value": 70, "setBy": [g1]}], seen_a)
        seen_b = b.get("/api/groups").json()
        check("2c", "B: in G1 and G2; 85% and interactive, set by G2",
              seen_b["groups"] == [g1, g2] and seen_b["policies"] == [
                  {"policy": "queueBand", "value": "interactive", "setBy": [g2]},
                  {"policy": "summaryContextPercent", "value": 85, "setBy": [g2]}], seen_b)

        say("3. the owner gives G1 a memory server; its members see it and cannot remove it")
        owner = Browser(ui)
        must("3a", "the owner signs in", owner.sign_in(passphrase, "operator").startswith("/#signin="))
        listed = owner.get("/api/groups/manage")
        must("3b", "the owner sees Eugene's groups", listed.status_code == 200
             and g1 in [{"id": g["id"], "name": g["name"]} for g in listed.json()["groups"]],
             listed.text[:300])
        attached = owner.http.put(ui + f"/api/groups/{g1['id']}/memory-server", headers=owner._headers(),
                                  json={"url": url["memory"] + "/mcp", "token": ""})
        must("3c", "the owner attaches the memory server to G1", attached.status_code == 200,
             attached.text[:300])
        for who, person in (("A", a), ("B", b)):
            servers = person.get("/api/groups").json()["servers"]
            check("3d", f"{who} sees it as set by G1",
                  [s["group"] for s in servers] == [g1]
                  and servers[0]["server"]["url"] == url["memory"] + "/mcp", servers)
            removed = person.http.delete(ui + f"/api/groups/{g1['id']}/memory-server",
                                         headers=person._headers())
            changed = person.http.put(ui + f"/api/groups/{g1['id']}/memory-server",
                                      headers=person._headers(), json={"url": url["memory"] + "/mcp"})
            check("3e", f"{who} cannot remove it or change it",
                  removed.status_code == 403 and changed.status_code == 403,
                  (removed.status_code, changed.status_code))
            check("3f", f"{who} cannot see the owner's list",
                  person.get("/api/groups/manage").status_code == 403)
        foreign = owner.http.put(ui + "/api/groups/not-a-group-here/memory-server",
                                 headers=owner._headers(), json={"url": url["memory"] + "/mcp"})
        check("3g", "a group id Eugene does not list gets no server", foreign.status_code == 404,
              foreign.text[:200])

        say("4. B is taken out of G2: at B's next sign-in, G1 only")
        moved = call("control", "PATCH", f"/v1/people/{people['b']}", root,
                     json={"groups": [g1["id"]]})
        must("4a", "B is taken out of G2 at the root", moved.status_code == 200, moved.text[:200])
        b2 = Browser(ui)
        must("4b", "B signs in again", b2.sign_in(PASSWORDS["b"], "b").startswith("/#signin="))
        seen = b2.get("/api/groups").json()
        check("4c", "B: G1 only; 70% and background",
              seen["groups"] == [g1] and [p["value"] for p in seen["policies"]] == ["background", 70],
              seen)

        say("5. C is in 40 groups: the ID token is cut, Workbench reads them all")
        c = Browser(ui)
        must("5a", "C signs in", c.sign_in(PASSWORDS["c"], "c").startswith("/#signin="))
        seen = c.get("/api/groups").json()
        check("5b", "every one of C's 40 groups shows", sorted(g["id"] for g in seen["groups"]) == sorted(many),
              len(seen.get("groups", [])))

        say("6. G1 is deleted at the root: the owner removes its server")
        assert call("control", "DELETE", f"/v1/permission-groups/{g1['id']}", root).status_code == 204
        page = owner.get("/api/groups/manage").json()
        check("6a", "the owner sees G1's server as a deleted group's",
              [g["id"] for g in page["gone"]] == [g1["id"]], page.get("gone"))
        removed = owner.http.delete(ui + f"/api/groups/{g1['id']}/memory-server", headers=owner._headers())
        check("6b", "the owner removes it", removed.status_code == 200 and removed.json()["gone"] == [],
              removed.text[:200])
    finally:
        for process in processes:
            r7.kill_hard(process.pid)
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve")
    parser.add_argument("--directory")
    parser.add_argument("--port", type=int)
    parser.add_argument("--workbench", default=os.environ.get("R70C_WORKBENCH_REF") or "main")
    parser.add_argument("--keep", action="store_true", help="keep the working directory")
    args = parser.parse_args()
    if args.serve:
        load("r7", "row7-person-removal-acceptance.py").serve(args.serve, Path(args.directory), args.port)
        return
    r7 = load("r7", "row7-person-removal-acceptance.py")
    commit = r7.resolve(args.workbench)
    work = Path(tempfile.mkdtemp(prefix="ep-r70c-"))
    print(f"working in {work}; Workbench {commit}", flush=True)
    try:
        exercise(work, commit)
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
    finished = any(r[0] == "6b" for r in RESULTS)
    sys.exit(1 if failed or not finished else 0)


if __name__ == "__main__":
    main()
