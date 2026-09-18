"""R2.3 sabotage pass: every check must fail when its defect is put back.

Run it after `r23-acceptance.sh`, and before believing either. Roadmap
§3.3; record `docs/acceptance/unseen-card-run.md` §5.

Restores from a COPY taken before anything is touched, never
`git checkout --`: that reverts uncommitted work, which in this repo
means deleting the change under test, after which every later result
reads *caught* for the wrong reason.

Opens with a baseline — all four gates pass unsabotaged — because a
sabotage that "fails" against an already-red gate proves nothing.

**The first four entries are the findings themselves**, each put back
the way the repo actually had it, and each driven against the LIVE
processes rather than only the unit gates: a real agent choosing a real
asset variant off a real upstream release, and a real library answering
`GET /v1/catalogue/starter`. The entries after them take each fix apart
one property at a time, on whichever gate can see them.

Four gates, because R2.3 is three components and a browser type: the
agent's detector, the library's verdict, the UI's badge, and the live
run that joins them.
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

HOST = "src/eugene_plexus_agent/engines/host.py"
LLAMA = "src/eugene_plexus_agent/engines/llama_cpp.py"
HW = "src/eugene_plexus_library/hardware.py"
FIT = "src/eugene_plexus_library/fit.py"
STARTER = "src/eugene_plexus_library/starter.py"
BADGE = "src/components/FitBadge.tsx"

AGENT = "agent"
LIBRARY = "library"
UI = "ui"
LIVE = "live"


def run_gate(gate: str) -> tuple[int, str]:
    """Run one gate.

    **Every child is decoded as UTF-8 explicitly.** vitest writes check
    marks; Python's default on Windows is cp1252, and the reader thread
    raised `UnicodeDecodeError`, which this runner then reported as a red
    gate for a green suite. Same family as R2.2's finding #34, one layer
    over: a decoder guessing at what a child process wrote.
    """
    if gate in (AGENT, LIBRARY):
        py = ROOT / gate / ".venv" / "Scripts" / "python.exe"
        done = subprocess.run(
            [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
             "tests/test_a_card_we_cannot_see.py"],
            cwd=ROOT / gate, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
        )
    elif gate == UI:
        done = subprocess.run(
            # **Through bash, not through cmd.** Under `cmd /c`, vitest
            # comes back with *"Vitest failed to find the current
            # suite"* from its own setup file and reports `no tests` --
            # measured, and it is an environment difference rather than
            # anything about the test. The same command from bash is
            # green. A runner that invokes a gate differently from the
            # way a person does is a runner reporting on something else.
            ["bash", "-lc", "cd /d/py/eugene-plexus/ui && "
             "npx vitest run src/components/FitBadge.unknown.test.tsx"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
        )
    else:
        done = subprocess.run(
            ["bash", str(SPECS / "scripts" / "r23-acceptance.sh")],
            cwd=SPECS, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
        )
    return done.returncode, (done.stdout or "")[-2500:] + (done.stderr or "")[-800:]


SABOTAGES: list[tuple[str, str, str, str, str, str]] = [
    # ---- the findings, put back, against the live processes ----------
    (
        "library: a card of unknown size takes the no-accelerator branch again "
        "(#28, THE finding)",
        "library", FIT,
        """    if card_of_unknown_size(budget) and not budget.unifiedMemory:
        # No comparison can be made, including a favourable one: a
        # `fits` computed against a number we do not have is right by
        # luck, and luck is not a verdict.
        return FitVerdict.unknown
""",
        "",
        LIVE,
    ),
    (
        "agent: a wedged nvidia-smi is a working one again (#29, THE finding)",
        "agent", HOST,
        """    if proc.returncode != 0:
        log.warning(
            "%s is installed and exited %d: %s. Treating this machine as though that "
            "accelerator is not here, because a build for a driver that is not working "
            "fails at load rather than at install.",
            argv[0],
            proc.returncode,
            (proc.stderr or proc.stdout or "").strip()[:200],
        )
        return Probe.FAILED
""",
        "",
        LIVE,
    ),
    (
        "agent: Windows has no fallback accelerator again (#11, THE finding)",
        "agent", HOST,
        """    if os_kind is Os.windows:
        return _windows_fallback_accelerator(), None

