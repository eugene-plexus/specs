"""R1.3 sabotage pass: every check must fail when its defect is put back.

Run it after `r13-acceptance.sh`, and before believing either. Roadmap
§2.3; record `docs/acceptance/one-fit-path-run.md` §3.

Restores from a COPY taken before anything is touched, never
`git checkout --`: that reverts uncommitted work, which in this repo
means deleting the change under test, after which every later result
reads *caught* for the wrong reason.

Opens with a baseline — the gates pass unsabotaged — because a sabotage
that "fails" against an already-red gate proves nothing at all.

**The first entry is the finding itself.** Putting `_shape_for`'s own
by-suffix reader back is the state this slice found the repo in, and it
has to fail the route check, the agreement check and the 65-layer check
together. If it failed only one, the other two would be asserting the
fixture.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")

GATES = {
    "library": "tests/test_one_fit_path.py",
    "agent": "tests/test_context_and_slots.py",
}

# The reader `_shape_for` had before this slice, verbatim in shape: only
# `int` values, no per-layer form, only the interval hybrid.
OLD_SHAPE_FOR = '''    raw = model.gguf.metadata or {}

    def by_suffix(suffix: str) -> int | None:
        for key, value in raw.items():
            if key.endswith(f".{suffix}") and isinstance(value, int):
                return value
        return None

    blocks = by_suffix("block_count")
    interval = by_suffix("full_attention_interval")
    attention = max(blocks // interval, 1) if blocks and interval and interval > 1 else blocks

    return fit_mod.ModelShape(
        block_count=blocks,
        attention_layers=attention,
        head_count_kv=by_suffix("attention.head_count_kv"),
        key_length=by_suffix("attention.key_length"),
        value_length=by_suffix("attention.value_length"),
        embedding_length=by_suffix("embedding_length"),
        head_count=by_suffix("attention.head_count"),
        context_length=model.contextLength,
        parameters=model.parameters,
    )
'''

SABOTAGES = [
    # -- the finding ------------------------------------------------------
    (
        "library: _shape_for builds its own shape again (THE finding)",
        "library",
        "src/eugene_plexus_library/routes/guidance.py",
        "    raw = model.gguf.metadata or {}\n    kv: dict[str, object] = {}",
        OLD_SHAPE_FOR + "\n    _unreachable: dict[str, object] = {}",
        "tests/test_one_fit_path.py",
    ),
    (
        "library: the delegation drops the per-layer form",
        "library",
        "src/eugene_plexus_library/preflight.py",
        "        layers=layers,\n        per_layer_unavailable=layers is None and per_layer_dropped(meta),",
        "        layers=None,\n        per_layer_unavailable=False,",
        "tests/test_one_fit_path.py::test_the_on_disk_route_reads_the_per_layer_cache",
    ),
    (
        "library: only the interval hybrid is honoured, not layer_indices",
        "library",
        "src/eugene_plexus_library/preflight.py",
        '    indices = meta.arch_key("attention.layer_indices")\n'
        "    if isinstance(indices, list) and indices:\n        return len(indices)",
        "    pass",
        "tests/test_one_fit_path.py::test_layer_indices_is_honoured_as_well_as_the_interval",
    ),
    (
        "library: the route stops reconciling the entry's own context",
        "library",
        "src/eugene_plexus_library/routes/guidance.py",
        "    return replace(\n        shape,\n        context_length=model.contextLength or shape.context_length,\n"
        "        parameters=model.parameters,\n    )",
        "    return shape",
        "tests/test_one_fit_path.py",
    ),
    # -- the array that was silently dropped ------------------------------
    (
        # The limit was 64 and the shipped starter block counts are 32,
        # 42, 48 and **65** -- it missed by one on a model in the
        # product's own starter file.
        "library: the inline-array limit goes back to 64",
        "library",
        "src/eugene_plexus_library/formats/gguf.py",
        "_INLINE_ARRAY_LIMIT = 512",
        "_INLINE_ARRAY_LIMIT = 64",
        "tests/test_one_fit_path.py::test_a_per_layer_array_too_long_to_store_is_not_called_metadata",
    ),
    (
        "library: a dropped per-layer term is still called metadata",
        "library",
        "src/eugene_plexus_library/fit.py",
        "    elif shape.per_layer_unavailable:",
        "    elif False:",
        "tests/test_one_fit_path.py::test_a_shape_that_lost_its_per_layer_terms_says_so",
    ),
    (
        # The *detection*, not the reporting: if a stepped-over array is
        # indistinguishable from a file that never had one, the honest
        # basis above can never fire.
        "library: a stepped-over array reads as a file with no per-layer terms",
        "library",
        "src/eugene_plexus_library/preflight.py",
        "    return any(\n        f\"{arch}.{suffix}\" in meta.array_lengths and meta.arch_key(suffix) is None\n"
        "        for suffix in _PER_LAYER_KEYS\n    )",
        "    return False",
        # **Not `test_a_shape_that_lost_its_per_layer_terms_says_so`.**
        # That one builds the `ModelShape` by hand, so it asserts the
        # reporting and never calls the detection — it escaped this
        # sabotage on the first pass, which is how the gap was found.
        # The check below builds a stored entry the way a pre-fix scan
        # left one and drives `_shape_for` over it.
        "tests/test_one_fit_path.py::test_a_library_scanned_before_this_fix_stops_claiming_metadata",
    ),
    (
        # The fixture's own encoder. A bool array written as int32 is a
        # type the reader never meets in the wild, and the check would
        # be green about a case it had not produced.
        "library: the fixture writes a bool array as int32",
        "library",
        "tests/conftest.py",
        '        elif isinstance(value[0], bool):',
        "        elif False:",
        "tests/test_one_fit_path.py",
    ),
    # -- §6.3 #36, against the measurement --------------------------------
    (
        "agent: contextSize is described as per-slot again",
        "agent",
        "src/eugene_plexus_agent/engines/llama_cpp.py",
        '            "Total tokens this runtime keeps in memory, shared by its "',
        '            "Maximum tokens the model can attend to, per slot. The "',
        "tests/test_context_and_slots.py::test_context_size_is_not_described_as_per_slot",
    ),
    (
        "agent: parallelSlots claims memory multiplies again",
        "agent",
        "src/eugene_plexus_agent/engines/llama_cpp.py",
        '            "Concurrent requests this runtime serves. The slots divide "',
        '            "Concurrent requests. Raising this is the usual way to "\n'
        '            "run out of VRAM. The slots each get their own "',
        "tests/test_context_and_slots.py::test_parallel_slots_does_not_claim_memory_multiplies",
    ),
    (
        # The "obvious" fix for the contradiction, and the measurement
        # says it is wrong: `llama_context: n_ctx` is 32768 at one slot
        # and at four.
        "agent: the arithmetic is made to match the old copy (memory x slots)",
        "agent",
        "src/eugene_plexus_agent/admission.py",
        "    slots = parallel_slots or 1\n    return max(context_length // slots, 1) if slots > 1 else context_length",
        "    slots = parallel_slots or 1\n    return context_length * slots",
        "tests/test_context_and_slots.py::test_the_per_request_window_is_the_context_divided_by_the_slots",
    ),
    (
        "agent: the divided window is computed and never said",
        "agent",
        "src/eugene_plexus_agent/admission.py",
        '    slot_text = f" {slot_note[0].upper()}{slot_note[1:]}." if slot_note else ""',
        '    slot_text = ""',
        "tests/test_context_and_slots.py::test_the_reason_carries_it_end_to_end",
    ),
    (
        "agent: every single-slot launch gets the division sentence",
        "agent",
        "src/eugene_plexus_agent/admission.py",
        "    if context_length is None or not parallel_slots or parallel_slots < 2:\n        return None",
        "    if context_length is None:\n        return None",
        "tests/test_context_and_slots.py::test_one_slot_says_nothing_extra",
    ),
]


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


def main() -> int:
    backup = Path(tempfile.mkdtemp(prefix="r13-sabotage-"))
    touched = {(repo, rel) for _, repo, rel, _, _, _ in SABOTAGES}
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
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run(repo, selector)
        finally:
            shutil.copy2(backup / repo / rel, path)  # restore FROM THE COPY
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
