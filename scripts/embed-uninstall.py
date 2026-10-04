"""Keep the one-file installers' offline removal payloads in sync.

Run after editing uninstall.ps1, uninstall.sh or uninstall_inventory.py.
--check is the CI gate; it never writes files.
"""

import argparse
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BEGIN = "# BEGIN GENERATED OFFLINE REMOVAL"
END = "# END GENERATED OFFLINE REMOVAL"


def generated(windows: bool) -> str:
    files = {
        "inventory.py": "uninstall_inventory.py",
        "remove.ps1" if windows else "remove.sh": "uninstall.ps1"
        if windows
        else "uninstall.sh",
    }
    output = [
        BEGIN,
        "# Source: scripts/uninstall*; regenerate with python scripts/embed-uninstall.py.",
    ]
    if windows:
        output += [
            "function Write-RemovalBundle {",
            "    param([string]$Path)",
            "    $dir = Join-Path $Path 'uninstall'",
            "    New-Item -ItemType Directory -Path $dir -Force | Out-Null",
        ]
        for target, source in files.items():
            # Git may check out CRLF on Windows; the payload is always UTF-8/LF.
            encoded = base64.b64encode(
                (ROOT / source).read_text(encoding="utf-8-sig").encode("utf-8")
            ).decode()
            output.append(
                f"    [IO.File]::WriteAllBytes((Join-Path $dir '{target}'), [Convert]::FromBase64String('{encoded}'))"
            )
        output += ["}"]
    else:
        output += ["write_removal_bundle() {", '    mkdir -p "$PREFIX/uninstall"']
        for target, source in files.items():
            marker = "EUGENE_REMOVAL_" + target.replace(".", "_").upper()
            output += [
                f"    cat > \"$PREFIX/uninstall/{target}\" <<'{marker}'",
                (ROOT / source).read_text(encoding="utf-8").rstrip(),
                marker,
            ]
        output += [
            "    cat > \"$PREFIX/uninstall/Remove Eugene.command\" <<'EUGENE_REMOVAL_COMMAND'",
            "#!/bin/sh",
            'HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)',
            'exec /bin/sh "$HERE/remove.sh" --interactive',
            "EUGENE_REMOVAL_COMMAND",
            '    chmod 700 "$PREFIX/uninstall/Remove Eugene.command" "$PREFIX/uninstall/remove.sh"',
            "}",
        ]
    output += [END]
    return "\n".join(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for windows, name in ((True, "install.ps1"), (False, "install.sh")):
        path = ROOT / name
        text = path.read_text(encoding="utf-8-sig")
        payload = generated(windows)
        if BEGIN in text:
            start, end = text.index(BEGIN), text.index(END) + len(END)
            expected = text[:start] + payload + text[end:]
        else:
            anchor = "# --- uninstall "
            start = text.index(anchor)
            expected = text[:start] + payload + "\n\n" + text[start:]
        if text != expected:
            stale.append(name)
            if not args.check:
                path.write_text(expected, encoding="utf-8", newline="\n")
    if stale and args.check:
        raise SystemExit("Offline removal payloads are stale: " + ", ".join(stale))
    print(
        "Offline removal payloads match source."
        if not stale
        else "Updated " + ", ".join(stale)
    )


if __name__ == "__main__":
    main()
