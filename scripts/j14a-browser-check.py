"""J14a in a real browser: a key made in Chrome, pinned at the machine, and the
site host's own verifier taking what Chrome signed (`person-held-keys.md` §12).

What is real: the system Chrome and its WebCrypto (Ed25519, and ECDSA P-256
when Ed25519 is withheld), the agent's own `/link` routes and page script,
the agent's lookup of which OS account owns the browser's connection, the
links file, and the site host's own app with its `/v1/held` API, token and
verifier, as two processes on loopback. What is not: a Windows service
install (the agent here runs as you, not LocalSystem, and the site host in
no account of its own), and the root and Workbench (the change is put in the
site host's held list as the root's word would leave it). Those are the
service run's and the CI harness's.

`--per-user` (J14a.2): the page as a per-user install serves it, to the one
account the agent runs as and linking nobody; the run is otherwise the same,
so Chrome makes, pins and signs with its key on a per-user page too.

Windows only, unelevated. Usage, from anywhere:

    python specs/scripts/j14a-browser-check.py [--per-user] [--keep DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT_PY = ROOT / "agent" / ".venv" / "Scripts" / "python.exe"
SITE_PY = ROOT / "site-host" / ".venv" / "Scripts" / "python.exe"
PLAYWRIGHT = ROOT / "ui" / "node_modules" / "playwright-core"
OWNER = "person-ada"
SITE_ID = "s-" + "a" * 26
ENROLLED_AT = "2026-10-06T12:00:00+00:00"

SITE_LAUNCHER = r'''
import json, sys
from pathlib import Path
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from eugene_plexus_site_host.app import create_app
from eugene_plexus_site_host.identity import Enrollment, Identity
from eugene_plexus_site_host.settings import Settings

data, links, port = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
Identity(data).record(
    Ed25519PrivateKey.generate(),
    Enrollment(site=sys.argv[4], label="desk", owner=sys.argv[5], ownerName="ada",
               url="http://127.0.0.1:9", rootKey="", enrolledAt=sys.argv[6]),
)

class Idle:
    last_contact = None
    problem = "No root in this check."
    async def run(self):
        return None

settings = Settings(data_dir=data, port=port, links_file=links, channel=None,
                    link_page=f"http://127.0.0.1:{sys.argv[7]}/link")
uvicorn.run(create_app(settings, channel=Idle()), host="127.0.0.1", port=port, log_level="warning")
'''

PAGE_LAUNCHER = r'''
import sys
from pathlib import Path
import httpx
import uvicorn
from fastapi import FastAPI
from eugene_plexus_agent.routes import site_link
from eugene_plexus_agent.site_links import LinkStore

config, site_port, port, token_file = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])
MODE = sys.argv[5]

class Supervisor:
    """The agent's supervisor, as far as the page asks of it."""
    def __init__(self):
        self.client = httpx.AsyncClient(trust_env=False, timeout=10)
    def link_page_offered(self): return MODE == "service"
    def key_page_offered(self): return True
    def link_store(self): return LinkStore(config)
    def never_linked(self): return frozenset({"S-1-5-18"})
    def links_changed(self): pass
    def mode(self): return MODE
    async def held(self, method, path, **kwargs):
        token = token_file.read_text(encoding="utf-8").strip()
        return await self.client.request(method, f"http://127.0.0.1:{site_port}{path}",
                                         headers={"Authorization": f"Bearer {token}"}, **kwargs)

