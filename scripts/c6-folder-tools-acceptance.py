"""C6: published Workbench folder tools under real Windows/Linux app accounts.

Disposable GitHub runners only. Includes the C5 local-process/account checks.
The model is scripted; this validates the integration, not model accuracy.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "c5", HERE / "c5-local-tools-acceptance.py"
)
assert spec and spec.loader
c5 = importlib.util.module_from_spec(spec)
sys.modules["c5"] = c5
spec.loader.exec_module(c5)
c1, c3 = c5.c1, c5.c3
api, check, must, wait_for = c5.api, c5.check, c5.must, c5.wait_for
FOLDER = Path(r"C:\ep-c6-files") if c1.WINDOWS else Path("/srv/ep-c6-files")
ACTION: tuple[str, dict] | None = None


class Model(c5.Model):
    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "messages" not in body:
            self.send_error(404)
            return
        c5.REQUESTS.append(body)
        if body.get("tools") and body["messages"][-1]["role"] != "tool":
            functions = [t["function"] for t in body["tools"]]
            function, arguments = functions[0], {}
            if ACTION:
                tool, arguments = ACTION
                function = next(
                    f for f in functions if f": {tool}." in f["description"]
                )
            delta = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": f"c6-call-{len(c5.REQUESTS)}",
                        "type": "function",
                        "function": {
                            "name": function["name"],
                            "arguments": json.dumps(arguments),
                        },
                    }
                ],
            }
            finish = "tool_calls"
        else:
            delta, finish = {"role": "assistant", "content": "C6 complete."}, "stop"
        frames = [
            {
                "id": "c6-answer",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": c5.MODEL,
                "choices": [{"index": 0, "delta": value, "finish_reason": end}],
            }
            for value, end in ((delta, None), ({}, finish))
        ]
        self.send(
            (
                "".join("data: " + json.dumps(f) + "\n\n" for f in frames)
                + "data: [DONE]\n\n"
            ).encode(),
            "text/event-stream",
        )


def host_write(name: str, text: str) -> None:
    if c1.WINDOWS:
        (FOLDER / name).write_text(text, encoding="utf-8")
    else:
        subprocess.run(
            ["sudo", "tee", str(FOLDER / name)],
            input=text,
            text=True,
            stdout=subprocess.DEVNULL,
            check=True,
        )
        subprocess.run(["sudo", "chgrp", "ep-c6-files", str(FOLDER / name)], check=True)
        subprocess.run(["sudo", "chmod", "660", str(FOLDER / name)], check=True)


def host_read(name: str) -> str:
    if c1.WINDOWS:
        return (FOLDER / name).read_text(encoding="utf-8")
    return subprocess.run(
        ["sudo", "cat", str(FOLDER / name)], check=True, capture_output=True, text=True
    ).stdout


def host_exists(name: str) -> bool:
    if c1.WINDOWS:
        return (FOLDER / name).exists()
    return subprocess.run(["sudo", "test", "-e", str(FOLDER / name)]).returncode == 0


def restart(token: str, label: str) -> dict:
    _, before = api("GET", c1.AGENT + "/v1/apps/workbench", token)
    status, response = api("POST", c1.AGENT + "/v1/apps/workbench/restart", token)
    must(label + "a", "agent accepts the Workbench restart", status == 200, response)

    def ready():
        _, current = api("GET", c1.AGENT + "/v1/apps/workbench", token)
        if (
            current.get("status") == "running"
            and current.get("pid")
            and current["pid"] != before.get("pid")
            and c1.healthy(f"http://127.0.0.1:{current['port']}")()
        ):
            return current
        return None

    app = wait_for(ready, 90, 2)
    must(label, "a new service process is healthy", bool(app))
    return app


def provision(app: dict, token: str) -> dict:
    if c1.WINDOWS:
        FOLDER.mkdir()
        subprocess.run(
            [
                "icacls",
                str(FOLDER),
                "/grant",
                str(app["account"]).split(" (", 1)[0] + ":(OI)(CI)M",
            ],
            check=True,
        )
    else:
        subprocess.run(["sudo", "groupadd", "--system", "ep-c6-files"], check=True)
        subprocess.run(
            [
                "sudo",
                "install",
                "-d",
                "-o",
                "root",
                "-g",
                "ep-c6-files",
                "-m",
                "2770",
                str(FOLDER),
            ],
            check=True,
        )
        directory = "/etc/systemd/system/eugene-plexus-app@workbench.service.d"
        subprocess.run(["sudo", "mkdir", "-p", directory], check=True)
        with tempfile.TemporaryDirectory() as work:
            config = Path(work) / "30-c6-files.conf"
            config.write_text(
                "[Service]\nSupplementaryGroups=ep-c6-files\n"
                f"ReadWritePaths={FOLDER}\nUMask=0007\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "sudo",
                    "install",
                    "-m",
                    "644",
                    str(config),
                    directory + "/30-c6-files.conf",
                ],
                check=True,
            )
        subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
    host_write("notes.txt", "C6 original")
    return restart(token, "60")


def sign_in(base: str, password: str, username: str):
    browser = c3.Browser(base)
    assert browser.sign_in(password, username).startswith("/#signin=")
    return browser


def offer(browser, grant: str, tool: str, **arguments) -> tuple[str, dict]:
    global ACTION
    ACTION = tool, arguments
    response = browser.post("/api/chats", json={"model": c5.MODEL})
    assert response.status_code == 201, response.text
    chat = response.json()["id"]
    response = browser.patch(
        f"/api/chats/{chat}", json={"settings": {"folderGrants": [grant]}}
    )
    assert response.status_code == 200, response.text
    response = browser.post(
        f"/api/chats/{chat}/messages", json={"content": "Use this folder."}
    )
    assert response.status_code == 201, response.text

    def pending():
        message = browser.get(f"/api/chats/{chat}").json()["messages"][-1]
        return (
            message
            if message.get("toolRounds") or message["status"] != "running"
            else None
        )

    message = wait_for(pending, 60, 0.2) or {}
    assert message.get("toolRounds"), message
    assert message["toolRounds"][0]["calls"][0]["status"] == "pending", message
    return chat, message


def decision(browser, chat: str, message: dict, approve: bool = True):
    return browser.post(
        f"/api/chats/{chat}/messages/{message['id']}/tools/decision",
        json={
            "callId": message["toolRounds"][0]["calls"][0]["id"],
            "approve": approve,
        },
    )


def finish(browser, chat: str, message: dict, approve: bool = True) -> dict:
    response = decision(browser, chat, message, approve)
    assert response.status_code == 204, response.text
    answer = browser.answer(chat, seconds=90)
    assert answer["status"] == "done", answer
    return answer["toolRounds"][0]["calls"][0]


def exercise(app: dict, token: str) -> None:
    base = f"http://127.0.0.1:{app['port']}"
    owner = sign_in(base, c1.PASSPHRASE, "operator")
    ada = sign_in(base, "c5-person-password", "ada")
    people = owner.get("/api/folders/people").json()["people"]
    subject = next(p["sub"] for p in people if p["username"] == "ada")

    def grant(name: str, **extra):
        response = owner.post(
            "/api/folders",
            json={
                "name": name,
                "subject": subject,
                "path": str(FOLDER),
                **extra,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    readonly = grant("Ada read-only")
    must("61", "new grants default to read-only", readonly["writable"] is False)
    writable = grant("Ada project", writable=True)
    private = owner.post(
        "/api/folders",
        json={
            "name": "private",
            "subject": subject,
            "path": str(c1.PREFIX / "apps/workbench"),
        },
    )
    check(
        "62", "Workbench refuses its private install tree", private.status_code == 400
    )
    chat, message = offer(ada, readonly["id"], "list_directory", path=".")
    descriptions = [t["function"]["description"] for t in c5.REQUESTS[-1]["tools"]]
    check(
        "63",
        "read-only grant exposes no write tool",
        not any(": write_text." in d for d in descriptions),
    )
    listing = finish(ada, chat, message)
    must(
        "64",
        "approved listing reaches the host folder",
        listing["status"] == "done"
        and "notes.txt" in json.loads(listing["result"])["names"],
        listing,
    )
    chat, message = offer(ada, writable["id"], "read_text", path="notes.txt")
    check(
        "65",
        "file contents do not reach the model before approval",
        "C6 original" not in json.dumps(c5.REQUESTS),
    )
    check(
        "66",
        "owner cannot approve Ada's call",
        decision(owner, chat, message).status_code == 404,
    )
    read = finish(ada, chat, message)
    must("67", "Ada approves a real file read", read["status"] == "done", read)
    contents = json.loads(read["result"])
    check(
        "68", "the approved result contains the file", contents["text"] == "C6 original"
    )
    check(
        "69",
        "host paths stay out of model requests and member grant listings",
        str(FOLDER) not in json.dumps(c5.REQUESTS)
        and all("path" not in g for g in ada.get("/api/folders").json()["grants"]),
    )

    _, login = api(
        "POST", c1.CONTROL + "/v1/auth/login", body={"passphrase": c1.PASSPHRASE}
    )
    status, person = api(
        "POST",
        c1.CONTROL + "/v1/people",
        login["sessionToken"],
        {"name": "bo", "password": "c6-person-password"},
    )
    must("70", "owner adds a second person", status == 201, person)
    bo = sign_in(base, "c6-person-password", "bo")
    check(
        "71",
        "another person cannot see Ada's folders",
        bo.get("/api/folders").json()["grants"] == [],
    )
    for label, browser in (("72", bo), ("73", owner)):
        other = browser.post("/api/chats", json={"model": c5.MODEL}).json()["id"]
        selected = browser.patch(
            f"/api/chats/{other}", json={"settings": {"folderGrants": [writable["id"]]}}
        )
        check(
            label,
            "only the named recipient can select a grant",
            selected.status_code == 400,
        )
    check(
        "74",
        "members cannot administer grants",
        ada.post(
            "/api/folders",
            json={
                "name": "bad",
                "path": str(FOLDER),
                "subject": subject,
            },
        ).status_code
        == 403
        and ada.get("/api/folders/people").status_code == 403,
    )

    chat, message = offer(
        ada,
        writable["id"],
        "write_text",
        path="notes.txt",
        text="Must not overwrite",
        expectedSha256=contents["sha256"],
    )
    host_write("notes.txt", "Host edit")
    stale = finish(ada, chat, message)
    check(
        "75",
        "a host edit invalidates the approved version",
        stale["status"] == "failed" and host_read("notes.txt") == "Host edit",
        stale,
    )
    chat, message = offer(ada, writable["id"], "read_text", path="notes.txt")
    current = json.loads(finish(ada, chat, message)["result"])
    chat, message = offer(
        ada,
        writable["id"],
        "write_text",
        path="notes.txt",
        text="Approved edit",
        expectedSha256=current["sha256"],
    )
    edited = finish(ada, chat, message)
    check(
        "76",
        "approved edit writes through the service account",
        edited["status"] == "done" and host_read("notes.txt") == "Approved edit",
        edited,
    )
    chat, message = offer(
        ada,
        writable["id"],
        "write_text",
        path="new.txt",
        text="Created by Workbench",
        expectedSha256="",
    )
    check(
        "77", "proposing a create has no file side effect", not host_exists("new.txt")
    )
    created = finish(ada, chat, message)
    must(
        "78",
        "approved create succeeds",
        created["status"] == "done" and host_read("new.txt") == "Created by Workbench",
        created,
    )
    saved_chat = chat
    if not c1.WINDOWS:
        permissions = subprocess.run(
            ["sudo", "stat", "-c", "%G:%a", str(FOLDER / "new.txt")],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        check(
            "78a",
            "new files retain stable group read/write permissions",
            permissions == "ep-c6-files:660",
            permissions,
        )
    temporary = grant("Temporary", writable=True)
    chat, message = offer(
        ada,
        temporary["id"],
        "write_text",
        path="revoked.txt",
        text="Must not exist",
        expectedSha256="",
    )
    removed = owner.http.delete(
        base + f"/api/folders/{temporary['id']}", headers=owner._headers()
    )
    assert removed.status_code == 204, removed.text
    revoked = finish(ada, chat, message)
    check(
        "79",
        "revocation blocks an already proposed write",
        revoked["status"] == "failed" and not host_exists("revoked.txt"),
        revoked,
    )
    chat, message = offer(
        ada,
        writable["id"],
        "write_text",
        path="declined.txt",
        text="Must not exist",
        expectedSha256="",
    )
    declined = finish(ada, chat, message, False)
    check(
        "80",
        "declining leaves no file",
        declined["status"] == "declined" and not host_exists("declined.txt"),
    )
    restart(token, "81")
    ada = sign_in(base, "c5-person-password", "ada")
    saved = ada.get(f"/api/chats/{saved_chat}").json()["messages"][-1]
    check(
        "82",
        "grants and completed tool records survive service restart",
        any(g["id"] == writable["id"] for g in ada.get("/api/folders").json()["grants"])
        and saved["toolRounds"][0]["calls"][0] == created,
    )
    chat, message = offer(ada, writable["id"], "read_text", path="new.txt")
    reopened = finish(ada, chat, message)
    must(
        "83",
        "the restarted account can read a file created before restart",
        reopened["status"] == "done",
        reopened,
    )
    chat, message = offer(
        ada,
        writable["id"],
        "write_text",
        path="new.txt",
        text="Edited after restart",
        expectedSha256=json.loads(reopened["result"])["sha256"],
    )
    rewritten = finish(ada, chat, message)
    check(
        "84",
        "stable host permissions allow editing after restart",
        rewritten["status"] == "done"
        and host_read("new.txt") == "Edited after restart",
        rewritten,
    )


original_exercise = c5.exercise


def combined(app: dict, token: str) -> None:
    app = provision(app, token)
    original_exercise(app, token)
    exercise(app, token)


if __name__ == "__main__":
    c5.Model, c5.exercise = Model, combined
    raise SystemExit(c5.main())
