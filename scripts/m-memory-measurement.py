"""MR8 and MV3: how often a model's memory writing is wrong, leaks or obeys a paste.

What is measured is Workbench's own code, imported from the Workbench checkout beside this
one: the labelled sets, the requests and the scorer are `memory_measure` (so Measure this
model on the Memory screen runs exactly these), and the verdict on each note is
`memory_suggest.read_answer`. This script only drives an engine.

Two paths (`workbench-memory-v2.md` section 27):

* `--path pass` (default): the background request, `memory_suggest.request_body`, sent as
  Eugene's driver sends it to `llama-server` (`reasoning_effort: none` as
  `chat_template_kwargs.enable_thinking: false`; `--thinking on` sends it as an older driver
  did, effort dropped).
* `--path tool`: a chat request with the person's messages as turns and the `remember` tool,
  streamed as Workbench streams a chat; each call's arguments judged by the same code.

Engines:

    # a local model: its own llama-server on its own port, killed at the end
    workbench/.venv/Scripts/python scripts/m-memory-measurement.py \
        --server DIR/llama-server.exe --model FILE.gguf --name NAME --gpu-layers 99 \
        [--samples 3] [--path pass|tool] [--tags 25] [--thinking off|on]

    # an outside model (the cloud reference): an OpenAI-compatible endpoint, the key read
    # from an environment variable and never printed
    workbench/.venv/Scripts/python scripts/m-memory-measurement.py \
        --endpoint https://api.openai.com/v1 --api-model MODEL --key-env OPENAI_API_KEY ...

    # after a rule or a label changes: judge every stored answer again, no engine
    workbench/.venv/Scripts/python scripts/m-memory-measurement.py --rescore

Data goes to `docs/acceptance/m-memory-data/`, one file a model and path;
`m-memory-summarize.py` prints the table and writes the measurements Workbench ships.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve()


def _load_workbench(src: Path):
    sys.path.insert(0, str(src))
    try:
        from eugene_plexus_workbench import memory_measure  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SystemExit(
            f"cannot import Workbench's memory_measure from {src} ({exc}); run this with "
            "Workbench's own .venv Python, or pass --workbench"
        ) from exc
    return memory_measure


_a5_spec = importlib.util.spec_from_file_location("a5", HERE.with_name("a5-tool-call-measurement.py"))
a5 = importlib.util.module_from_spec(_a5_spec)
_a5_spec.loader.exec_module(a5)  # type: ignore[union-attr]


def rescore(mm, out: Path) -> int:
    """Judge every stored answer again: the raw notes stay what the model wrote, and what the
    code lets through is what the code now lets through (and the labels now say)."""
    by_id = {s["id"]: s for s in mm.SETS}
    for path in sorted(out.glob("*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        for record in run["records"]:
            s = by_id[record["set"]]
            record["raw_score"] = mm.score(s, record.get("raw", []))
            if record.get("asked") and not record.get("unreadable"):
                kept, record["rejected"] = mm.judged(s, record["raw"])
                record["kept"] = kept
                record.pop("accepted", None)
            record["score"] = mm.score(s, record.get("kept", record.get("accepted", [])))
        run["sets"] = {k: {f: by_id[k][f] for f in ("category", "expect", "canary")}
                       for k in run["sets"]}
        run["rescored"] = True
        path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"rescored {path.name}", flush=True)
    return 0


def outside_post(url: str, key: str, body: dict, timeout: float) -> tuple[int | None, object]:
    """POST to an outside endpoint with its key, through the user's proxy settings."""
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    request.add_header("content-type", "application/json")
    request.add_header("authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return None, str(e)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--endpoint", help="an OpenAI-compatible base URL (an outside model)")
    parser.add_argument("--api-model", help="the outside model's id")
    parser.add_argument("--key-env", help="the environment variable holding the outside key")
    parser.add_argument("--name", help="how the table names the model (default: the file's stem)")
    parser.add_argument("--path", choices=["pass", "tool"], default="pass")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--context", type=int, default=8192)
    parser.add_argument("--gpu-layers", type=int, default=0)
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--thinking", choices=["off", "on"], default="off",
                        help="off: as Eugene's driver sends reasoning_effort none; on: effort dropped")
    parser.add_argument("--only", help="comma-separated set ids or categories")
    parser.add_argument("--workbench", type=Path, default=HERE.parents[2] / "workbench" / "src")
    parser.add_argument("--out", type=Path, default=HERE.parents[1] / "docs/acceptance/m-memory-data")
    parser.add_argument("--tags", type=int, default=0,
                        help="send the person's tag list as its first N tags of TAG_POOL (MV1)")
    parser.add_argument("--rescore", action="store_true",
                        help="judge the stored answers in --out again with Workbench's code as it is now; no engine")
    args = parser.parse_args()

    mm = _load_workbench(args.workbench)
    ms = mm.ms
    if args.rescore:
        return rescore(mm, args.out)
    outside = args.endpoint is not None
    if outside and not (args.api_model and args.key_env and os.environ.get(args.key_env)):
        parser.error("--endpoint needs --api-model and --key-env naming a variable that is set")
    if not outside and (args.server is None or args.model is None):
        parser.error("--server and --model (or --endpoint) are needed unless --rescore")
    name = args.name or (args.api_model if outside else args.model.stem)
    label = name + ("" if args.thinking == "off" else "+thinking")
    label += "+tool" if args.path == "tool" else ""
    label += f"+tags{args.tags}" if args.tags else ""
    tags = [ms.TagChoice(t, d) for t, d in mm.TAG_POOL[: args.tags]] if args.tags else []
    chosen = [s for s in mm.SETS if not args.only or s["id"] in args.only.split(",")
              or s["category"] in args.only.split(",")]
    args.out.mkdir(parents=True, exist_ok=True)
    process = None
    engine = None
    if outside:
        url = args.endpoint.rstrip("/") + "/chat/completions"
        key = os.environ[args.key_env]
        engine = f"outside: {args.endpoint}"
    else:
        port = a5.free_port()
        url = f"http://127.0.0.1:{port}/v1/chat/completions"
        log = Path(tempfile.gettempdir()) / f"m-memory-{label}.server.log"
        version = subprocess.run([str(args.server), "--version"], capture_output=True, text=True).stderr.strip()
        engine = version.splitlines()[0] if version else None
        process = a5.serve(args.server, args.model, port, log, args)
    print(f"{label}: {engine or '?'}; {len(chosen)} sets x {args.samples}", flush=True)
    dropped: set[str] = set()

    def send(body: dict) -> tuple[int | None, object]:
        if not outside:
            # What the driver does with it for a llama.cpp backend.
            if body.pop("reasoning_effort", None) == "none" and args.thinking == "off":
                body["chat_template_kwargs"] = {"enable_thinking": False}
            if args.path == "tool":
                return a5.post_streamed(url, body, timeout=600)
            return a5.post(url, body, timeout=600)
        body = {**body, "model": args.api_model}
        for k in dropped:
            body.pop(k, None)
        for _ in range(4):
            status, answer = outside_post(url, key, body, timeout=300)
            text = json.dumps(answer) if not isinstance(answer, str) else answer
            # A parameter this model does not take is dropped, once, and the request sent again.
            bad = next((k for k in ("reasoning_effort", "temperature", "max_tokens", "seed")
                        if status == 400 and k in body and k in text), None)
            if bad is None:
                return status, answer
            if bad == "max_tokens":
                body["max_completion_tokens"] = body.pop("max_tokens")
            else:
                body.pop(bad)
            dropped.add(bad)
        return status, answer

    records: list[dict] = []
    try:
        for s in chosen:
            for seed in range(1, args.samples + 1):
                body = (mm.chat_request(name, s["messages"], s["known"]) if args.path == "tool"
                        else mm.pass_request(name, s, tags))
                if body is None:
                    record = mm.record_of(s, args.path, seed, None, None)
                    records.append(record)
                    print(f"  {s['id']:>16} #{seed}  not asked (nothing left to read)", flush=True)
                    continue
                if not outside:
                    body["seed"] = seed
                started = time.perf_counter()
                status, answer = send(body)
                seconds = round(time.perf_counter() - started, 2)
                good = status == 200 and isinstance(answer, dict)
                record = mm.record_of(s, args.path, seed, answer if good else {}, seconds)
                choice = ((answer.get("choices") or [{}])[0] if good else {}) or {}
                message = choice.get("message") or {}
                usage = answer.get("usage", {}) if good else {}
                record.update({
                    "status": status, "finish": choice.get("finish_reason"),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "thought": bool(message.get("reasoning_content")) or "<think" in (message.get("content") or ""),
                })
                if not good or record["unreadable"]:
                    record["unreadable"] = True
                    record["content"] = (message.get("content") or "")[:600] if good else str(answer)[:600]
                records.append(record)
                sc = record["score"]
                print(f"  {s['id']:>16} #{seed}  raw {len(record['raw'])} kept {len(record['kept'])}"
                      f"  facts {len(sc['facts'])} false {len(sc['false'])} leak {sc['leaks']}"
                      f" inj {sc['injections']} wrongrep {sc['replaces_wrong']}  {seconds}s"
                      + ("  UNREADABLE" if record["unreadable"] else ""), flush=True)
    finally:
        if process is not None:
            process.kill()
            process.wait()
    result = {"model": label, "name": name, "path": args.path,
              "file": args.api_model if outside else args.model.name, "engine": engine,
              "thinking": args.thinking, "tags": args.tags,
              "today": mm.TODAY.isoformat(), "samples": args.samples,
              "measuredOn": time.strftime("%Y-%m-%d"),
              "sets": {s["id"]: {k: s[k] for k in ("category", "expect", "canary")} for s in chosen},
              "records": records}
    (args.out / f"{label}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{label}: wrote {args.out / (label + '.json')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
