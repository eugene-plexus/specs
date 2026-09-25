"""R2.4 sabotage pass: every check must fail when its defect is put back.

Run it after `r24-acceptance.sh`, and before believing either. Roadmap
§3.4; record `docs/acceptance/proportionate-credentials-run.md` §5.

**Sabotages a MIRROR of the component source, never the repos.** Since
2026-09-25 the three touched `src/` trees (control, agent, gateway) are
copied into a temporary directory, and every gate runs with that copy
first on `PYTHONPATH` -- the development venvs import the repos through
plain `.pth` path entries, which `PYTHONPATH` precedes. So the repos on
disk are never edited, and another acceptance run that starts a
component from the same venvs while this pass is running cannot pick up
a sabotaged file. The baseline asserts that each gate really imports the
mirror; the end asserts every repo file is byte-identical to the copy
taken before anything started.

Restores from an IN-MEMORY copy taken before anything is touched, never
`git checkout --`: that reverts uncommitted work, which in this repo
means deleting the change under test, after which every later result
reads *caught* for the wrong reason.

Opens with a baseline -- all four gates pass unsabotaged -- because a
sabotage that "fails" against an already-red gate proves nothing.

**The first three entries are the findings themselves**, each put back
the way the repo actually had it, and each driven against the LIVE
processes: a real trust root handing its snapshot to a real member
node's service token, a real root recording a correctly signed
announcement of the cloud metadata address, and a real gateway putting
its own token on a real socket. The entries after them take each fix
apart one property at a time, on whichever gate can see them.

**Re-anchored to per-node token keys (2026-09-25).** `decode_token`,
the `service:<kind>` audiences and the probe's `service_token` argument
are gone. The replication door is now `require_replica = require_operator`
(a session only) and the class list the verifier checks; the probe's
credential is `auth=`, and putting it back means handing it the
gateway's own outbound credential. The address rules did not move.
Removed: "require_replica drops service:control, so replication needs an
operator" -- that is now the design (D5; §5 names the standby gap), so
the sabotage would be the fix.

Four gates, because R2.4 is three repos plus the run that joins them.
The live gate inherits this process's environment, so pass the ports
there:

    EP_CONTROL_PORT=8283 EP_GATEWAY_PORT=8280 EP_LISTENER_PORT=8291 \\
    EP_NODE_PORT=8292 <agent venv python> scripts/r24-sabotage.py

Last run 2026-09-25 with exactly that (the agent venv's python,
`d:/py/eugene-plexus/agent/.venv/Scripts/python.exe`): baseline 4/4 PASS,
all four importing the mirror; 20 caught, 0 escaped, 20 sabotages;
restored 4/4 PASS. Second execution: the first reported two sabotages as
ANCHOR (matched nothing), because `node_address.py` is checked out with
CRLF endings on this box and the anchors are written with "\\n"; anchors
now take the file's own line ending.
2026-09-18 (old model): 20 sabotages, 20 caught.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")
SPECS = ROOT / "specs"

CONTROL_ROUTES = "src/eugene_plexus_control/routes/control.py"
DEPS = "src/eugene_plexus_control/dependencies.py"
TOKENS = "src/eugene_plexus_control/tokens.py"
ADDR = "src/eugene_plexus_control/node_address.py"
NODES = "src/eugene_plexus_control/routes/nodes.py"
IDENT = "src/eugene_plexus_agent/node_identity.py"
PROXY = "src/eugene_plexus_agent/install_proxy.py"
ADMIN = "src/eugene_plexus_gateway/routes/admin.py"

CONTROL = "control"
AGENT = "agent"
GATEWAY = "gateway"
LIVE = "live"
REPOS = (CONTROL, AGENT, GATEWAY)
PACKAGE = {CONTROL: "eugene_plexus_control", AGENT: "eugene_plexus_agent", GATEWAY: "eugene_plexus_gateway"}

GATE_FILES = {
    CONTROL: ["tests/test_auth.py", "tests/test_node_address.py", "tests/test_nodes.py"],
    AGENT: ["tests/test_install_wide_proxy.py"],
    GATEWAY: ["tests/test_admin_and_config.py"],
}


def _bash() -> str:
    """Git's bash, never WSL's: the live gate is a Windows-side script."""
    found = os.environ.get("EP_BASH") or shutil.which("bash")
    if not found or "windowsapps" in found.lower() or "system32" in found.lower():
        raise SystemExit(f"no Git bash found (got {found!r}); set EP_BASH")
    return found


def gate_env(mirror: Path, repos: tuple[str, ...]) -> dict[str, str]:
    """This process's environment, minus any EUGENE_PLEXUS_*, with the mirror first."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
    env["PYTHONPATH"] = os.pathsep.join(str(mirror / repo / "src") for repo in repos)
    # No bytecode: a sabotage and its restore can land in one mtime tick
    # with the same size, and a stale .pyc would run the wrong one.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def gate_python(gate: str) -> Path:
    return ROOT / (gate if gate in GATE_FILES else AGENT) / ".venv" / "Scripts" / "python.exe"


