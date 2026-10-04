"""Node files through a real installed service and signed-in Workbench.

Disposable GitHub runners only, enforced by the reused C5 entry point.
Includes C1 account probes and the existing C5/C6 local tool acceptance.
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
    "c6", HERE / "c6-folder-tools-acceptance.py"
)
assert spec and spec.loader
c6 = importlib.util.module_from_spec(spec)
sys.modules["c6"] = c6
spec.loader.exec_module(c6)
c5, c1 = c6.c5, c6.c1
api, check, must, wait_for = c6.api, c6.check, c6.must, c6.wait_for
FOLDER = Path(r"C:\ep-node-files") if c1.WINDOWS else Path("/srv/ep-node-files")
ENDPOINT = c1.CONTROL + "/v1/node-helpers/c1-node"


def exercise(app: dict, token: str) -> None:
    _, login = api(
        "POST", c1.CONTROL + "/v1/auth/login", body={"passphrase": c1.PASSPHRASE}
    )
    control_token = login["sessionToken"]

    def report():
        status, body = api("GET", c1.CONTROL + "/v1/node-helpers", control_token)
        if status != 200:
            return {}
        return next((h for h in body["helpers"] if h["node"] == "c1-node"), {})

    def toggle(enabled: bool, label: str):
        status, body = api("PUT", ENDPOINT, control_token, {"enabled": enabled})
        must(label, "file support setting saves", status == 200, body)
        state = wait_for(
            lambda: (
                (h if h.get("ready") is enabled else None) if (h := report()) else None
            ),
            180,
            2,
        )
        must(label + "a", "helper reaches the requested state", bool(state), report())
        return state

    helper = toggle(True, "N1")
    must(
        "N2",
        "helper reports its separate OS account",
        bool(helper.get("account")),
        helper,
    )
    if c1.WINDOWS:
        FOLDER.mkdir()
        subprocess.run(
            ["icacls", str(FOLDER), "/grant", helper["account"] + ":(OI)(CI)M"],
            check=True,
        )
        (FOLDER / "notes.txt").write_text("Node original", encoding="utf-8")
        account = subprocess.run(
            ["sc.exe", "qc", "EugenePlexusApp-node-files"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        must(
            "N3",
            "SCM runs the helper as its virtual account",
            helper["account"].lower() in account.lower(),
        )
    else:
        subprocess.run(["sudo", "groupadd", "--system", "ep-node-files"], check=True)
        subprocess.run(
            [
                "sudo",
                "install",
                "-d",
                "-o",
                "root",
                "-g",
                "ep-node-files",
                "-m",
                "2770",
                str(FOLDER),
            ],
            check=True,
        )
        subprocess.run(
            ["sudo", "tee", str(FOLDER / "notes.txt")],
            input="Node original",
            text=True,
            stdout=subprocess.DEVNULL,
            check=True,
        )
        subprocess.run(
            ["sudo", "chgrp", "ep-node-files", str(FOLDER / "notes.txt")], check=True
        )
        subprocess.run(["sudo", "chmod", "660", str(FOLDER / "notes.txt")], check=True)
        directory = "/etc/systemd/system/eugene-plexus-app@node-files.service.d"
        subprocess.run(["sudo", "mkdir", "-p", directory], check=True)
        with tempfile.TemporaryDirectory() as work:
            config = Path(work) / "30-node-files.conf"
            config.write_text(
                "[Service]\nSupplementaryGroups=ep-node-files\n"
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
                    directory + "/30-node-files.conf",
                ],
                check=True,
            )
        subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
        account = subprocess.run(
            [
                "systemctl",
                "show",
                "eugene-plexus-app@node-files.service",
                "--property=DynamicUser",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        must(
            "N3",
            "systemd runs the helper as a dynamic user",
            "DynamicUser=yes" in account,
        )
    toggle(False, "N4")
    toggle(True, "N5")
    status, folder = api(
        "POST",
        ENDPOINT + "/folders",
        control_token,
        {"name": "Node project", "path": str(FOLDER), "writable": True},
    )
    must("N6", "helper registers the provisioned folder", status == 201, folder)
    status, private = api(
        "POST",
        ENDPOINT + "/folders",
        control_token,
        {"name": "Private", "path": str(c1.PREFIX)},
    )
    check("N7", "helper refuses the private installation tree", status == 400, private)
    _, people = api("GET", c1.CONTROL + "/v1/people", control_token)
    ada_id = next(p["id"] for p in people["people"] if p["name"] == "ada")
    person_url = c1.CONTROL + "/v1/people/" + ada_id
    status, person = api(
        "PATCH",
        person_url,
        control_token,
        {"helperGrants": [{"folderId": folder["id"], "writable": True}]},
    )
    must("N8", "owner assigns node folder access to Ada", status == 200, person)
    base = f"http://127.0.0.1:{app['port']}"
    ada = c6.sign_in(base, "c5-person-password", "ada")
    owner = c6.sign_in(base, c1.PASSPHRASE, "operator")
    bo = c6.sign_in(base, "c6-person-password", "bo")
    grant = "node:" + folder["id"]
    visible = ada.get("/api/folders").json()
    must(
        "N9",
        "Workbench discovers the authorized node folder",
        any(g["id"] == grant and g["available"] for g in visible["grants"]),
        visible,
    )
    for label, browser in (("N10", owner), ("N11", bo)):
        check(
            label,
            "unassigned people cannot see the node folder",
            all(g["id"] != grant for g in browser.get("/api/folders").json()["grants"]),
        )
    chat, message = c6.offer(ada, grant, "read_text", path="notes.txt")
    check(
        "N12",
        "node content waits for per-call approval",
        "Node original" not in json.dumps(c5.REQUESTS),
    )
    call = c6.finish(ada, chat, message)
    must(
        "N13",
        "approved read crosses root, node relay and isolated worker",
        call["status"] == "done",
        call,
    )
    contents = json.loads(call["result"])
    must("N14", "node file contents arrive intact", contents["text"] == "Node original")
    chat, message = c6.offer(
        ada,
        grant,
        "write_text",
        path="notes.txt",
        text="Node edited",
        expectedSha256=contents["sha256"],
    )
    call = c6.finish(ada, chat, message)
    actual = (
        (FOLDER / "notes.txt").read_text(encoding="utf-8")
        if c1.WINDOWS
        else subprocess.check_output(
            ["sudo", "cat", str(FOLDER / "notes.txt")], text=True
        )
    )
    must(
        "N15",
        "approved edit changes the node file",
        call["status"] == "done" and actual == "Node edited",
        call,
    )
    chat, message = c6.offer(ada, grant, "read_text", path="../outside.txt")
    call = c6.finish(ada, chat, message)
    check("N16", "node helper refuses traversal", call["status"] == "failed", call)
    chat, message = c6.offer(
        ada,
        grant,
        "write_text",
        path="revoked.txt",
        text="Forbidden",
        expectedSha256="",
    )
    status, _ = api("PATCH", person_url, control_token, {"helperGrants": []})
    must("N17", "owner revokes Ada's access", status == 200)
    call = c6.finish(ada, chat, message)
    exists = (
        (FOLDER / "revoked.txt").exists()
        if c1.WINDOWS
        else subprocess.run(
            ["sudo", "test", "-e", str(FOLDER / "revoked.txt")]
        ).returncode
        == 0
    )
    check(
        "N18",
        "revocation blocks a pending approved write",
        call["status"] == "failed" and not exists,
        call,
    )
    toggle(False, "N19")
    if c1.WINDOWS:
        state = subprocess.check_output(
            ["sc.exe", "query", "EugenePlexusApp-node-files"], text=True
        )
        stopped = "STOPPED" in state
    else:
        state = subprocess.check_output(
            [
                "systemctl",
                "show",
                "eugene-plexus-app@node-files.service",
                "--property=ActiveState",
            ],
            text=True,
        )
        stopped = "ActiveState=inactive" in state
    check("N20", "disabling file support stops its OS service", stopped, state)
    check(
        "N21",
        "helper stays out of the ordinary app list",
        all(
            a["id"] != "node-files"
            for a in api("GET", c1.AGENT + "/v1/apps", token)[1]["apps"]
        ),
    )


def combined(app: dict, token: str) -> None:
    c6.combined(app, token)
    exercise(app, token)


if __name__ == "__main__":
    c5.Model, c5.exercise = c6.Model, combined
    raise SystemExit(c5.main())
