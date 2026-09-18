"""R2.4 sabotage pass: every check must fail when its defect is put back.

Run it after `r24-acceptance.sh`, and before believing either. Roadmap
§3.4; record `docs/acceptance/proportionate-credentials-run.md` §5.

Restores from a COPY taken before anything is touched, never
`git checkout --`: that reverts uncommitted work, which in this repo
means deleting the change under test, after which every later result
reads *caught* for the wrong reason.

Opens with a baseline -- all four gates pass unsabotaged -- because a
sabotage that "fails" against an already-red gate proves nothing.

**The first three entries are the findings themselves**, each put back
the way the repo actually had it, and each driven against the LIVE
processes: a real trust root handing its snapshot to a real
`service:gateway` token, a real root recording a correctly signed
announcement of the cloud metadata address, and a real gateway putting
a real service token on a real socket. The entries after them take each
fix apart one property at a time, on whichever gate can see them.

Four gates, because R2.4 is three repos plus the run that joins them.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")
SPECS = ROOT / "specs"

DEPS = "src/eugene_plexus_control/dependencies.py"
SEC = "src/eugene_plexus_control/security.py"
ADDR = "src/eugene_plexus_control/node_address.py"
NODES = "src/eugene_plexus_control/routes/nodes.py"
IDENT = "src/eugene_plexus_agent/node_identity.py"
PROXY = "src/eugene_plexus_agent/install_proxy.py"
ADMIN = "src/eugene_plexus_gateway/routes/admin.py"

CONTROL = "control"
AGENT = "agent"
GATEWAY = "gateway"
LIVE = "live"

GATE_FILES = {
    CONTROL: ["tests/test_auth.py", "tests/test_node_address.py", "tests/test_nodes.py"],
    AGENT: ["tests/test_install_wide_proxy.py"],
    GATEWAY: ["tests/test_admin_and_config.py"],
}


def run_gate(gate: str) -> tuple[int, str]:
    if gate in GATE_FILES:
        py = ROOT / gate / ".venv" / "Scripts" / "python.exe"
        done = subprocess.run(
            [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
             *GATE_FILES[gate]],
            cwd=ROOT / gate,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
    else:
        done = subprocess.run(
            ["bash", str(SPECS / "scripts" / "r24-acceptance.sh")],
            cwd=SPECS,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
    return done.returncode, (done.stdout or "")[-2500:] + (done.stderr or "")[-800:]


SABOTAGES: list[tuple[str, str, str, str, str, str]] = [
    # ---- the findings, put back, against the live processes ----------
    (
        "control: the replication surface takes any service token again (#12, THE finding)",
        CONTROL, NODES.replace("routes/nodes.py", "routes/control.py"),
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
        "gateway: the probe hands out service:gateway again (#33, THE finding)",
        GATEWAY, ADMIN,
        "        service_token=None,\n    )",
        "        service_token=request.app.state.auth_state.service_token,\n    )",
        LIVE,
    ),
    # ---- taking each fix apart, on the gate that can see it ----------
    (
        "control: the log goes back to any service token (#12's other half)",
        CONTROL, NODES.replace("routes/nodes.py", "routes/control.py"),
        "    dependencies=[Depends(require_replica)],\n)\nasync def read_log",
        "    dependencies=[Depends(require_authorized)],\n)\nasync def read_log",
        CONTROL,
    ),
    (
        # The narrow door must stay narrow. Adding `accept_any_service`
        # beside the kind list is the plausible wrong edit -- it reads
        # like a widening for safety and is the defect verbatim.
        "control: require_replica accepts any service beside the kind list",
        CONTROL, DEPS,
        "        accept_any_service=False,\n        accept_service_kinds=REPLICA_SERVICE_KINDS,",
        "        accept_any_service=True,\n        accept_service_kinds=REPLICA_SERVICE_KINDS,",
        CONTROL,
    ),
    (
        # And it must not become operator-only, which would be the other
        # plausible over-correction and would cost failover at 3am.
        "control: require_replica drops service:control, so replication needs an operator",
        CONTROL, DEPS,
        'REPLICA_SERVICE_KINDS = frozenset({"control"})',
        "REPLICA_SERVICE_KINDS = frozenset()",
        CONTROL,
    ),
    (
        "control: decode_token ignores the kind list and takes any service",
        CONTROL, SEC,
        "        is_service = aud.removeprefix(SERVICE_AUDIENCE_PREFIX) in set(accept_service_kinds)",
        "        is_service = True",
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
        # genuinely swaps the two blocks.
        "control: the address is checked after the join token is spent",
        CONTROL, NODES,
        """    reason = node_address.rejection(announced_url) if announced_url else None
    if reason is not None:
        # Checked **before** the join token is consumed: a single-use
        # credential spent on a request that was never going to be
        # recorded is an operator minting a second one for no reason.
        raise problem(
            status.HTTP_400_BAD_REQUEST,
            "Address cannot be a node",
            f"{body.url} cannot be this node's address: {reason}.",
        )

    try:
        store.consume(body.token, node_name=body.name)""",
        """    try:
        store.consume(body.token, node_name=body.name)""",
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
    backup = Path(tempfile.mkdtemp(prefix="r24-sabotage-"))
    touched = {(repo, rel) for _, repo, rel, _, _, _ in SABOTAGES}
    for repo, rel in touched:
        dst = backup / repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / repo / rel, dst)
    print(f"copies in {backup}\n")

    gates = sorted({g for *_, g in SABOTAGES})
    failures = []
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[baseline] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            failures.append(f"baseline {gate}\n{out}")
    if failures:
        print("\nBASELINE FAILED - a sabotage result would mean nothing.")
        print("\n".join(failures))
        return 1
    print()

    caught = escaped = 0
    for label, repo, rel, old, new, gate in SABOTAGES:
        path = ROOT / repo / rel
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run_gate(gate)
        finally:
            shutil.copy2(backup / repo / rel, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}\n{out}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")

    for gate in gates:
        code, out = run_gate(gate)
        print(f"[restored] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
