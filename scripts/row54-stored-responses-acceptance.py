"""Row 54 acceptance: stored responses and conversations, each kept for its owner.

Row 53's harness (`row53-store-acceptance.py`, imported, not copied): real
processes on loopback ports the operating system hands out, with temporary
state and every ambient `EUGENE_PLEXUS_*` variable cleared; never the default
ports 8079-8083 and never the live install. A control root, and an agent
enrolled with it that starts the store by itself; a gateway placing new
conversations in turn (`loadBalancing: round_robin`); and two replicas of one
model -- two inference-drivers over one scripted backend, which records which
replica each request reached and what it was sent. Two people, Ann and Ben,
sign in to a Workbench-style app (an app key plus each person's own token).

1. Ann sends a Responses request with `store: true`, and three more chained by
   `previous_response_id`: the backend receives the whole conversation each
   time, and every request lands on one replica. A second chat of Ann's that
   opens with the same words is another conversation: it is placed on its own,
   on the other replica, and stays there.
2. Ann's `GET`, `input_items` and `DELETE` work; after `DELETE`, chaining from
   the deleted response is the 400 `previous_response_not_found` (OpenAI's).
3. Ben chaining from Ann's id is the same 400 as for an id that does not
   exist, and the backend is not asked; Ben's `GET` of Ann's id is the same
   404 as a missing id.
4. `store: false` keeps nothing: the store's count of Ann's responses is
   unchanged.
5. Ann makes a conversation and sends three Responses requests with it: the
   backend receives the whole conversation each time; Ben can neither read
   it nor continue it (the 404 of a missing conversation).
6. `--sabotage`: a store whose chain read drops its owner check serves the
   install; step 3's check must fail. The sabotage is made in that store's
   process only (a method replaced before it starts); no file changes, so
   nothing needs restoring.

Run with a Python that has agent, control, gateway, inference-driver and store
installed (CI's Pinned integration job has them).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import yaml

HERE = Path(__file__).resolve().parent
PASSES: list[str] = []
MODEL = "row54-fixture"
MISSING = "resp_" + "0" * 32
MISSING_CONVERSATION = "conv_" + "0" * 48


def _row53() -> Any:
    """Row 53's harness: the install, its people, and a caller at the door."""
    spec = importlib.util.spec_from_file_location(
        "row53_harness", HERE / "row53-store-acceptance.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R53 = _row53()


def ok(message: str) -> None:
    PASSES.append(message)
    print(f"PASS {message}", flush=True)


@contextmanager
def must_fail(label: str) -> Iterator[None]:
    """The block must raise `AssertionError`: a check the sabotage breaks."""
    try:
        yield
    except AssertionError as caught:
        ok(f"sabotage caught: {label} ({caught})")
        return
    raise AssertionError(f"sabotage NOT caught: {label} passed against a broken store")


# --------------------------------------------------------------------------- #
# The processes
# --------------------------------------------------------------------------- #


def fixture_app() -> Any:
    """One backend process serving two replicas (`/a/model`, `/b/model`), each
    answer numbered so a conversation's history can be read back."""
    from fastapi import FastAPI

    app = FastAPI()
    seen: list[dict[str, Any]] = []

    @app.get("/healthz")
    async def health() -> dict[str, Any]:
        return {}

    @app.get("/seen")
    async def requests() -> list[dict[str, Any]]:
        return seen

    @app.get("/{replica}/model/props")
    async def props(replica: str) -> dict[str, Any]:
        return {"default_generation_settings": {"n_ctx": 32768}, "modalities": {"vision": False}}

    @app.get("/{replica}/model/v1/models")
    async def models(replica: str) -> dict[str, Any]:
        return {"data": [{"id": MODEL, "object": "model"}]}

    @app.post("/{replica}/model/v1/chat/completions")
    async def complete(replica: str, body: dict[str, Any]) -> dict[str, Any]:
        seen.append({"replica": replica, "messages": body["messages"]})
        return {
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": f"ROW54-ANSWER-{len(seen)}"},
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 2, "total_tokens": 22},
        }

    return app