app = FastAPI()
app.include_router(site_link.router)
app.state.site_host = Supervisor()
uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
'''


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def own_sid() -> str:
    out = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True
    )
    return out.stdout.strip().split(",")[-1].strip('"')


def wait(url: str, seconds: float = 30) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except Exception as exc:  # noqa: BLE001
            if getattr(exc, "code", None):
                return
            time.sleep(0.2)
    raise SystemExit(f"nothing answered at {url}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", type=Path)
    parser.add_argument("--per-user", dest="per_user", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32":
        print("SKIP: the link page serves a Windows service install")
        return 0
    work = args.keep or Path(tempfile.mkdtemp(prefix="j14a-"))
    work.mkdir(parents=True, exist_ok=True)
    config = work / "config"
    (config / "site").mkdir(parents=True, exist_ok=True)
    links = config / "site" / "links.json"
    data = work / "site-data"
    data.mkdir(exist_ok=True)
    sid = own_sid()
    links.write_text(
        json.dumps(
            {
                "version": 1,
                "links": [
                    {
                        "subject": OWNER,
                        "name": "ada",
                        "account": sid,
                        "accountName": "this account",
                        "linkedAt": ENROLLED_AT,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    # Rules made on the root's word before the owner had a key (J52), and a
    # change the root asked for once the owner had one (J50).
    (data / "policy.json").write_text(
        json.dumps(
            {
                "version": 1,
                "folders": [
                    {
                        "id": "f" * 32,
                        "name": "Notes",
                        "path": "C:\\Notes",
                        "identity": "vol:1",
                        "writable": False,
                        "people": [{"subject": OWNER, "writable": False}],
                    }
                ],
                "access": [],
                "enabled": {},
                "ownerInDevMode": False,
            }
        ),
        encoding="utf-8",
    )
    held = {
        "version": 1,
        "items": [
            {
                "id": "a1b2c3d4e5f60718",
                "subject": OWNER,
                "action": "settings.set",
                "arguments": {"ownerInDevMode": True},
                "names": {},
                "heldAt": time.time(),
            }
        ],
    }
    (data / "held.json").write_text(json.dumps(held), encoding="utf-8")
    site_port, page_port = free_port(), free_port()
    (work / "site.py").write_text(SITE_LAUNCHER, encoding="utf-8")
    (work / "page.py").write_text(PAGE_LAUNCHER, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
    site = subprocess.Popen(
        [str(SITE_PY), str(work / "site.py"), str(data), str(links), str(site_port), SITE_ID,
         OWNER, ENROLLED_AT, str(page_port)],
        env=env,
    )
    page = subprocess.Popen(
        [str(AGENT_PY), str(work / "page.py"), str(config), str(site_port), str(page_port),
         str(data / "local_token"), "user" if args.per_user else "service"],
        env=env,
    )
    try:
        wait(f"http://127.0.0.1:{site_port}/healthz")
        wait(f"http://127.0.0.1:{page_port}/link")
        cfg = {
            "playwright": str(PLAYWRIGHT),
            "base": f"http://127.0.0.1:{page_port}",
            "held": str(data / "held.json"),
            "owner": OWNER,
            "profile": str(work / "chrome"),
        }
        (work / "cfg.json").write_text(json.dumps(cfg), encoding="utf-8")
        out = subprocess.run(
            ["node", str(Path(__file__).with_suffix(".mjs")), str(work / "cfg.json")],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
        )
        if out.returncode != 0:
            print(out.stdout, out.stderr)
            return 1
        result = json.loads(out.stdout)
        checks = list(result["checks"])
        pinned = json.loads(links.read_text(encoding="utf-8"))["links"][0].get("keys") or []
        policy = json.loads((data / "policy.json").read_text(encoding="utf-8"))
        seqs = json.loads((data / "signatures.json").read_text(encoding="utf-8"))["seq"]
        audit = [
            json.loads(line)
            for line in (data / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        approved = [e for e in audit if (e.get("reason") or "").startswith("Approved at the machine")]
        checks.append(
            [
                "S1",
                "the links file holds both keys, Ed25519 and ES256, each id the SHA-256 of its key",
                sorted(k["alg"] for k in pinned) == ["ES256", "Ed25519"],
                [k["alg"] for k in pinned],
            ]
        )
        checks.append(
            [
                "S2",
                "the site host applied what Chrome signed: dev-mode let in, the rules approved",
                policy["ownerInDevMode"] is True and policy.get("authorized") is not None,
                {"ownerInDevMode": policy["ownerInDevMode"], "authorized": policy.get("authorized")},
            ]
        )
        checks.append(
            [
                "S3",
                "four approvals, each with the next sequence number, each in the audit log",
                seqs.get(OWNER) == 4 and len(approved) == 4,
                {"seq": seqs, "approved": len(approved)},
            ]
        )
        failed = [c for c in checks if not c[2]]
        for number, claim, passed, detail in checks:
            print(
                f"{'PASS' if passed else 'FAIL'} {number}: {claim}"
                + ("" if passed else f" -- {detail}")
            )
        for problem in result.get("problems") or []:
            print(f"PROBLEM: {problem}")
        print(f"{len(checks) - len(failed)}/{len(checks)} passed")
        return 1 if failed or result.get("problems") else 0
    finally:
        for process in (page, site):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        if args.keep is None:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
