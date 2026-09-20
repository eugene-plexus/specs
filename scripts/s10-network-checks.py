"""Exercise the shared line cap with competing transfers, not one idle socket."""
import asyncio
import importlib.util
from pathlib import Path
import time

spec = importlib.util.spec_from_file_location("network", Path(__file__).with_name("s10-network.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


async def check():
    line = module.Line(8_000_000)  # 1 MB/s; short enough for every CI run.
    started = time.monotonic()
    async def transfer(host):
        for _ in range(8):
            await line.deliver(65536, host)
    await asyncio.gather(transfer("first"), transfer("second"))
    elapsed = time.monotonic() - started
    assert line.bytes == 1048576
    assert line.hosts == {"first": 524288, "second": 524288}
    assert elapsed >= (line.bytes - line.burst) / line.rate - .01, elapsed
    assert elapsed < 3, f"unexpected pacing delay: {elapsed}"
    print(f"PASS: two transfers share one line cap ({elapsed:.3f}s, 1 MiB)")


asyncio.run(check())
