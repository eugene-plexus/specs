"""R3.2 sabotage pass: the reservation ledger and the context-scaled fallback.

Roadmap §4 item 2, review §6.2 #19. Restores from a COPY, never
`git checkout --`, and opens with a baseline.

**The first three entries put the finding itself back**, one per half of
it: the flat allowance that made the context control inert, the
reservations dropped on the floor at the one `check_admission` call
site, and the device pick that goes back to reading the emptiest-looking
card rather than the one with room left.

The rest take the fix apart one rule at a time -- the dry run that must
not reserve, the forced launch that must, `copying` on both the blocker
list and the pending set, the reconcile sweep, the TTL, the
self-exclusion and the subtraction handed to the library.

**Three entries were written and then deleted rather than recorded as
escapes, and all three named a SECOND MECHANISM rather than a weak
check.** Explicit releases on stop and delete: both escaped because the
reconcile sweep already covers them -- it runs at every read, and both
routes change the status it reads. A default context inside
`file_size_requirement`: it escaped because its one caller settles on a
number first, so the helper's own fallback is unreachable and was a
place for two assumptions to disagree unseen. In each case the answer
was one mechanism instead of two, and the code lost the spare.

The gate is the WHOLE agent suite across three files, not just the new
one: two of the three modules under test are read by every runtime route
there is, and the two tests in `test_admission.py` that asserted the
flat tenth are the ones a careless revert would put back.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")
AGENT = "agent"
ADMISSION = "src/eugene_plexus_agent/admission.py"
LEDGER = "src/eugene_plexus_agent/reservations.py"
ROUTES = "src/eugene_plexus_agent/routes/runtimes.py"
FILES = (ADMISSION, LEDGER, ROUTES)

UNIT_TIMEOUT = 600


def run_gate() -> tuple[int, str]:
    try:
        py = ROOT / AGENT / ".venv" / "Scripts" / "python.exe"
        done = subprocess.run(
            [
                str(py),
                "-m",
                "pytest",
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
                "tests/test_admission_reserves.py",
                "tests/test_admission.py",
                "tests/test_lifecycle_routes.py",
                "tests/test_storage_separation.py",
                "tests/test_runtimes.py",
            ],
            cwd=ROOT / AGENT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=UNIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:]


# (label, file, old, new)
SABOTAGES: list[tuple[str, str, str, str]] = [
    (
        "THE FINDING, the fallback: the KV term stops moving with the context",
        ADMISSION,
        "    kv = size_bytes * ESTIMATED_KV_FRACTION * "
        "(context_length / ESTIMATED_KV_BASELINE_CONTEXT)",
        "    kv = size_bytes * 0.10",
    ),
    (
        "THE FINDING, the ledger: admission is handed the promises and ignores them",
        ADMISSION,
        "    reserved = held_bytes(reservations, device_index=device.index, exclude=spec.name)",
        "    reserved = 0",
    ),
    (
        "THE FINDING, the routes: a launch that is scheduled promises nothing",
        ROUTES,
        "    if admission is None or not admission.requiredBytes:\n        return",
        "    if admission is None or not admission.requiredBytes:\n        return\n    return",
    ),
    (
        "the budget goes back to the card's own reading, so the verdict ignores the promise",
        ADMISSION,
        "    budget = max(0, free - reserved) if free is not None else None",
        "    budget = free",
    ),
    (
        "the device pick goes back to emptiest-looking, so a second launch picks a spoken-for card",
        ADMISSION,
        "    device = max(targets, key=lambda d: (_spare(d), -(d.index or 0)))",
        "    device = max(targets, key=lambda d: (d.memoryFreeBytes or -1, -(d.index or 0)))",
    ),
    (
        "the library is scored against the whole card again",
        ADMISSION,
        "            vram_bytes=budget,",
        "            vram_bytes=free,",
    ),
    (
        "A DRY RUN RESERVES: the admission endpoint starts promising memory",
        ROUTES,
        "    return await _admission_for(request, body)\n\n\n@router.post(\n    \"/v1/runtimes\",",
        "    admission = await _admission_for(request, body)\n    _reserve(request, body, admission)\n"
        "    return admission\n\n\n@router.post(\n    \"/v1/runtimes\",",
    ),
    (
        "a forced launch stops being measured, so it is invisible to the next admission",
        ROUTES,
        "    admission: Admission | None = None\n    if body.autoStart is not False:\n"
        "        admission = await _admission_for(request, body)\n"
        "        if admission.decision is AdmissionDecision.refuse and not force:",
        "    admission: Admission | None = None\n    if body.autoStart is not False and not force:\n"
        "        admission = await _admission_for(request, body)\n"
        "        if admission.decision is AdmissionDecision.refuse:",
    ),
    (
        "a forced START stops being measured",
        ROUTES,
        "    if not already:\n        # Where a runtime declared with `autoStart: false` meets",
        "    if not already and not force:\n        # Where a runtime declared with `autoStart: false` meets",
    ),
    (
        "`copying` leaves the pending set, so a copy's promise is swept away at once",
        ADMISSION,
        "PENDING_STATUSES = frozenset({RuntimeStatus.copying, RuntimeStatus.starting, "
        "RuntimeStatus.loading})",
        "PENDING_STATUSES = frozenset({RuntimeStatus.starting, RuntimeStatus.loading})",
    ),
    (
        "`copying` leaves the blocker list, so nothing says what is holding the card",
        ADMISSION,
        "        RuntimeStatus.copying,\n        RuntimeStatus.starting,\n        RuntimeStatus.loading,\n        RuntimeStatus.ready,",
        "        RuntimeStatus.starting,\n        RuntimeStatus.loading,\n        RuntimeStatus.ready,",
    ),
    (
        "`ready` joins the pending set, so a loaded model is counted twice",
        ADMISSION,
        "PENDING_STATUSES = frozenset({RuntimeStatus.copying, RuntimeStatus.starting, "
        "RuntimeStatus.loading})",
        "PENDING_STATUSES = frozenset({RuntimeStatus.copying, RuntimeStatus.starting, "
        "RuntimeStatus.loading, RuntimeStatus.ready})",
    ),
    (
        "reconcile keeps everything, so a promise outlives the launch it describes",
        ROUTES,
        "    ledger.reconcile(other.name for other, status in observed if status in PENDING_STATUSES)",
        "    ledger.reconcile(other.name for other, status in observed)",
    ),
    (
        "the TTL never fires, so an abandoned launch strands the card for the life of the process",
        LEDGER,
        "        cutoff = self._clock() - self._ttl",
        "        cutoff = self._clock() - self._ttl * 1e9",
    ),
    (
        "a runtime's own promise is counted against it, so every restart is refused",
        LEDGER,
        "        if exclude is not None and reservation.runtime == exclude:\n            continue",
        "        if False:\n            continue",
    ),
    (
        "a promise with no device stops counting anywhere",
        LEDGER,
        "        if reservation.device_index is not None and reservation.device_index != device_index:",
        "        if reservation.device_index != device_index:",
    ),
    (
        "reserving twice stacks, so a re-measured launch is counted two or three times",
        LEDGER,
        "        self._held[runtime] = Reservation(",
        "        self._held[runtime + str(self._clock())] = Reservation(",
    ),
    (
        "a zero-byte promise is recorded, so the ledger carries entries that promise nothing",
        LEDGER,
        "        if size_bytes <= 0:",
        "        if size_bytes < 0:",
    ),
    (
        "the reason stops naming the reservation, so a card reads 24 GiB free and refuses",
        ADMISSION,
        '        f" {_gib(reserved)} of it is reserved for a launch already under way, "\n        f"leaving {_gib(budget)}."',
        '        ""',
    ),
    (
        "the refusal stops offering waiting as the remedy",
        ADMISSION,
        '        waiting = "Wait for the launch already under way, " if reserved else ""',
        '        waiting = ""',
    ),
    (
        "the assumed context is not reported, so the number that decided the verdict is invisible",
        ADMISSION,
        "            context_length = context_length or ASSUMED_CONTEXT_LENGTH\n            required = file_size_requirement(size, context_length)",
        "            required = file_size_requirement(size, context_length)",
    ),
    (
        "reservedBytes never reaches the wire",
        ADMISSION,
        "        reservedBytes=reserved or None,",
        "        reservedBytes=None,",
    ),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    backup = Path(tempfile.mkdtemp(prefix="r32-sabotage-"))
    for relative in FILES:
        destination = backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / AGENT / relative, destination)
    print(f"copy in {backup}\n")

    code, out = run_gate()
    print(f"[baseline] {AGENT}: {'PASS' if code == 0 else 'FAIL'}")
    if code != 0:
        print(out)
        return 1
    print()

    caught = escaped = 0
    for label, relative, old, new in SABOTAGES:
        path = ROOT / AGENT / relative
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run_gate()
        finally:
            shutil.copy2(backup / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")
    code, out = run_gate()
    print(f"[restored] {AGENT}: {'PASS' if code == 0 else 'FAIL'}")
    if code != 0:
        print(out)
        return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
