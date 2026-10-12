#!/usr/bin/env python3
"""Sabotage pass for the MR6 acceptance (2026-10-12): break the product once each, run the checks
the break can reach, and see them fail.

An acceptance whose checks cannot fail proves nothing, so each break here is one the acceptance has
to catch, run with `--only` for the checks that can see it (a pass over the whole script for each
would be minutes for nothing):

  normalisation   the driver serves a logit backend's scores unnormalised (`score=raw`): D5 fails
                  (the driver's own schema refuses a score over 1, so bge answers 5xx and D4 fails)
  clamp           the driver clamps a logit into 0..1 instead of the logistic: D5 fails (the
                  scores are in range, in the wrong places, and tied)
  second-tier     the gateway's `pick_rerank` is given a second tier, so a slot's next target is
                  reached: D11b and D11c fail (the slot is answered by bge, which logs the request)
  catalogue       the agent's catalogue entry for Open WebUI loses `RAG_RERANKING_MODEL`: O1a, O3,
                  O5b, O5d and O5e fail (no sorter is configured, so none is called)
  preexisting     the "shipped" entry is the one from before MR6 (agent eb89e58), so an existing
                  install has nothing to be migrated to, and its documents go to OpenAI: O3b, O7b
                  and O7c fail
  unbatched       the entry loses RAG_EMBEDDING_BATCH_SIZE and RAG_EMBEDDING_CONCURRENT_REQUESTS:
                  Open WebUI sends one request a passage, all at once, past the key's 8 at a time:
                  O4a and O4b fail
  batch-64        the entry batches 64 passages to a request, not 32: O9a fails
  old-agent       the agent as it was before the app key's limits and the refusal to start without
                  the gateway's address (commit 0f24cba, imported from a `git archive` of it): O8
                  and O10 fail

The two source breaks edit a file in a sibling repo and put it back from a COPY (never
`git checkout --`: a checkout would take the work being checked with it), with the copy's hash
and the repo's `git status` checked afterwards. The copy is kept under the system temporary
directory with a manifest, so a pass that is killed can be undone with `--restore`. The catalogue
breaks edit nothing: the acceptance renders from a copy of the catalogue (`--catalogue`), and the
old agent is a `git archive`, so a session working in the agent's tree is never in the way.

Usage (the acceptance's own model arguments, then the breaks to run; none is all of them):

    agent/.venv/Scripts/python.exe specs/scripts/mr6-rerank-sabotage.py \\
        --llama-server PATH/llama-server.exe --qwen3-reranker ... --bge-reranker ... \\
        --embedding-model ... --chat-model ... --open-webui-venv PATH/owui-venv [LABEL ...]
    agent/.venv/Scripts/python.exe specs/scripts/mr6-rerank-sabotage.py --restore

Exit status 0 when every break that ran was caught.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPOS = HERE.parents[1]
ACCEPTANCE = HERE / "mr6-rerank-acceptance.py"
KEPT = Path(tempfile.gettempdir()) / "mr6-sabotage-copies"
MANIFEST = KEPT / "manifest.json"

DRIVER = REPOS / "inference-driver/src/eugene_plexus_inference_driver/engines/openai_compat_http.py"
GATEWAY = REPOS / "gateway/src/eugene_plexus_gateway/routing.py"
CATALOGUE = REPOS / "agent/src/eugene_plexus_agent/apps_catalogue.yaml"
#: The agent's last commit before MR6 (its catalogue is the entry an existing install started with).
PRE_FIX_AGENT = "eb89e58"
#: The agent before an app's key had an app's limits and a start needed the gateway's address.
OLD_AGENT = "0f24cba"

LOGISTIC = "score=_logistic(raw) if scale is RerankScale.logit else raw,"
FIRST_TIER = """        eligible = [b for b in resolution.first_model() if b.reranks]
        if not eligible:
            return None
        ordered = [b.client for b in self._order(resolution.model, eligible)]
        return TieredClient(name=resolution.model, tiers=[ordered], hooks=self)

    def pick_speech("""
EVERY_TIER = """        tiers: list[list[DriverClient]] = []
        for tier in resolution.tiers:
            eligible = [b for b in tier.eligible() if b.reranks]
            tiers.append([b.client for b in self._order(tier.target, eligible)] if eligible else [])
        if not any(tiers):
            return None
        return TieredClient(name=resolution.model, tiers=tiers, hooks=self)

    def pick_speech("""


@dataclass
class Break:
    label: str
    what: str
    only: str
    #: The checks this break must make fail.
    expect: tuple[str, ...]
    #: A source break: the file, the text to replace and what to put there.
    path: Path | None = None
    old: str = ""
    new: str = ""
    #: The agent's code from this commit, imported from a `git archive` of it.
    agent_at: str = ""


BREAKS = {
    b.label: b
    for b in [
        Break("normalisation", "the driver serves a logit backend's scores unnormalised",
              "D1,D2,D4,D5", ("D5",), DRIVER, LOGISTIC, "score=raw,"),
        Break("clamp", "the driver clamps a logit into 0..1 instead of the logistic",
              "D1,D2,D4,D5", ("D5",), DRIVER, LOGISTIC,
              "score=min(1.0, max(0.0, raw)) if scale is RerankScale.logit else raw,"),
        Break("second-tier", "pick_rerank is given a second tier", "D1,D11", ("D11b", "D11c"),
              GATEWAY, FIRST_TIER, EVERY_TIER),
        Break("catalogue", "Open WebUI's entry loses RAG_RERANKING_MODEL", "O1,O2,O3,O4,O5,O6",
              ("O1a", "O3", "O5b", "O5d", "O5e")),
        Break("preexisting", "the shipped entry is the one from before MR6", "O3,O7",
              ("O3b", "O7b", "O7c")),
        Break("unbatched", "the entry loses its embeddings batch size and concurrency", "O1,O2,O3,O4",
              ("O4a", "O4b")),
        Break("batch-64", "the entry batches 64 passages to a request", "O1,O2,O3,O4,O9", ("O9a",)),
        Break("old-agent", "the agent before an app key's limits and the refusal to start "
              "without the gateway's address", "O8,O10", ("O8", "O10"), agent_at=OLD_AGENT),
    ]
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", check=False)
    return (done.stdout or done.stderr).strip()


def manifest() -> dict[str, dict[str, str]]:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}


def save(data: dict[str, dict[str, str]]) -> None:
    KEPT.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(data, indent=2), encoding="utf-8")


def restore() -> None:
    """Put back every file this script left changed, from its copy."""
    data = manifest()
    for target, entry in list(data.items()):
        Path(target).write_bytes(Path(entry["copy"]).read_bytes())
        print(f"restored {target}; hash {'matches' if sha(Path(target)) == entry['sha'] else 'DIFFERS'}")
        del data[target]
    save(data)


def catalogue_copy(label: str) -> Path:
    """The catalogue to render from for a catalogue break: a copy, never the agent's own file."""
    KEPT.mkdir(parents=True, exist_ok=True)
    out = KEPT / f"apps_catalogue.{label}.yaml"
    if label == "preexisting":
        text = git(REPOS / "agent", "show", f"{PRE_FIX_AGENT}:src/eugene_plexus_agent/apps_catalogue.yaml")
    else:
        lines = CATALOGUE.read_text(encoding="utf-8").splitlines(keepends=True)

        def hits(name: str) -> list[int]:
            found = [i for i, ln in enumerate(lines) if ln.lstrip().startswith(f"{name}:")]
            if len(found) != 1:
                raise SystemExit(f"{name} occurs {len(found)} times in the catalogue")
            return found

        if label == "catalogue":
            del lines[hits("RAG_RERANKING_MODEL")[0]]
        elif label == "unbatched":
            for name in ("RAG_EMBEDDING_BATCH_SIZE", "RAG_EMBEDDING_CONCURRENT_REQUESTS"):
                lines[hits(name)[0]] = ""
        elif label == "batch-64":
            i = hits("RAG_EMBEDDING_BATCH_SIZE")[0]
            lines[i] = re.sub(r'"\d+"', '"64"', lines[i])
        else:
            raise SystemExit(f"no catalogue break called {label!r}")
        text = "".join(lines)
    out.write_text(text, encoding="utf-8", newline="\n")
    return out


def agent_archive(commit: str) -> Path:
    """The agent's `src` as it was at `commit`, from the object store (the working tree is not read)."""
    where = Path(tempfile.mkdtemp(prefix=f"mr6-agent-{commit}-"))
    done = subprocess.run(["git", "-C", str(REPOS / "agent"), "archive", "--format=tar", commit],
                          capture_output=True, check=True)
    with tarfile.open(fileobj=io.BytesIO(done.stdout)) as tar:
        tar.extractall(where, filter="data")
    return where / "src"


def run_one(brk: Break, acceptance_args: list[str], out: Path) -> bool:
    extra: list[str] = []
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env["PYTHONUTF8"] = "1"
    repo = None
    archive: Path | None = None
    if brk.path is not None:
        repo = Path(*brk.path.parts[: brk.path.parts.index("src")])
        original = brk.path.read_bytes()
        text = original.decode("utf-8")
        if text.count(brk.old) != 1:
            raise SystemExit(f"{brk.label}: the text to replace occurs {text.count(brk.old)} times")
        if git(repo, "status", "--porcelain", "--untracked-files=no"):
            raise SystemExit(f"{brk.label}: {repo.name} has changes before the break; not touching it")
        KEPT.mkdir(parents=True, exist_ok=True)
        copy = KEPT / f"{brk.label}-{brk.path.name}"
        copy.write_bytes(original)
        data = manifest()
        data[str(brk.path)] = {"copy": str(copy), "sha": hashlib.sha256(original).hexdigest()}
        save(data)
        brk.path.write_bytes(text.replace(brk.old, brk.new).encode("utf-8"))
        print(f"BROKEN   {brk.label}: {brk.what} ({brk.path.name})", flush=True)
    elif brk.agent_at:
        archive = agent_archive(brk.agent_at)
        env["PYTHONPATH"] = str(archive)
        print(f"BROKEN   {brk.label}: {brk.what} (agent {brk.agent_at}, from `git archive`)", flush=True)
    else:
        extra = ["--catalogue", str(catalogue_copy(brk.label))]
        print(f"BROKEN   {brk.label}: {brk.what} (a copy of the catalogue)", flush=True)
    try:
        started = time.perf_counter()
        with out.open("wb") as log:
            subprocess.run([sys.executable, "-u", str(ACCEPTANCE), *acceptance_args,
                            "--allow-dirty", "--only", brk.only, *extra],
                           env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
        print(f"         the acceptance ran in {time.perf_counter() - started:.0f} s; output {out}", flush=True)
    finally:
        if archive is not None:
            shutil.rmtree(archive.parent, ignore_errors=True)
        if brk.path is not None and repo is not None:
            data = manifest()
            entry = data.pop(str(brk.path), None)
            if entry is not None:
                brk.path.write_bytes(Path(entry["copy"]).read_bytes())
                save(data)
                same = sha(brk.path) == entry["sha"]
                clean = not git(repo, "status", "--porcelain", "--untracked-files=no")
                print(f"RESTORED {brk.path.name} from its copy; hash {'matches' if same else 'DIFFERS'}; "
                      f"{repo.name} {'clean' if clean else 'NOT clean'}", flush=True)
                if not (same and clean):
                    raise SystemExit(f"{brk.label}: the file was not put back as it was")
    failed = [ln.split()[1] for ln in out.read_text(encoding="utf-8", errors="replace").splitlines()
              if ln.startswith("FAIL")]
    missed = [label for label in brk.expect if label not in failed]
    verdict = "CAUGHT " if not missed else "ESCAPED"
    print(f"{verdict}  {brk.label}: expected to fail {list(brk.expect)}; failed {failed}"
          + (f"; NOT failed {missed}" if missed else ""), flush=True)
    return not missed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("labels", nargs="*", help=f"breaks to run ({', '.join(BREAKS)}); none is all")
    parser.add_argument("--restore", action="store_true", help="put back any file left broken")
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()),
                        help="where each break's acceptance output is written")
    names = ("llama-server", "qwen3-reranker", "bge-reranker", "embedding-model", "chat-model",
             "open-webui-venv")
    for name in names:
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args()
    if args.restore:
        restore()
        return 0
    for label in args.labels:
        if label not in BREAKS:
            print(f"unknown break {label!r}; known: {', '.join(BREAKS)}")
            return 2
    given = {n: getattr(args, n.replace("-", "_")) for n in names}
    if any(v is None for v in given.values()):
        print("every model and engine argument of the acceptance is needed: " + ", ".join(
            f"--{n}" for n, v in given.items() if v is None))
        return 2
    acceptance_args = [part for n, v in given.items() for part in (f"--{n}", str(v))]
    caught = [run_one(BREAKS[label], acceptance_args, args.out / f"mr6-sabotage-{label}.txt")
              for label in (args.labels or list(BREAKS))]
    return 0 if all(caught) else 1


if __name__ == "__main__":
    sys.exit(main())
