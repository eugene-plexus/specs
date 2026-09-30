"""A4 probe v2 (throwaway): how mlx_lm.server behaves, measured on a macOS runner.

Answers the instrument questions the A4 acceptance run depends on:
  1. does mlx_lm.server log one line per request (so probe completions can be counted)?
  2. does /health answer 200 before the model can generate (claims 6 and 7)?
  3. what do /v1/models and a completion body carry (claim 8, and context length)?
  4. what does a client disconnect mid-stream do to the server?
  5. does a ctypes read of Metal's recommendedMaxWorkingSetSize match MLX's?
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

BIN = os.path.expanduser("~/eugene-mlx/bin/mlx_lm.server")
MODEL = sys.argv[1] if len(sys.argv) > 1 else "mlx-community/Qwen3-0.6B-4bit"


def metal_probe() -> None:
    try:
        ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        metal = ctypes.CDLL("/System/Library/Frameworks/Metal.framework/Metal")
        objc = ctypes.CDLL(ctypes.util.find_library("objc"))
        metal.MTLCreateSystemDefaultDevice.restype = ctypes.c_void_p
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value

        def send(obj, sel, restype):
            fn = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p)(address)
            return fn(obj, objc.sel_registerName(sel))

        device = metal.MTLCreateSystemDefaultDevice()
        print("metal device ptr", bool(device))
        if not device:
            return
        print("recommendedMaxWorkingSetSize", send(device, b"recommendedMaxWorkingSetSize", ctypes.c_uint64))
        print("hasUnifiedMemory", send(device, b"hasUnifiedMemory", ctypes.c_bool))
        print("currentAllocatedSize", send(device, b"currentAllocatedSize", ctypes.c_uint64))
        name = send(device, b"name", ctypes.c_void_p)
        print("name", send(name, b"UTF8String", ctypes.c_char_p))
    except Exception as e:  # noqa: BLE001
        print("metal probe raised", repr(e))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str, timeout: float = 2.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def post(url: str, body: dict, timeout: float = 30.0) -> tuple[int, str]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"content-type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main() -> None:
    metal_probe()
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    log = open("/tmp/mlx-probe.log", "w")
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        [BIN, "--model", MODEL, "--host", "127.0.0.1", "--port", str(port)],
        stdout=log, stderr=subprocess.STDOUT,
    )
    first_health = first_token = None
    health_while_not_ready = 0
    tried = 0
    while time.perf_counter() - t0 < 180 and first_token is None:
        try:
            code, _ = get(f"{base}/health", timeout=0.5)
        except Exception:  # noqa: BLE001
            code = None
        if code == 200 and first_health is None:
            first_health = time.perf_counter() - t0
        if code == 200:
            tried += 1
            try:
                c, body = post(
                    f"{base}/v1/chat/completions",
                    {"model": "default_model", "messages": [{"role": "user", "content": "ok"}],
                     "max_tokens": 1, "temperature": 0},
                    timeout=0.3,
                )
                if c == 200:
                    first_token = time.perf_counter() - t0
                    print("first completion body:", body[:600])
                else:
                    health_while_not_ready += 1
            except Exception:  # noqa: BLE001
                health_while_not_ready += 1
        time.sleep(0.01)
    print(f"first /health 200 at {first_health}, first token at {first_token}, "
          f"health-ok-but-no-token polls {health_while_not_ready}, completion attempts {tried}")
    print("/v1/models:", get(f"{base}/v1/models")[1][:1500])
    # A second completion with a public-looking alias, to see what an unknown id does.
    print("unknown id:", post(f"{base}/v1/chat/completions",
          {"model": "qwen-public-alias", "messages": [{"role": "user", "content": "ok"}], "max_tokens": 1})[:2])
    # A long stream, closed after three chunks.
    req = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=json.dumps({"model": "default_model", "stream": True, "max_tokens": 2000,
                         "messages": [{"role": "user", "content": "Count from 1 to 1000."}]}).encode(),
        headers={"content-type": "application/json"},
    )
    r = urllib.request.urlopen(req, timeout=30)
    chunks = 0
    for line in r:
        if line.startswith(b"data:"):
            chunks += 1
            if chunks == 3:
                print("stream chunk sample:", line[:300])
                break
    r.close()
    t_cut = time.perf_counter()
    time.sleep(3)
    code, _ = post(f"{base}/v1/chat/completions",
                   {"model": "default_model", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 4})
    print(f"after a cut stream, next completion {code} in {time.perf_counter() - t_cut - 3:.2f}s")
    proc.terminate()
    proc.wait(timeout=30)
    log.close()
    print("---- server log ----")
    print(open("/tmp/mlx-probe.log").read()[-6000:])


if __name__ == "__main__":
    main()
