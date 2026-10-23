"""Acceptance isolation and fixture generation; never starts an agent."""

import importlib.util
from pathlib import Path

import pytest


def acceptance():
    path = Path(__file__).with_name("row43-cards-left-acceptance.py")
    spec = importlib.util.spec_from_file_location("row43_acceptance", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixture_environment_removes_install_credentials_and_default_ports(tmp_path):
    module = acceptance()
    env = module.isolated_env(
        tmp_path,
        19043,
        {
            "PATH": "vendor",
            "EUGENE_PLEXUS_AGENT_MASTER_KEY": "secret",
            "eugene_plexus_gateway_bind_port": "8080",
            "HOME": "home",
        },
    )
    assert "EUGENE_PLEXUS_AGENT_MASTER_KEY" not in env
    assert "eugene_plexus_gateway_bind_port" not in env
    assert env["EUGENE_PLEXUS_AGENT_BIND_PORT"] == "19043"
    assert int(env["EUGENE_PLEXUS_AGENT_MACHINE_PORT"]) not in range(8079, 8084)
    assert str(tmp_path) in env["LD_LIBRARY_PATH"]


@pytest.mark.parametrize("broken", ["uuid", "context", "missing", "ready"])
def test_acceptance_rejects_a_wrong_card_or_unapplied_refit(broken):
    module = acceptance()
    runtime = {
        "status": "ready",
        "lastDevices": ["GPU-b"],
        "startedOnFewerCards": {
            "missing": [{"uuid": "GPU-a", "lastIndex": 0}],
            "changes": ["Context 32768 → 16384."],
        },
    }
    record = {"cuda": "GPU-b", "argv": ["--ctx-size", "16384"]}
    module.assert_launch(runtime, record, ["GPU-b"], 16384, ["GPU-a"])
    if broken == "uuid":
        record["cuda"] = "GPU-a"
    elif broken == "context":
        record["argv"] = ["--ctx-size", "32768"]
    elif broken == "missing":
        runtime["startedOnFewerCards"] = None
    else:
        runtime["status"] = "loading"
    with pytest.raises(AssertionError):
        module.assert_launch(runtime, record, ["GPU-b"], 16384, ["GPU-a"])
