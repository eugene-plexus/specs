"""R1.2 sabotage pass: every check must fail when its defect is put back.

Run it after `r12-acceptance.sh`, and before believing either. Roadmap
§2.2; record `docs/acceptance/two-rules-run.md` §3.

Restores from a COPY taken before anything is touched, never
`git checkout --`: that reverts uncommitted work, which in this repo
means deleting the change under test, after which every later result
reads *caught* for the wrong reason.

Opens with a baseline — the gates pass unsabotaged — because a sabotage
that "fails" against an already-red gate proves nothing at all.

**Two of these remove a pair of guards rather than one.** R1.1's pass
learned it the hard way with a double-checked lock: disabling one half
of a redundant guard changes no behaviour, the check stays green, and it
is the sabotage that was wrong rather than the check. Here the library
validates a destination twice on purpose (once before the network, once
per file), so the sabotage that means anything removes both.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")

# The gate each repo's baseline runs.
GATES = {
    "agent": "tests/test_forwarded_peer.py",
    "control": "tests/test_forwarded_peer.py",
    "gateway": "tests/test_forwarded_peer.py",
    "library": "tests/test_download_destination_stays_in_the_root.py",
    "inference-driver": "tests/test_forwarded_peer.py",
}

SABOTAGES = [
    # -- the entrypoints ---------------------------------------------------
    (
        "agent: uvicorn trusts X-Forwarded-For from loopback again",
        "agent",
        "src/eugene_plexus_agent/__main__.py",
        "        app, host=bind_host, port=port, log_level=log_level, forwarded_allow_ips=[]",
        "        app, host=bind_host, port=port, log_level=log_level",
        "tests/test_forwarded_peer.py",
    ),
    (
        "control: uvicorn trusts X-Forwarded-For from loopback again",
        "control",
        "src/eugene_plexus_control/__main__.py",
        "        forwarded_allow_ips=[],\n    )",
        "    )",
        "tests/test_forwarded_peer.py",
    ),
    (
        "gateway: uvicorn trusts X-Forwarded-For from loopback again",
        "gateway",
        "src/eugene_plexus_gateway/__main__.py",
        "        forwarded_allow_ips=[],\n    )",
        "    )",
        "tests/test_forwarded_peer.py",
    ),
    (
        "library: uvicorn trusts X-Forwarded-For from loopback again",
        "library",
        "src/eugene_plexus_library/__main__.py",
        "        forwarded_allow_ips=[],\n    )",
        "    )",
        "tests/test_forwarded_peer.py",
    ),
    (
        "inference-driver: uvicorn trusts X-Forwarded-For from loopback again",
        "inference-driver",
        "src/eugene_plexus_inference_driver/__main__.py",
        "        forwarded_allow_ips=[],\n    )",
        "    )",
        "tests/test_forwarded_peer.py",
    ),
    # -- the rule ----------------------------------------------------------
    (
        # The one that makes a forged header worthless. Without the
        # loopback gate the header is believed from anywhere.
        "peer: the header is believed whatever the peer is",
        "agent",
        "src/eugene_plexus_agent/peer.py",
        "    if is_loopback(peer):\n        forwarded = _parsed(supplied)\n"
        "        if forwarded is not None:\n            return str(forwarded)\n    return peer",
        "    forwarded = _parsed(supplied)\n    if forwarded is not None:\n"
        "        return str(forwarded)\n    return peer",
        "tests/test_forwarded_peer.py::test_an_off_host_caller_cannot_name_its_own_bucket",
    ),
    (
        "peer: a header that is not an address is used as a bucket key",
        "agent",
        "src/eugene_plexus_agent/peer.py",
        "    if is_loopback(peer):\n        forwarded = _parsed(supplied)\n"
        "        if forwarded is not None:\n            return str(forwarded)\n    return peer",
        "    if is_loopback(peer) and supplied:\n        return supplied\n    return peer",
        "tests/test_forwarded_peer.py::test_the_header_is_read_only_where_it_can_only_be_ours",
    ),
    (
        # `"testclient"`, a Unix socket peer, anything unparseable. If
        # unknown counts as local, the header is believed from a caller
        # we cannot see.
        "peer: an unparseable peer counts as loopback",
        "agent",
        "src/eugene_plexus_agent/peer.py",
        "    parsed = _parsed(host)\n    if parsed is None:\n        return False",
        "    parsed = _parsed(host)\n    if parsed is None:\n        return True",
        "tests/test_forwarded_peer.py::test_the_header_is_read_only_where_it_can_only_be_ours",
    ),
    # -- the proxy ---------------------------------------------------------
    (
        "proxy: the forwarding headers are forwarded verbatim again",
        "agent",
        "src/eugene_plexus_agent/routes/proxy.py",
        "    | peer.FORWARDING_HEADERS\n)",
        ")",
        "tests/test_forwarded_peer.py::test_the_proxy_strips_every_forwarding_header",
    ),
    (
        # The laundering case: strip the header and it is evidence,
        # forward it and the forgery has just moved one header left.
        "proxy: our own header survives the hop",
        "agent",
        "src/eugene_plexus_agent/routes/proxy.py",
        "        peer.PEER_HEADER,\n    }",
        "    }",
        # **The strip and the overwrite are two guards, and only this
        # check names the case the strip covers alone** -- a request
        # whose transport reports no client, where the overwrite does
        # not run. The first version of this sabotage escaped every
        # other check in the file, which is how the gap was found.
        "tests/test_forwarded_peer.py::test_a_request_with_no_peer_cannot_launder_our_header",
    ),
    (
        "proxy: nobody says who the request is from",
        "agent",
        "src/eugene_plexus_agent/routes/proxy.py",
        "    if origin:\n        headers[peer.PEER_HEADER] = origin",
        "    del origin",
        "tests/test_forwarded_peer.py::test_the_proxy_says_who_it_is_forwarding_for",
    ),
    (
        "proxy: a second hop relabels the caller as loopback",
        "agent",
        "src/eugene_plexus_agent/routes/proxy.py",
        "    origin = peer.peer_of(\n        request.client.host if request.client else None,\n"
        "        request.headers.get(peer.PEER_HEADER),\n    )",
        "    origin = request.client.host if request.client else None",
        "tests/test_forwarded_peer.py::test_the_proxy_carries_the_original_peer_through_a_second_hop",
    ),
    # -- the login routes --------------------------------------------------
    (
        "agent login: keyed on the socket again, so every browser shares one bucket",
        "agent",
        "src/eugene_plexus_agent/routes/auth.py",
        '    remote = (\n        peer.peer_of(\n'
        '            request.client.host if request.client else None,\n'
        '            request.headers.get(peer.PEER_HEADER),\n'
        '        )\n        or "unknown"\n    )',
        '    remote = request.client.host if request.client else "unknown"',
        "tests/test_forwarded_peer.py::test_our_own_header_does_separate_the_buckets",
    ),
    (
        "control login: keyed on the socket again",
        "control",
        "src/eugene_plexus_control/routes/auth.py",
        '    remote = (\n        peer.peer_of(\n'
        '            request.client.host if request.client else None,\n'
        '            request.headers.get(peer.PEER_HEADER),\n'
        '        )\n        or "unknown"\n    )',
        '    remote = request.client.host if request.client else "unknown"',
        "tests/test_forwarded_peer.py::test_our_own_header_does_separate_the_buckets",
    ),
    # -- the witness -------------------------------------------------------
    (
        "off-host witness: reads the socket, so a phone through the proxy is invisible",
        "agent",
        "src/eugene_plexus_agent/off_host.py",
        "            origin = peer.peer_of(\n                str(client[0]) if client else None,\n"
        "                peer.header_of(scope.get(\"headers\") or ()),\n            )",
        "            origin = str(client[0]) if client else None",
        "tests/test_forwarded_peer.py::test_a_browser_reaching_a_component_through_the_proxy_is_seen",
    ),
    # -- the frame headers -------------------------------------------------
    (
        "ui: the console can be framed again",
        "agent",
        "src/eugene_plexus_agent/ui_assets.py",
        "        response = await super().get_response(path, scope)\n"
        "        response.headers.update(FRAME_HEADERS)\n        return response",
        "        return await super().get_response(path, scope)",
        "tests/test_forwarded_peer.py::test_the_ui_refuses_to_be_framed",
    ),
    (
        # A header only some of `/`'s answers carry is a header an
        # attacker asks for the other of.
        "ui: only the real page carries the headers, not the degraded one",
        "agent",
        "src/eugene_plexus_agent/ui_assets.py",
        "            return HTMLResponse(\n"
        "                unavailable_page(assets), status_code=503, headers=dict(FRAME_HEADERS)\n"
        "            )",
        "            return HTMLResponse(unavailable_page(assets), status_code=503)",
        "tests/test_forwarded_peer.py::test_the_no_ui_page_refuses_to_be_framed_too",
    ),
    # -- the download destination ------------------------------------------
    (
        "library: the destination is joined unchecked again (the finding)",
        "library",
        "src/eugene_plexus_library/downloads.py",
        "    if not path_utils.is_within(candidate, root) or path_utils.same_path("
        "candidate, directory):",
        "    if False:",
        "tests/test_download_destination_stays_in_the_root.py",
    ),
    (
        # **Both guards, not one.** `start()` checks the filename before
        # the network AND resolves every entry in the loop, so removing
        # either alone changes nothing and the escape would be the
        # sabotage's fault rather than the check's.
        "library: start() stops resolving the destination, both places",
        "library",
        "src/eugene_plexus_library/downloads.py",
        "        if spec.filename:\n            resolve_file(directory=directory, root=root, name=spec.filename)",
        "        pass",
        "tests/test_download_destination_stays_in_the_root.py::"
        "test_the_manager_refuses_a_spec_that_would_leave_the_root",
    ),
    (
        "library: the check is about the spelling `..` rather than where the bytes land",
        "library",
        "src/eugene_plexus_library/downloads.py",
        "    candidate = Path(os.path.normpath((directory / name).expanduser()))",
        "    if '..' in name:\n        raise DownloadError(name, code='PathTraversal')\n"
        "    candidate = (directory / name).expanduser()",
        "tests/test_download_destination_stays_in_the_root.py::"
        "test_a_filename_that_climbs_back_inside_is_allowed",
    ),
]

# The second half of the paired library sabotage: the loop's resolve.
# Applied together with the one above, because either alone is covered.
PAIRED = {
    "library: start() stops resolving the destination, both places": (
        "library",
        "src/eugene_plexus_library/downloads.py",
        "destinationPath=str(resolve_file(directory=directory, root=root, name=name)),",
        "destinationPath=str(directory / name),",
    )
}


def run(repo: str, selector: str) -> tuple[int, str]:
    py = ROOT / repo / ".venv" / "Scripts" / "python.exe"
    done = subprocess.run(
        [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", selector],
        cwd=ROOT / repo,
        capture_output=True,
        text=True,
        timeout=900,
    )
    return done.returncode, done.stdout[-1500:] + done.stderr[-500:]


def read(path: Path) -> str:
    return io.open(path, encoding="utf-8").read()


def write(path: Path, text: str) -> None:
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)


def main() -> int:
    backup = Path(tempfile.mkdtemp(prefix="r12-sabotage-"))
    touched = {(repo, rel) for _, repo, rel, _, _, _ in SABOTAGES}
    touched |= {(repo, rel) for repo, rel, _, _ in PAIRED.values()}
    for repo, rel in touched:
        dst = backup / repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / repo / rel, dst)
    print(f"copies in {backup}\n")

    failures: list[str] = []
    for repo, gate in sorted(GATES.items()):
        code, out = run(repo, gate)
        print(f"[baseline] {repo}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            failures.append(f"baseline {repo}\n{out}")
    if failures:
        print("\nBASELINE FAILED - a sabotage result would mean nothing.")
        print("\n".join(failures))
        return 1
    print()

    caught = escaped = 0
    for label, repo, rel, old, new, selector in SABOTAGES:
        path = ROOT / repo / rel
        source = read(path)
        if source.count(old) != 1:
            print(f"[SKIP] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        write(path, source.replace(old, new, 1))
        pair = PAIRED.get(label)
        if pair is not None:
            pair_repo, pair_rel, pair_old, pair_new = pair
            pair_path = ROOT / pair_repo / pair_rel
            pair_source = read(pair_path)
            if pair_source.count(pair_old) != 1:
                print(f"[SKIP] {label}: paired anchor matched {pair_source.count(pair_old)} times")
                shutil.copy2(backup / repo / rel, path)
                escaped += 1
                continue
            write(pair_path, pair_source.replace(pair_old, pair_new, 1))
        try:
            code, out = run(repo, selector)
        finally:
            for repo_, rel_ in touched:
                shutil.copy2(backup / repo_ / rel_, ROOT / repo_ / rel_)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}\n{out}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")

    for repo, gate in sorted(GATES.items()):
        code, out = run(repo, gate)
        print(f"[restored] {repo}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
