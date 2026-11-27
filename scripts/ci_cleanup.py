"""Dispose of owned CI fixtures after short Windows sharing violations."""

import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


def cleanup(directory: tempfile.TemporaryDirectory, owned: Path) -> None:
    deadline = time.perf_counter() + 10
    reported = False
    while True:
        # Recheck the exact owned target before every recursive removal.
        if Path(directory.name).resolve() != owned:
            raise RuntimeError("Temporary directory cleanup target changed")
        try:
            directory.cleanup()
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) != 32:
                raise
            if not reported:
                print(
                    f"Waiting for the test directory to be released: {error}",
                    flush=True,
                )
                reported = True
            if time.perf_counter() >= deadline:
                raise
            time.sleep(0.25)


@contextmanager
def temporary_directory(*, prefix: str, dir=None):
    # Only the guarded explicit cleanup may remove this directory, including
    # when cleanup refuses a changed target or fails on a persistent lock.
    directory = tempfile.TemporaryDirectory(prefix=prefix, dir=dir, delete=False)
    owned = Path(directory.name).resolve()
    try:
        yield str(owned)
    finally:
        cleanup(directory, owned)
