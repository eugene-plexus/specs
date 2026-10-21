"""Compare the installed durable run protocol with the contract under test."""

import json
from importlib.util import find_spec
from pathlib import Path


def checkout_contract(module: str) -> Path | None:
    """Find the vendored contract beside an installed consumer's src directory."""
    spec = find_spec(module)
    assert spec is not None and spec.origin, f"cannot locate installed {module}"
    source = Path(spec.origin).resolve()
    if source.parent.parent.name != "src":
        return None
    return source.parents[2] / "contracts/run-operations.json"


def verify_run_protocol(actual: dict, specs: Path, *, library_ref: str) -> None:
    """Candidates follow specs; pins must agree before reporting specs ahead."""
    contract = specs
    if not library_ref:
        contract = checkout_contract("eugene_plexus_library.run_operations")
        assert contract is not None, "pinned library must be installed from a source checkout"
    # UTF-8, as vendor-platform.py writes it (Windows defaults to cp1252).
    canonical = json.loads(contract.read_text(encoding="utf-8"))
    assert actual["paths"] == canonical["paths"], f"run protocol paths drifted from {contract}"
    assert actual["components"] == canonical["components"], (
        f"run protocol schemas drifted from {contract}"
    )
    if not library_ref:
        agent = checkout_contract("eugene_plexus_agent.run_worker")
        if agent is not None:
            assert json.loads(agent.read_text(encoding="utf-8")) == canonical, (
                f"agent's vendored run protocol {agent} differs from pinned library's {contract}"
            )
        if json.loads(specs.read_text(encoding="utf-8")) != canonical:
            print(
                "specs main is ahead of the pinned library's run protocol; "
                "the next ship moves the pins"
            )
