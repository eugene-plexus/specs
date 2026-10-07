"""J14a.3 in a real browser: a passkey made in Chrome at an HTTPS name, paired
with the site's code by Workbench's own code, and its approval taken by the
site host's own verifier (`person-held-keys.md` §4.2, §12.5).

What is real: the system Chrome, its WebAuthn (`navigator.credentials.create`
and `.get`, a CDP virtual authenticator that verifies the person, the way §2
measured: a real authenticator refuses an untrusted certificate, so the name's
certificate is trusted by its SPKI pin), its WebCrypto PBKDF2 and HMAC, and
Workbench's own `web/src/lib/passkeys.ts`, compiled as it is; and the site
host's own `Host`, with its codes, its pairing check, its passkey store and its
assertion verifier, applying what is approved. What is not: the root and
Workbench's server, which only carry these bytes (their own tests, and the CI
harness `job-sites-acceptance.py`, carry them for real).

Checks, each against what Chrome actually produced:

1. Chrome makes a passkey at `https://workbench.home.arpa` (RP ID that name),
   and its `getPublicKey()` is a key the site takes.
2. The pairing MAC Chrome computed from the code typed (as a person types it,
   lower case) checks at the site, which pins the passkey.
3. The same passkey's MAC with one character of the code wrong is refused.
4. Chrome's assertion over the site's envelope for its rules approves them,
   and the site's signing state becomes `signed`.
5. A change that gives access is held, and Chrome's assertion over that
   change's envelope applies it.
6. Chrome's assertion over a different envelope is refused for that reason.
7. An authenticator that cannot verify the person: Chrome refuses to sign
   for a page that requires it (`userVerification: "required"`), so nothing
   reaches the site.

Windows (the system Chrome), unelevated. Usage, from anywhere:

    python specs/scripts/j14a3-browser-check.py [--keep DIR]
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE_PY = ROOT / "site-host" / ".venv" / "Scripts" / "python.exe"
WORKBENCH_WEB = ROOT / "workbench" / "web"
PLAYWRIGHT = ROOT / "ui" / "node_modules" / "playwright-core"
NAME = "workbench.home.arpa"
OWNER = "person-ada"

SERVER = r'''
import asyncio, json, secrets, ssl, sys, time
from pathlib import Path
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from eugene_plexus_site_host import local_channel
from eugene_plexus_site_host._generated.models import SiteManage
from eugene_plexus_site_host.host import Host
from eugene_plexus_site_host.identity import Enrollment, Identity
from eugene_plexus_site_host.settings import Settings

work, port, owner, name = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]

def certificate():
    """A certificate for the name, and its SPKI pin for Chrome."""
    import base64, datetime, hashlib
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .sign(key, hashes.SHA256()))
    (work / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (work / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    spki = cert.public_key().public_bytes(serialization.Encoding.DER,
                                          serialization.PublicFormat.SubjectPublicKeyInfo)
    (work / "pin.txt").write_text(base64.b64encode(hashlib.sha256(spki).digest()).decode())

certificate()
data = work / "data"
data.mkdir(parents=True, exist_ok=True)
Identity(data).record(
    Ed25519PrivateKey.generate(),
    Enrollment(site="s-" + "a" * 26, label="desk", owner=owner, ownerName="ada",
               url="http://127.0.0.1:9", rootKey="", enrolledAt="2026-10-07T12:00:00+00:00"),
)
links = work / "links.json"
links.write_text(json.dumps({"version": 1, "links": [{
    "subject": owner, "name": "ada", "account": local_channel.own_account(),
    "accountName": "HOST/ada", "linkedAt": "2026-10-07T12:00:00Z"}]}), encoding="utf-8")
host = Host(Settings(data_dir=data, port=port, links_file=links, channel=None))
app = FastAPI()

async def manage(action, **arguments):
    return await host.manage(SiteManage.model_validate({
        "id": secrets.token_hex(8), "expiresAt": time.time() + 20, "subject": owner,
        "action": action, "arguments": arguments}))

@app.get("/")
async def page():
    return HTMLResponse("<!doctype html><title>check</title>"
        "<script type=module>import * as wb from '/passkeys.js'; window.wb = wb; "
        "window.ready = true;</script>")

@app.get("/passkeys.js")
async def script():
    return Response((work / "passkeys.js").read_text(encoding="utf-8"),
                    media_type="text/javascript")

@app.post("/code")
async def code():
    return host.passkey_code(owner)

@app.post("/manage/{action}")
async def act(action: str, request: Request):
    return await manage(action, **(await request.json()))

@app.get("/state")
async def state():
    return {"signing": host.signing_state(), "ownerInDevMode": host.policy.owner_in_dev_mode,
            "passkeys": [p.view() for p in host.passkeys_of(owner)]}

uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning",
            ssl_certfile=str(work / "cert.pem"), ssl_keyfile=str(work / "key.pem"))
'''

COMPILE = r"""
const ts = require(process.argv[2]);
const fs = require("node:fs");
const source = fs.readFileSync(process.argv[3], "utf8");
const out = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
});
fs.writeFileSync(process.argv[4], out.outputText);
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", type=Path, help="keep the run's files here")
    args = parser.parse_args()
    if sys.platform != "win32":
        print("SKIP: the browser check drives the system Chrome on Windows")
        return 0
    for need in (SITE_PY, PLAYWRIGHT, WORKBENCH_WEB / "node_modules" / "typescript"):
        if not need.exists():
            print(f"FAIL: {need} is missing")
            return 1
    work = args.keep or Path(tempfile.mkdtemp(prefix="j14a3-"))
    work.mkdir(parents=True, exist_ok=True)
    compiler = work / "compile.cjs"
    compiler.write_text(COMPILE, encoding="utf-8")
    subprocess.run(
        [
            "node",
            str(compiler),
            str(WORKBENCH_WEB / "node_modules" / "typescript"),
            str(WORKBENCH_WEB / "src" / "lib" / "passkeys.ts"),
            str(work / "passkeys.js"),
        ],
        check=True,
    )
    port = free_port()
    launcher = work / "server.py"
    launcher.write_text(SERVER, encoding="utf-8")
    log = (work / "server.log").open("w", encoding="utf-8")
    server = subprocess.Popen(
        [str(SITE_PY), str(launcher), str(work), str(port), OWNER, NAME], stdout=log, stderr=log
    )
    try:
        import ssl

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        deadline = time.perf_counter() + 30
        while True:
            try:
                urllib.request.urlopen(f"https://127.0.0.1:{port}/state", context=context, timeout=2)
                break
            except OSError:
                if time.perf_counter() > deadline or server.poll() is not None:
                    print("FAIL: the check's server did not start; see", work / "server.log")
                    return 1
                time.sleep(0.2)
        pin = (work / "pin.txt").read_text(encoding="utf-8").strip()
        config = work / "config.json"
        config.write_text(
            json.dumps(
                {
                    "playwright": str(PLAYWRIGHT),
                    "base": f"https://{NAME}:{port}",
                    "name": NAME,
                    "port": port,
                    "pin": pin,
                    "owner": OWNER,
                    "site": "s-" + "a" * 26,
                }
            ),
            encoding="utf-8",
        )
        driver = Path(__file__).with_suffix(".mjs")
        run = subprocess.run(
            ["node", str(driver), str(config)], capture_output=True, text=True, timeout=180
        )
        if run.returncode != 0 and not run.stdout.strip():
            print("FAIL: the driver did not finish:", run.stderr[-2000:])
            return 1
        result = json.loads(run.stdout)
    finally:
        server.terminate()
        server.wait(timeout=10)
        log.close()
    failed = 0
    for number, claim, passed, detail in result["checks"]:
        print(f"{'PASS' if passed else 'FAIL'} {number}: {claim}" + (f" ({detail})" if detail else ""))
        failed += 0 if passed else 1
    for problem in result["problems"]:
        print("PROBLEM:", problem)
    total = len(result["checks"])
    print(f"{total - failed}/{total} checks passed" + ("" if not failed else "; see above"))
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failed or result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
