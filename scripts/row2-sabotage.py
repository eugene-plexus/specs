"""Row 2 sabotage pass: put each hole back and prove a check notices.

Row 2 (2026-09-24): on Linux the agent runs as its own account, so it has
no keyring and unlocks from a passphrase file only that account can
read; the wizard follows `AuthStatus.passphraseFile`, and proposes the
folder the installer chose rather than the library's own home.

Restores from a COPY, never `git checkout --`, and opens with a baseline
assertion that every gate passes unsabotaged (memory:
`sabotage-runs-restore-from-a-copy`). The installer's own guards are
sabotaged against the live system install, which takes minutes a pass:
`--installer` adds them, run from the WSL guest as root like
`row2-system-install-acceptance.sh`.
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Upper-case drive letter: Vitest run from `d:/...` loads itself twice
# (once per spelling of the path) and then finds no suite at all.
ROOT = Path("D:/py/eugene-plexus")
PF = ("agent", "src/eugene_plexus_agent/passphrase_file.py")
APP = ("agent", "src/eugene_plexus_agent/app.py")
AUTH = ("agent", "src/eugene_plexus_agent/routes/auth.py")
PAGE = ("ui", "src/app/setup/page.tsx")
DRAFT = ("ui", "src/app/setup/draft.ts")
SCREEN = ("ui", "src/app/setup/screens/Passphrase.tsx")
FOLDER = ("ui", "src/lib/proposedModelsFolder.ts")
INSTALLER = ("specs", "scripts/install.sh")
FILES = (PF, APP, AUTH, PAGE, DRAFT, SCREEN, FOLDER, INSTALLER)
TIMEOUT = 1500

# (label, (repo, file), old, new)
SABOTAGES: list[tuple[str, tuple[str, str], str, str]] = [
    # --- the agent -----------------------------------------------------------
    (
        "a file holding some other passphrase is derived from without checking",
        PF,
        "    if not security.verify_passphrase(passphrase, passphrase_hash):\n",
        "    if False:\n",
    ),
    (
        "the file is trusted under any mode, not only passphrase_file",
        APP,
        '        and state.get_config("securityMode") == "passphrase_file"\n'
        "        and not app.state.auth_state.has_master_key()\n",
        "        and not app.state.auth_state.has_master_key()\n",
    ),
    (
        "the file is written under any mode",
        AUTH,
        '    if state.get_config("securityMode") != "passphrase_file":\n        return\n'
        "    passphrase_file.store_passphrase(",
        "    passphrase_file.store_passphrase(",
    ),
    (
        "sign-in never repairs a missing file",
        AUTH,
        "    _persist_master_key_if_keyring_mode(state, derived)\n"
        "    _persist_passphrase_if_file_mode(request, state, body.passphrase)\n",
        "    _persist_master_key_if_keyring_mode(state, derived)\n",
    ),
    (
        "the wizard is told the file mode where there is nowhere to keep it",
        AUTH,
        "        and _passphrase_path(request) is not None\n",
        "",
    ),
    (
        "the passphrase is stripped of every space, not one newline",
        PF,
        '    if text.endswith("\\r\\n"):\n        text = text[:-2]\n'
        '    elif text.endswith("\\n"):\n        text = text[:-1]\n',
        "    text = text.strip()\n",
    ),
    (
        "the passphrase is kept 0600 rather than 0400 (POSIX only)",
        PF,
        "FILE_MODE = 0o400\n",
        "FILE_MODE = 0o600\n",
    ),
    # --- the wizard ----------------------------------------------------------
    (
        "the wizard ignores passphraseFile",
        PAGE,
        '        setDraft((prev) => ({ ...prev, securityMode: "passphrase_file" }));\n',
        "",
    ),
    (
        "the screen still offers the keyring checkbox on a file install",
        SCREEN,
        "      {!passphraseFile && (\n",
        "      {true && (\n",
    ),
    (
        "a saved draft can carry the file mode to a host without one",
        DRAFT,
        '      saved.securityMode === "os_keyring" || saved.securityMode === "prompt_on_startup"\n',
        '      saved.securityMode === "os_keyring" || saved.securityMode === "prompt_on_startup" ||\n'
        '      saved.securityMode === "passphrase_file"\n',
    ),
    (
        "the wizard proposes the library's home past the installer's folder",
        PAGE,
        "        if (preset) {\n",
        "        if (false && preset) {\n",
    ),
]

# Against the live system install. Each is a full install: minutes.
INSTALLER_SABOTAGES: list[tuple[str, tuple[str, str], str, str]] = [
    (
        "the unit runs the agent as root",
        INSTALLER,
        "User=$SYSTEM_ACCOUNT\nGroup=$SYSTEM_ACCOUNT\n",
        "",
    ),
    (
        "the unit never adds the person's group",
        INSTALLER,
        "    UNIT_GROUPS=${PERSON_GROUP:-}\n",
        "    UNIT_GROUPS=\n",
    ),
    (
        "the prefix is left open to everyone",
        INSTALLER,
        '    as_root install -d -m 0750 -o "$SYSTEM_ACCOUNT"',
        '    as_root install -d -m 0755 -o "$SYSTEM_ACCOUNT"',
    ),
    (
        "a fresh system install is left on prompt_on_startup",
        INSTALLER,
        "    set_config_line securityMode passphrase_file\n",
        "    :\n",
    ),
    (
        "a system install starts beside a per-user one",
        INSTALLER,
        '        && { [ -f "$PERSON_USER_UNIT" ] || [ -f "$PERSON_USER_PREFIX/agent.yaml" ]; }; then\n',
        "        && false; then\n",
    ),
]


def run(repo: str) -> tuple[int, str]:
    if repo == "agent":
        py = ROOT / "agent" / ".venv" / "Scripts" / "python.exe"
        argv = [
            str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
            "tests/test_passphrase_file.py", "tests/test_auth.py", "tests/test_keyring_scope.py",
        ]
    elif repo == "ui":
        argv = ["npx.cmd", "vitest", "run", "src/app/setup", "src/lib/proposedModelsFolder"]
    else:
        argv = [
            "wsl.exe", "-u", "root", "-e", "env", "EP_PERSON=tcorbin", "EP_LOCAL_REPOS=agent ui",
            "bash", "/mnt/d/py/eugene-plexus/specs/scripts/row2-system-install-acceptance.sh",
        ]
    try:
        done = subprocess.run(
            argv, cwd=ROOT / repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=TIMEOUT,
            env={**__import__("os").environ, "MSYS_NO_PATHCONV": "1"},
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", action="store_true", help="also sabotage install.sh")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sabotages = SABOTAGES + (INSTALLER_SABOTAGES if args.installer else [])
    repos = sorted({repo for _, (repo, _), _, _ in sabotages})

    backup = Path(tempfile.mkdtemp(prefix="row2-sabotage-"))
    for repo, relative in FILES:
        destination = backup / repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / repo / relative, destination)
    print(f"copy in {backup}\n")

    for repo in repos:
        code, out = run(repo)
        print(f"[baseline {repo}] {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    print()

    caught = escaped = 0
    for label, (repo, relative), old, new in sabotages:
        path = ROOT / repo / relative
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run(repo)
        finally:
            shutil.copy2(backup / repo / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(sabotages)} sabotages")
    for repo in repos:
        code, out = run(repo)
        print(f"[restored {repo}] {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