""",
        "",
        LIVE,
    ),
    (
        # **Gated by the unit file, not the live run, and the escape that
        # said so is worth keeping.** The first shape of this sabotage
        # (`and not gpus`) stopped expressing anything once the warning
        # moved into `_run`: the sentence is appended where the probe
        # fails, so suppressing the tie-breaker changes no output. And
        # the live run cannot reach the state this one is about -- its
        # Intel stub supplies a card, so the no-GPU branch never runs.
        "library: a wedged tool still gets the `not on PATH` sentence (#29)",
        "library", HW,
        """    wedged = any("exited non-zero" in w for w in warnings)""",
        """    wedged = False""",
        LIBRARY,
    ),
    (
        "agent: the probe runs a bare name again, so System32 wins over PATH",
        "agent", HOST,
        """        proc = subprocess.run(
            [exe, *argv[1:]],""",
        """        proc = subprocess.run(
            argv,""",
        LIVE,
    ),
    (
        "agent: the vulkan variant maps to the CPU build (#11)",
        "agent", LLAMA,
        """        if accelerator is Accelerator.vulkan:""",
        """        if False:""",
        LIVE,
    ),
    # ---- taking each fix apart, on the gate that can see it ----------
    (
        "library: `card_of_unknown_size` asks about free rather than about a card",
        "library", FIT,
        "    return (budget.gpuCount or 0) > 0 and (budget.vramTotalBytes or 0) == 0",
        "    return (budget.vramFreeBytes or 0) == 0",
        LIBRARY,
    ),
    (
        "library: the starter set inverts on `vramTotalBytes` again (#28)",
        "library", STARTER,
        "    return (budget.gpuCount or 0) == 0 and not budget.unifiedMemory",
        "    return (budget.vramTotalBytes or 0) == 0 and not budget.unifiedMemory",
        LIBRARY,
    ),
    (
        "library: a probe that fails is reported as absent",
        "library", HW,
        """        return Probe.FAILED
    return completed.stdout""",
        """        return Probe.ABSENT
    return completed.stdout""",
        LIBRARY,
    ),
    (
        "library: the unknown verdict says nothing about why",
        "library", FIT,
        """    if card_of_unknown_size(budget) and not budget.unifiedMemory:
        notes.append(""",
        """    if False:
        notes.append(""",
        LIBRARY,
    ),
    (
        "library: an unmeasurable machine gets the nothing-fits sentence again",
        "library", STARTER,
        "    if fit_mod.card_of_unknown_size(budget) and not budget.unifiedMemory:\n        cards",
        "    if False:\n        cards",
        LIBRARY,
    ),
    (
        # A machine with a GPU we could not size must not be told it has
        # none; a machine with genuinely no GPU must still get a real
        # verdict. Collapsing the two the other way is the regression
        # that reads as caution.
        "library: every CPU-only machine becomes `unknown` too",
        "library", FIT,
        "    return (budget.gpuCount or 0) > 0 and (budget.vramTotalBytes or 0) == 0",
        "    return (budget.vramTotalBytes or 0) == 0",
        LIBRARY,
    ),
    (
        # **This one escaped on the first pass and was a real
        # diagnosis.** Removing the exclusion list changed no answer,
        # because the vendor allowlist had already rejected every name
        # on it -- so the list was unreachable and is deleted. What
        # replaces the sabotage is the filter that does the work.
        "agent: any adapter with a vendor word counts, whatever it is",
        "agent", HOST,
        """        if any(vendor in lowered for vendor in _VULKAN_VENDORS):""",
        """        if True:""",
        AGENT,
    ),
    (
        "agent: ROCm is claimed on Windows without the HIP SDK",
        "agent", HOST,
        """    if platform.system().lower() == "windows":""",
        """    if False:""",
        AGENT,
    ),
    (
        "agent: the Windows probe overtakes a working nvidia-smi",
        "agent", HOST,
        """    cuda_version = _probe_cuda()
    if cuda_version is not None:
        return Accelerator.cuda, cuda_version""",
        """    if os_kind is Os.windows:
        return _windows_fallback_accelerator(), None
    cuda_version = _probe_cuda()
    if cuda_version is not None:
        return Accelerator.cuda, cuda_version""",
        AGENT,
    ),
    (
        "agent: a probe that is absent is reported as failed",
        "agent", HOST,
        """    exe = shutil.which(argv[0])
    if exe is None:
        return Probe.ABSENT""",
        """    exe = shutil.which(argv[0])
    if exe is None:
        return Probe.FAILED""",
        AGENT,
    ),
    (
        "agent: the WMI probe runs on Linux too",
        "agent", HOST,
        "    if os_kind is Os.windows:\n        return _windows_fallback_accelerator(), None",
        "    if True:\n        return _windows_fallback_accelerator(), None",
        AGENT,
    ),
    (
        "ui: an unknown verdict is dressed as a success",
        "ui", BADGE,
        """  unknown: "status-warn",""",
        """  unknown: "status-success",""",
        UI,
    ),
    (
        "ui: an unknown verdict reads as `fits`",
        "ui", BADGE,
        """  unknown: "can't tell",""",
        """  unknown: "fits",""",
        UI,
    ),
    (
        "ui: the budget line claims 0 B of GPU memory again",
        "ui", BADGE,
        "  const unmeasured = gpus > 0 && !(budget.vramTotalBytes ?? 0);",
        "  const unmeasured = false;",
        UI,
    ),
    (
        # The regression the live install run caught: answering "which
        # tool failed" by probing all three again is up to three extra
        # subprocesses per hardware read, on a request path.
        "library: the wedged tool is found by probing everything again",
        "library", HW,
        """    result = probe(argv)
    if result is Probe.FAILED and warnings is not None:""",
        """    result = probe(argv)
    if False:""",
        LIBRARY,
    ),
]


def main() -> int:
    backup = Path(tempfile.mkdtemp(prefix="r23-sabotage-"))
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