def _sabotage_chain() -> None:
    """The chain read, without its owner check: any owner's response by id."""
    from eugene_plexus_store import keeper, responses

    def anyones(self: Any, connection: Any, owner: str, ident: str) -> Any:
        if not responses.RESPONSE_ID.match(ident):
            return None
        return connection.execute(
            f"SELECT * FROM responses WHERE id = ? AND {keeper.LIVE} AND {keeper.SHOWN}",
            (ident, self.keeper.now()),
        ).fetchone()

    responses.Responses._response = anyones  # type: ignore[method-assign]


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    assert port not in R53.DEFAULT_PORTS and port != 8084, "default ports are forbidden"
    if kind == "agent":
        R53.serve_agent(directory, port)
        return
    if kind == "control":
        from eugene_plexus_control.app import create_app as control_app
        from eugene_plexus_control.settings import Settings as ControlSettings

        app = control_app(
            ControlSettings(config_file=directory / "control.yaml", state_dir=directory / "state")
        )
    elif kind == "fixture":
        app = fixture_app()
    else:
        bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
        if kind == "model":
            from eugene_plexus_inference_driver.app import create_app as driver_app
            from eugene_plexus_inference_driver.settings import Settings as DriverSettings

            app = driver_app(
                settings=DriverSettings(config_file=directory / "driver.yaml", **bootstrap)
            )
        elif kind == "gateway":
            from eugene_plexus_gateway.app import create_app as gateway_app
            from eugene_plexus_gateway.settings import Settings as GatewaySettings

            app = gateway_app(
                settings=GatewaySettings(
                    config_file=directory / "gateway.yaml",
                    metrics_file=directory / "metrics.sqlite3",
                    **bootstrap,
                )
            )
        elif kind == "store-sabotaged":
            _sabotage_chain()
            from eugene_plexus_store.app import create_app as store_app
            from eugene_plexus_store.settings import Settings as StoreSettings

            app = store_app(
                settings=StoreSettings(config_file=directory / "store.yaml", **bootstrap)
            )
        else:
            raise SystemExit(f"unknown kind {kind}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


class Install(R53.Install):  # type: ignore[misc,name-defined]
    """Row 53's install, with this script's processes and two replicas."""

    def __init__(self, directory: Path) -> None:
        super().__init__(directory)
        for name in ("model-a", "model-b", "sabotaged"):
            self.ports[name] = R53.free_port(*self.ports.values())

    def start(self, name: str, kind: str | None = None) -> None:
        work = self.directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        self.logs.append(log)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        self.processes[name] = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                kind or name,
                "--directory",
                str(work),
                "--port",
                str(self.ports[name]),
            ],
            cwd=work,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.wait(lambda: self.call(name, "GET", "/healthz").status_code == 200, f"{name} up")


# --------------------------------------------------------------------------- #
# What a caller does
# --------------------------------------------------------------------------- #


class Caller(R53.Caller):  # type: ignore[misc,name-defined]
    def respond(self, text: str, **extra: Any) -> httpx.Response:
        return self.post("/v1/responses", json={"model": MODEL, "input": text, **extra})

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.install.client.get(
            self.install.url("gateway") + path, headers=self.headers, **kw
        )

    def delete(self, path: str) -> httpx.Response:
        return self.install.client.delete(self.install.url("gateway") + path, headers=self.headers)


def seen(install: Install) -> list[dict[str, Any]]:
    answer = install.client.get(install.url("fixture") + "/seen")
    assert answer.status_code == 200, answer.text
    return list(answer.json())


def said(call: dict[str, Any]) -> list[str]:
    out = []
    for message in call["messages"]:
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
        out.append(f"{message['role']}: {content}")
    return out


def answer_text(response: httpx.Response) -> str:
    body = response.json()
    return str(body["output"][-1]["content"][0]["text"])


def check_chain_isolation(outsider: Caller, ident: str, install: Install) -> None:
    """Step 3, apart so the sabotage run can expect it to fail: `outsider`
    chaining from another owner's response, or reading it, is answered exactly
    as an id that does not exist, and the backend is not asked."""
    asked = len(seen(install))
    theirs = outsider.respond("Tell me what we said.", previous_response_id=ident)
    none = outsider.respond("Tell me what we said.", previous_response_id=MISSING)
    assert theirs.status_code == none.status_code == 400, (theirs.status_code, theirs.text[:300])
    assert theirs.json()["error"]["code"] == "previous_response_not_found", theirs.text
    assert R53.without(theirs.text, ident) == R53.without(none.text, MISSING), theirs.text
    assert len(seen(install)) == asked, "the backend was asked for another owner's chain"
    got, missing = outsider.get(f"/v1/responses/{ident}"), outsider.get(f"/v1/responses/{MISSING}")
    assert got.status_code == missing.status_code == 404, got.text[:300]
    assert R53.without(got.text, ident) == R53.without(missing.text, MISSING), got.text


