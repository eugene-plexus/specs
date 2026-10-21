"""Portable CX9 protocol acceptance over isolated Library and worker processes.

The worker hosts the production report loop and send route with a disposable
signed trust bundle. This tests the transfer protocol independently of the
installer/browser acceptance. --copy-folder must be on another filesystem.
Run through cx9-ollama-models-acceptance.py --row65 --copy-folder <folder>.
No live services, default ports, accounts or model stores are used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import struct
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx

HERE = Path(__file__).resolve().parent
REPOS = HERE.parent.parent


def python(repo: str) -> Path:
    return (
        REPOS
        / repo
        / ".venv"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )


def ports() -> tuple[int, int]:
    held = []
    try:
        for _ in range(2):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            held.append(sock)
        return tuple(s.getsockname()[1] for s in held)
    finally:
        for sock in held:
            sock.close()


def serve(kind: str, root: Path) -> None:
    import uvicorn

    sys.path.insert(0, str(REPOS / kind / "src"))
    prefix = "eugene_plexus_" + kind
    tokens = __import__(prefix + ".tokens", fromlist=["tokens"])
    data = json.loads((root / "trust.json").read_text())
    bundle = tokens.parse_bundle(data["bundle"], authority=data["authority"])
    if kind == "library":
        from eugene_plexus_library.app import create_app
        from eugene_plexus_library.settings import Settings

        app = create_app(
            settings=Settings(
                config_file=root / "library.yaml",
                state_file=root / "library-state.json",
                agent_url=data["workerUrl"],
                trust_bundle_file=str(root / "bundle.json"),
                trust_authority=data["authority"],
                auth_recipient="node:library",
                service_token=data["libraryService"],
            )
        )
        port = data["libraryPort"]
    else:
        from eugene_plexus_agent.admission import LibraryFitClient
        from eugene_plexus_agent.auth_state import AuthState
        from eugene_plexus_agent.ollama_report import run as report
        from eugene_plexus_agent.routes.ollama import router
        from fastapi import FastAPI

        @asynccontextmanager
        async def lifespan(app):
            task = asyncio.create_task(report(app))
            try:
                yield
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        app = FastAPI(lifespan=lifespan)
        trust = SimpleNamespace(
            recipient="node:worker",
            verify=lambda token, classes: tokens.verify(
                token, bundle=bundle, recipient="node:worker", classes=classes
            ),
        )
        app.state.auth_state = AuthState(trust=trust)
        app.state.library_fit_client = LibraryFitClient(
            data["libraryUrl"], data["workerService"]
        )
        app.state.agent_state = SimpleNamespace(
            get_config=lambda key: True, list_topology_entries=list
        )
        app.state.node_identity = SimpleNamespace(
            record=SimpleNamespace(enrolled=True, name="worker")
        )
        app.include_router(router)
        # Stand-in topology hop; the production sender still verifies the job
        # with its own service token before opening its local store.
        app.include_router(router, prefix="/api/proxy/node:worker")
        port = data["workerPort"]
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def wait(check, description: str):
    deadline = time.perf_counter() + 100
    while time.perf_counter() < deadline:
        try:
            found = check()
            if found:
                return found
        except httpx.ConnectError:
            pass
        time.sleep(0.1)
    raise AssertionError("Timed out: " + description)


def run(root: Path, copy_folder: Path) -> None:
    sys.path.insert(0, str(REPOS / "library" / "src"))
    import hashlib

    from eugene_plexus_library import tokens

    root.mkdir(parents=True, exist_ok=False)
    assert copy_folder.is_dir(), "--copy-folder must already exist"
    assert root.stat().st_dev != copy_folder.stat().st_dev, (
        "--copy-folder must be on another filesystem"
    )
    copy_root = copy_folder / root.name
    copy_root.mkdir(exist_ok=False)
    library_port, worker_port = ports()
    assert not {library_port, worker_port} & set(range(8079, 8084))
    authority = tokens.generate_private_key()
    control = tokens.Signer(tokens.generate_private_key(), "control")
    worker = tokens.Signer(tokens.generate_private_key(), "node:worker")
    local = tokens.Signer(tokens.generate_private_key(), "node:library")
    bundle = tokens.build_bundle(
        authority=authority,
        version=1,
        epoch=1,
        keys=[
            control.trust_key(["authority"]),
            worker.trust_key(["node"]),
            local.trust_key(["node"]),
        ],
    )
    tokens.write_bundle_file(root / "bundle.json", bundle)
    session, _ = control.mint(
        typ=tokens.TYP_SESSION,
        sub="operator",
        aud=["node:library", "node:worker"],
        ttl_seconds=3600,
    )
    service, _ = worker.mint(
        typ=tokens.TYP_SERVICE, sub="agent", aud=["node:library"], ttl_seconds=3600
    )
    lib_service, _ = local.mint(
        typ=tokens.TYP_SERVICE, sub="library", aud=["node:library"], ttl_seconds=3600
    )
    library_url, worker_url = (
        f"http://127.0.0.1:{library_port}",
        f"http://127.0.0.1:{worker_port}",
    )
    # Read back the public signed bundle in its on-disk envelope format.
    envelope = json.loads((root / "bundle.json").read_text())
    (root / "trust.json").write_text(
        json.dumps(
            {
                "bundle": envelope["jws"],
                "authority": tokens.public_b64(authority),
                "libraryUrl": library_url,
                "workerUrl": worker_url,
                "libraryPort": library_port,
                "workerPort": worker_port,
                "workerService": service,
                "libraryService": lib_service,
            }
        )
    )
    models = root / "models"
    models.mkdir()
    (root / "library.yaml").write_text(
        json.dumps({"modelRoots": [str(models), str(copy_root)]})
    )

    def text(value):
        return struct.pack("<Q", len(value)) + value

    data = (
        b"GGUF"
        + struct.pack("<IQQ", 3, 0, 1)
        + text(b"general.architecture")
        + struct.pack("<I", 8)
        + text(b"llama")
    )
    digest = hashlib.sha256(data).hexdigest()
    stores = [root / "local-store", root / "worker-store"]
    for store in stores:
        blob = store / "blobs" / ("sha256-" + digest)
        blob.parent.mkdir(parents=True)
        blob.write_bytes(data)
        path = (
            store / "manifests" / "registry.ollama.ai" / "library" / "tiny" / "latest"
        )
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "runner": "llamacpp",
                    "layers": [
                        {
                            "mediaType": "application/vnd.ollama.image.model",
                            "digest": "sha256:" + digest,
                        }
                    ],
                }
            )
        )
    processes, logs = [], []
    try:
        for kind, store in zip(("library", "agent"), stores, strict=True):
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith("EUGENE_PLEXUS_")
            }
            env.update(OLLAMA_MODELS=str(store), PYTHONUTF8="1")
            log = (root / (kind + ".log")).open("w")
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    [
                        str(python(kind)),
                        str(Path(__file__)),
                        "--serve",
                        kind,
                        "--output",
                        str(root),
                    ],
                    env=env,
                    cwd=root,
                    stdout=log,
                    stderr=log,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            )
        with httpx.Client(
            headers={"Authorization": "Bearer " + session}, trust_env=False
        ) as client:
            wait(
                lambda: client.get(library_url + "/v1/models").status_code == 200,
                "Library",
            )

            def scanned():
                rows = client.get(library_url + "/v1/models").json()["models"]
                return next((m for m in rows if m.get("ollama")), None)

            model = wait(scanned, "local store")
            # The new tag sorts first but does not rename the served model.
            tag = next(stores[0].glob("manifests/*/*/*/latest"))
            tag.with_name("8b").write_bytes(tag.read_bytes())
            client.post(library_url + "/v1/scan")
            wait(
                lambda: (
                    client.get(library_url + "/v1/scan").json()["state"] != "scanning"
                ),
                "rescan",
            )
            assert (
                client.get(library_url + f"/v1/models/{model['id']}").json()["name"]
                == "tiny:latest"
            )
            linked_folder = models / "linked-store"
            if os.name == "nt":
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(linked_folder), str(stores[0])],
                    check=True,
                    capture_output=True,
                )
            else:
                linked_folder.symlink_to(stores[0], target_is_directory=True)
            refused = client.post(
                library_url + "/v1/downloads",
                json={
                    "repo": "a/b",
                    "files": ["m.gguf"],
                    "root": str(models),
                    "subdirectory": "linked-store",
                },
            )
            assert refused.status_code == 409, refused.text
            profile = client.post(
                library_url + f"/v1/models/{model['id']}/profiles",
                json={"name": "tuned", "engine": "llama_cpp"},
            )
            assert profile.status_code == 201, profile.text

            def keep(path, body):
                response = client.post(library_url + path, json=body)
                assert response.status_code == 202, response.text
                job = response.json()
                result = wait(
                    lambda: (
                        j
                        if (
                            j := client.get(
                                library_url + "/v1/keep-jobs/" + job["id"]
                            ).json()
                        )["state"]
                        != "running"
                        else None
                    ),
                    "Keep",
                )
                assert result["state"] == "done", result
                return result

            linked = keep(f"/v1/models/{model['id']}/keep", {})
            assert linked["method"] == "link"
            profiles = client.get(
                library_url + f"/v1/models/{linked['model']['id']}/profiles"
            ).json()["profiles"]
            assert [p["name"] for p in profiles] == ["tuned"]
            assert os.path.samefile(
                linked["target"], stores[0] / "blobs" / ("sha256-" + digest)
            )
            copied = keep(f"/v1/models/{model['id']}/keep", {"folder": str(copy_root)})
            assert copied["method"] == "copy"
            assert (
                hashlib.sha256(Path(copied["target"]).read_bytes()).hexdigest()
                == digest
            )
            # Free the default destination for the worker's separate Keep.
            remote_root = root / "remote-models"
            remote_root.mkdir()
            client.patch(
                library_url + "/v1/config",
                json={"modelRoots": [str(models), str(copy_root), str(remote_root)]},
            )
            wait(
                lambda: client.get(library_url + "/v1/nodes/ollama").json()["nodes"],
                "worker report",
            )
            remote = keep(
                "/v1/nodes/worker/ollama/keep",
                {"digest": "sha256:" + digest, "folder": str(remote_root)},
            )
            assert remote["model"]["keptFrom"]["node"] == "worker"
            (root / "kept-target.json").write_text(json.dumps(remote["target"]))
            copy_env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith("EUGENE_PLEXUS_")
            }
            copy_env["OLLAMA_MODELS"] = str(stores[1])
            subprocess.run(
                [
                    str(python("agent")),
                    str(Path(__file__)),
                    "--output",
                    str(root),
                    "--check-copy",
                ],
                check=True,
                env=copy_env,
            )
            wrong = client.put(
                library_url + "/v1/nodes/another/ollama",
                headers={"Authorization": "Bearer " + service},
                json={"stores": [], "readAt": "2026-10-21T00:00:00Z"},
            )
            assert wrong.status_code == 403
            (stores[0] / "blobs" / ("sha256-" + digest)).unlink()
            assert Path(linked["target"]).read_bytes() == data
            assert remote["model"]["name"] == "tiny:latest"
        (root / "row65-result.json").write_text(
            json.dumps(
                {"passed": True, "libraryPort": library_port, "workerPort": worker_port}
            )
        )
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        for log in logs:
            log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--copy-folder", type=Path)
    parser.add_argument("--serve", choices=["library", "agent"])
    parser.add_argument("--check-copy", action="store_true")
    args = parser.parse_args()
    if args.check_copy:
        sys.path.insert(0, str(REPOS / "agent" / "src"))
        from eugene_plexus_agent import model_copies

        source = json.loads((args.output / "kept-target.json").read_text())
        target = args.output / "worker-copies" / "tiny.gguf"
        plan = model_copies.CopyPlan(source, source, str(target))
        settings = model_copies.CopySettings(True, str(target.parent), 0)
        model_copies.copy_file(
            plan,
            settings,
            model_copies.CopyState(str(target), Path(source).stat().st_size),
        )
        assert any(
            os.path.samefile(target, blob)
            for blob in (args.output / "worker-store" / "blobs").iterdir()
        )
    elif args.serve:
        serve(args.serve, args.output)
    else:
        assert args.copy_folder, "--copy-folder is required"
        run(args.output.resolve(), args.copy_folder.resolve())
