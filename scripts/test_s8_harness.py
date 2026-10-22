"""The shared acceptance harness starts the agent the way an install does (roadmap row 2).

`s8-ui-acceptance.py --serve` is how ten acceptance scripts start an agent. It
used to build its own app (`create_app`) and its own uvicorn server, so a check
through it tested the harness: no console log copy, no machine port, no client
doors. These tests fake the agent's modules, so no agent install is needed, and
fail while the harness builds anything itself.

Run: python -m pytest scripts/test_s8_harness.py
(the harness imports httpx and PyYAML, which the integration job has).
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HARNESS = Path(__file__).resolve().with_name("s8-ui-acceptance.py")


def load_harness() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("s8_ui_acceptance", HARNESS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeSettings:
    """What the harness hands to the agent: a record of the keyword arguments."""

    model_fields: dict[str, object] = {
        "config_file": None,
        "bind_port": None,
        "default_topology": None,
        "machine_port": None,
    }

    def __init__(self, **fields: object) -> None:
        unknown = set(fields) - set(self.model_fields)
        if unknown:  # as pydantic-settings does for an agent that lacks the field
            raise TypeError(f"unknown settings: {sorted(unknown)}")
        self.fields = fields


class OlderSettings(FakeSettings):
    """An agent before the machine port (v0.3.0 and older)."""

    model_fields = {"config_file": None, "bind_port": None, "default_topology": None}


class Agent:
    """Fake `eugene_plexus_agent` modules, and everything the harness did to them."""

    def __init__(self, *, has_serve: bool = True, has_build_server: bool = True,
                 settings: type[FakeSettings] = FakeSettings) -> None:
        self.calls: list[tuple[str, object]] = []
        self.stop_seen: list[bool] = []
        package = types.ModuleType("eugene_plexus_agent")
        package.__path__ = []  # type: ignore[attr-defined]
        entry = types.ModuleType("eugene_plexus_agent.__main__")
        settings_module = types.ModuleType("eugene_plexus_agent.settings")
        settings_module.Settings = settings  # type: ignore[attr-defined]
        app_module = types.ModuleType("eugene_plexus_agent.app")
        capture = types.ModuleType("eugene_plexus_agent.console_logging")

        def create_app(*args: object, **kwargs: object) -> None:
            self.calls.append(("create_app", kwargs))
            raise AssertionError("the harness built its own app instead of the agent's start path")

        def install_console_capture(**kwargs: object) -> None:
            self.calls.append(("install_console_capture", kwargs))

        app_module.create_app = create_app  # type: ignore[attr-defined]
        capture.install_console_capture = install_console_capture  # type: ignore[attr-defined]

        if has_serve:

            def serve(settings: object, *, unattended: bool = False, should_stop: object = None) -> None:
                self.calls.append(("serve", {"settings": settings, "unattended": unattended}))
                assert callable(should_stop)
                self.stop_seen.append(bool(should_stop()))

            entry.serve = serve  # type: ignore[attr-defined]
        if has_build_server:

            def build_server(settings: object, *, unattended: bool = False) -> object:
                self.calls.append(("build_server", {"settings": settings, "unattended": unattended}))
                return _OldServer(self)

            entry.build_server = build_server  # type: ignore[attr-defined]
        self.modules = {
            "eugene_plexus_agent": package,
            "eugene_plexus_agent.__main__": entry,
            "eugene_plexus_agent.settings": settings_module,
            "eugene_plexus_agent.app": app_module,
            "eugene_plexus_agent.console_logging": capture,
        }

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


class _OldServer:
    """The uvicorn server of an agent without `serve`: `run` returns when told to stop."""

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.should_exit = False

    def run(self) -> None:
        import time

        for _ in range(200):
            if self.should_exit:
                self.agent.calls.append(("stopped", None))
                return
            time.sleep(0.01)
        raise AssertionError("the harness never stopped the agent's own server")


class HarnessServeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = load_harness()
        self.root = Path(tempfile.mkdtemp(prefix="s8-harness-test-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))

    def run_serve(self, agent: Agent, port: int = 49321, machine_port: int | None = None) -> str:
        out = io.StringIO()
        with mock.patch.dict(sys.modules, agent.modules), contextlib.redirect_stdout(out):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("S8_HARNESS_RESTARTS", None)
                if machine_port is None:
                    self.harness.serve(self.root, port)
                else:
                    self.harness.serve(self.root, port, machine_port)
        return out.getvalue()

    def test_serve_goes_through_the_agents_own_start_path(self) -> None:
        agent = Agent()
        self.run_serve(agent)
        self.assertEqual(agent.names(), ["serve"], agent.calls)
        call = dict(agent.calls)["serve"]
        assert isinstance(call, dict)
        self.assertIs(call["unattended"], True)
        fields = call["settings"].fields
        self.assertEqual(fields["bind_port"], 49321)
        self.assertEqual(fields["config_file"], self.root / "agent.yaml")
        self.assertIs(fields["default_topology"], False)
        self.assertNotIn(fields["machine_port"], range(8079, 8084))
        self.assertNotIn(fields["machine_port"], range(8279, 8284))
        self.assertNotEqual(fields["machine_port"], 49321)
        # An install turns the machine port and the client doors on in `build_server`;
        # the harness leaves both unset so that happens here too.
        self.assertNotIn("machine_port_enabled", fields)
        self.assertNotIn("client_doors_enabled", fields)

    def test_the_stop_file_is_what_asks_the_agent_to_stop(self) -> None:
        agent = Agent()
        self.run_serve(agent)
        self.assertEqual(agent.stop_seen, [False])
        (self.root / "stop").touch()
        agent = Agent()
        self.run_serve(agent)
        self.assertEqual(agent.stop_seen, [True])

    def test_a_machine_port_given_on_the_command_line_is_used(self) -> None:
        agent = Agent()
        self.run_serve(agent, machine_port=49400)
        call = dict(agent.calls)["serve"]
        assert isinstance(call, dict)
        self.assertEqual(call["settings"].fields["machine_port"], 49400)

    def test_an_agent_without_a_machine_port_is_not_given_one(self) -> None:
        agent = Agent(settings=OlderSettings)
        self.run_serve(agent, machine_port=49400)
        call = dict(agent.calls)["serve"]
        assert isinstance(call, dict)
        self.assertNotIn("machine_port", call["settings"].fields)

    def test_an_agent_without_serve_runs_its_build_server(self) -> None:
        agent = Agent(has_serve=False, settings=OlderSettings)
        (self.root / "stop").touch()
        said = self.run_serve(agent)
        self.assertEqual(agent.names(), ["build_server", "stopped"], agent.calls)
        self.assertIs(dict(agent.calls)["build_server"]["unattended"], True)  # type: ignore[index]
        self.assertIn("has no serve(should_stop); running its build_server", said)
        self.assertNotIn("create_app", agent.names())
        self.assertNotIn("install_console_capture", agent.names())

    def test_an_agent_older_than_build_server_is_refused_by_name(self) -> None:
        agent = Agent(has_serve=False, has_build_server=False)
        with self.assertRaises(SystemExit) as stopped:
            self.run_serve(agent)
        message = str(stopped.exception)
        self.assertIn("predates build_server", message)
        self.assertIn("v0.2.0 is the oldest supported", message)
        self.assertEqual(agent.calls, [])

    def test_a_restarted_agent_says_so(self) -> None:
        agent = Agent()
        out = io.StringIO()
        with mock.patch.dict(sys.modules, agent.modules), contextlib.redirect_stdout(out):
            with mock.patch.dict(os.environ, {"S8_HARNESS_RESTARTS": "1"}):
                self.harness.serve(self.root, 49321)
        self.assertIn("agent restarted in place (entry point)", out.getvalue())

    def test_the_hand_copied_start_path_is_gone(self) -> None:
        source = HARNESS.read_text(encoding="utf-8")
        for copied in ("create_app", "install_console_capture", "GRACEFUL_SHUTDOWN_SECONDS",
                       "uvicorn.Config"):
            if copied in source:
                self.fail(f"the harness copies the agent's {copied} again")


class FreePortTests(unittest.TestCase):
    def test_an_os_assigned_port_is_never_a_default_or_a_live_install_port(self) -> None:
        harness = load_harness()
        for _ in range(20):
            port = harness.free_port()
            self.assertNotIn(port, range(8079, 8084))
            self.assertNotIn(port, range(8279, 8284))
        self.assertNotEqual(harness.free_port(49999), 49999)


if __name__ == "__main__":
    unittest.main()
