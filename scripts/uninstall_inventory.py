"""Read an install's removal inventory before its Python is removed.

Installed verbatim by both installers. This program never deletes files.
The native uninstallers retain its plain-text inventory for offline cleanup.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shlex
import sys


def absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def overlaps(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a == b or a in b.parents or b in a.parents


def read_config(path: Path, warnings: list[str]) -> dict:
    if not path.exists():
        return {}
    try:
        import yaml

        value = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
        if not isinstance(value, dict):
            raise ValueError("expected a mapping")
        return value
    except Exception as exc:
        warnings.append(
            f"Could not read {path} ({type(exc).__name__}). Custom downloads are kept."
        )
        return {}


def inventory(prefix: Path) -> dict:
    warnings: list[str] = []
    agent = read_config(prefix / "agent.yaml", warnings)
    protected = [prefix / "models", Path.home() / "Eugene Models"]

    # Library state contains modelRoots and, on newer installations, folders.
    def roots(value: object, key: str = "") -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ("modelRoots", "defaultModelRoots") and isinstance(v, list):
                    protected.extend(absolute(p) for p in v if isinstance(p, str))
                    roots(v, k)
                elif (
                    k in ("path", "localPath")
                    and key in ("folders", "modelRoots")
                    and isinstance(v, str)
                ):
                    protected.append(absolute(v))
                else:
                    roots(v, k)
        elif isinstance(value, list):
            for v in value:
                roots(v, key)

    for config in prefix.glob("library*.yaml"):
        roots(read_config(config, warnings))
    roots(agent)
    software = [
        prefix / name for name in ("venv", "pythons", "bin", ".cache/uv", "update")
    ]
    software += [
        prefix / name for name in ("install-check.py", "release-requirements.lock")
    ]
    apps = prefix / "apps"
    software += [apps / name for name in ("pythons", "launcher", "ctl")]
    data = [prefix / name for name in ("logs", "passphrase", "control-state")]
    for app in apps.iterdir() if apps.is_dir() and not apps.is_symlink() else []:
        if (
            app.is_dir()
            and not app.is_symlink()
            and app.name not in ("pythons", "launcher", "ctl")
        ):
            software += [app / "versions", app / "python"]
            data += [p for p in app.iterdir() if p.name not in ("versions", "python")]
    for item in prefix.iterdir():
        if item.is_file() and (
            item.suffix
            in (
                ".yaml",
                ".json",
                ".sqlite3",
                ".db",
                ".sqlite3-wal",
                ".sqlite3-shm",
                ".db-wal",
                ".db-shm",
            )
            or item.name.startswith(
                (
                    ".update-channel",
                    "agent.yaml.",
                    "node.yaml.",
                    "control.yaml.",
                    "gateway.yaml.",
                    "library.yaml.",
                )
            )
        ):
            data.append(item)
    if apps.is_dir():
        data += [p for p in apps.iterdir() if p.is_file()]
    downloads = [prefix / "engines"]
    engine = os.environ.get("EUGENE_PLEXUS_AGENT_ENGINE_ROOT")
    # Service installs own prefix/engines. Do not also sweep the invoking
    # administrator's per-user store (which may belong to another install).
    info_path = prefix / "uninstall/install-info.json"
    if info_path.exists():
        try:
            recorded_engine = json.loads(info_path.read_text(encoding="utf-8"))[
                "engineRoot"
            ]
            downloads.append(absolute(recorded_engine))
        except (OSError, ValueError, KeyError, TypeError):
            warnings.append(
                "Could not read the installed download location. External engines were kept."
            )
    elif not (prefix / "engines").exists():
        if engine and absolute(engine) != prefix / "engines":
            warnings.append(
                f"External engine store kept: {engine}. Its ownership cannot be confirmed from this installation."
            )
        elif not engine:
            downloads.append(Path.home() / ".eugene-plexus/engines")
    copies = agent.get("modelCopyDir")
    if isinstance(copies, str) and copies:
        if Path(copies).expanduser().is_absolute():
            downloads.append(absolute(copies))
        else:
            warnings.append(
                f"Relative model-copy location kept: {copies}. Its working directory cannot be confirmed."
            )
    if any(w.startswith("Could not read") for w in warnings):
        downloads = []
        warnings.append(
            "Downloads were kept because the configuration could not be read safely."
        )
    result: dict = {"version": 1, "prefix": str(prefix), "warnings": warnings}
    for kind, candidates in (
        ("software", software),
        ("data", data),
        ("downloads", downloads),
    ):
        kept = []
        for path in dict.fromkeys(absolute(p) for p in candidates):
            if not path.exists() and not path.is_symlink():
                continue
            if "\n" in str(path) or "\r" in str(path):
                warnings.append(
                    f"Kept a {kind} path containing a newline; remove it manually."
                )
                continue
            if (
                path == prefix
                or path in prefix.parents
                or path == absolute(Path.home())
                or len(path.parts) < 3
            ):
                warnings.append(f"Kept unsafe {kind} path: {path}")
                continue
            if any(overlaps(path, p) for p in protected):
                warnings.append(f"Kept {path}: it overlaps an original model folder.")
                continue
            # Never traverse a symlink/junction to make a deletion inventory.
            if any(
                p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                for p in (path, *path.parents)
            ):
                warnings.append(f"Kept {path}: it uses a link or junction.")
                continue
            kept.append(str(path))
        result[kind] = kept
    result["protected"] = list(dict.fromkeys(str(absolute(p)) for p in protected))
    return result


def keyring_cleanup(prefix: Path) -> dict:
    warnings: list[str] = []
    config = read_config(prefix / "agent.yaml", warnings)
    auth = config.get("auth") or {}
    if not isinstance(auth, dict):
        return {
            "removed": 0,
            "warnings": ["Credentials kept: the auth configuration is not readable."],
        }
    salt = auth.get("masterSalt")
    names = []
    if salt:
        try:
            fingerprint = hashlib.sha256(
                base64.b64decode(salt, validate=True)
            ).hexdigest()[:12]
            # The application uses a colon. The old uninstall/test code
            # incorrectly used a dash; also remove that historical spelling.
            names = ["master-key:" + fingerprint, "master-key-" + fingerprint]
        except Exception as exc:
            warnings.append(f"Could not identify this install's credentials: {exc}")
    elif config.get("auth"):
        # A legacy entry is shared; do not delete a different install's key.
        warnings.append(
            "Legacy unscoped credentials were kept. Review Eugene entries in the OS credential store."
        )
    removed = 0
    if names:
        try:
            import keyring

            for service in ("eugene-plexus-agent", "eugene-plexus-control"):
                for name in names:
                    try:
                        if keyring.get_password(service, name) is not None:
                            keyring.delete_password(service, name)
                            if keyring.get_password(service, name) is not None:
                                raise RuntimeError(
                                    "entry is still present after deletion"
                                )
                            removed += 1
                    except Exception as exc:
                        warnings.append(f"Credential left: {service}/{name}: {exc}")
        except Exception as exc:
            warnings.append(f"Could not open the OS credential store: {exc}")
    return {"removed": removed, "warnings": warnings}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--keyring-only", action="store_true")
    parser.add_argument("--install-macos", action="store_true")
    args = parser.parse_args()
    prefix = absolute(args.prefix)
    if args.install_macos:
        install_macos(prefix)
        return
    if args.output is None:
        parser.error("--output is required")
    result = keyring_cleanup(prefix) if args.keyring_only else inventory(prefix)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    if not args.keyring_only:
        for kind in ("software", "data", "downloads", "protected"):
            (args.output.parent / f"{kind}.txt").write_text(
                "".join(p + "\n" for p in result[kind]), encoding="utf-8"
            )
        (args.output.parent / "original-prefix.txt").write_text(
            str(prefix) + "\n", encoding="utf-8"
        )
        (args.output.parent / "warnings.txt").write_text(
            "\n".join(result["warnings"]), encoding="utf-8"
        )
        programs = [prefix / "venv/bin/python", Path(sys.executable).resolve()]
        owned_programs = [
            str(p) for p in programs if p.resolve().is_relative_to(prefix.resolve())
        ]
        (args.output.parent / "firewall.txt").write_text(
            "".join(p + "\n" for p in dict.fromkeys(owned_programs)), encoding="utf-8"
        )
        app_record = prefix / "uninstall/mac-app.txt"
        if app_record.exists():
            (args.output.parent / "mac-app.txt").write_text(
                app_record.read_text(encoding="utf-8"), encoding="utf-8"
            )
    for warning in result["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)


def install_macos(prefix: Path) -> None:
    """A Finder-visible local utility; no interpreter or network at launch."""
    suffix = (
        ""
        if prefix == Path.home() / ".local/share/eugene-plexus"
        else " " + hashlib.sha256(str(prefix).encode()).hexdigest()[:8]
    )
    app = Path.home() / "Applications" / f"Remove Eugene Plexus{suffix}.app"
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Resources").mkdir(exist_ok=True)
    (contents / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": "com.eugeneplexus.remove" + suffix.strip(),
                "CFBundleName": "Remove Eugene Plexus",
                "CFBundleDisplayName": "Remove Eugene Plexus",
                "CFBundleExecutable": "remove",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1",
                "LSUIElement": True,
            }
        )
    )
    executable = contents / "MacOS/remove"
    executable.write_text(
        "#!/bin/sh\nexec /bin/sh "
        + shlex.quote(str(prefix / "uninstall/remove.sh"))
        + " --interactive\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    (contents / "Resources/prefix.txt").write_text(str(prefix) + "\n", encoding="utf-8")
    (prefix / "uninstall/mac-app.txt").write_text(str(app) + "\n", encoding="utf-8")
    engine = os.environ.get("EUGENE_PLEXUS_AGENT_ENGINE_ROOT") or str(
        Path.home() / ".eugene-plexus/engines"
    )
    (prefix / "uninstall/install-info.json").write_text(
        json.dumps({"engineRoot": engine}), encoding="utf-8"
    )
    print(f"Removal utility: {app}")


if __name__ == "__main__":
    main()
