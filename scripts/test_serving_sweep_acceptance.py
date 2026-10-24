"""Check the CI measurement instrument without starting any processes."""

import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def module():
    spec = importlib.util.spec_from_file_location(
        "serving_acceptance", HERE / "serving-sweep-acceptance.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_fixture_processes_get_a_cleared_environment_and_shared_harness(tmp_path):
    acceptance = module()
    with patch.dict(
        os.environ, {"EUGENE_PLEXUS_AGENT_CONFIG_FILE": "LIVE", "eugene_plexus_other": "LIVE"}
    ):
        env = acceptance.child_environment(tmp_path)
    assert not any(k.upper().startswith("EUGENE_PLEXUS_") for k in env)
    command = acceptance.agent_command(tmp_path, 40123, 40124)
    assert "s8-ui-acceptance.py" in command[1]
    assert command[2:] == ["--serve", str(tmp_path), "--port", "40123", "--machine-port", "40124"]


def test_acceptance_refuses_default_ports_and_checks_all_six_promises():
    acceptance = module()
    ports = acceptance.free_ports(12)
    assert len(set(ports)) == 12
    assert not set(ports) & set(range(8079, 8084))
    assert acceptance.CHECKS == {
        "streams",
        "agents",
        "replicas-cloud",
        "foreign",
        "cancel-revoke",
        "restart-stale",
    }


def test_terminal_client_uses_the_same_job_doors():
    source = (HERE / "serving-sweep.py").read_text(encoding="utf-8")
    assert "/v1/serving-measurements" in source
    assert "--replay" in source
    assert "--ttft-threshold-ms" in source and "--speed-ratio-threshold" in source


def test_fixture_streams_usage_and_keeps_a_prefix_cache_without_a_listener():
    import json

    from fastapi.testclient import TestClient

    acceptance = module()
    with TestClient(acceptance.fixture_app()) as client:
        body = {
            "model": "m",
            "messages": [{"role": "user", "content": "Session fixture. " + "corpus " * 100}],
            "max_tokens": 2,
            "stream": True,
        }
        response = client.post("/v1/chat/completions", json=body)
        assert response.status_code == 200
        assert response.text.count('"content": "word "') == 2
        second = client.post("/v1/chat/completions", json=body)
        frames = [
            json.loads(line[6:]) for line in second.text.splitlines() if line.startswith("data: {")
        ]
        assert frames[-1]["usage"]["prompt_tokens_details"]["cached_tokens"] > 0
        assert frames[-1]["usage"]["completion_tokens"] == 2
        assert client.get("/stats").json() == {"requests": 2, "cloud": 0}
