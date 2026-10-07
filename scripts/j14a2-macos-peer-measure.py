"""J14a.2 measurement (macOS): what can an unprivileged process learn about the
account at the far end of a loopback TCP connection to it?

The per-user agent's key page must serve only the account it runs as
(`person-held-keys.md` §12, J14a.2). Linux answers from `/proc/net/tcp`
(each socket's uid, readable by anyone); Windows from the connection table
and the process's token. macOS has neither, so this measures what it has, as
the user the runner logs in as, for one connection from that user and one
from a second account made for the run (`sudo` is used only to make it and
to run its client):

- `netstat -anv -p tcp`: does a row for the other account's socket show,
  and with which pid?
- `lsof -nP -iTCP`: whose sockets does an unprivileged lsof list?
- `ps -o uid= -p <pid>`: the uid of a pid found above;
- `sysctl net.inet.tcp.pcblist_n`, read with ctypes: does each socket
  record carry the owner's uid (`xsocket_n.so_uid`), unprivileged?

Prints one JSON document. Usage (on a macOS runner):

    python3 scripts/j14a2-macos-peer-measure.py --other eptest2
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
import platform
import socket
import struct
import subprocess
import threading
import time

CLIENT = "import socket,sys,time;c=socket.create_connection(('127.0.0.1',int(sys.argv[1])));time.sleep(3);c.close()"


def run(*argv: str) -> dict[str, object]:
    done = subprocess.run(list(argv), capture_output=True, text=True, timeout=60)
    return {"code": done.returncode, "out": done.stdout, "err": done.stderr[-2000:]}


def netstat_rows(client_port: int, server_port: int) -> dict[str, object]:
    done = run("netstat", "-anv", "-p", "tcp")
    lines = str(done["out"]).splitlines()
    header = [line for line in lines if "Proto" in line][:1]
    rows = [
        line
        for line in lines
        if f"127.0.0.1.{client_port} " in line and f"127.0.0.1.{server_port} " in line
    ]
    return {"code": done["code"], "header": header, "rows": rows, "err": done["err"]}


def lsof_rows(port: int) -> dict[str, object]:
    done = run("lsof", "-nP", f"-iTCP:{port}", "-Fpuc")
    return done


def pcblist_uids(client_port: int, server_port: int) -> dict[str, object]:
    """Walk `net.inet.tcp.pcblist_n` (xnu bsd/netinet/in_pcblist.c): records,
    each `u_int32 len, u_int32 kind`, padded to 8 bytes. XSO_SOCKET (0x001)
    carries `xsocket_n`; XSO_INPCB (0x010) carries `xinpcb_n`, whose ports
    are at a fixed offset. Report the socket record's uid for a pcb whose
    ports match."""
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    name = b"net.inet.tcp.pcblist_n"
    size = ctypes.c_size_t(0)
    if libc.sysctlbyname(name, None, ctypes.byref(size), None, 0) != 0:
        return {"error": f"size errno {ctypes.get_errno()}"}
    buf = ctypes.create_string_buffer(size.value + 65536)
    size = ctypes.c_size_t(len(buf))
    if libc.sysctlbyname(name, buf, ctypes.byref(size), None, 0) != 0:
        return {"error": f"read errno {ctypes.get_errno()}"}
    data = buf.raw[: size.value]
    first_len = struct.unpack_from("<I", data, 0)[0]  # struct xinpgen
    offset = (first_len + 7) & ~7
    records: list[tuple[int, bytes]] = []
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        if length == 0:
            break
        records.append((kind, data[offset : offset + length]))
        offset += (length + 7) & ~7
    # Group: each pcb is a run of records starting with XSO_SOCKET... ending
    # with XSO_TCPCB. Find the inpcb whose lport/fport match, then its socket.
    found = []
    group: list[tuple[int, bytes]] = []
    for kind, rec in records:
        group.append((kind, rec))
        if kind == 0x020:  # XSO_TCPCB closes a group
            sock = next((r for k, r in group if k == 0x001), None)
            inp = next((r for k, r in group if k == 0x010), None)
            group_kinds, group = group, []
            if sock is None or inp is None:
                continue
            # xinpcb_n: len, kind, u_int64 xi_inpp, then u_short inp_fport,
            # inp_lport (network order). Searched, not assumed: the first
            # adjacent pair of the two ports in the record's head.
            pair = None
            for at in range(8, 64, 2):
                fport, lport = struct.unpack_from(">HH", inp, at)
                if {fport, lport} == {client_port, server_port}:
                    pair = (at, fport, lport)
                    break
            if pair is not None:
                _at, fport, lport = pair
                # xsocket_n: len, kind, u_int64 xso_so, short so_type,
                # u_int32 so_options, short so_linger, short so_state,
                # u_int64 so_pcb, int xso_protocol, int xso_family,
                # short so_qlen, so_incqlen, so_qlimit, so_timeo,
                # u_short so_error, pid_t so_pgid, u_int32 so_oobmark,
                # uid_t so_uid, pid_t so_last_pid, pid_t so_e_pid.
                # The offsets are read from the struct as compiled, so
                # report the raw words too and let the reader check.
                words = struct.unpack_from("<" + "I" * (len(sock) // 4), sock)
                found.append({"lport": lport, "fport": fport, "portsAt": _at,
                              "socketWords": words, "socketLen": len(sock),
                              "inpcbLen": len(inp), "inpcbHex": inp[:160].hex(),
                              "kinds": [k for k, _r in group_kinds]})
    return {"records": len(records), "matches": found}


def measure(other: str | None) -> dict[str, object]:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    port = server.getsockname()[1]
    result: dict[str, object] = {
        "macos": platform.mac_ver()[0],
        "machine": platform.machine(),
        "uid": os.getuid(),
        "serverPort": port,
    }

    def one(label: str, argv: list[str]) -> None:
        client = subprocess.Popen([*argv, "python3", "-c", CLIENT, str(port)])
        conn, addr = server.accept()
        time.sleep(0.5)
        client_port = addr[1]
        seen: dict[str, object] = {"clientPort": client_port, "clientPid": client.pid}
        seen["netstat"] = netstat_rows(client_port, port)
        seen["lsof"] = lsof_rows(client_port)
        pids = set()
        for row in seen["netstat"]["rows"]:  # type: ignore[index]
            for part in str(row).split():
                if ":" in part and part.split(":")[-1].isdigit():
                    pids.add(part.split(":")[-1])
                elif part.isdigit() and len(part) > 2:
                    pids.add(part)
        seen["psUid"] = {pid: run("ps", "-o", "uid=,user=,comm=", "-p", pid)["out"] for pid in sorted(pids)}
        try:
            seen["pcblist"] = pcblist_uids(client_port, port)
        except Exception as exc:  # noqa: BLE001 - reported
            seen["pcblist"] = {"error": repr(exc)}
        result[label] = seen
        client.wait()
        conn.close()

    one("self", [])
    if other:
        uid = run("id", "-u", other)["out"]
        result["otherUid"] = str(uid).strip()
        one("other", ["sudo", "-n", "-u", other])
    server.close()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--other")
    args = parser.parse_args()
    print(json.dumps(measure(args.other), indent=1))
    return 0


if __name__ == "__main__":
    threading.stack_size(0)
    raise SystemExit(main())
