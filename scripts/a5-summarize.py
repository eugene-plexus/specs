"""A5: the per-model table from `docs/acceptance/a5-data/*.json`.

    python scripts/a5-summarize.py [DATA_DIR]

Prints markdown: one row per model with its answers by kind (engine, the
model's JSON, wrong, no call), then the failures by scenario, then each
non-ok answer's class and detail so a reader can check the classification.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "a5_measurement", Path(__file__).with_name("a5-tool-call-measurement.py")
)
measurement = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(measurement)  # type: ignore[union-attr]
SCENARIOS = {s["id"]: s for s in measurement.SCENARIOS}

KIND = {
    "ok": "ok",
    "unparsed_call": "engine",
    "engine_error": "engine",
    "choice_ignored": "engine",
    "broken_json": "json",
    "cut_off": "json",
    "truncated_valid": "json",
    "wrong_tool": "wrong",
    "bad_args": "wrong",
    "wrong_args": "wrong",
    # One of two calls, the other left for the next turn: allowed by
    # OpenAI's semantics, and an agent loop makes the second call after
    # the first result. Counted apart, not as a failure.
    "partial": "sequential",
    "unneeded_call": "wrong",
    "no_call": "no_call",
}


def coerce(value, schema: dict):
    """Schema-guided coercion of string-typed values: `"15"` for an integer,
    `"false"` for a boolean, a JSON string for an array or object."""
    kind = schema.get("type")
    if isinstance(value, str) and kind in ("integer", "boolean", "array", "object"):
        try:
            parsed = json.loads(value)
        except ValueError:
            return value
        if kind == "integer" and isinstance(parsed, int) and not isinstance(parsed, bool):
            return parsed
        if kind == "boolean" and isinstance(parsed, bool):
            return parsed
        if kind == "array" and isinstance(parsed, list):
            value = parsed
        elif kind == "object" and isinstance(parsed, dict):
            value = parsed
        else:
            return value
    if kind == "object" and isinstance(value, dict):
        props = schema.get("properties", {})
        return {k: coerce(v, props[k]) if k in props else v for k, v in value.items()}
    if kind == "array" and isinstance(value, list) and "items" in schema:
        return [coerce(v, schema["items"]) for v in value]
    return value


def reclassify(record: dict) -> dict:
    """What the harness could not see from one answer alone.

    * `forced` names a function in `tool_choice`, and llama-server b11303
      reads `tool_choice` as a string: an object falls back to `auto` with
      only a log warning (`json_value` in tools/server/server-common.h). So
      prose there is the engine ignoring the choice, not the model.
    * A schema break that type coercion repairs is the model typing a value
      as a string, which a schema-guided repair fixes; one it does not is
      the model choosing wrong.
    """
    record = dict(record)
    scenario = SCENARIOS.get(record["scenario"])
    if record["scenario"] == "forced" and record["class"] == "no_call":
        record["class"] = "choice_ignored"
    if record["class"] == "bad_args" and scenario is not None:
        calls = ((record.get("message") or {}).get("tool_calls") or []) if isinstance(record.get("message"), dict) else []
        offered = {t["function"]["name"]: t["function"]["parameters"] for t in scenario["tools"]}
        fixed = True
        for call in calls:
            function = call.get("function") or {}
            schema = offered.get(function.get("name"))
            try:
                args = json.loads(function.get("arguments") or "{}")
            except ValueError:
                fixed = False
                break
            if schema is None or measurement.schema_errors(coerce(args, schema), schema):
                fixed = False
                break
        record["coercible"] = bool(calls) and fixed
    return record


def main() -> int:
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "docs/acceptance/a5-data"
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(data.glob("*.json"))]
    if not runs:
        print(f"no data in {data}")
        return 1
    for run in runs:
        run["records"] = [reclassify(r) for r in run["records"]]
    print("| Model | Answers | OK | One call at a time | Engine | Model's JSON | Wrong "
          "| of which coercion fixes | No call | Engine: text a lenient parse recovers "
          "| Truncated but valid |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    scenario_failures: dict[str, Counter] = {}
    for run in runs:
        # The budget scenario is expected to cut off; it is reported apart.
        records = [r for r in run["records"] if r["scenario"] != "truncated"]
        kinds = Counter(KIND.get(r["class"], r["class"]) for r in records)
        repairable = sum(1 for r in records if r["class"] == "unparsed_call" and r.get("repairable"))
        coercible = sum(1 for r in records if r.get("coercible"))
        truncated = [r for r in run["records"] if r["scenario"] == "truncated"]
        hazard = sum(1 for r in truncated if r["class"] == "truncated_valid")
        print(f"| {run['model']} | {len(records)} | {kinds['ok']} | {kinds['sequential']} | "
              f"{kinds['engine']} | {kinds['json']} | "
              f"{kinds['wrong']} | {coercible} | {kinds['no_call']} | {repairable} | "
              f"{hazard} of {len(truncated)} |")
        for r in records:
            if r["class"] != "ok":
                scenario_failures.setdefault(r["scenario"], Counter())[r["class"]] += 1
    print("\nFailures by scenario (every model together):\n")
    print("| Scenario | Failures |\n|---|---|")
    for scenario, counts in sorted(scenario_failures.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"| {scenario} | " + ", ".join(f"{k} {v}" for k, v in counts.most_common()) + " |")
    print("\nEvery answer that was not ok:\n")
    for run in runs:
        for r in run["records"]:
            if r["class"] != "ok":
                detail = (r.get("detail") or r.get("text") or "").replace("\n", " ").replace("|", "/")[:160]
                print(f"- {run['model']} / {r['scenario']} #{r['seed']}: **{r['class']}**"
                      f" (finish {r.get('finish')}) {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
