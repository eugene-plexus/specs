"""Sabotage pass for settings that tell the truth (2026-09-30).

Each sabotage puts back one way a setting lied -- in a component or in the
UI -- runs that repo's own settings-truth tests, and requires them to FAIL.
Restores are from byte copies taken before the first edit, never `git
checkout --`. It opens with a baseline assertion that every gate passes
unsabotaged, and refuses to start if any anchor is not found exactly once.

    python scripts/settings-sabotage.py [label filter | --from=N]

Every Python gate runs in that repo's own `.venv`; the UI gate is vitest.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SPECS = Path(__file__).resolve().parents[1]
ROOT = SPECS.parent


def src(repo: str, package: str, *parts: str) -> Path:
    return ROOT / repo / "src" / package / Path(*parts)


AGENT_STATE = src("agent", "eugene_plexus_agent", "state.py")
AGENT_UPDATES = src("agent", "eugene_plexus_agent", "updates.py")
AGENT_ROUTES_UPDATES = src("agent", "eugene_plexus_agent", "routes", "updates.py")
AGENT_ROUTES_CONFIG = src("agent", "eugene_plexus_agent", "routes", "config.py")
AGENT_SHARES = src("agent", "eugene_plexus_agent", "share_credentials.py")
AGENT_COMPANIONS = src("agent", "eugene_plexus_agent", "companions.py")
GW_CONFIG = src("gateway", "eugene_plexus_gateway", "config.py")
GW_APP = src("gateway", "eugene_plexus_gateway", "app.py")
GW_ROUTING = src("gateway", "eugene_plexus_gateway", "routing.py")
LIB_CONFIG = src("library", "eugene_plexus_library", "config.py")
LIB_SOURCES = src("library", "eugene_plexus_library", "catalogue_sources.py")
CTL_CONFIG = src("control", "eugene_plexus_control", "config.py")
CTL_ROUTES = src("control", "eugene_plexus_control", "routes", "config.py")
DRV_CONFIG = src("inference-driver", "eugene_plexus_inference_driver", "config.py")
DRV_INFO = src("inference-driver", "eugene_plexus_inference_driver", "routes", "info.py")
TOOL_CONFIG = src("tool-driver", "eugene_plexus_tool_driver", "config.py")
UI = ROOT / "ui" / "src"
UI_FIELD = UI / "components" / "ConfigField.tsx"
UI_VALUE = UI / "lib" / "configValue.ts"
UI_PRESENT = UI / "lib" / "configPresentation.ts"
UI_TRIO = UI / "lib" / "configTrio.ts"
UI_UPDATES = UI / "lib" / "updates.ts"
UI_LIMITS = UI / "components" / "home" / "ClientKeyLimitsEditor.tsx"
UI_PROFILE = UI / "components" / "ProfileEditor.tsx"
UI_FOLDERS = UI / "components" / "LibraryFolders.tsx"


def venv(repo: str) -> str:
    return str(ROOT / repo / ".venv" / "Scripts" / "python.exe")


def pytest(repo: str, *tests: str) -> tuple[list[str], Path]:
    return [venv(repo), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests], ROOT / repo


GATES = {
    "agent": pytest(
        "agent",
        "tests/test_settings_truth.py",
        "tests/test_updates.py",
        "tests/test_share_credentials.py",
        "tests/test_companion_config_is_the_operators.py",
    ),
    "gateway": pytest("gateway", "tests/test_settings_truth.py"),
    "library": pytest("library", "tests/test_settings_truth.py", "tests/test_default_roots.py"),
    "control": pytest("control", "tests/test_config.py"),
    "driver": pytest(
        "inference-driver", "tests/test_settings_truth.py", "tests/test_runtime_following.py"
    ),
    "tool": pytest("tool-driver", "tests/test_settings_truth.py"),
    "ui": (
        [
            "cmd",
            "/c",
            "npx",
            "vitest",
            "run",
            "src/components/ConfigFieldTruth.test.tsx",
            "src/components/ConfigFieldEnum.test.tsx",
            "src/components/ShareCredentials.test.tsx",
            "src/components/ProfileEditor.test.tsx",
            "src/components/LibraryFoldersOverrides.test.tsx",
            "src/components/home/ClientKeyLimitsEditor.test.tsx",
            "src/lib/configValue.test.ts",
            "src/lib/configTrio.test.ts",
            "src/lib/updates.test.ts",
        ],
        ROOT / "ui",
    ),
}


@dataclass(frozen=True)
class Sabotage:
    label: str
    edits: tuple[tuple[Path, str, str], ...]
    gate: str
    #: Why it is expected to ESCAPE, when it is.
    escapes: str | None = None


def one(label: str, gate: str, path: Path, old: str, new: str, escapes: str | None = None) -> Sabotage:
    return Sabotage(label, ((path, old, new),), gate, escapes)


SABOTAGES: list[Sabotage] = [
    # --- the agent: the update channel -------------------------------------------------
    one("an older build is placed as newer (different means newer again)", "agent", AGENT_UPDATES,
        "        if commit_date(get, name, pinned) > commit_date(get, name, mine):\n",
        "        if True:\n"),
    one("a part the target predates is not counted ahead", "agent", AGENT_UPDATES,
        "            if mine is not None:\n                ahead.append(name)\n",
        "            if False:\n                ahead.append(name)\n"),
    one("an update is offered with a part ahead", "agent", AGENT_UPDATES,
        "        return bool(self.behind) and not self.ahead\n",
        "        return bool(self.behind)\n"),
    one("the route installs a downgrade's refusal as 'up to date'", "agent", AGENT_ROUTES_UPDATES,
        "        if view.ahead:\n", "        if False:\n"),
    one("a pending install is not settled by its check", "agent", AGENT_UPDATES,
        "            self._settle(channel)\n", "            pass\n"),
    one("a pending install checks a channel it guessed", "agent", AGENT_UPDATES,
        "        if channel is None:\n", "        if False:\n"),
    one("a result for another channel is still offered", "agent", AGENT_UPDATES,
        "        if result.channel is not None and channel is not None and result.channel is not channel:\n",
        "        if False:\n"),
    one("a pending channel is shown as the default", "agent", AGENT_STATE,
        '                doc["updateChannel"] = None if self._channel_settling else default_update_channel()\n',
        '                doc["updateChannel"] = default_update_channel()\n'),
    one("the environment's default is ignored", "agent", AGENT_STATE,
        '    return raw if raw in UPDATE_CHANNELS else "releases"\n', '    return "releases"\n'),
    one("a settled install is settled again at every boot", "agent", AGENT_STATE,
        "        if self._channel_marker().exists():\n            return False\n        from .updates",
        "        if False:\n            return False\n        from .updates"),
    one("a container is left pending instead of settled from its image", "agent", AGENT_STATE,
        "        if image:\n", "        if False:\n"),
    one("a reset writes the default into the file", "agent", AGENT_STATE,
        "                    if new_value is None:\n                        self._config.pop(key, None)\n",
        "                    if new_value is None:\n                        self._config[key] = None\n"),
    one("a null in agent.yaml is shown as null", "agent", AGENT_STATE,
        "                    merged[k] = field.default if v is None and field.default is not None else v\n",
        "                    merged[k] = v\n"),
    one("every share login reads as having a password", "agent", AGENT_SHARES,
        '                "hasPassword": has_password(entry),\n', '                "hasPassword": True,\n'),
    one("a reset of share logins is refused again", "agent", AGENT_ROUTES_CONFIG,
        "    if patch[SHARE_CREDENTIALS_KEY] is None:\n", "    if False:\n"),
    one("securityMode says restart required again", "agent", AGENT_STATE,
        "        # for.\n    ),", "        # for.\n        requiresRestart=True,\n    ),"),
    one("passphrase_file with nowhere to keep it is not warned about", "agent", AGENT_ROUTES_CONFIG,
        '        path = live["passphrase_path"]\n        if path is None:\n',
        '        path = live["passphrase_path"]\n        if False:\n'),
    one("an unset engine path does not name what PATH finds", "agent", AGENT_ROUTES_CONFIG,
        'f"Not set: uses the `{script}` found on PATH ({found}), unless a runtime names "',
        'f"Not set: uses the `{script}` found on PATH, unless a runtime names "'),
    one("a new companion is not told its managed keys", "agent", AGENT_COMPANIONS,
        "            spawn=SpawnConfig(configFile=str(path), env=_companion_env()),\n",
        "            spawn=SpawnConfig(configFile=str(path)),\n"),
    one("an old companion is never given its managed keys", "agent", AGENT_COMPANIONS,
        "        env = dict(spawn.env or {}) | _companion_env()\n",
        "        env = dict(spawn.env or {})\n"),
    # --- the gateway -------------------------------------------------------------------
    one("the gateway's restart result is not per PATCH", "gateway", GW_CONFIG,
        "                if field.requiresRestart and self._values.get(key) != self._started.get(key):\n                    pending_restart.append(key)\n",
        "                if field.requiresRestart:\n                    pending_restart.append(key)\n"),
    one("a null in gateway.yaml is shown as null", "gateway", GW_CONFIG,
        "                    merged[k] = field.default if v is None and field.default is not None else v\n",
        "                    merged[k] = v\n"),
    one("the gateway stores NaN", "gateway", GW_CONFIG,
        "        if not math.isfinite(value):\n", "        if False:\n"),
    one("an empty origin list is not said to admit any website", "gateway", GW_CONFIG,
        '        "Empty: any website may call the three OpenAI paths from a browser. Every request "\n',
        '        "None. Every request "\n'),
    one("an unset controlUrl does not name the root in use", "gateway", GW_CONFIG,
        '            update["unsetResolvesTo"] = derived_control_url\n', "            pass\n"),
    one("a pending restart is not in the gateway's schema", "gateway", GW_CONFIG,
        '        if pending and field.key in pending:\n            update["pendingRestart"] = True\n',
        '        if pending and field.key in pending:\n            pass\n'),
    one("0 days of metrics runs as 7 again", "gateway", GW_APP,
        '                    7\n                    if store.get("metricsRetentionDays") is None\n',
        '                    7\n                    if not store.get("metricsRetentionDays")\n'),
    one("the refresh interval is captured at start", "gateway", GW_ROUTING,
        "            refresh_seconds if callable(refresh_seconds) else (lambda: float(refresh_seconds))\n",
        "            (lambda v=(refresh_seconds() if callable(refresh_seconds) else refresh_seconds): (lambda: float(v)))()\n"),
    # --- the library -------------------------------------------------------------------
    # LS4: a hub's token lives in `catalogueSources`, per entry. An empty
    # one forgets it; one a round trip never saw is kept; a saved one
    # reaches the hub's client, downloads included, at once.
    one("forgetting a hub's token keeps it", "library", LIB_SOURCES,
        "            if token is None:\n                old = previous.get(entry[\"id\"])\n",
        "            if not token:\n                old = previous.get(entry[\"id\"])\n"),
    one("a hub's token is lost in a round trip that never saw it", "library", LIB_SOURCES,
        "                if old:\n                    kept[\"token\"] = old\n",
        "                if False:\n                    kept[\"token\"] = old\n"),
    one("a saved token does not reach the hub client", "library", LIB_SOURCES,
        "            token=source.token or None,\n",
        "            token=None,\n"),
    one("the library's restart result is not per PATCH", "library", LIB_CONFIG,
        "                if field.requiresRestart and self._values.get(key) != self._started.get(key):\n                    pending_restart.append(key)\n",
        "                if field.requiresRestart:\n                    pending_restart.append(key)\n"),
    one("the default roots do not say where they come from", "library", LIB_CONFIG,
        '            update["defaultSource"] = (\n', '            update["description"] = (\n'),
    one("a null in library.yaml is shown as null", "library", LIB_CONFIG,
        "                    if _is_unset(field, value):\n                        value = field.default\n",
        "                    if False:\n                        value = field.default\n"),
    # --- the control root ----------------------------------------------------------------
    one("control's securityMode says restart required again", "control", CTL_CONFIG,
        "        # back in prompt mode comes back locked.\n    ),",
        "        # back in prompt mode comes back locked.\n        requiresRestart=True,\n    ),"),
    one("an anonymous caller is told what values are doing", "control", CTL_ROUTES,
        "    if _may_read(request):\n", "    if True:\n"),
    one("control's restart keys are not compared with what runs", "control", CTL_CONFIG,
        "    return [k for k in out if now.get(k) != running().get(k)]\n", "    return out\n"),
    one("control stores NaN", "control", CTL_CONFIG,
        "        and not math.isfinite(value)\n", "        and False\n"),
    # --- the inference driver ------------------------------------------------------------
    one("baseUrl is hidden where it is read", "driver", DRV_CONFIG,
        '        "baseUrl": http,\n', '        "baseUrl": ["openai_compat_custom", "systemone_custom"],\n'),
    one("apiKey stays hidden for TypeSafe", "driver", DRV_CONFIG,
        '        "apiKey": http,\n', ""),
    one("a key from the environment reads as not set", "driver", DRV_CONFIG,
        "        if env and os.environ.get(env):\n", "        if False:\n"),
    one("an agent-managed key can be PATCHed", "driver", DRV_CONFIG,
        "                if key in managed_keys():\n", "                if False:\n"),
    one("an empty driver key reads as saved", "driver", DRV_CONFIG,
        "        field.valueType == ConfigValueType.secret and isinstance(value, str) and not value.strip()\n",
        "        False\n"),
    one("/v1/info names the saved provider", "driver", DRV_INFO,
        '    provider_key = str(store.started("provider") or "") or None\n',
        '    provider_key = str(store.get("provider") or "") or None\n'),
    # --- the tool driver -----------------------------------------------------------------
    one("a null probe interval turns the probe off", "tool", TOOL_CONFIG,
        "                    merged[key] = field.default if _is_unset(field, value) else value\n",
        "                    merged[key] = value\n"),
    one("the tool-driver's restart result is not compared with what runs", "tool", TOOL_CONFIG,
        "                if field.requiresRestart and self._values.get(key) != self._started.get(key):\n                    pending.append(key)\n",
        "                if field.requiresRestart:\n                    pending.append(key)\n"),
    # --- the UI --------------------------------------------------------------------------
    one("an enum value that is not a choice is drawn as the first choice", "ui", UI_VALUE,
        '    if (typeof value === "string" && choices.includes(value)) return { kind: "value" };\n',
        '    if (typeof value === "string") return { kind: "value" };\n'),
    one("an unset enum with a default shows its first option (the original bug)", "ui", UI_FIELD,
        '      const showUnset = (unsettable || reading.kind === "unset") && !field.enumValues.includes("");\n',
        '      const showUnset = unsettable && !field.enumValues.includes("");\n'),
    one("a checkbox draws Boolean(value)", "ui", UI_FIELD,
        "          checked={shown}\n", "          checked={Boolean(value)}\n"),
    one("an unset field says nothing about what it does", "ui", UI_FIELD,
        '        {reading.kind === "unset" &&\n          !compound &&\n',
        "        {false &&\n          !compound &&\n"),
    one("an empty list reads 'none'", "ui", UI_VALUE,
        '    if (value.length === 0) return "empty";\n', '    if (value.length === 0) return "none";\n'),
    one("a URL list borrows the standby sentence again", "ui", UI_FIELD,
        "          copy={withEmpty(URL_LIST_COPY, field.unsetMeans)}\n", "          copy={URL_LIST_COPY}\n"),
    one("a pending restart is not shown", "ui", UI_FIELD,
        "        {field.pendingRestart && (\n", "        {false && (\n"),
    one("an agent-managed field is editable", "ui", UI_FIELD,
        "  const locked = pending || Boolean(field.managedBy);\n", "  const locked = pending;\n"),
    one("every share login reads as saved in the UI", "ui", UI_FIELD,
        "  return row.hasPassword ?? null;\n", "  return true;\n"),
    one("showWhen reads the document, not the effective value", "ui", UI_PRESENT,
        "  const target = JSON.stringify(effectiveValue(field.showWhen.key, values, fields));\n",
        "  const target = JSON.stringify(values[field.showWhen.key]);\n"),
    one("a write leaves the settings cache as it was", "ui", UI_TRIO,
        "  if (cache.size === 0) return;\n  cache.clear();\n  announce();\n",
        "  if (cache.size === 0) return;\n"),
    one("an older agent's 'available' is called newer", "ui", UI_UPDATES,
        "  const knowsOrder = Array.isArray(update.ahead);\n", "  const knowsOrder = true;\n"),
    one("a machine newer than its channel is not told so", "ui", UI_UPDATES,
        "  if (ahead.length > 0 && label) {\n", "  if (false) {\n"),
    one("a newer install is named after the older release", "ui", UI_UPDATES,
        "      update.behind.length === 0 &&\n      (update.ahead ?? []).length === 0\n",
        "      update.behind.length === 0\n"),
    one("a key allowed web_search reads as not allowed", "ui", UI_LIMITS,
        '  return value.allowedTools.some((t) => toolPattern(t).test("web_search"));\n',
        "  return false;\n"),
    one("an emptied limit is 0", "ui", UI_LIMITS,
        '  if (raw.trim() === "") return undefined;\n', '  if (raw.trim() === "") return 0;\n'),
    one("an unset profile flag shows the schema default", "ui", UI_PROFILE,
        "              value={flags[field.key]}\n",
        '              value={flags[field.key] ?? field.default ?? ""}\n'),
    one("a profile's own engine is drawn as the first one offered", "ui", UI_PROFILE,
        "            {!engines.some((e) => e.engine === engine) && (\n", "            {false && (\n"),
    one("an override is looked up by the exact string", "ui", UI_FOLDERS,
        '          const value = overrides[overrideKeyFor(overrides, folder.path)] ?? "";\n',
        '          const value = overrides[folder.path] ?? "";\n'),
    one("overrides that could not be read can be edited and saved over", "ui", UI_FOLDERS,
        "          busy={busy !== null || !overridesRead}\n", "          busy={busy !== null}\n"),
]


def run_gate(gate: str) -> int:
    command, cwd = GATES[gate]
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=900,
                            stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    lines = [line for line in (result.stdout + result.stderr).strip().splitlines() if line.strip()]
    print(f"    [{gate}] exit={result.returncode}  {lines[-1] if lines else ''}", flush=True)
    return result.returncode


def main() -> None:
    # vitest prints ✓ and ×; a redirected stdout on Windows is cp1252, and
    # the first UI gate's last line crashed the run (it restored, then died).
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only and only.startswith("--from="):
        chosen = SABOTAGES[int(only.split("=", 1)[1]) - 1 :]
    else:
        chosen = [s for s in SABOTAGES if only is None or only in s.label]
    files = {path for s in chosen for path, _, _ in s.edits}
    copies = {path: path.read_bytes() for path in files}
    for sabotage in chosen:
        for path, old, _ in sabotage.edits:
            if copies[path].decode("utf-8").replace("\r\n", "\n").count(old) != 1:
                raise SystemExit(f"anchor not found exactly once in {path.name}: {sabotage.label}")
    caught = 0
    escaped: list[str] = []
    expected: list[str] = []
    try:
        for gate in sorted({s.gate for s in chosen}):
            print(f"baseline: {gate} must pass unsabotaged", flush=True)
            if run_gate(gate) != 0:
                raise SystemExit(f"BASELINE FAILED: {gate} does not pass unsabotaged")
        print("baselines PASS\n", flush=True)
        for number, sabotage in enumerate(chosen, start=1):
            print(f"sabotage {number}: {sabotage.label}", flush=True)
            sources: dict[Path, str] = {}
            for path, old, new in sabotage.edits:
                source = sources.get(path, copies[path].decode("utf-8").replace("\r\n", "\n"))
                sources[path] = source.replace(old, new)
            for path, source in sources.items():
                path.write_text(source, encoding="utf-8", newline="\n")
            try:
                code = run_gate(sabotage.gate)
            finally:
                for path in sources:
                    path.write_bytes(copies[path])
            if code != 0:
                caught += 1
                print("    CAUGHT", flush=True)
            elif sabotage.escapes:
                expected.append(sabotage.label)
                print(f"    escaped, as expected: {sabotage.escapes}", flush=True)
            else:
                escaped.append(sabotage.label)
                print("    ESCAPED", flush=True)
    finally:
        for path, data in copies.items():
            path.write_bytes(data)
    print(f"\n{caught} of {len(chosen)} caught; {len(expected)} expected escapes; "
          f"{len(escaped)} unexpected escapes", flush=True)
    for label in escaped:
        print(f"  ESCAPED: {label}", flush=True)
    raise SystemExit(1 if escaped else 0)


if __name__ == "__main__":
    main()
