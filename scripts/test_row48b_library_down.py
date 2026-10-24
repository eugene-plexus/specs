"""Acceptance isolation and the regression gate for row 48b."""

import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def acceptance():
    spec = importlib.util.spec_from_file_location("row48b", HERE / "row48b-library-down-acceptance.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_acceptance_clears_install_variables_and_uses_only_free_ports(tmp_path):
    module = acceptance()
    env = module.isolated_env(tmp_path, {"EUGENE_PLEXUS_AGENT_CONFIG_FILE": "live", "eugene_plexus_secret": "secret", "PATH": os.environ["PATH"]})
    assert not any(key.upper().startswith("EUGENE_PLEXUS_") for key in env)
    assert env["TEMP"] == env["TMP"] == str(tmp_path)
    ports = module.free_ports(6)
    assert len(set(ports)) == 6
    assert not set(ports) & set(range(8079, 8084))


def test_stale_bound_mutation_drops_values_during_an_unlimited_outage():
    script = (HERE / "r8-profile-checks.py").read_text(encoding="utf-8")
    case = script.split('("stale-bound",', 1)[1].split('("retry-backoff",', 1)[0]
    assert 'if limit is None:' in case
    assert 'age < fresh + 300' in case
