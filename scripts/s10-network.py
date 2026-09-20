"""Loopback CONNECT proxy with an aggregate downstream cap; TLS stays end to end.

Only the acceptance processes use this proxy. No system network setting changes.
The cap includes TLS overhead and applies across simultaneous downloads. A fresh
bucket per connection would let parallel transfers evade the line-rate condition.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time


class Line:
    def __init__(self, bits_per_second):
        self.rate = bits_per_second / 8
        self.burst = 256 * 1024
        self.next = 0.0
        self.bytes = 0
        self.hosts = {}
        self.started = time.monotonic()
        self.lock = asyncio.Lock()

    async def deliver(self, count, host):
        async with self.lock:
            # Credit up to 256 KiB of idle time. Sleeping for every 64 KiB
            # packet rounds 5ms waits to ~16ms on Windows and accidentally
            # emulates a 30-Mbit line. A bounded token bucket preserves the
            # 100-Mbit sustained cap without that timer-resolution artifact.
            self.next = max(self.next, time.monotonic() - self.burst / self.rate) + count / self.rate
            due = self.next
        await asyncio.sleep(max(0, due - time.monotonic()))
        self.bytes += count
        self.hosts[host] = self.hosts.get(host, 0) + count


async def run(port, root, mbps):
    line = Line(mbps * 1_000_000)

    async def connection(reader, writer):
        upstream = None
        tasks = []
        try:
            headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
            method, destination, _ = headers.split(b"\r\n", 1)[0].decode("ascii").split()
            if method != "CONNECT":
                writer.write(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            host, remote_port = destination.rsplit(":", 1)
            if int(remote_port) != 443:
                raise ValueError("only HTTPS upstreams are accepted")
            remote, upstream = await asyncio.wait_for(asyncio.open_connection(host, 443), 30)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

            async def pipe(source, target, downstream=False):
                while chunk := await source.read(65536):
                    if downstream:
                        await line.deliver(len(chunk), host)
                    target.write(chunk)
                    await target.drain()

            tasks = [asyncio.create_task(pipe(reader, upstream)),
                     asyncio.create_task(pipe(remote, writer, True))]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            if upstream:
                upstream.close()

    server = await asyncio.start_server(connection, "127.0.0.1", port)
    (root / "proxy-ready").touch()
    async with server:
        while not (root / "stop-proxy").exists():
            (root / "network.json").write_text(json.dumps({
                "capMbps": mbps, "burstBytes": line.burst, "downstreamBytes": line.bytes,
                "elapsedSeconds": time.monotonic() - line.started, "hosts": line.hosts,
            }, indent=2), encoding="utf-8")
            await asyncio.sleep(.5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mbps", type=float, default=100)
    args = parser.parse_args()
    assert args.mbps > 0
    asyncio.run(run(args.port, args.output, args.mbps))
