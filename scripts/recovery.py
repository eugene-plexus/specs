"""Encrypted, stopped-install checkpoints and reconstruction. See docs/recovery.md.

Run with the installed Python (PyYAML, PyNaCl and argon2-cffi are required).
No command starts a service or contacts an enrolled node.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import closing
from datetime import datetime, timezone
import getpass
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import urllib.request

import nacl.pwhash
import nacl.secret
import yaml
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

FORMAT = 1
MARKER = ".recovery-quarantine"
CHUNK = 1024 * 1024
EXCLUDED = {"venv", "pythons", "bin", "logs", ".cache", "__pycache__"}
MODEL_SUFFIXES = {".gguf", ".safetensors", ".pt", ".pth", ".bin"}


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    if os.name == "nt":
        sid = (
            subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True)
            .strip()
            .split(",")[-1]
            .strip('"')
        )
        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"*{sid}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
                "*S-1-5-32-544:(OI)(CI)F",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )


def secret_file(path, prompt):
    value = (
        Path(path).read_text(encoding="utf-8").rstrip("\r\n")
        if path
        else getpass.getpass(prompt)
    )
    if not value:
        raise ValueError("unlock material must not be empty")
    return value


def box_for(password, salt):
    return nacl.secret.SecretBox(
        nacl.pwhash.argon2id.kdf(
            32,
            password.encode(),
            salt,
            opslimit=nacl.pwhash.argon2id.OPSLIMIT_INTERACTIVE,
            memlimit=nacl.pwhash.argon2id.MEMLIMIT_INTERACTIVE,
        )
    )


def encrypt_file(source, target, box):
    with source.open("rb") as src, target.open("xb") as dst:
        while chunk := src.read(CHUNK):
            sealed = box.encrypt(chunk)
            dst.write(struct.pack(">I", len(sealed)))
            dst.write(sealed)


def decrypt_file(source, target, box):
    with source.open("rb") as src, target.open("xb") as dst:
        while length := src.read(4):
            if len(length) != 4:
                raise ValueError("truncated checkpoint")
            size = struct.unpack(">I", length)[0]
            if not 40 <= size <= CHUNK + 40:
                raise ValueError("invalid checkpoint chunk")
            dst.write(box.decrypt(src.read(size)))


def safe_relative(name):
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or any(p in ("..", ".") for p in path.parts)
        or ":" in name
        or "\\" in name
    ):
        raise ValueError("invalid inventory path")
    return path


def environment():
    packages = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        direct = json.loads(dist.read_text("direct_url.json") or "null")
        requirement = f"{name}=={dist.version}"
        if direct:
            url = direct["url"]
            # Source checkouts, moving tags and authenticated/private URLs cannot
            # honestly promise reconstruction on a replacement machine.
            if not re.fullmatch(
                r"https://github.com/eugene-plexus/[a-z-]+/archive/[0-9a-f]{40}\.tar\.gz",
                url,
            ):
                raise ValueError(
                    f"{name}: recovery requires an installed immutable source archive, not an editable/local URL"
                )
            sha = direct.get("archive_info", {}).get("hashes", {}).get("sha256")
            if not sha:
                # uv records the immutable URL but not always the archive hash.
                # Fetch that exact revision while making the checkpoint; never
                # substitute main, a version tag, or the package's shared 0.1.0.
                with urllib.request.urlopen(url, timeout=90) as response:
                    hasher = hashlib.sha256()
                    while chunk := response.read(CHUNK):
                        hasher.update(chunk)
                    sha = hasher.hexdigest()
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise ValueError(f"{name}: invalid source archive SHA256")
            requirement = f"{name} @ {url}#sha256={sha}"
        elif name.lower().replace("_", "-").startswith("eugene-plexus-"):
            raise ValueError(f"{name}: exact Eugene source revision is missing")
        packages.append(
            {"name": name, "version": dist.version, "requirement": requirement}
        )
    return {
        "python": platform.python_version(),
        "os": sys.platform,
        "arch": platform.machine(),
        "packages": sorted(packages, key=lambda p: p["name"].lower()),
    }


def validate_state(root):
    if not (root / "agent.yaml").is_file():
        raise ValueError(
            "agent.yaml is missing; source state will not be initialized by recovery"
        )
    from eugene_plexus_agent.state import AgentState
    from eugene_plexus_agent.node_identity import NodeIdentityStore

    AgentState(root / "agent.yaml").load()
    if (root / "node.yaml").exists():
        NodeIdentityStore(root / "node.yaml").load()
    if (root / "control-state").exists():
        from eugene_plexus_control.log_store import LogStore
        from eugene_plexus_control.state_machine import StateMachine

        machine = StateMachine(LogStore(root / "control-state"), role="control")
        machine.load()
        if machine.dropped_tail_lines:
            raise ValueError(
                "control log has a torn tail; recover it before checkpointing"
            )


def walk_values(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_values(child)


def verify_unlock(root, phrases):
    """Validate known salts/verifiers and every local SecretBox envelope offline."""
    keys = []
    agent = yaml.safe_load((root / "agent.yaml").read_text(encoding="utf-8"))
    auth = agent.get("auth") or {}
    checks = []
    if auth.get("passphraseHash"):
        checks.append(("agent", auth["passphraseHash"], auth["masterSalt"]))
    snapshot = root / "control-state" / "snapshot.json"
    control = (
        json.loads(snapshot.read_text(encoding="utf-8")) if snapshot.exists() else {}
    )
    if control.get("passphraseVerifier"):
        checks.append(("control", control["passphraseVerifier"], control["salt"]))
    for kind, verifier, salt in checks:
        phrase = phrases.get(kind)
        if not phrase:
            raise ValueError(f"missing {kind} unlock passphrase")
        try:
            PasswordHasher().verify(verifier, phrase)
        except VerificationError as exc:
            raise ValueError(f"wrong {kind} unlock passphrase") from exc
        # Eugene's existing KDF: Argon2id, time=3, memory=65536 KiB, parallelism=4.
        from argon2.low_level import Type, hash_secret_raw

        keys.append(
            hash_secret_raw(
                phrase.encode(),
                base64.b64decode(salt),
                time_cost=3,
                memory_cost=65536,
                parallelism=4,
                hash_len=32,
                type=Type.ID,
            )
        )
    for path in root.rglob("*"):
        if path.suffix not in (".yaml", ".json") or not path.is_file():
            continue
        if any(part in EXCLUDED for part in path.relative_to(root).parts):
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        envelopes = [
            v for v in walk_values(raw) if v.get("alg") == "secretbox-xsalsa20poly1305"
        ]
        if path == snapshot:
            for field in ("sealedSigningKey", "sealedControlKey", "sealedRecoveryKey"):
                if control.get(field):
                    nonce, cipher = (
                        base64.b64decode(control[field]).decode().split(".", 1)
                    )
                    envelopes.append({"nonce": nonce, "ciphertext": cipher})
        for envelope in envelopes:
            for key in keys:
                try:
                    nacl.secret.SecretBox(key).decrypt(
                        base64.b64decode(envelope["ciphertext"]),
                        base64.b64decode(envelope["nonce"]),
                    )
                    break
                except nacl.exceptions.CryptoError:
                    pass
            else:
                raise ValueError(
                    f"unlock material cannot decrypt secrets in {path.name}"
                )
    return [item[0] for item in checks]


def inventory(root, external):
    included, models, omitted = [], {}, []
    for current, dirs, files in os.walk(root, followlinks=False):
        base = Path(current)
        for directory in list(dirs):
            path = base / directory
            if path.is_symlink() or path.is_junction():
                raise ValueError(
                    f"linked directory must be inventoried separately: {path}"
                )
            if directory in {".cache", "__pycache__", "logs"} or (
                base == root and directory in EXCLUDED
            ):
                dirs.remove(directory)
                omitted.append(str(path.relative_to(root)))
        for name in files:
            path = base / name
            if path.is_symlink() and not path.resolve().is_relative_to(root):
                raise ValueError(f"linked file must be inventoried separately: {path}")
            if (
                path.suffix.lower() in MODEL_SUFFIXES
                and "engines" not in path.relative_to(root).parts
            ):
                models[str(path)] = {
                    "path": str(path),
                    "sha256": digest(path),
                    "bytes": path.stat().st_size,
                }
            elif name != MARKER:
                included.append(path)
    agent = yaml.safe_load((root / "agent.yaml").read_text(encoding="utf-8"))
    for runtime in agent.get("runtimes", []):
        for field in ("modelPath", "binary"):
            if runtime.get(field):
                external.append(Path(runtime[field]))
    library = root / "library.yaml"
    if library.exists():
        for folder in (yaml.safe_load(library.read_text(encoding="utf-8")) or {}).get(
            "modelRoots", []
        ):
            external.append(Path(folder if isinstance(folder, str) else folder["path"]))
    # Explicit external paths cover folders, projectors, custom engine bundles
    # and state placed outside the usual installer-owned directory.
    for path in external:
        path = path.resolve()
        if not path.exists():
            raise ValueError(f"required external asset is missing: {path}")
        for file in sorted(path.rglob("*")) if path.is_dir() else [path]:
            if file.is_file() and file not in included:
                models[str(file)] = {
                    "path": str(file),
                    "sha256": digest(file),
                    "bytes": file.stat().st_size,
                }
    for entry in agent.get("components", []):
        config = (entry.get("spawn") or {}).get("configFile")
        if config and not Path(config).resolve().is_relative_to(root):
            raise ValueError(
                "component configuration outside the state directory: consolidate it before backup"
            )
    return sorted(included), list(models.values()), omitted


def backup(root, destination, password, phrases, external, *, stopped):
    root, destination = root.resolve(), destination.resolve()
    if not stopped:
        raise ValueError("stop this install and its children, then pass --stopped")
    if destination.is_relative_to(root) or root.is_relative_to(destination):
        raise ValueError("checkpoint and source must be separate directories")
    if (root / MARKER).exists():
        raise ValueError("cannot checkpoint an unactivated restore")
    installed = environment()
    if importlib.util.find_spec("eugene_plexus_agent.recovery_guard") is None:
        raise ValueError(
            "checkpoint creation requires an A7-capable agent with the recovery quarantine guard"
        )
    validate_state(root)
    verified = verify_unlock(root, phrases)
    files, assets, omitted = inventory(root, external)
    private_directory(destination)
    salt = nacl.utils.random(nacl.pwhash.argon2id.SALTBYTES)
    box = box_for(password, salt)
    (destination / "salt").write_bytes(salt)
    records = []
    for index, source in enumerate(files):
        before = digest(source)
        payload = f"{index}.sealed"
        encrypt_file(source, destination / payload, box)
        if digest(source) != before:
            raise ValueError(
                "state changed during checkpoint; keep the install stopped"
            )
        records.append(
            {
                "path": source.relative_to(root).as_posix(),
                "sha256": before,
                "mode": source.stat().st_mode & 0o777,
                "payload": payload,
            }
        )
    for record in records:
        if digest(root / record["path"]) != record["sha256"]:
            raise ValueError(
                "state changed during checkpoint; keep the install stopped"
            )
    engine_metadata = []
    for path in [*files, *(Path(a["path"]) for a in assets)]:
        if path.name == "install.json":
            engine_metadata.append(
                {
                    "path": str(path),
                    "build": json.loads(path.read_text(encoding="utf-8")),
                }
            )
        if path.name in ("llama-server", "llama-server.exe"):
            version = subprocess.run(
                [str(path), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=True,
            )
            engine_metadata.append(
                {
                    "path": str(path),
                    "versionOutput": (version.stdout + version.stderr)[:4096],
                }
            )
    manifest = {
        "format": FORMAT,
        "created": datetime.now(timezone.utc).isoformat(),
        "source": str(root),
        "environment": installed,
        "files": records,
        "externalAssets": assets,
        "engineBuilds": engine_metadata,
        "excluded": omitted,
        "unlock": {k: phrases[k] for k in verified},
    }
    (destination / "manifest.sealed").write_bytes(
        box.encrypt(json.dumps(manifest).encode())
    )
    shutil.copyfile(__file__, destination / "recover.py")
    print(
        f"Checkpoint complete: {destination} ({len(records)} files; {len(assets)} external assets)"
    )


def read_checkpoint(checkpoint, password):
    salt = (checkpoint / "salt").read_bytes()
    box = box_for(password, salt)
    manifest = json.loads(box.decrypt((checkpoint / "manifest.sealed").read_bytes()))
    if manifest.get("format") != FORMAT:
        raise ValueError(
            "unsupported backup format; source and destination are unchanged"
        )
    return manifest, box


def verify_assets(manifest):
    for asset in manifest["externalAssets"]:
        path = Path(asset["path"])
        if not path.is_file() or digest(path) != asset["sha256"]:
            raise ValueError(f"external asset missing or changed: {path}")


def restore(checkpoint, destination, password, uv, *, reconstruct=True):
    manifest, box = read_checkpoint(checkpoint, password)
    expected = manifest["environment"]
    if (expected["os"], expected["arch"]) != (sys.platform, platform.machine()):
        raise ValueError("restore requires the original OS and CPU architecture")
    if destination.exists():
        raise ValueError(
            "restore destination must not exist; never overwrite an installation"
        )
    verify_assets(manifest)
    # Verify every encrypted file in a private staging directory before creating
    # the replacement. Source, checkpoint and any existing destination are read-only.
    staging = Path(tempfile.mkdtemp(prefix="ep-recovery-"))
    try:
        # tempfile creates mode 0700 on POSIX; use the same explicit Windows ACL.
        staging.rmdir()
        private_directory(staging)
        for record in manifest["files"]:
            rel = safe_relative(record["path"])
            payload = safe_relative(record["payload"])
            if len(payload.parts) != 1:
                raise ValueError("invalid payload path")
            target = staging / rel
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            decrypt_file(checkpoint / payload, target, box)
            if digest(target) != record["sha256"]:
                raise ValueError("checkpoint file checksum mismatch")
            target.chmod(record["mode"] & 0o700)
        verify_unlock(staging, manifest["unlock"])
        for database in staging.rglob("*.sqlite3"):
            with closing(
                sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
            ) as db:
                if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise ValueError("checkpoint SQLite integrity check failed")
        private_directory(destination)
        (destination / MARKER).write_text(
            "Restored identity: activation required.\n", encoding="utf-8"
        )
        state = destination / "state"
        shutil.copytree(staging, state)
        # Metadata and credentials inherit the private destination ACL.
        (destination / "recovery.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        shutil.copyfile(__file__, destination / "recover.py")
        requirements = destination / "requirements.lock"
        requirements.write_text(
            "\n".join(p["requirement"] for p in expected["packages"]) + "\n",
            encoding="utf-8",
        )
        if reconstruct:
            reconstruction_env = {
                **os.environ,
                "UV_PYTHON_INSTALL_DIR": str(destination / "pythons"),
            }
            subprocess.run(
                [
                    str(uv),
                    "venv",
                    "--python",
                    expected["python"],
                    "--python-preference",
                    "only-managed",
                    str(destination / "venv"),
                ],
                check=True,
                env=reconstruction_env,
            )
            python = (
                destination
                / "venv"
                / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            )
            subprocess.run(
                [
                    str(uv),
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    "--no-deps",
                    "-r",
                    str(requirements),
                ],
                check=True,
            )
            subprocess.run(
                [str(uv), "pip", "check", "--python", str(python)], check=True
            )
            subprocess.run(
                [
                    str(python),
                    str(destination / "recover.py"),
                    "validate",
                    "--destination",
                    str(destination),
                ],
                check=True,
            )
        print(
            f"Restored and quarantined at {destination}. No services were registered or started."
        )
    finally:
        shutil.rmtree(staging)


def activate(destination, *, original_stopped):
    if not original_stopped:
        raise ValueError(
            "stop the original and fence it from restarting, then pass --original-stopped"
        )
    marker = destination / MARKER
    if not marker.exists():
        raise ValueError("this is not a quarantined restore")
    python = (
        destination
        / "venv"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    subprocess.run(
        [
            str(python),
            str(destination / "recover.py"),
            "validate",
            "--destination",
            str(destination),
        ],
        check=True,
    )
    manifest = json.loads((destination / "recovery.json").read_text(encoding="utf-8"))
    verify_assets(manifest)
    verify_unlock(destination / "state", manifest["unlock"])
    # Only the local topology's spawn paths move. Replicated logs and signed node
    # identity remain byte-for-byte intact; model paths continue to name assets.
    agent_path = destination / "state" / "agent.yaml"
    agent = yaml.safe_load(agent_path.read_text(encoding="utf-8"))
    source = Path(manifest["source"])
    for entry in agent.get("components", []):
        spawn = entry.get("spawn") or {}
        if spawn.get("configFile"):
            rel = Path(spawn["configFile"]).relative_to(source)
            spawn["configFile"] = str((destination / "state" / rel).resolve())
    agent_path.write_text(yaml.safe_dump(agent), encoding="utf-8")
    marker.unlink()
    print(f"Activated replacement state: {destination / 'state' / 'agent.yaml'}")
    print(
        "Start with that config path, sign in, then restore service registration separately."
    )


def validate_restore(destination):
    manifest = json.loads((destination / "recovery.json").read_text(encoding="utf-8"))
    if manifest["format"] != FORMAT or environment() != manifest["environment"]:
        raise ValueError(
            "installed Python/packages differ from checkpoint; do not pair older code with migrated state"
        )
    if (
        not Path(sys.base_prefix)
        .resolve()
        .is_relative_to((destination / "pythons").resolve())
    ):
        raise ValueError(
            "restored Python must live under the replacement's pythons directory"
        )
    validate_state(destination / "state")
    verify_unlock(destination / "state", manifest["unlock"])
    print("Restored schema, identity, unlock material and exact environment verified.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("backup")
    make.add_argument("--root", required=True, type=Path)
    make.add_argument("--destination", required=True, type=Path)
    make.add_argument("--stopped", action="store_true")
    make.add_argument("--agent-passphrase-file", type=Path)
    make.add_argument("--control-passphrase-file", type=Path)
    make.add_argument("--external", action="append", default=[], type=Path)
    load = sub.add_parser("restore")
    load.add_argument("--checkpoint", required=True, type=Path)
    load.add_argument("--destination", required=True, type=Path)
    load.add_argument("--uv", required=True, type=Path)
    for command in (make, load):
        command.add_argument("--backup-password-file", type=Path)
    enable = sub.add_parser("activate")
    enable.add_argument("--destination", required=True, type=Path)
    enable.add_argument("--original-stopped", action="store_true")
    validate = sub.add_parser("validate")
    validate.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "validate":
        validate_restore(args.destination.resolve())
        return
    if args.command == "activate":
        activate(args.destination.resolve(), original_stopped=args.original_stopped)
        return
    password = secret_file(args.backup_password_file, "Backup encryption password: ")
    if args.command == "restore":
        restore(
            args.checkpoint.resolve(), args.destination.resolve(), password, args.uv
        )
    else:
        phrases = {}
        agent = yaml.safe_load((args.root / "agent.yaml").read_text(encoding="utf-8"))
        if (agent.get("auth") or {}).get("passphraseHash"):
            phrases["agent"] = secret_file(
                args.agent_passphrase_file, "Agent unlock passphrase: "
            )
        snapshot = args.root / "control-state" / "snapshot.json"
        if snapshot.exists() and json.loads(snapshot.read_text(encoding="utf-8")).get(
            "passphraseVerifier"
        ):
            phrases["control"] = secret_file(
                args.control_passphrase_file, "Control unlock passphrase: "
            )
        backup(
            args.root,
            args.destination,
            password,
            phrases,
            args.external,
            stopped=args.stopped,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not print sealed contents, passphrases or subprocess environments.
        print(f"Recovery refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
