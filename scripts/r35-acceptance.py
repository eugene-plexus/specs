"""R3.5: real filesystem links through a real library, including a restart.

Run with the library's dev interpreter. Uses port 8182, temporary state,
no inherited EUGENE_PLEXUS_* settings, and teardown of only its own PID.
Windows uses junctions without elevation; Linux uses symlinks. No GPU,
network download, agent, live library folder, or installed service is used.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--library", type=Path, default=Path(__file__).resolve().parents[2] / "library"
    )
    parser.add_argument("--port", type=int, default=8182)
    args = parser.parse_args()
    library = args.library.resolve()
    sys.path.insert(0, str(library))
    from tests.conftest import qwen_like_kv, write_gguf

    with socket.socket() as probe:
        if os.name == "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(("127.0.0.1", args.port))

    def link_directory(link: Path, target: Path) -> None:
        if os.name == "nt":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                check=True,
                capture_output=True,
            )
            assert link.is_junction()
        else:
            link.symlink_to(target, target_is_directory=True)
            assert link.is_symlink()

    checks = 0

    def passed(label: str) -> None:
        nonlocal checks
        checks += 1
        print(f"PASS {checks}: {label}", flush=True)

    with tempfile.TemporaryDirectory(prefix="ep-r35-") as temporary:
        work = Path(temporary)
        root = work / "models"
        plain = write_gguf(root / "plain.gguf", qwen_like_kv())
        target = write_gguf(work / "external" / "linked.gguf", qwen_like_kv())
        link_directory(root / "alias", target.parent)
        link_directory(target.parent / "back", root)
        linked_path = str(root / "alias" / target.name)
        original_bytes = {path: path.read_bytes() for path in (plain, target)}
        config = work / "config.yaml"
        config.write_text(
            yaml.safe_dump(
                {"modelRoots": [str(root)], "scanOnStartup": True, "catalogueEnabled": False}
            ),
            encoding="utf-8",
        )
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("EUGENE_PLEXUS_")
        }
        env.update(
            {
                "EUGENE_PLEXUS_LIBRARY_CONFIG_FILE": str(config),
                "EUGENE_PLEXUS_LIBRARY_STATE_FILE": str(work / "state.json"),
                "PYTHONPATH": str(library / "src"),
                "PYTHONPYCACHEPREFIX": str(work / "pycache"),
                "PYTHONUTF8": "1",
            }
        )
        process: subprocess.Popen[bytes] | None = None
        log_path = work / "library.log"
        with (
            log_path.open("wb") as log,
            httpx.Client(
                base_url=f"http://127.0.0.1:{args.port}", timeout=2, trust_env=False
            ) as client,
        ):

            def start() -> None:
                nonlocal process
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "eugene_plexus_library.app:create_app",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(args.port),
                    ],
                    cwd=work,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                deadline = time.perf_counter() + 20
                while time.perf_counter() < deadline:
                    assert process.poll() is None, "library exited before readiness"
                    try:
                        response = client.get("/v1/config")
                        if response.status_code == 200:
                            assert response.json()["modelRoots"][0]["path"] == str(root)
                            return
                    except httpx.TransportError:
                        continue
                raise AssertionError("library did not become ready")

            def stop() -> None:
                nonlocal process
                if process is not None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    process = None

            def scan(*, startup: bool = False) -> dict:
                if not startup:
                    assert client.post("/v1/scan").status_code == 202
                deadline = time.perf_counter() + 10
                while time.perf_counter() < deadline:
                    response = client.get("/v1/scan")
                    response.raise_for_status()
                    body = response.json()
                    if body["state"] != "scanning":
                        assert body["state"] == "done", body
                        return body
                raise AssertionError("scan did not settle; possible link cycle")

            def set_follow(value: bool) -> None:
                response = client.patch("/v1/config", json={"followSymlinks": value})
                response.raise_for_status()
                assert response.json()["applied"] == ["followSymlinks"]
                assert response.json()["rejected"] == []

            def models() -> dict[str, dict]:
                response = client.get("/v1/models")
                response.raise_for_status()
                return {model["path"]: model for model in response.json()["models"]}

            try:
                start()
                scan(startup=True)
                assert set(models()) == {str(plain)}
                passed("startup defaults to skipping linked directories")
                schema = client.get("/v1/config/schema").json()
                field = next(
                    field for field in schema["fields"] if field["key"] == "followSymlinks"
                )
                assert field["default"] is False and field["valueType"] == "boolean"
                passed("the existing config UI field is a default-off boolean")
                set_follow(True)
                result = scan()
                found = models()
                assert set(found) == {str(plain), linked_path}
                assert found[linked_path]["root"] == str(root)
                passed("PATCH takes effect without restart; the alias is the model path")
                assert any(
                    entry["path"] == str(root / "alias" / "back") and "cycle" in entry["detail"]
                    for entry in result["skipped"]
                )
                passed("an ancestor cycle terminates and is reported")
                model_id = found[linked_path]["id"]
                profile = client.post(
                    f"/v1/models/{model_id}/profiles",
                    json={"name": "tuned", "engine": "llama_cpp", "flags": {"contextSize": 4096}},
                )
                assert profile.status_code == 201
                saved = profile.json()
                set_follow(False)
                scan()
                assert models()[linked_path]["status"] == "missing"
                assert models()[str(plain)]["status"] == "present"
                passed(
                    "switching off marks a profiled alias missing without losing ordinary models"
                )
                set_follow(True)
                scan()
                assert models()[linked_path]["id"] == model_id
                assert models()[linked_path]["status"] == "present"
                passed("switching on restores the same identity")
                stop()
                start()
                result = scan(startup=True)
                assert result["filesScanned"] == 2
                assert models()[linked_path]["id"] == model_id
                assert models()[linked_path]["status"] == "present"
                passed("persisted setting controls the startup scan after a real process restart")
                assert client.get(f"/v1/models/{model_id}/profiles").json()["profiles"] == [saved]
                passed("the saved profile survives toggle, rescan, and restart")
                assert all(path.read_bytes() == content for path, content in original_bytes.items())
                passed("every model file remains byte-identical")
            except BaseException:
                print(
                    log_path.read_text(encoding="utf-8", errors="replace")[-6000:], file=sys.stderr
                )
                raise
            finally:
                stop()
        passed("only the owned library process was stopped")
    print(
        f"{checks} PASS; {'Windows junctions' if os.name == 'nt' else 'Linux symlinks'}; "
        "no live install touched"
    )


if __name__ == "__main__":
    main()
