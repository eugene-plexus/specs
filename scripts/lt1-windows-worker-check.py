"""LT1, the platform check: a Windows worker joined to a container root.

`docs/design/tls-between-machines.md` §5 (platforms). The root runs in a
container (Docker in WSL2), published on remapped ports the way the Unraid
template's owner runs it (+400 here: 8479, 8480, 8483 for 8079, 8080, 8083).
The worker is a real agent on this Windows machine, on ports clear of the
live install (8379 for the agent, 8383 for its machine port, 8490 for its
driver), with every ambient `EUGENE_PLEXUS_*` variable cleared.

Checks:

1. The worker joins at the root's remapped control port with a token that
   carries the root's machine key, over TLS (`https://<wsl>:8483/control`).
2. The root's machine URL followed the remap (`https://<wsl>:8483`, from an
   advertised 8479), and the worker's is `https://<this PC>:8383`.
3. A prompt with a canary goes root gateway -> the Windows worker's driver
   and back, and the root reports the worker's link `encrypted`.
4. The bind rule on Windows: the machine port listens on every interface,
   and once the install requires encryption the driver listens on loopback
   only (`Get-NetTCPConnection`).
   The firewall rule follows the machine port too (`listeners_of`, the
   agent's unit tests); it changes only in an elevated agent, which this
   check is not, so the live install's rule is never touched.
5. The wire between Windows and WSL (`tcpdump` on WSL's `eth0`, as WSL's
   root) holds no canary, no `Bearer`, no `eyJ`, and every flow is TLS.

Run on Amish_Station from the specs worktree, with the agent's venv and
`PYTHONPATH` naming the worktrees' `src` folders, after a run of
`lt1-machine-tls-acceptance.py` has built the image:

    python scripts/lt1-windows-worker-check.py --image ep-lt1:<tag> \\
        --sources ..  --output <new dir>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve()
WSL = ["wsl", "-d", "Ubuntu", "--"]
ROOT_PORTS = {"agent": 8479, "gateway": 8480, "control": 8483}
WORKER = {"agent": 8379, "machine": 8383, "driver": 8490, "stub": 9400}
MODEL = "lt1-stub"
PYTHON_IN_IMAGE = "/opt/ep/venv/bin/python"

for _key in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
    del os.environ[_key]


def run(argv: list[str], check: bool = True) -> str:
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=600, check=False
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(argv[:6])}: {result.stderr or result.stdout}")
    return (result.stdout or "").strip()


def docker(*args: str, check: bool = True) -> str:
    return run([*WSL, "docker", *args], check=check)


def wsl_path(path: Path) -> str:
    return run(["wsl", "-d", "Ubuntu", "wslpath", "-a", str(path).replace("\\", "/")])


class Record:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, name: str, passed: bool, **observed: object) -> None:
        status = "pass" if passed else "FAIL"
        self.checks.append({"check": name, "status": status, "observed": observed})
        print(
            f"{status.upper():6} {name} {json.dumps(observed, default=str)[:600]}",
            flush=True,
        )


def wait_for(check, label: str, timeout: float = 90.0):
    deadline = time.perf_counter() + timeout
    last: object = None
    while time.perf_counter() < deadline:
        try:
            last = check()
        except httpx.HTTPError as exc:
            last = exc
        if last:
            return last
        time.sleep(1.0)
    raise AssertionError(
        f"timed out after {timeout:.0f} s waiting for {label} (last: {last!r})"
    )


EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def powershell(command: str, check: bool = True) -> str:
    return run(["powershell", "-NoProfile", "-Command", command], check=check)


def lt2_edge(
    record: Record,
    output: Path,
    client: httpx.Client,
    worker: str,
    operator: str,
    pc_ip: str,
    wsl_ip: str,
) -> None:
    """LT2 (`tls-for-clients.md` §10, Windows): the worker holds a leaf from
    the install CA; the CA goes into this account's Root store the way a
    person adds it (Windows asks to confirm, once); headless Edge, which
    reads that store, opens the worker's and the root's consoles over https;
    and the CA is taken out again (Windows asks again)."""
    headers = {"Authorization": f"Bearer {operator}"}

    def issued() -> dict | None:
        node = client.get(worker + "/v1/node", headers=headers).json()
        tls = node.get("clientTls") or {}
        return tls if tls.get("state") == "issued" else None

    try:
        tls = wait_for(issued, "the Windows worker's leaf from the install CA", 120)
    except AssertionError as exc:
        record.add(
            "the Windows worker holds a leaf from the install CA", False, error=str(exc)
        )
        return
    record.add(
        "the Windows worker holds a leaf from the install CA",
        pc_ip in (tls.get("names") or []),
        names=tls.get("names"),
    )
    der = client.get(worker + "/v1/trust/ca?format=der")
    ca_file = output / "eugene-plexus-ca.cer"
    ca_file.write_bytes(der.content)
    thumbprint = ""
    try:
        thumbprint = (
            powershell(
                f"(Import-Certificate -FilePath '{ca_file}' "
                "-CertStoreLocation Cert:\\CurrentUser\\Root).Thumbprint"
            )
            .splitlines()[-1]
            .strip()
        )
        seen: dict[str, str] = {}
        for label, url in (
            ("worker", f"https://{pc_ip}:{WORKER['agent']}/healthz"),
            ("root", f"https://{wsl_ip}:{ROOT_PORTS['agent']}/healthz"),
        ):
            profile = Path(tempfile.mkdtemp(prefix="ep-lt2-edge-"))
            seen[label] = run(
                [str(EDGE), "--headless=new", "--disable-gpu", "--no-first-run",
                 f"--user-data-dir={profile}", "--dump-dom", url],
                check=False,
            )  # fmt: skip
        record.add(
            "Edge, with the CA in this account's store, opens both consoles over https",
            all('"status":"ok"' in dom for dom in seen.values()),
            **{k: v[:160] for k, v in seen.items()},
            thumbprint=thumbprint,
        )
    finally:
        if thumbprint:
            powershell(
                f"Remove-Item Cert:\\CurrentUser\\Root\\{thumbprint}", check=False
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--lt2",
        action="store_true",
        help="also the install CA in this account's Root store and Edge over https "
        "(Windows asks to confirm adding and removing it)",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    record = Record()
    wsl_ip = run([*WSL, "bash", "-c", "hostname -I | cut -d' ' -f1"])
    # Windows reaches WSL from its side of the virtual switch, not its LAN address.
    windows_side = next(
        line.split()[2]
        for line in run([*WSL, "ip", "route"]).splitlines()
        if line.startswith("default via ")
    )
    pc_ip = next(
        line.split()[-1]
        for line in run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias Ethernet).IPAddress"]
        ).splitlines()
        if line.strip()
    )  # fmt: skip
    name = f"ep-lt1-win-{secrets.token_hex(3)}"
    passphrase = secrets.token_urlsafe(18)
    canary = "LT1CANARY" + secrets.token_hex(12)
    work = Path(tempfile.mkdtemp(prefix="ep-lt1-win-"))
    processes: list[subprocess.Popen] = []
    capture = None
    client = httpx.Client(trust_env=False, timeout=60)
    worker = f"http://127.0.0.1:{WORKER['agent']}"

    def exec_root(command: str, argument: dict) -> dict:
        out = docker("exec", name, PYTHON_IN_IMAGE, "/instruments/lt1-machine-tls-acceptance.py",
                     "--inside", command, "--argument", json.dumps(argument))  # fmt: skip
        return json.loads(out.splitlines()[-1]) if out else {}

    def root_call(method: str, url: str, token: str | None = None, **kw) -> dict:
        # Inside the container, so these calls are on its loopback, never the wire.
        return exec_root("call", {"method": method, "url": url, "token": token, **kw})

    try:
        # ---- the root, in a container on remapped ports ---------------------
        instruments = wsl_path(HERE.parent)
        docker(
            "run", "-d", "--name", name,
            "-p", f"{ROOT_PORTS['agent']}:8079", "-p", f"{ROOT_PORTS['gateway']}:8080",
            "-p", f"{ROOT_PORTS['control']}:8083",
            "--mount", f"type=bind,src={instruments},dst=/instruments,readonly",
            args.image, "sleep", "infinity",
        )  # fmt: skip
        advertise = f"http://{wsl_ip}:{ROOT_PORTS['agent']}"
        local = "http://127.0.0.1"
        exec_root("write", {"path": "/data/a/control.yaml", "text": "{}\n"})
        exec_root(
            "write",
            {"path": "/data/a/gateway.yaml", "text": '{"routingRefreshSeconds": 1}'},
        )
        exec_root(
            "write",
            {
                "path": "/data/a/agent.yaml",
                "text": json.dumps(
                    {
                        "firstRunComplete": True,
                        "updateChecks": False,
                        "advertiseUrl": advertise,
                        "securityMode": "prompt_on_startup",
                        "components": [
                            {
                                "name": "control",
                                "kind": "control",
                                "url": f"{local}:8083",
                                "spawn": {"configFile": "/data/a/control.yaml"},
                            },
                            {
                                "name": "gateway",
                                "kind": "gateway",
                                "url": f"{local}:8080",
                                "spawn": {"configFile": "/data/a/gateway.yaml"},
                            },
                        ],
                    }
                ),  # fmt: skip
            },
        )
        exec_root(
            "spawn",
            {
                "argv": [PYTHON_IN_IMAGE, "-m", "eugene_plexus_agent", "--unattended"],
                "cwd": "/data/a",
                "log": "/data/a/agent.log",
                "env": {
                    "EUGENE_PLEXUS_AGENT_CONFIG_FILE": "/data/a/agent.yaml",
                    "EUGENE_PLEXUS_AGENT_BIND_HOST": "0.0.0.0",
                    "EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY": "false",
                },
            },
        )
        wait_for(
            lambda: root_call("GET", f"{local}:8083/healthz")["status"] == 200,
            "control",
        )
        got = root_call(
            "POST", f"{local}:8083/v1/auth/initialize", json={"passphrase": passphrase}
        )
        assert got["status"] == 204, got

        def login(url: str, inside: bool = True) -> str:
            def attempt():
                if inside:
                    answer = root_call("POST", url + "/v1/auth/login",
                                       json={"passphrase": passphrase})  # fmt: skip
                    return (
                        answer["body"]["sessionToken"]
                        if answer["status"] == 200
                        else None
                    )
                response = client.post(
                    url + "/v1/auth/login", json={"passphrase": passphrase}
                )
                return (
                    response.json()["sessionToken"]
                    if response.status_code == 200
                    else None
                )

            return str(wait_for(attempt, f"sign-in at {url}", 45))

        session = login(f"{local}:8083")

        def join(grants: list[str]) -> str:
            answer = root_call("POST", f"{local}:8083/v1/nodes/join-token", session,
                               json={"grants": grants})  # fmt: skip
            assert answer["status"] == 201, answer
            return str(answer["body"]["token"])

        def enroll(call, base: str, control_url: str, token: str, node: str) -> None:
            answer = call(
                "POST", base + "/v1/auth/initialize", json={"passphrase": passphrase}
            )
            standalone = answer["body"]["sessionToken"]
            answer = call("POST", base + "/v1/node/enroll", standalone,
                          json={"controlUrl": control_url, "token": token, "name": node})  # fmt: skip
            assert answer["status"] == 200, answer

        enroll(root_call, f"{local}:8079", f"{local}:8083", join(["gateway"]), "root")
        token = join([])

        # ---- the capture, from before the worker exists ---------------------
        # A script, because `wsl --` hands its arguments to a shell and the
        # filter's parentheses do not survive that.
        script = args.output / "capture.sh"
        script.write_text(
            "#!/usr/bin/env bash\n"
            "exec tcpdump -i eth0 -s 0 -U -w /tmp/lt1-win.pcap "
            f"'tcp and (host {pc_ip} or host {windows_side})'\n",
            encoding="utf-8",
            newline="\n",
        )
        run(["wsl", "-d", "Ubuntu", "-u", "root", "--", "rm", "-f", "/tmp/lt1-win.pcap"],
            check=False)  # fmt: skip
        capture = subprocess.Popen(
            ["wsl", "-d", "Ubuntu", "-u", "root", "--", "bash", wsl_path(script)],
            stdout=subprocess.DEVNULL,
            stderr=(args.output / "capture.log").open("wb"),
        )
        time.sleep(2)

        # ---- the worker, on this Windows machine ----------------------------
        (work / "inference-driver.yaml").write_text(
            json.dumps({"provider": "openai_compat_custom",
                        "baseUrl": f"http://127.0.0.1:{WORKER['stub']}",
                        "modelId": MODEL, "backendLocality": "local"}),
            encoding="utf-8",
        )  # fmt: skip
        (work / "agent.yaml").write_text(
            json.dumps(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "advertiseUrl": f"http://{pc_ip}:{WORKER['agent']}",
                    "securityMode": "prompt_on_startup",
                    "components": [
                        {"name": "lt1-driver", "kind": "inference-driver",
                         "url": f"http://127.0.0.1:{WORKER['driver']}",
                         "spawn": {"configFile": str(work / "inference-driver.yaml")}},
                    ],
                }
            ),
            encoding="utf-8",
        )  # fmt: skip
        env = dict(os.environ)
        env.update(
            {
                "PYTHONUNBUFFERED": "1",
                "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(work / "agent.yaml"),
                "EUGENE_PLEXUS_AGENT_BIND_HOST": "0.0.0.0",
                "EUGENE_PLEXUS_AGENT_BIND_PORT": str(WORKER["agent"]),
                "EUGENE_PLEXUS_AGENT_MACHINE_PORT": str(WORKER["machine"]),
                "EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY": "false",
            }
        )
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        stub_argv = [sys.executable, str(HERE.parent / "lt1-machine-tls-acceptance.py"),
                     "--inside", "stub", "--argument",
                     json.dumps({"port": WORKER["stub"], "stats": str(work / "stub.json")})]  # fmt: skip
        for argv, log_name in (
            (stub_argv, "stub.log"),
            (
                [sys.executable, "-m", "eugene_plexus_agent", "--unattended"],
                "agent.log",
            ),
        ):
            processes.append(
                subprocess.Popen(
                    argv,
                    cwd=work,
                    env=env,
                    creationflags=flags,
                    stdout=(work / log_name).open("ab"),
                    stderr=subprocess.STDOUT,
                )  # fmt: skip
            )
        wait_for(
            lambda: client.get(worker + "/healthz").status_code == 200,
            "the Windows agent",
        )

        def worker_call(method: str, url: str, token: str | None = None, **kw) -> dict:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            response = client.request(method, url, headers=headers, **kw)
            try:
                return {"status": response.status_code, "body": response.json()}
            except ValueError:
                return {"status": response.status_code, "body": response.text}

        control_url = f"http://{wsl_ip}:{ROOT_PORTS['control']}"
        try:
            enroll(worker_call, worker, control_url, token, "windows-worker")
            node = client.get(worker + "/v1/node",
                              headers={"Authorization": f"Bearer {login(worker, inside=False)}"})  # fmt: skip
            joined = node.status_code == 200 and node.json().get("enrolled")
            record.add("the worker joined at the root's remapped port, over TLS", bool(joined),
                       controlUrl=control_url, pin=token.rpartition(".")[2])  # fmt: skip
        except AssertionError as exc:
            record.add("the worker joined at the root's remapped port, over TLS", False,
                       error=str(exc))  # fmt: skip
            raise

        operator_w = login(worker, inside=False)
        operator = login(f"{local}:8079")
        machine_w = client.get(worker + "/v1/node",
                               headers={"Authorization": f"Bearer {operator_w}"}).json()["machine"]  # fmt: skip
        machine_r = root_call("GET", f"{local}:8079/v1/node", operator)["body"][
            "machine"
        ]
        record.add(
            "machine URLs follow the remap and the port setting",
            machine_r["url"].rstrip("/") == f"https://{wsl_ip}:{ROOT_PORTS['control']}"
            and machine_w["url"].rstrip("/") == f"https://{pc_ip}:{WORKER['machine']}",
            root=machine_r["url"],
            worker=machine_w["url"],
        )

        def listed() -> bool:
            answer = root_call("GET", f"{local}:8080/v1/models", operator)
            return MODEL in {
                m.get("id") for m in (answer.get("body") or {}).get("data", [])
            }

        wait_for(listed, "the root's gateway to list the Windows worker's model", 150)
        answer = root_call(
            "POST", f"{local}:8080/v1/chat/completions", operator,
            json={"model": MODEL, "messages": [{"role": "user", "content": f"repeat {canary}"}]},
            timeout=60,
        )  # fmt: skip
        echoed = answer["status"] == 200 and canary in json.dumps(answer.get("body"))

        def encrypted() -> dict | None:
            got = root_call("GET", f"{local}:8083/v1/nodes/windows-worker", session)
            link = (got.get("body") or {}).get("machineTls") or {}
            return link if link.get("state") == "encrypted" else None

        try:
            link = wait_for(encrypted, "the root to report the link encrypted", 60)
        except AssertionError as exc:
            link = {"error": str(exc)}
        record.add("a prompt reaches the Windows worker, and the link is encrypted",
                   echoed and link.get("state") == "encrypted",
                   chat=answer["status"], link=link)  # fmt: skip

        def listening(port: int) -> list[str]:
            out = run(["powershell", "-NoProfile", "-Command",
                       f"(Get-NetTCPConnection -State Listen -LocalPort {port} "
                       "-ErrorAction SilentlyContinue).LocalAddress"], check=False)  # fmt: skip
            return sorted({line.strip() for line in out.splitlines() if line.strip()})

        def driver_on_loopback() -> list[str] | None:
            seen = listening(WORKER["driver"])
            return (
                seen if seen and all(a in ("127.0.0.1", "::1") for a in seen) else None
            )

        try:
            driver_bind = wait_for(
                driver_on_loopback, "the driver to listen on loopback", 90
            )
        except AssertionError:
            driver_bind = listening(WORKER["driver"])
        machine_bind = listening(WORKER["machine"])
        record.add(
            "the bind rule: the machine port wide, the driver on loopback once required",
            machine_bind == ["0.0.0.0"]
            and driver_bind
            and driver_on_loopback() is not None,
            machinePort=machine_bind,
            driver=driver_bind,
            required=machine_w.get("required"),
        )

        # ---- LT2: the install CA on Windows, and Edge over https -------------
        if args.lt2:
            lt2_edge(record, args.output, client, worker, operator_w, pc_ip, wsl_ip)
    except Exception as exc:
        record.add("the run completed", False, error=f"{type(exc).__name__}: {exc}")
    finally:
        wire = b""
        if capture is not None:
            run(
                ["wsl", "-d", "Ubuntu", "-u", "root", "--", "pkill", "-INT", "tcpdump"],
                check=False,
            )
            time.sleep(2)
            wire_path = args.output / "wire.pcap"
            run(["wsl", "-d", "Ubuntu", "-u", "root", "--", "cp", "/tmp/lt1-win.pcap",
                 wsl_path(args.output) + "/wire.pcap"], check=False)  # fmt: skip
            wire = wire_path.read_bytes() if wire_path.exists() else b""
        for proc in processes:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                           check=False)  # fmt: skip
        docker("cp", f"{name}:/data", wsl_path(args.output) + "/root", check=False)
        docker("rm", "-f", name, check=False)
        for log_name in ("agent.log", "stub.log"):
            if (work / log_name).exists():
                (args.output / f"worker-{log_name}").write_bytes(
                    (work / log_name).read_bytes()
                )
        if wire:
            sys.path.insert(0, str(HERE.parent))
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "lt1acc", HERE.parent / "lt1-machine-tls-acceptance.py"
            )
            assert spec and spec.loader
            acceptance = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(acceptance)
            flows = acceptance.pcap_flows(wire)
            plain = sorted(f"{s}:{sp}->{d}:{dp}" for (s, sp, d, dp), v in flows.items()
                           if v[:1] != b"\x16")  # fmt: skip
            streams = b"".join(bytes(v) for v in flows.values())
            hits = [n.decode() for n in (canary.encode(), b"Bearer")
                    if n in wire or n in streams]  # fmt: skip
            # A token, not the bytes "eyJ", which turn up by chance in TLS ciphertext.
            jwt = re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.")
            if jwt.search(wire) or jwt.search(streams):
                hits.append("eyJ")
            record.add(
                "the wire between Windows and WSL: TLS only, no canary or token",
                bool(flows) and not plain and not hits,
                flows=len(flows),
                plain=plain[:10],
                found=hits,
            )
        else:
            record.add("the wire between Windows and WSL: TLS only, no canary or token", False,
                       error="no capture")  # fmt: skip
        (args.output / "result.json").write_text(json.dumps(record.checks, indent=2),
                                                 encoding="utf-8")  # fmt: skip
    sys.exit(1 if any(c["status"] != "pass" for c in record.checks) else 0)


if __name__ == "__main__":
    main()
