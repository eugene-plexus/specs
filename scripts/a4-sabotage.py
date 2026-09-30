"""Sabotage pass for the A4 fixes, against the unit tests that guard them.

A4's acceptance run lives on a GitHub macOS runner
(scripts/a4-macos-acceptance.py), so it cannot be run once per sabotage
from here. Every fix it found is also guarded by a unit test in the
component that owns it, and those run anywhere: this reintroduces each
defect in turn into the component's working tree, runs that repo's A4
tests, and requires them to FAIL.

Restores are from byte copies taken before the first edit, never
`git checkout --` (feedback: sabotage-runs-restore-from-a-copy), and the
pass opens with a baseline that must pass unsabotaged.

    python scripts/a4-sabotage.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "agent"
LIBRARY = ROOT / "library"
GATEWAY = ROOT / "gateway"


def python(repo: Path) -> Path:
    windows = repo / ".venv" / "Scripts" / "python.exe"
    return windows if windows.exists() else repo / ".venv" / "bin" / "python"


TESTS = {
    AGENT: ["tests/test_a_mac_on_a_runner.py"],
    LIBRARY: ["tests/test_a_mac_on_a_runner.py"],
    GATEWAY: ["tests/test_a_sealed_root_on_one_machine.py"],
}

A_DEV = AGENT / "src/eugene_plexus_agent/engines/devices.py"
A_MLX = AGENT / "src/eugene_plexus_agent/engines/mlx.py"
L_HW = LIBRARY / "src/eugene_plexus_library/hardware.py"
L_SCAN = LIBRARY / "src/eugene_plexus_library/scanner.py"
L_ST = LIBRARY / "src/eugene_plexus_library/formats/safetensors.py"
L_PROBE = LIBRARY / "src/eugene_plexus_library/gpu_probe.py"
G_ROUTE = GATEWAY / "src/eugene_plexus_gateway/routing.py"

# (label, repo, file, old, new)
SABOTAGES: list[tuple[str, Path, Path, str, str]] = [
    (
        "agent: the Apple budget is a share of RAM again, whatever Metal says",
        AGENT,
        A_DEV,
        "        budget = device.working_set_bytes\n",
        "        budget = int((ram_total or 0) * 0.75)\n",
    ),
    (
        "agent: the fallback fraction is 75% again",
        AGENT,
        A_DEV,
        "APPLE_WIRED_LIMIT_FRACTION = 2 / 3\n",
        "APPLE_WIRED_LIMIT_FRACTION = 0.75\n",
    ),
    (
        "agent: the Metal device is named by platform.processor() ('arm')",
        AGENT,
        A_DEV,
        '        name = device.name or _apple_chip() or "Apple silicon"\n',
        '        name = platform.processor() or "Apple silicon"\n',
    ),
    (
        "agent: the MLX recipe names a bare uv, not the install's own",
        AGENT,
        A_MLX,
        '    own = Path(sys.prefix).parent / "bin" / "uv"\n    if own.is_file():\n'
        "        return shlex.quote(str(own))\n",
        "",
    ),
    (
        "agent: the MLX recipe lets uv pick any Python (a Rosetta shell gets x86_64)",
        AGENT,
        A_MLX,
        'f"{uv} venv --python {_NATIVE_PYTHON} ~/eugene-mlx && ',
        'f"{uv} venv ~/eugene-mlx && ',
    ),
    (
        "library: the Apple budget is a share of RAM again, whatever Metal says",
        LIBRARY,
        L_HW,
        "        budget = device.working_set_bytes\n",
        "        budget = int((ram_total or 0) * 0.75)\n",
    ),
    (
        "library: an MLX model's packed words are reported as its parameters",
        LIBRARY,
        L_SCAN,
        "            parameters = safetensors.mlx_parameters(elements, quantization) or 0\n",
        "            pass\n",
    ),
    (
        "library: a quantized module counts its scales, not scales x group size",
        LIBRARY,
        L_ST,
        "            total += count * group\n",
        "            total += count\n",
    ),
    (
        "library: a chat template in tokenizer_config.json is not looked for",
        LIBRARY,
        L_ST,
        '    return isinstance(tokenizer, dict) and bool(tokenizer.get("chat_template"))\n',
        "    return False\n",
    ),
    (
        "library: gpu_probe.py drifts from the agent's copy",
        LIBRARY,
        L_PROBE,
        '__all__ = [\n',
        '# drift\n__all__ = [\n',
    ),
    (
        "gateway: runtime facts keyed by the node the agent reports again",
        GATEWAY,
        G_ROUTE,
        "            owner = node\n",
        '            reported = entry.get("node")\n'
        "            owner = reported if isinstance(reported, str) and reported else node\n",
    ),
]


def run_tests(repo: Path) -> int:
    result = subprocess.run(
        [str(python(repo)), "-m", "pytest", "-q", "-p", "no:warnings", "-p", "no:cacheprovider",
         *TESTS[repo]],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=600,
    )
    last = (result.stdout + result.stderr).strip().splitlines()[-1:] or [""]
    print(f"    {repo.name}: exit={result.returncode}  {last[0]}")
    return result.returncode


def main() -> None:
    files = {path for _, _, path, _, _ in SABOTAGES}
    copies = {path: path.read_bytes() for path in files}
    caught = 0
    escaped: list[str] = []
    try:
        print("baseline: every guard passes unsabotaged")
        if any(run_tests(repo) != 0 for repo in TESTS):
            raise SystemExit("BASELINE FAILED; fix that first")
        print("baseline PASS\n")
        for label, repo, path, old, new in SABOTAGES:
            source = copies[path].decode("utf-8").replace("\r\n", "\n")
            if source.count(old) != 1:
                raise SystemExit(f"sabotage anchor not found exactly once: {label}")
            print(f"sabotage: {label}")
            path.write_text(source.replace(old, new), encoding="utf-8", newline="\n")
            try:
                code = run_tests(repo)
            finally:
                path.write_bytes(copies[path])
            if code != 0:
                caught += 1
                print("    CAUGHT\n")
            else:
                escaped.append(label)
                print("    ESCAPED\n")
        print(f"{caught} of {len(SABOTAGES)} caught")
        for label in escaped:
            print(f"ESCAPED: {label}")
        if escaped:
            sys.exit(1)
    finally:
        for path, raw in copies.items():
            path.write_bytes(raw)


if __name__ == "__main__":
    main()