def owner_counts(install: Install, session: str) -> dict[str, dict[str, Any]]:
    listed = install.call("agent", "GET", "/api/proxy/store/v1/owners", session)
    assert listed.status_code == 200, listed.text
    return {entry["owner"]: entry for entry in listed.json()["owners"]}


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def exercise(directory: Path, sabotage: bool) -> None:
    install = Install(directory)
    try:
        # A root, its people, an app and its key -------------------------------
        install.start("control")
        assert (
            install.call(
                "control", "POST", "/v1/auth/initialize", json={"passphrase": install.passphrase}
            ).status_code
            == 204
        )
        login = install.call(
            "control", "POST", "/v1/auth/login", json={"passphrase": install.passphrase}
        )
        assert login.status_code == 200, login.text
        root = str(login.json()["sessionToken"])
        app = install.call(
            "control",
            "POST",
            "/v1/oidc/clients",
            root,
            json={"name": "Workbench", "owner": R53.APP_OWNER, "redirectUris": [R53.CALLBACK]},
        )
        assert app.status_code == 201, app.text
        limits = {"allowedModels": [MODEL], "requestsPerMinute": 1000, "maxConcurrentRequests": 8}
        app_key = install.call(
            "control",
            "POST",
            "/v1/auth/client-keys",
            root,
            json={"name": R53.APP_OWNER, "limits": limits},
        )
        assert app_key.status_code == 201, app_key.text
        people = {}
        for name in ("Ann", "Ben"):
            made = install.call(
                "control",
                "POST",
                "/v1/people",
                root,
                json={
                    "name": name,
                    "password": R53.PASSWORD,
                    "apps": [app.json()["client"]["clientId"]],
                },
            )
            assert made.status_code == 201, made.text
            people[name] = made.json()

        # The root's agent, which starts the store ------------------------------
        agent_dir = directory / "agent"
        agent_dir.mkdir(exist_ok=True)
        (agent_dir / "machine-port").write_text(str(install.ports["machine"]), encoding="utf-8")
        (agent_dir / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "advertiseUrl": install.url("agent"),
                    "securityMode": "prompt_on_startup",
                    "components": [
                        {
                            "name": "control",
                            "kind": "control",
                            "url": install.url("control"),
                            "safeMode": False,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        install.start("agent")
        initialized = install.call(
            "agent", "POST", "/v1/auth/initialize", json={"passphrase": install.passphrase}
        )
        assert initialized.status_code == 200, initialized.text
        join = install.call(
            "control", "POST", "/v1/nodes/join-token", root, json={"grants": ["gateway"]}
        )
        assert join.status_code in (200, 201), join.text
        enrolled = install.call(
            "agent",
            "POST",
            "/v1/node/enroll",
            initialized.json()["sessionToken"],
            json={
                "controlUrl": install.url("control"),
                "token": join.json()["token"],
                "name": "root",
            },
        )
        assert enrolled.status_code == 200, enrolled.text
        install.wait(lambda: (agent_dir / "trust_bundle.json").is_file(), "the agent's bundle")
        operator = install.call(
            "agent", "POST", "/v1/auth/login", json={"passphrase": install.passphrase}
        )
        assert operator.status_code == 200, operator.text
        session = str(operator.json()["sessionToken"])
        install.wait(
            lambda: install.call("agent", "GET", "/api/proxy/store/healthz").status_code == 200,
            "the store answering through the agent",
        )

        # Two replicas of one model, and the gateway ----------------------------
        install.start("fixture")
        for replica in ("a", "b"):
            name = f"model-{replica}"
            model_dir = directory / name
            model_dir.mkdir(exist_ok=True)
            (model_dir / "bootstrap.json").write_text(
                json.dumps(R53.bootstrap_for(agent_dir, install.url("agent"), "inference-driver")),
                encoding="utf-8",
            )
            (model_dir / "driver.yaml").write_text(
                yaml.safe_dump(
                    {
                        "provider": "openai_compat_custom",
                        "baseUrl": install.url("fixture") + f"/{replica}/model",
                        "modelId": MODEL,
                        "backendLocality": "local",
                    }
                ),
                encoding="utf-8",
            )
            install.start(name, "model")
            declared = install.call(
                "agent",
                "POST",
                "/v1/components",
                session,
                json={
                    "name": f"row54-{name}",
                    "kind": "inference-driver",
                    "url": install.url(name),
                },
            )
            assert declared.status_code == 201, declared.text
        gateway_dir = directory / "gateway"
        gateway_dir.mkdir(exist_ok=True)
        (gateway_dir / "bootstrap.json").write_text(
            json.dumps(R53.bootstrap_for(agent_dir, install.url("agent"), "gateway")),
            encoding="utf-8",
        )
        (gateway_dir / "gateway.yaml").write_text(
            yaml.safe_dump({"routingRefreshSeconds": 1, "loadBalancing": "round_robin"}),
            encoding="utf-8",
        )
        install.start("gateway")
        tokens = {name: install.sign_in(app.json(), name) for name in ("Ann", "Ben")}
        ann = Caller(install, app_key.json()["token"], tokens["Ann"])
        ben = Caller(install, app_key.json()["token"], tokens["Ben"])

        warmed = iter(range(10_000))

        def both_replicas() -> bool:
            # Each a new chat (its own opening words), so each is placed in turn.
            assert ann.respond(f"warm up {next(warmed)}", store=False).status_code == 200
            return {call["replica"] for call in seen(install)} == {"a", "b"}

        install.wait(both_replicas, "both replicas routable", seconds=90)
        ann_owner = f"person:{people['Ann']['id']}"

        # ------------------------------------------------------------------ #
        # 1. A chain of four: the whole conversation each time, one replica
        # ------------------------------------------------------------------ #
        before = len(seen(install))
        first = ann.respond("ROW54 one", store=True)
        assert first.status_code == 200, first.text
        assert first.json()["store"] is True, first.text
        # A second chat that opens with the same words, started at once: under
        # round_robin a new conversation takes the next replica in turn, and a
        # chat keyed by its opening words would have gone home to the first.
        twin = ann.respond("ROW54 one")
        assert twin.status_code == 200, twin.text
        calls = seen(install)[before:]
        assert len(calls) == 2, calls
        home, twin_home = calls[0]["replica"], calls[1]["replica"]
        assert home != twin_home, f"two chats that open alike shared replica {home}"
        history = ["user: ROW54 one", f"assistant: {answer_text(first)}"]
        previous = first.json()["id"]
        for word in ("two", "three", "four"):
            asked = len(seen(install))
            turn = ann.respond(f"ROW54 {word}", previous_response_id=previous)
            assert turn.status_code == 200, turn.text
            assert turn.json()["previous_response_id"] == previous
            call = seen(install)[asked]
            assert said(call) == [*history, f"user: ROW54 {word}"], said(call)
            assert call["replica"] == home, f"turn {word} left replica {home}"
            history += [f"user: ROW54 {word}", f"assistant: {answer_text(turn)}"]
            previous = turn.json()["id"]
        last = previous
        asked = len(seen(install))
        twin_turn = ann.respond("ROW54 two", previous_response_id=twin.json()["id"])
        assert twin_turn.status_code == 200, twin_turn.text
        assert seen(install)[asked]["replica"] == twin_home
        ok(
            "step 1: four requests chained by previous_response_id each gave the backend the "
            f"whole conversation on one replica ({home}); a chat opening alike kept to its own "
            f"({twin_home})"
        )

        # ------------------------------------------------------------------ #
        # 2. GET, input_items and DELETE for the owner
        # ------------------------------------------------------------------ #
        got = ann.get(f"/v1/responses/{last}")
        assert got.status_code == 200, got.text
        assert got.json()["id"] == last and got.json()["store"] is True
        assert got.json()["output"][-1]["content"][0]["text"] == history[-1].split(": ", 1)[1]
        items = ann.get(f"/v1/responses/{last}/input_items", params={"order": "asc", "limit": 100})
        assert items.status_code == 200, items.text
        texts = [
            part.get("text") for item in items.json()["data"] for part in item.get("content", [])
        ]
        assert texts == [line.split(": ", 1)[1] for line in history[:-1]], texts
        gone = ann.delete(f"/v1/responses/{last}")
        assert gone.json() == {"id": last, "object": "response.deleted", "deleted": True}, gone.text
        after = ann.respond("ROW54 five", previous_response_id=last)
        assert after.status_code == 400, after.text
        assert after.json()["error"]["code"] == "previous_response_not_found", after.text
        assert ann.get(f"/v1/responses/{last}").status_code == 404
        ok(
            "step 2: Ann read her response and its input items, deleted it, and it continues no more"
        )

        # ------------------------------------------------------------------ #
        # 3. Ben: Ann's ids are ids that do not exist
        # ------------------------------------------------------------------ #
        anns = first.json()["id"]
        check_chain_isolation(ben, anns, install)
        assert ann.get(f"/v1/responses/{anns}").status_code == 200
        ok("step 3: Ben chaining from or reading Ann's response is answered as a missing id")

        # ------------------------------------------------------------------ #
        # 4. store: false keeps nothing
        # ------------------------------------------------------------------ #
        kept = owner_counts(install, session)[ann_owner]["responses"]
        forgotten = ann.respond("ROW54 forget this", store=False)
        assert forgotten.status_code == 200 and forgotten.json()["store"] is False
        assert owner_counts(install, session)[ann_owner]["responses"] == kept
        assert ann.get(f"/v1/responses/{forgotten.json()['id']}").status_code == 404
        ok(f"step 4: store: false kept nothing (Ann keeps {kept} responses, before and after)")

        # ------------------------------------------------------------------ #
        # 5. A conversation of three requests, Ann's alone
        # ------------------------------------------------------------------ #
        made = ann.post(
            "/v1/conversations",
            json={"metadata": {"row": "54"}, "items": [{"role": "user", "content": "ROW54 hello"}]},
        )
        assert made.status_code == 200, made.text
        conversation = made.json()["id"]
        talk: list[str] = []
        for word in ("alpha", "beta", "gamma"):
            asked = len(seen(install))
            turn = ann.respond(f"ROW54 {word}", conversation=conversation)
            assert turn.status_code == 200, turn.text
            assert turn.json()["conversation"] == {"id": conversation}
            call = seen(install)[asked]
            # The conversation's first item and the first request's input are two user
            # messages in a row, which the door joins (as for any input).
            expected = (
                [*talk, f"user: ROW54 {word}"] if talk else ["user: ROW54 hello\n\nROW54 alpha"]
            )
            assert said(call) == expected, (said(call), expected)
            talk = [*expected, f"assistant: {answer_text(turn)}"]
        listed = ann.get(
            f"/v1/conversations/{conversation}/items", params={"order": "asc", "limit": 100}
        )
        assert listed.status_code == 200, listed.text
        assert len(listed.json()["data"]) == 7, listed.text
        for path in ("", "/items"):
            theirs = ben.get(f"/v1/conversations/{conversation}{path}")
            none = ben.get(f"/v1/conversations/{MISSING_CONVERSATION}{path}")
            assert theirs.status_code == none.status_code == 404, theirs.text
            assert R53.without(theirs.text, conversation) == R53.without(
                none.text, MISSING_CONVERSATION
            )
        asked = len(seen(install))
        used = ben.respond("ROW54 what did she say?", conversation=conversation)
        assert used.status_code == 404, used.text
        assert len(seen(install)) == asked
        assert "ROW54 hello" not in used.text
        ok("step 5: a conversation of three requests gave the backend all of it; Ben gets a 404")

        if not sabotage:
            return

        # ------------------------------------------------------------------ #
        # 6. Sabotage: a store whose chain read drops the owner check
        # ------------------------------------------------------------------ #
        sabotaged_dir = directory / "sabotaged"
        sabotaged_dir.mkdir(exist_ok=True)
        (sabotaged_dir / "bootstrap.json").write_text(
            json.dumps(R53.bootstrap_for(agent_dir, install.url("agent"), "store")),
            encoding="utf-8",
        )
        install.start("sabotaged", "store-sabotaged")
        removed = install.call("agent", "DELETE", "/v1/components/store", session)
        assert removed.status_code in (200, 204), removed.text
        install.wait(
            lambda: install.call("agent", "GET", "/api/proxy/store/healthz").status_code != 200,
            "the store gone",
        )
        declared = install.call(
            "agent",
            "POST",
            "/v1/components",
            session,
            json={"name": "store", "kind": "store", "url": install.url("sabotaged")},
        )
        assert declared.status_code == 201, declared.text
        install.wait(
            lambda: ann.respond("ROW54 planted", store=True).json().get("store") is True,
            "the sabotaged store keeping answers",
        )
        planted = ann.respond("ROW54 planted secret", store=True)
        assert planted.json()["store"] is True, planted.text
        with must_fail("step 3's isolation check against a chain read without its owner check"):
            check_chain_isolation(ben, planted.json()["id"], install)
    finally:
        install.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--sabotage", action="store_true", help="also run step 6 against a broken chain read"
    )
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
        return 0
    with tempfile.TemporaryDirectory(prefix="ep-row54-", ignore_cleanup_errors=True) as tmp:
        directory = Path(tmp)
        try:
            exercise(directory, args.sabotage)
        except BaseException:
            for log in sorted(directory.glob("**/process.log")):
                tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
                print(f"--- {log.parent.name} ---", *tail, sep="\n")
            store_log = directory / "agent" / "logs"
            for log in sorted(store_log.glob("*.log")) if store_log.is_dir() else []:
                tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
                print(f"--- {log.name} ---", *tail, sep="\n")
            raise
    print(f"{len(PASSES)} PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