def run_gate(gate: str, mirror: Path) -> tuple[int, str]:
    if gate in GATE_FILES:
        done = subprocess.run(
            [str(gate_python(gate)), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
             *GATE_FILES[gate]],
            cwd=ROOT / gate,
            env=gate_env(mirror, (gate,)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
    else:
        done = subprocess.run(
            [_bash(), str(SPECS / "scripts" / "r24-acceptance.sh")],
            cwd=SPECS,
            env=gate_env(mirror, REPOS),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
    return done.returncode, (done.stdout or "")[-2500:] + (done.stderr or "")[-800:]


def imports_mirror(gate: str, mirror: Path) -> str | None:
    """Why this gate would NOT run the mirror, or None when it does."""
    repos = (gate,) if gate in GATE_FILES else REPOS
    probe = "; ".join(f"import {PACKAGE[r]}; print({PACKAGE[r]}.__file__)" for r in repos)
    if gate in GATE_FILES:
        argv = [str(gate_python(gate)), "-c", probe]
        cwd = ROOT / gate
    else:
        # Through bash, as the live gate runs, so a path conversion on the
        # way into a native program would show here.
        argv = [_bash(), "-c", f'"{gate_python(gate).as_posix()}" -c "{probe}"']
        cwd = SPECS
    done = subprocess.run(
        argv, cwd=cwd, env=gate_env(mirror, repos), capture_output=True, text=True, timeout=120
    )
    paths = [line.strip() for line in done.stdout.splitlines() if line.strip()]
    root = str(mirror.resolve()).lower()
    if done.returncode != 0 or len(paths) != len(repos):
        return f"probe failed: {done.stdout} {done.stderr}"
    wrong = [p for p in paths if not str(Path(p).resolve()).lower().startswith(root)]
    return f"imports {wrong}, not the mirror under {mirror}" if wrong else None


# The enrollment's address check and what follows it, exactly as the
# route has them: the swap below moves the check after the join token is
# consumed.
_ENROLL_ADDRESS_CHECK = """    reason = node_address.rejection(announced_url) if announced_url else None
    if reason is not None:
        # Checked **before** the join token is consumed: a single-use
        # credential spent on a request that was never going to be
        # recorded is an operator minting a second one for no reason.
        raise problem(
            status.HTTP_400_BAD_REQUEST,
            "Address cannot be a node",
            f"{body.url} cannot be this node's address: {reason}.",
        )"""
_ENROLL_LOCK_AND_CONSUME = """    # Before the token is consumed: a locked root used to spend the
    # single-use credential and then answer 503.
    if auth.signing_key is None or auth.control_private_key is None:
        raise problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Locked",
            "This control root has not been unlocked, so it cannot sign the trust bundle a "
            "new node needs. Log in first; the join token was not used.",
        )

    try:
        grants = store.consume(body.token, node_name=body.name)
    except JoinTokenConsumed as exc:
        raise problem(status.HTTP_409_CONFLICT, "Token already used", str(exc)) from exc
    except JoinTokenError as exc:
        raise problem(status.HTTP_401_UNAUTHORIZED, "Join token rejected", str(exc)) from exc"""


SABOTAGES: list[tuple[str, str, str, str, str, str]] = [
    # ---- the findings, put back, against the live processes ----------
    (
        "control: the replication surface takes a member's service token again (#12, THE finding)",
        CONTROL, CONTROL_ROUTES,
        "    dependencies=[Depends(require_replica)],\n)\nasync def read_snapshot",
        "    dependencies=[Depends(require_authorized)],\n)\nasync def read_snapshot",
        LIVE,
    ),
    (
        "control: a correctly signed announcement may name any URL again (#15, THE finding)",
        CONTROL, NODES,
        "    reason = node_address.rejection(announced_url)\n    if reason is not None:\n        log.warning(",
        "    reason = None\n    if reason is not None:\n        log.warning(",
        LIVE,
    ),
    (
        # What `service_token=auth_state.service_token` was under the old
        # model: the gateway's own outbound credential for its machine.
        "gateway: the probe presents the gateway's own token again (#33, THE finding)",
        GATEWAY, ADMIN,
        "        auth=None,\n    )",
        "        auth=request.app.state.outbound.auth(request.app.state.outbound.recipient),\n    )",
        LIVE,
    ),
    # ---- taking each fix apart, on the gate that can see it ----------
    (
        "control: the log goes back to a member's service token (#12's other half)",
        CONTROL, CONTROL_ROUTES,
        "    dependencies=[Depends(require_replica)],\n)\nasync def read_log",
        "    dependencies=[Depends(require_authorized)],\n)\nasync def read_log",
        CONTROL,
    ),
    (
        # The narrow door must stay narrow. Pointing the replication
        # level at the read level is the plausible wrong edit -- "a
        # standby is a member too" -- and is the defect verbatim.
        "control: require_replica is require_authorized, so any member's service token replicates",
        CONTROL, DEPS,
        "require_replica = require_operator\n",
        "require_replica = require_authorized\n",
        CONTROL,
    ),
    (
        "control: require_operator takes a service token beside a session",
        CONTROL, DEPS,
        "    return verify_bearer(request, _bearer(request, creds), classes=(tokens.TYP_SESSION,))",
        "    return verify_bearer(\n        request, _bearer(request, creds), "
        "classes=(tokens.TYP_SESSION, tokens.TYP_SERVICE)\n    )",
        CONTROL,
    ),
    (
        # Where `decode_token` ignoring its kind list lived: the verifier
        # itself, which now reads the token classes the route asks for.
        "control: the verifier ignores the token classes a route accepts",
        CONTROL, TOKENS,
        "    if typ not in classes:\n        raise TokenError(",
        "    if False:\n        raise TokenError(",
        CONTROL,
    ),
    (
        "control: the widening rule is dropped, so a node can go public by itself",
        CONTROL, NODES,
        "    if node_address.goes_public(record.url, normalized):",
        "    if False:",
        CONTROL,
    ),
    (
        # The rule has to be about *becoming public*, not about any
        # widening. Written as a rank comparison it refuses the S5 Reach
        # switch -- which is what the reproduction check caught first,
        # so it is put back here as a sabotage in its own right.
        "control: the rule becomes 'any widening', which refuses the Reach switch",
        CONTROL, ADDR,
        "    return after == CLASS_PUBLIC and before != CLASS_PUBLIC",
        "    return {CLASS_LOOPBACK: 0, CLASS_PRIVATE: 1, CLASS_PUBLIC: 2}[after] > "
        "{CLASS_LOOPBACK: 0, CLASS_PRIVATE: 1, CLASS_PUBLIC: 2}[before]",
        CONTROL,
    ),
    (
        # `is_private` is False for 100.64.0.0/10, so classifying on it
        # calls a tailnet address public and refuses the Reach switch on
        # exactly the deployment this product is for.
        "control: the classes are built from is_private instead of is_global",
        CONTROL, ADDR,
        "    if address.is_global:\n        return CLASS_PUBLIC\n    return CLASS_PRIVATE",
        "    if not address.is_private:\n        return CLASS_PUBLIC\n    return CLASS_PRIVATE",
        CONTROL,
    ),
    (
        "control: a bare hostname is treated as private, so an attacker names one",
        CONTROL, ADDR,
        '        if lowered == "localhost" or lowered.endswith(".localhost"):\n'
        "            return CLASS_LOOPBACK\n        return CLASS_PUBLIC",
        '        if lowered == "localhost" or lowered.endswith(".localhost"):\n'
        "            return CLASS_LOOPBACK\n        return CLASS_PRIVATE",
        CONTROL,
    ),
    (
        "control: link-local stops being refused, so the metadata address is a node",
        CONTROL, ADDR,
        "    if address.is_link_local:",
        "    if False:",
        CONTROL,
    ),
    (
        "control: any scheme is a node's address",
        CONTROL, ADDR,
        "    if parts.scheme.lower() not in _ALLOWED_SCHEMES:",
        "    if False:",
        CONTROL,
    ),
    (
        "control: enrollment stops checking the address it records",
        CONTROL, NODES,
        "    reason = node_address.rejection(announced_url) if announced_url else None\n"
        "    if reason is not None:",
        "    reason = None\n    if reason is not None:",
        CONTROL,
    ),
    (
        # The address check has to run BEFORE the join token is
        # consumed, or a malformed enrollment burns an operator-minted
        # single-use credential.
        #
        # **The first version of this sabotage was a no-op and escaped
        # for that reason**: it inserted a dead `reason = None` *after*
        # the real check, which still ran and still raised. A sabotage
        # has to produce the defect, not mention it -- so this one
        # genuinely swaps the two blocks. Since per-node keys a locked-
        # root check sits between them; it moves with the consume.
        "control: the address is checked after the join token is spent",
        CONTROL, NODES,
        _ENROLL_ADDRESS_CHECK + "\n\n" + _ENROLL_LOCK_AND_CONSUME,
        _ENROLL_LOCK_AND_CONSUME + "\n\n" + _ENROLL_ADDRESS_CHECK,
        CONTROL,
    ),
    (
        "agent: the proxy dials whatever the registry holds",
        AGENT, PROXY,
        "    unusable = not_a_node_address(url)\n    if unusable is not None:",
        "    unusable = None\n    if unusable is not None:",
        AGENT,
    ),
    (
        "agent: the point-of-use check stops looking at the scheme",
        AGENT, IDENT,
        '    if parts.scheme.lower() not in ("http", "https"):',
        "    if False:",
        AGENT,
    ),
    (
        "agent: the point-of-use check stops looking at link-local",
        AGENT, IDENT,
        "    if address.is_link_local:\n        return (\n"
        '            f"{host} is link-local -- not routable between hosts, and where cloud "',
        "    if False:\n        return (\n"
        '            f"{host} is link-local -- not routable between hosts, and where cloud "',
        AGENT,
    ),
    (
        # A 401 is the answer a real backend gives an anonymous probe.
        # Calling that unreachable sends the operator to check cables
        # when their backend is up and wants a key -- and it is what
        # made dropping the credential cheap, so it is load-bearing.
        "gateway: a 401 goes back to reachable: false",
        GATEWAY, ADMIN,
        "        return DriverHealth(\n            name=client.name,\n            reachable=True,\n"
        "            url=base_url,  # type: ignore[arg-type]\n            error=detail,\n        )",
        "        return DriverHealth(\n            name=client.name,\n            reachable=False,\n"
        "            url=base_url,  # type: ignore[arg-type]\n            error=detail,\n        )",
        GATEWAY,
    ),
    (
        "gateway: the status branch is removed, so a 401 is a transport failure again",
        GATEWAY, ADMIN,
        "    except httpx.HTTPStatusError as e:",
        "    except NotImplementedError as e:",
        GATEWAY,
    ),
]


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)  # progress, not one block at the end
    work = Path(tempfile.mkdtemp(prefix="r24-sabotage-"))
    mirror = work / "mirror"
    for repo in REPOS:
        shutil.copytree(
            ROOT / repo / "src", mirror / repo / "src", ignore=shutil.ignore_patterns("__pycache__")
        )
    touched = sorted({(repo, rel) for _, repo, rel, _, _, _ in SABOTAGES})
    # The in-memory copy every restore comes from, and the proof at the
    # end that the repos themselves were never written.
    originals = {(repo, rel): (ROOT / repo / rel).read_bytes() for repo, rel in touched}
    for key, data in originals.items():
        assert (mirror / key[0] / key[1]).read_bytes() == data, f"mirror of {key} differs"
    print(f"mirror in {mirror}\n")

    gates = sorted({g for *_, g in SABOTAGES})
    failures = []
    for gate in gates:
        why = imports_mirror(gate, mirror)
        if why is not None:
            failures.append(f"baseline {gate}: {why}")
            continue
        code, out = run_gate(gate, mirror)
        print(f"[baseline] {gate}: {'PASS' if code == 0 else 'FAIL'} (imports the mirror)")
        if code != 0:
            failures.append(f"baseline {gate}\n{out}")
    if failures:
        print("\nBASELINE FAILED - a sabotage result would mean nothing.")
        print("\n".join(failures))
        return 1
    print()

    caught = escaped = 0
    for label, repo, rel, old, new, gate in SABOTAGES:
        path = mirror / repo / rel
        original = originals[(repo, rel)]
        source = original.decode("utf-8")
        # The anchors are written with "\n"; a checkout may hold a file
        # with CRLF endings (node_address.py does on this box), and an
        # anchor that silently matches nothing is a sabotage never made.
        newline = "\r\n" if "\r\n" in source else "\n"
        old, new = old.replace("\n", newline), new.replace("\n", newline)
        if source.count(old) != 1:
            print(f"[ANCHOR ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        path.write_bytes(source.replace(old, new, 1).encode("utf-8"))
        try:
            code, out = run_gate(gate, mirror)
        finally:
            path.write_bytes(original)  # restore FROM THE IN-MEMORY COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}\n{out}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")

    untouched = [key for key, data in originals.items() if (ROOT / key[0] / key[1]).read_bytes() != data]
    if untouched:
        print(f"A REPO FILE CHANGED DURING THE PASS: {untouched}")
        return 1
    for gate in gates:
        code, out = run_gate(gate, mirror)
        print(f"[restored] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    shutil.rmtree(work, ignore_errors=True)
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
