"""R7 signing regressions and isolated mutation gate for all five components.

Run in a disposable Python environment with all five consumer runtime packages
and scripts/requirements-acceptance.txt.
Every mutation happens in a copied source tree and restores saved bytes.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPOS = ("agent", "control", "gateway", "library", "inference-driver")
LEAVES = ("gateway", "library", "inference-driver")


def mutations():
    for repo in REPOS:
        yield repo, "security.py", 'else "EdDSA"', 'else "HS256"', "public_key_verifies"
        yield repo, "security.py", "if len(key) == 32:", "if False:", "legacy_hs256"
    for repo in LEAVES:
        yield (
            repo,
            "app.py",
            "verify_key_b64=settings.auth_verify_key",
            "verify_key_b64=None",
            "application_wires",
        )
        yield (
            repo,
            "auth_state.py",
            "if verify_key_b64 is not None:",
            "if False:",
            "bootstrap_accepts",
        )
        yield (
            repo,
            "auth_state.py",
            "if len(raw) != expected_len:",
            "if False:",
            "legacy_bootstrap_cannot",
        )
    for repo in ("agent", "control"):
        yield (
            repo,
            "security.py",
            "return Ed25519PrivateKey.generate().private_bytes(",
            "return b'L' * 32\n    return Ed25519PrivateKey.generate().private_bytes(",
            "new_keys_mint",
        )
    yield (
        "agent",
        "supervisor.py",
        "security.verification_key(key)",
        "key",
        "children_receive",
    )
    yield (
        "agent",
        "node_identity.py",
        "if held_key is not None and len(held_key) != 32 and len(offered_key) == 32:",
        "if False:",
        "downgrade",
    )


def run(directory: Path, selection: str = "") -> subprocess.CompletedProcess:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("EUGENE_PLEXUS_")
    }
    env["PYTHONPATH"] = str(directory / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    test = (
        "tests/test_node.py"
        if selection == "downgrade"
        else "tests/test_asymmetric_auth.py"
    )
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "--disable-warnings",
        test,
    ]
    if selection:
        command += ["-k", selection]
    return subprocess.run(
        command, cwd=directory, env=env, text=True, capture_output=True, timeout=90
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--polyrepo", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ep-r7-signing-") as temp:
        copies = {}
        for repo in REPOS:
            source = args.polyrepo / repo
            target = Path(temp) / repo
            target.mkdir()
            for tree in ("src", "tests"):
                shutil.copytree(
                    source / tree,
                    target / tree,
                    ignore=shutil.ignore_patterns("__pycache__"),
                )
            shutil.copy2(source / "pyproject.toml", target / "pyproject.toml")
            copies[repo] = target
            result = run(target)
            if result.returncode:
                raise SystemExit(
                    f"{repo} baseline failed:\n{result.stdout}\n{result.stderr}"
                )
            print(f"PASS {repo} asymmetric baseline", flush=True)
        result = run(copies["agent"], "downgrade")
        if result.returncode:
            raise SystemExit(
                f"downgrade baseline failed:\n{result.stdout}\n{result.stderr}"
            )
        count = 0
        for repo, filename, old, new, selection in mutations():
            path = (
                copies[repo]
                / "src"
                / ("eugene_plexus_" + repo.replace("-", "_"))
                / filename
            )
            original = path.read_bytes()
            text = original.decode("utf-8")
            if old not in text:
                raise SystemExit(f"missing mutation anchor: {repo}/{filename}: {old}")
            try:
                path.write_text(text.replace(old, new), encoding="utf-8")
                result = run(copies[repo], selection)
                if (
                    result.returncode != 1
                    or "FAILURES" not in result.stdout
                    or "ERROR" in result.stdout
                ):
                    raise SystemExit(
                        f"mutation escaped or broke collection: {repo}/{filename}: {selection}\n"
                        f"{result.stdout}\n{result.stderr}"
                    )
                count += 1
                print(f"CAUGHT {repo}/{filename}: {selection}", flush=True)
            finally:
                path.write_bytes(original)
        for repo in REPOS:
            result = run(copies[repo])
            if result.returncode:
                raise SystemExit(
                    f"restored {repo} failed:\n{result.stdout}\n{result.stderr}"
                )
        assert run(copies["agent"], "downgrade").returncode == 0
        print(f"{count}/{count} mutations caught; restored baselines pass")


if __name__ == "__main__":
    main()
