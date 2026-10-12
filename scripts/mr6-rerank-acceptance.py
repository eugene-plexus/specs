#!/usr/bin/env python3
"""MR6 acceptance: the rerank door, and Open WebUI's document search through Eugene.

2026-10-12. A result sorter (reranker) scores each passage a search found against the question
(`POST /v1/rerank`: Jina's, Cohere's and Hugging Face TEI's bodies, one door), and Open WebUI
uses it as its external reranker. This is the whole of it, through the real stack, on a stack of
its own:

* a real agent (its own `main()`, `--unattended`) on free ports, supervising a real library, a
  real gateway and the real companion inference-driver it keeps for each runtime. The one thing
  moved is where the agent starts handing out runtime and driver ports (it has no setting for it
  and starts at 8090, where the live install draws its own);
* real `llama-server` processes (CPU, `-ngl 0`: the live install holds the GPU), started by the
  agent with `POST /v1/runtimes`: two sorters (Qwen3-Reranker, which answers probabilities, and
  bge-reranker-v2-m3, which answers logits), a search model, and a chat model;
* client keys minted by the agent, the gateway called with them as an app would;
* Open WebUI 0.11.4, installed in a scratch venv, started with the environment the agent's REAL
  launcher renders (`app_launcher.render_start`, from the catalogue's `open-webui` manifest).

What it asserts (the letters are the ones printed beside each result):

  D  the door, through the gateway, with a client key
     D1  GET /v1/models lists both sorters as exactly `rerank`, the embedder as `embeddings`, and
         the chat model as not `rerank`
     D2  Jina's body to Qwen3-Reranker: best first, the passages that answer above 0.9 and the
         others below 0.1, every score in 0..1, and the envelope (`object`, `id`, `model`, `usage`)
     D3  Cohere's body: objects (one with an extra field), `return_documents`, `top_n`
     D4  TEI's body to bge: a bare array; `return_text` adds the text; `raw_scores` gives the
         engine's own logits
     D5  bge's scores are 0..1 and in its raw logits' order, each the logistic of its raw
     D6  `model` left out: 400 naming both sorters; a key that may use one: answered by it; a key
         that may use none: 404
     D7  a chat model named: 400 in the door's words
     D8  an empty list: 200, no results, and no backend reached (read from the drivers' and
         engines' own logs, current to a marker sent after it)
     D9  1,001 passages, an object without `text`, and a passage longer than the model reads: 400,
         each naming what is wrong
     D10 the ignored settings are named, in order, and `truncate: false` alone names nothing
     D11 no cross-model failover: a slot whose targets are [Qwen3-Reranker, bge], Qwen3-Reranker
         stopped: the rerank fails and bge's own log shows it received nothing
     D12 same-model failover: two runtimes under one model id, one stopped while the gateway's table
         still lists it, so that it is tried first: every rerank answered, by that model, and a
         failover seen (the one setting this run changes while it runs is that table's refresh
         interval, held at 20 s for the burst and put back)
     D13 the gateway's metrics hold the rerank requests under door `rerank`, one row for each
     D14 a body over the embeddings door's 16 MiB limit is refused (413), not served
  O  Open WebUI's document search through Eugene
     O1  the launcher's render of Open WebUI's start: the search model, the sorter and the sorter's
         address and key seeded; with the embedder stopped it is still named, and the note says it
         is not running; with none listed at all the variable is left unset and the notes say why
     O2  Open WebUI started from that render, with the two changes sign-in needs and no others
     O3  its retrieval settings show what was seeded, and every OpenAI-compatible connection it
         holds for a feature (documents' embeddings, speech-to-text, text-to-speech, images) is the
         gateway's with the app's key, none naming api.openai.com (a document is not uploaded to an
         Open WebUI that would send it outside the install)
     O4  a 30-paragraph document, processed; the gateway served its embeddings to Open WebUI's key
     O5  Open WebUI's own retrieval and its chat, over that document: the code word found and
         answered, the sorter called through the gateway with more than one passage, its scores used
     O6  the sorter stopped: Open WebUI still answers, and the gateway's answer to the failed rerank
         names its cause
     O7  an install made before this change: a data directory started once with the entry as it was
         (agent eb89e58, rendered through today's launcher), then the corrected entry's render sets
         the launcher's one-start reset with its note, that start shows the gateway's addresses and
         the seeded models, and a third render does not reset again
     O8  the key the registry mints for an app has the limits of an app (8 at once, 600 a minute)
     O9  a file of about two hundred passages completes, its embeddings sent at most 32 to a
         request, one request at a time, none refused, and retrieval over it finds the code word
     O10 the entry rendered with no gateway address refuses the start, in words, and starts nothing
  S  the run itself: component heads, ambient variables dropped, what the agent logged, and that
     its teardown leaves no owned port listening

Safe beside a live install: every ambient EUGENE_PLEXUS_* variable is dropped (install.ps1 sets
them for the whole account), every port is chosen by the OS, the engines run on the CPU, and
nothing outside its own temporary directory is written (the models are hard-linked into it, and
Open WebUI's data directory, home and temporary files are inside it).

Run with the agent's interpreter (it has httpx, pyyaml and every component):

    agent/.venv/Scripts/python.exe specs/scripts/mr6-rerank-acceptance.py \\
        --llama-server PATH/llama-server.exe \\
        --qwen3-reranker qwen3-reranker-0.6b-q8_0.gguf --bge-reranker bge-reranker-v2-m3-Q8_0.gguf \\
        --embedding-model Qwen3-Embedding-0.6B-Q8_0.gguf --chat-model Qwen3-0.6B-Q4_K_M.gguf \\
        --open-webui-venv PATH/owui-venv

`--only D5,D11,O` runs only those checks (a sabotage pass runs the ones a break can reach), and
`--allow-dirty` lets it run with a component's working tree changed (a sabotage pass changes one
on purpose: the run of record refuses). `--catalogue FILE` renders Open WebUI's start from that
copy of the agent's catalogue instead of the shipped one (a sabotage of the catalogue). `--keep`
keeps the temporary directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import yaml

RESULTS: list[tuple[str, str, bool, str]] = []
SKIPPED: list[tuple[str, str]] = []
#: The checks this run was asked for (`--only`), or None for all of them.
ONLY: set[str] | None = None

#: The name the gateway's metrics know this run's own key by.
MAIN_KEY = "mr6-acceptance"
#: The agent's last commit before MR6: its catalogue is the entry an install made before the change
#: started Open WebUI with (O7).
PRE_FIX_AGENT = "eb89e58"

#: The agent's own entry point, run after the one setting it has no knob for is moved: the first
#: port it hands to a runtime or to the driver it keeps for it. That range starts at 8090, where
#: the live install draws its own, so this run starts it well away. Nothing else about the agent
#: is changed.
LAUNCHER = (
    "import os\n"
    "import eugene_plexus_agent.state as state\n"
    "state._RUNTIME_PORT_BASE = int(os.environ['MR6_PORT_BASE'])\n"
    "from eugene_plexus_agent.__main__ import main\n"
    "main()\n"
)

QUERY = "What is the capital of France?"
PASSAGES = [
    "Berlin is the capital of Germany.",
    "Paris is the capital and largest city of France.",
    "Bananas are a yellow fruit that grows in tropical regions.",
    "The capital of France is Paris, which stands on the river Seine.",
]
#: Which of the four answer the question, and which do not.
ANSWERING = (1, 3)
OTHERS = (0, 2)

#: What the signal-station paragraph says; nothing else in the document could know it.
CODE_WORD = "JACKDAW-7342"
ASKED = "What is the code word for the signal station side door? Reply with only the code word."

FILLER = [
    "The bakery on Harbour Lane opens at five each morning and sells out of its rye loaves by "
    "eight. The baker learned the recipe from her grandmother, who ran the same oven for forty "
    "years. On Saturdays she adds cardamom buns, and a queue forms along the wall before the "
    "shutters go up.",
    "Ferries leave the Skerry Point landing every ninety minutes between seven and nineteen "
    "hundred. The crossing to the mainland takes about forty minutes in calm weather and an hour "
    "when the swell is up. Bicycles travel free, and cars must be booked a day ahead because the "
    "deck holds only six.",
    "Tide tables for the point are printed each December and pinned to the board outside the "
    "harbour master's hut. Fishermen check them twice, once the night before and once at the "
    "slip, because the channel beside the old pier dries out at low water and has caught more "
    "than one careless keel.",
    "Every spring the village cuts seaweed from the rocks below the chapel. It is dried on racks "
    "along the shingle and sold to a garden supplier on the mainland. The money pays for new "
    "benches on the promenade, and the benches are always painted green because the first donor "
    "insisted on it.",
    "The school choir has fourteen members and rehearses in the church hall on Wednesday "
    "afternoons. They are working up a medley of sea shanties for the midwinter concert. The "
    "conductor, who also teaches arithmetic, says the basses are strong and the sopranos need "
    "more breath.",
    "The lifeboat station keeps a crew of nine volunteers on call. Pagers go off at any hour, "
    "and the boat can be in the water within eight minutes. Last year the crew answered eleven "
    "calls, most of them to small craft with failed engines, and one to a kayaker swept past the "
    "headland.",
    "The weather diary kept by the old schoolmaster runs unbroken for sixty-one years. He noted "
    "wind, cloud and the first frost of every autumn, and his notebooks fill a whole shelf in "
    "the library. Researchers from the university visit now and then to copy figures from the "
    "earliest volumes.",
    "Net-mending takes place in the long shed behind the fish market. Three women work there "
    "most days, tying new mesh into torn trawl nets with wooden needles that are older than any "
    "of them. A radio plays on a shelf, tuned permanently to the shipping forecast.",
    "The cheese market in the square runs on the first Sunday of the month. Farmers from the "
    "inland valleys bring wheels of hard cheese wrapped in cloth, and tasting is free. Prizes "
    "are given for the sharpest, the creamiest and the most unusual, though arguments about the "
    "judging last longer than the market.",
    "The old mill above the stream has not ground flour since the war, but its wheel still "
    "turns on festival days. A trust of local people repaired the sluice gate and replaced the "
    "rotten paddles. Visitors may climb to the loft, where the beams are scored with the tally "
    "marks of long-dead millers.",
    "The community garden occupies the lot where the cannery once stood. Raised beds of beans, "
    "kale and potatoes are tended by anyone with an hour to spare. A rain barrel collects water "
    "from the shed roof, and a notice asks that nobody pick the strawberries before the "
    "children have had their turn.",
    "The library opens at ten and closes at four, except on Thursdays when it stays open until "
    "seven for the reading circle. The front door sticks in damp weather and must be lifted "
    "slightly as it is pushed. The librarian keeps a list of requests for books she intends to "
    "order.",
    "Repairs to the footbridge over the creek began in March and finished three weeks behind "
    "schedule. The planks are now treated oak, and the handrails have been replaced with "
    "galvanised steel. A plaque at the east end records the names of the carpenters who "
    "volunteered their weekends.",
    "A grey cat named Pilchard went missing from the harbour cafe in October and was found nine "
    "days later asleep in a lobster crate on the far quay. He had put on weight. The cafe owner "
    "has since fitted a small bell to his collar, which he regards as an insult.",
    "The autumn fair fills the green with stalls selling jam, knitwear, driftwood carvings and "
    "secondhand books. There is a coconut shy, a tombola and a tug of war between the "
    "fishermen and the farmers. The fishermen have won four years running, a fact the farmers "
    "attribute to wet rope.",
    "Bicycle repairs are done on Tuesdays and Fridays in the lean-to beside the post office. "
    "Jonas, who runs it, can true a wheel by ear and keeps a drawer of odd spokes salvaged from "
    "abandoned frames. He charges what he thinks a job is worth and rarely thinks it is worth "
    "much.",
    # the fact goes here
    "The pottery class meets above the chandlery on Monday evenings. Beginners start with pinch "
    "pots and graduate to a wheel after a month. The kiln in the back room is fired every "
    "second weekend, and the glazes, mostly blues and greens, are mixed from recipes pinned to "
    "the wall.",
    "Sheep from the high pasture are sheared in June by a travelling crew of four. The fleeces "
    "are rolled and bagged beside the fold, and the whole flock is dipped afterwards. Children "
    "are allowed to watch from the wall, provided they keep their distance and their dogs on "
    "leads.",
    "The harbour master's annual report records 412 vessel movements, three groundings and one "
    "collision, which involved two rowing boats and a misplaced buoy. He recommends dredging the "
    "approach channel and installing brighter lamps at the pierhead. The council has promised "
    "to consider the matter at its next meeting.",
    "Lamp oil for the lighthouse arrives by barge on the first Monday of each quarter. The "
    "drums are hoisted by crane and rolled into the cellar beneath the tower. Although the lamp "
    "is electric now, the cellar is kept stocked in case of a long power cut.",
    "Rainwater is collected from the roofs of the terrace in a row of tanks painted white. In "
    "dry summers the tanks run low, and a rota decides who may fill their watering cans. "
    "Disputes over the rota are settled by the chair of the village committee, usually over "
    "tea.",
    "Three hives stand in the lee of the stone wall above the chapel. The bees feed on heather "
    "and clover, and the honey is dark and slightly bitter. It is sold in jars with handwritten "
    "labels at the post office, and the supply never lasts beyond the first week of September.",
    "The chapel bell is rung by a team of six on the first and third Sundays of the month. "
    "Their method has been handed down by ear, and no one has written it out. When a ringer is "
    "ill the others close up the gap, and the pattern changes in ways only the team can hear.",
    "The post is delivered on foot by a woman who has walked the same round for twenty-two "
    "years. She knows every dog by name and every letterbox by its squeak. In winter she wears "
    "a yellow oilskin, and the children say you can see her coming from the far end of the "
    "quay.",
    "The orchard behind the manse grows eleven kinds of apple, several of which have no name "
    "beyond the family that planted them. Pruning takes place in February, when the trees are "
    "bare, and the cuttings are burned in a drum at the corner of the plot.",
    "The little museum above the market hall displays harpoons, ships' lanterns, a barometer "
    "from a wrecked steamer and a case of knots tied by sailors in the last century. Admission "
    "is free, and donations go into a tin shaped like a lighthouse that the curator won at a "
    "raffle.",
    "Chimney sweeps are booked weeks ahead in autumn, when every household wants its flue "
    "cleared before the first fire. The village sweep, a cheerful man with a long brush and a "
    "longer ladder, drinks only tea while he works and refuses payment in fish.",
    "Before each winter storm season the council checks the sea wall, the slipways and the "
    "drains along the front. Sandbags are stacked beside the harbour hut, and neighbours "
    "exchange telephone numbers. The first gale of the year usually arrives in the third week "
    "of October and takes at least one dustbin lid.",
    "At the end of the summer the village holds a lantern walk along the cliff path. Children "
    "carry paper lanterns they have made themselves, and the procession ends at the beach with "
    "hot chocolate. Nobody has ever managed to light all the lanterns at once, though the "
    "attempt is made every year.",
]
FACT = (
    "The night keeper of the Skerry Point signal station changes the code word for the station's "
    f"side door every Thursday. This week the code word for the signal station side door is "
    f"{CODE_WORD}, and the keeper asks that it be told only to the relief crew."
)


def document_text() -> str:
    """Thirty paragraphs, one of which holds the made-up fact, the seventeenth."""
    paragraphs = [*FILLER[:16], FACT, *FILLER[16:]]
    return "\n\n".join(paragraphs) + "\n"


def big_document_text(paragraphs: int = 600) -> str:
    """Hundreds of paragraphs, each its own (a made-up entry number leads it, so no two chunks
    are alike), with the same made-up fact five eighths of the way through: about two hundred
    chunks once Open WebUI has cut it at its default size."""
    out: list[str] = []
    for n in range(paragraphs):
        if n == paragraphs * 5 // 8:
            out.append(FACT)
        out.append(f"Log entry {n + 1:04d}. {FILLER[n % len(FILLER)]}")
    return "\n\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# printing
# --------------------------------------------------------------------------- #


def base_of(label: str) -> str:
    found = re.match(r"[A-Z]\d+", label)
    return found.group(0) if found else label


def wants(label: str) -> bool:
    """Whether `--only` asks for this check: its own label, its number (D4 for D4a), or its
    letter (D for every D)."""
    if ONLY is None:
        return True
    return label in ONLY or base_of(label) in ONLY or label[:1] in ONLY


def wants_any(letter: str) -> bool:
    return ONLY is None or any(item[:1] == letter for item in ONLY)


def check(label: str, claim: str, ok: bool, detail: object = "") -> bool:
    shown = str(detail)
    if len(shown) > 420:
        shown = shown[:417] + "..."
    RESULTS.append((label, claim, bool(ok), shown))
    print(f"{'PASS' if ok else 'FAIL'}  {label:<4} {claim}" + (f"  -- {shown}" if shown else ""),
          flush=True)
    return bool(ok)


def skip(label: str, claim: str, why: str) -> None:
    SKIPPED.append((label, claim))
    print(f"SKIP  {label:<4} {claim}  -- {why}", flush=True)


def info(text: str) -> None:
    print(f"INFO  {text}", flush=True)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def free_ports(count: int) -> list[int]:
    held = [socket.socket() for _ in range(count)]
    try:
        for sock in held:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in held]
    finally:
        for sock in held:
            sock.close()


def listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def wait_until(what: str, probe: Callable[[], Any], seconds: float, every: float = 1.0) -> Any:
    """Wait for the subject itself: `probe()` answers something truthy, or the time runs out."""
    deadline = time.perf_counter() + seconds
    last: Any = None
    while time.perf_counter() < deadline:
        try:
            last = probe()
        except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError, OSError):
            last = None
        if last:
            return last
        time.sleep(every)
    info(f"never saw: {what}")
    return None


def link(source: Path, destination: Path) -> None:
    """Hard link when the volume allows, a copy otherwise: the original is never touched."""
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_environment() -> dict[str, str]:
    """This process's environment without any of the live install's own variables."""
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}


def kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def logistic(x: float) -> float:
    if x >= 0.0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def said(response: httpx.Response) -> str:
    """What a refusal says, in its own words: an OpenAI-shaped `error.message`, or the body."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        detail = body.get("detail")
        if isinstance(detail, dict):
            return str(detail.get("detail") or detail.get("title") or detail)
    return str(body)[:300]


def scored(body: Any) -> dict[int, float]:
    """index -> score from either answer shape: `results[].relevance_score` or TEI's bare array."""
    if isinstance(body, dict):
        rows = [(r["index"], r["relevance_score"]) for r in body.get("results", [])]
    else:
        rows = [(r["index"], r["score"]) for r in body]
    return dict(rows)


def show(argv: list[str]) -> str:
    """A command line as the record prints it: the engine and the model by name."""
    words = [Path(argv[0]).name, *argv[1:]]
    if "--model" in words:
        words[words.index("--model") + 1] = Path(words[words.index("--model") + 1]).name
    return " ".join(words)


def provenance(llama_server: Path, linked: dict[str, Path]) -> None:
    """What this run used, so a record of it can be compared with the publishers' own numbers
    (the SHA-256 Hugging Face lists for each file, the digest GitHub lists for the build)."""
    try:
        done = subprocess.run(
            [str(llama_server), "--version"], capture_output=True, text=True, timeout=60,
            stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace", check=False,
        )
        words = [ln.strip() for ln in (done.stdout + done.stderr).splitlines()
                 if ln.startswith("version:")]
    except (OSError, subprocess.TimeoutExpired):
        words = []
    info(f"engine {llama_server}: {words[0] if words else 'version not readable'}")
    for label, path in linked.items():
        info(f"model {path.name} ({label}): {path.stat().st_size} bytes, sha256 {sha256(path)}")


def git(repo: Path, *args: str) -> tuple[int, str]:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
        errors="replace", stdin=subprocess.DEVNULL, check=False,
    )
    return done.returncode, (done.stdout or done.stderr).strip()


# --------------------------------------------------------------------------- #
# the stack
# --------------------------------------------------------------------------- #


class AgentLog:
    """The agent's own stdout, which carries every child's lines under its supervisor's prefix
    (`[engine: NAME]`, `[driver: NAME-driver]`, `[gateway]`), written as they arrive."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def lines(self) -> list[str]:
        return self.path.read_text(encoding="utf-8", errors="replace").splitlines()

    def count(self, source: str, *needles: str) -> int:
        prefix = f"[{source}]"
        return sum(
            1 for line in self.lines() if line.startswith(prefix) and all(n in line for n in needles)
        )


class Stack:
    """One agent, with the library and the gateway under it, and everything about them."""

    def __init__(self, work: Path, args: argparse.Namespace) -> None:
        self.work = work
        self.args = args
        ports = free_ports(3)
        self.agent_port, self.library_port, self.gateway_port = ports
        self.agent = f"http://127.0.0.1:{self.agent_port}"
        self.gateway = f"http://127.0.0.1:{self.gateway_port}"
        self.process: subprocess.Popen[bytes] | None = None
        self.log_path = work / "agent.log"
        self.log = AgentLog(self.log_path)
        self.client = httpx.Client(base_url=self.agent, timeout=120, trust_env=False)
        self.app = httpx.Client(timeout=300, trust_env=False)
        #: Every port this run's processes were given, learned as they are declared, so that
        #: teardown can say none is still listening.
        self.owned_ports = list(ports)
        base = free_ports(1)[0]
        self.port_base = base if base + 100 < 65000 else base - 1000

    # -- bring up --------------------------------------------------------------------

    def write_config(self, models: Path) -> None:
        (self.work / "library.yaml").write_text(
            yaml.safe_dump({"logLevel": "INFO", "modelRoots": [str(models)]}), encoding="utf-8"
        )
        # `routingRefreshSeconds` is how soon the gateway learns what the agent runs. The slot
        # `sorter` is a virtual alias nothing is launched under, whose targets are the two
        # sorters: what D11 asks the door to fail over across, and must not.
        (self.work / "gateway.yaml").write_text(
            yaml.safe_dump(
                {
                    "logLevel": "INFO",
                    "routingRefreshSeconds": 2,
                    "idleCheckSeconds": 2,
                    "requestTimeoutSeconds": 120,
                    "modelSlots": [
                        {"model": "sorter", "targets": ["qwen3-reranker", "bge-reranker"]}
                    ],
                }
            ),
            encoding="utf-8",
        )
        (self.work / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "securityMode": "prompt_on_startup",
                    # The directory the agent is told it may run an engine from.
                    "engineBinaryRoots": [str(Path(self.args.llama_server).resolve().parent)],
                    "components": [
                        {
                            "name": "library",
                            "kind": "library",
                            "url": f"http://127.0.0.1:{self.library_port}",
                            "spawn": {"configFile": str(self.work / "library.yaml")},
                        },
                        {
                            "name": "gateway",
                            "kind": "gateway",
                            "url": f"http://127.0.0.1:{self.gateway_port}",
                            "spawn": {"configFile": str(self.work / "gateway.yaml")},
                        },
                    ],
                    "runtimes": [],
                }
            ),
            encoding="utf-8",
        )

    def child_environment(self) -> dict[str, str]:
        env = clean_environment()
        env.update(
            {
                "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(self.work / "agent.yaml"),
                "EUGENE_PLEXUS_AGENT_BIND_HOST": "127.0.0.1",
                "EUGENE_PLEXUS_AGENT_BIND_PORT": str(self.agent_port),
                "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(self.work / "engines"),
                # The one case the agent cannot detect for itself; declared so no default
                # component (8080, 8082, 8083) is ever started beside the live install.
                "EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY": "0",
                "MR6_PORT_BASE": str(self.port_base),
                "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
                "PYTHONUNBUFFERED": "1",
                "PYTHONUTF8": "1",
            }
        )
        return env

    def start(self) -> None:
        log = self.log_path.open("wb")
        self.process = subprocess.Popen(
            [sys.executable, "-c", LAUNCHER, "--unattended"],
            cwd=self.work,
            env=self.child_environment(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        # Each runtime goes first, by the agent's own API (its driver goes with it), so the
        # engines are stopped by the agent and not by this script.
        try:
            for runtime in self.client.get("/v1/runtimes").json().get("runtimes", []):
                self.note_ports(runtime)
                self.client.delete(f"/v1/runtimes/{runtime['name']}")
        except (httpx.HTTPError, KeyError, ValueError):
            pass
        try:
            if os.name == "nt":
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.process.terminate()
        except OSError as exc:
            # No console to send a break through: end the agent's whole tree, which is every
            # component and engine it started and nothing else.
            info(f"could not ask the agent to stop ({exc}); ending its process tree")
            kill_tree(self.process.pid)
        try:
            self.process.wait(timeout=120)
        except subprocess.TimeoutExpired:
            kill_tree(self.process.pid)
            info("the agent did not stop in 120 s and its process tree was ended")

    # -- calls -----------------------------------------------------------------------

    def runtime(self, name: str) -> dict[str, Any]:
        response = self.client.get(f"/v1/runtimes/{name}")
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body

    def note_ports(self, runtime: dict[str, Any]) -> None:
        """Remember the ports a runtime and its driver were given, for the teardown check."""
        if isinstance(runtime.get("port"), int):
            self.owned_ports.append(runtime["port"])
        driver = runtime.get("driver")
        if driver:
            got = self.client.get(f"/v1/components/{driver}")
            if got.status_code == 200:
                self.owned_ports.append(int(str(got.json()["url"]).rsplit(":", 1)[1].rstrip("/")))

    def declare(self, body: dict[str, Any]) -> tuple[int, Any]:
        """Declare a runtime as a console does: the agent allocates its port, and keeps a
        companion driver for it."""
        response = self.client.post("/v1/runtimes", json=body)
        try:
            answer: Any = response.json()
        except ValueError:
            answer = response.text
        if response.status_code == 201 and isinstance(answer, dict):
            self.note_ports(answer)
        return response.status_code, answer

    def remove(self, name: str) -> None:
        """Take a runtime away, as a console's Remove does; its driver goes with it."""
        self.client.delete(f"/v1/runtimes/{name}")

    def lifecycle(self, name: str, action: str) -> int:
        return self.client.post(f"/v1/runtimes/{name}/{action}").status_code

    def status_of(self, name: str, wanted: str, seconds: float = 180) -> dict[str, Any] | None:
        def probe() -> dict[str, Any] | None:
            runtime = self.runtime(name)
            if runtime["status"] == "crashed" and wanted != "crashed":
                raise SystemExit(f"{name} crashed: {runtime.get('lastError')}")
            return runtime if runtime["status"] == wanted else None

        found: dict[str, Any] | None = wait_until(f"{name} {wanted}", probe, seconds, 1.0)
        return found

    def gateway_call(
        self, method: str, path: str, body: Any = None, key: str = ""
    ) -> httpx.Response:
        return self.app.request(
            method, f"{self.gateway}{path}", json=body, headers={"Authorization": f"Bearer {key}"}
        )

    def mint(self, name: str, limits: dict[str, Any] | None = None) -> str:
        """A client key as the agent mints one for an app."""
        body: dict[str, Any] = {"name": name, "ttlDays": 1}
        if limits is not None:
            body["limits"] = limits
        response = self.client.post("/v1/auth/client-keys", json=body)
        token = response.json().get("token", "") if response.status_code in (200, 201) else ""
        return str(token)

    def metric_rows(self) -> list[dict[str, Any]]:
        """Every row the gateway's metrics hold, newest first (operator-only: the agent's own
        proxy carries this run's session)."""
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(20):
            params: dict[str, Any] = {"limit": 500}
            if cursor:
                params["cursor"] = cursor
            response = self.client.get("/api/proxy/gateway/v1/metrics/requests", params=params)
            response.raise_for_status()
            page = response.json()
            rows.extend(page["requests"])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        return rows


def runtime_body(
    stack: Stack, name: str, model: Path, alias: str | None = None, *,
    flags: dict[str, Any] | None = None, **overrides: Any
) -> dict[str, Any]:
    """The declaration a console makes for a model, CPU only: `gpuLayers: 0`, and the pin that
    keeps admission and the engine off the card the live install holds."""
    body: dict[str, Any] = {
        "name": name,
        "engine": "llama_cpp",
        "modelPath": str(model),
        "modelAlias": alias or name,
        "binary": str(Path(stack.args.llama_server).resolve()),
        "env": {"CUDA_VISIBLE_DEVICES": "-1"},
        "flags": {"gpuLayers": 0, **(flags or {})},
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------- #
# Open WebUI
# --------------------------------------------------------------------------- #


class OpenWebUI:
    """Open WebUI 0.11.4, started from a venv as the agent starts it, with a rendered environment."""

    def __init__(self, work: Path, port: int, name: str = "open-webui") -> None:
        self.work = work
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self.log_path = work / f"{name}.log"
        self.process: subprocess.Popen[bytes] | None = None
        self.http = httpx.Client(base_url=self.url, timeout=600, trust_env=False)
        self.token = ""

    def start(self, argv: list[str], env: dict[str, str], cwd: Path) -> None:
        log = self.log_path.open("wb")
        self.process = subprocess.Popen(
            argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )

    def ready(self, path: str, seconds: float = 600) -> bool:
        def probe() -> bool:
            if self.process is not None and self.process.poll() is not None:
                raise SystemExit(
                    f"Open WebUI exited with code {self.process.returncode}: {self.tail()}"
                )
            return self.http.get(path, timeout=10).status_code == 200

        return bool(wait_until("Open WebUI ready", probe, seconds, 2.0))

    def stop(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.terminate()
            process.wait(timeout=30)
        except (subprocess.TimeoutExpired, OSError):
            kill_tree(process.pid)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                info("Open WebUI did not stop in 15 s after being killed")

    def tail(self, lines: int = 12) -> str:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return " | ".join(text.splitlines()[-lines:])[-900:]

    def log_lines(self, needle: str) -> list[str]:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return [line for line in text.splitlines() if needle in line]

    def api(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        return self.http.request(method, path, headers=headers, **kwargs)


def answer_of(body: Any) -> str:
    """The reply's text with a thinking model's `<think>` block taken off."""
    if not isinstance(body, dict):
        return ""
    message = ((body.get("choices") or [{}])[0] or {}).get("message") or {}
    text = str(message.get("content") or "")
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def registry_key_request(work: Path, app_id: str, node: str) -> dict[str, Any]:
    """What the agent's registry asks for when it mints an app's key: its own `_ensure_key`
    (routes/apps.py), run here on an app store of this run's own, with the mint itself captured
    and never sent. The agent's code is imported here and in `Kit`, and nowhere else."""
    import asyncio
    from types import SimpleNamespace

    from eugene_plexus_agent.apps import AppStore
    from eugene_plexus_agent.routes import apps as app_routes

    sent: dict[str, Any] = {}

    async def capture(_request: Any, body: Any, *, authorization: str | None = None) -> Any:
        sent["body"] = body
        return SimpleNamespace(token="not-a-key",
                               key=SimpleNamespace(id="captured-not-minted", name=body.name))

    manager = SimpleNamespace(store=AppStore(work / "registry-capture" / "apps.yaml"),
                              node_name=lambda: node)
    original = app_routes.mint_client_key
    app_routes.mint_client_key = capture
    try:
        asyncio.run(app_routes._ensure_key(SimpleNamespace(headers={}), manager, app_id))
    finally:
        app_routes.mint_client_key = original
    body = sent["body"]
    limits = body.limits.model_dump(mode="json", exclude_none=True) if body.limits else {}
    return {"name": body.name, "limits": limits}


class Kit:
    """Open WebUI's start as the agent's own launcher renders it. The agent's code is imported
    here and nowhere else in this script: its catalogue (`apps.load_catalogue`), the command that
    starts an app from its venv (`apps.entry_argv`) and the launcher's `render_start`."""

    def __init__(self, run: Run) -> None:
        from eugene_plexus_agent import app_launcher, apps

        self.run = run
        self.app_launcher, self.apps = app_launcher, apps
        venv = Path(run.args.open_webui_venv)
        self.python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.key_file = run.stack.work / "owui-key"
        self.key_file.write_text(run.keys["owui"], encoding="utf-8")

    def manifest(self, text: str | None) -> Any:
        """The `open-webui` entry of the shipped catalogue, or of `text`."""
        return next((m for m in self.apps.load_catalogue(text) if m.id == "open-webui"), None)

    def render(
        self, manifest: Any, data_dir: Path, port: int, *, gateway_known: bool = True
    ) -> tuple[list[str], dict[str, str], list[str]]:
        """One start's command, environment and notes, as the agent's launcher renders them: the
        spec is what the agent's `_AppPlanner.launch()` writes, `render_start` fills it in. The
        base environment is the account's with every EUGENE_PLEXUS_* variable dropped, and the
        home, caches and temporary files inside the app's own data directory, as the launcher
        gives an app's account. With `gateway_known` false the spec carries no gateway address,
        as the agent's does when it cannot say what it is."""
        stack = self.run.stack
        values = {"bindHost": "127.0.0.1", "port": str(port), "gatewayUrl": stack.gateway,
                  "appUrl": f"http://127.0.0.1:{port}"}
        if not gateway_known:
            del values["gatewayUrl"]
        spec = {
            "argv": self.apps.entry_argv(self.python, manifest),
            "args": [getattr(a, "root", a) for a in manifest.args or []],
            "environment": dict(manifest.environment or {}),
            "values": values,
            "resetOnConnectionChange": manifest.resetOnConnectionChange,
            "dataDir": str(data_dir),
            "keyFile": str(self.key_file),
            "oidcSecretFile": str(stack.work / "owui-no-oidc-secret"),
        }
        base = clean_environment()
        for name, where in (("HOME", ""), ("USERPROFILE", ""), ("APPDATA", "appdata"),
                            ("LOCALAPPDATA", "localappdata"), ("XDG_CACHE_HOME", "cache"),
                            ("TEMP", "tmp"), ("TMP", "tmp")):
            folder = data_dir / where if where else data_dir
            folder.mkdir(parents=True, exist_ok=True)
            base[name] = str(folder)
        base.update({"PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1",
                     "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
        rendered: tuple[list[str], dict[str, str], list[str]] = self.app_launcher.render_start(
            spec, base)
        return rendered

    @staticmethod
    def sign_in_for_the_test(env: dict[str, str]) -> list[str]:
        """The two changes this run makes to a rendered environment, and no others: sign-in by
        Open WebUI's own form (the entry's is Eugene's, which C4 proved), so the OAuth variables
        are dropped. Returns the names dropped."""
        removed = sorted(n for n in env if n.startswith(("OAUTH_", "OPENID_", "ENABLE_OAUTH_")))
        for name in removed:
            del env[name]
        env["ENABLE_LOGIN_FORM"] = "true"
        env["ENABLE_SIGNUP"] = "true"
        return removed


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #


class Run:
    def __init__(self, stack: Stack, linked: dict[str, Path], repos: Path) -> None:
        self.stack = stack
        self.args = stack.args
        self.linked = linked
        self.repos = repos
        self.keys: dict[str, str] = {}
        #: Reranks answered 200 with at least one passage, by the key's label: what D13 counts.
        self.served: Counter[str] = Counter()
        #: Tasks a 2-passage marker makes an engine run, learned once for each runtime.
        self.marker_tasks: dict[str, int] = {}
        #: Every Open WebUI this run started, for the teardown.
        self.owuis: list[OpenWebUI] = []
        #: What each component repo held when the run began, for S9.
        self.repo_state: dict[str, tuple[str, str]] = {}
        #: What the agent's registry sends to mint an app's key (`registry_key_request`), and the
        #: name the gateway's metrics know Open WebUI's key by.
        self.registry_key: dict[str, Any] = {}
        self.owui_key_name = ""

    # -- the door --------------------------------------------------------------------

    def rerank(self, key: str, body: dict[str, Any]) -> httpx.Response:
        response = self.stack.app.post(
            f"{self.stack.gateway}/v1/rerank", json=body,
            headers={"Authorization": f"Bearer {self.keys[key]}"},
        )
        passages = body.get("documents") or body.get("texts") or []
        if response.status_code == 200 and passages:
            self.served[key] += 1
        return response

    def ready_backends(self, key: str, model: str) -> int | None:
        """How many backends the gateway lists as ready for this model, for this key; None when
        the list does not name it."""
        response = self.stack.gateway_call("GET", "/v1/models", key=self.keys[key])
        if response.status_code != 200:
            return None
        for listed in response.json()["data"]:
            if listed["id"] == model:
                return int((listed.get("x_eugene_plexus") or {}).get("ready_backends") or 0)
        return None

    def in_gateway(
        self, key: str, wanted: dict[str, Callable[[list[str]], bool]], *, ready: int = 1,
        seconds: float = 120
    ) -> dict[str, Any]:
        """Each named model in the gateway's list for this key with enough backends ready and the
        surfaces asked for. The surfaces are learned by trying the engine, so the entry alone is
        not the thing to wait for. Returns the last look it had, matching or not."""
        seen: dict[str, Any] = {}

        def probe() -> bool | None:
            response = self.stack.gateway_call("GET", "/v1/models", key=self.keys[key])
            if response.status_code != 200:
                return None
            found = {m["id"]: m for m in response.json()["data"]}
            seen.clear()
            seen.update({n: found[n] for n in wanted if n in found})
            ok = all(
                n in found
                and ((found[n].get("x_eugene_plexus") or {}).get("ready_backends") or 0) >= ready
                and wanted[n]((found[n].get("x_eugene_plexus") or {}).get("surfaces") or [])
                for n in wanted
            )
            return True if ok else None

        wait_until(f"{', '.join(wanted)} ready in the gateway's list", probe, seconds, 1.0)
        return dict(seen)

    # -- what the engines and drivers say they were asked ----------------------------------

    def backend_counts(self, runtime: str) -> tuple[int, int]:
        """(rerank requests the runtime's driver made of its engine, tasks its engine ran), from
        the agent's own log, which carries both."""
        driver = self.stack.runtime(runtime)["driver"]
        requests = self.stack.log.count(f"driver: {driver}", "HTTP Request: POST", "/v1/rerank")
        tasks = self.stack.log.count(f"engine: {runtime}", "processing task")
        return requests, tasks

    def marker(self, model: str) -> httpx.Response:
        """A rerank of two passages sent straight to a model, after the thing being tested: it
        has to show in the log before the log is read, so what the log lacks is not lag."""
        return self.rerank("main", {"model": model, "query": "marker", "documents": ["one", "two"]})

    def tasks_per_marker(self, runtime: str, model: str) -> int:
        """How many tasks this engine's log shows for a 2-passage rerank: learned once, since a
        build that logs none cannot be asked what it was not sent."""
        if runtime not in self.marker_tasks:
            before = self.backend_counts(runtime)
            self.marker(model)
            wait_until("the calibration marker in the driver's log",
                       lambda: self.backend_counts(runtime)[0] >= before[0] + 1, 20, 0.5)
            time.sleep(1.5)
            self.marker_tasks[runtime] = self.backend_counts(runtime)[1] - before[1]
        return self.marker_tasks[runtime]

    def reached(
        self, runtime: str, model: str, action: Callable[[], Any]
    ) -> tuple[Any, int | None, int | None]:
        """Run `action`, then a marker straight to `model`, and say how many rerank requests
        reached `runtime`'s engine beyond the marker's own, and how many tasks it ran beyond the
        marker's. None when the marker never showed in the log (the log was not current)."""
        per_marker = self.tasks_per_marker(runtime, model)
        before = self.backend_counts(runtime)
        result = action()
        self.marker(model)
        arrived = wait_until(
            "the marker in the driver's log",
            lambda: self.backend_counts(runtime)[0] >= before[0] + 1, 20, 0.5,
        )
        time.sleep(1.5)
        after = self.backend_counts(runtime)
        if not arrived:
            return result, None, None
        return result, after[0] - (before[0] + 1), after[1] - (before[1] + per_marker)

    def say_reached(self, runtime: str, requests: int | None, tasks: int | None) -> str:
        per = self.marker_tasks.get(runtime, 0)
        if requests is None:
            return f"{runtime}: the marker never showed in the log"
        return (f"{runtime}'s driver made {requests} request(s) beyond the marker's, its engine "
                f"ran {tasks} task(s) beyond the marker's (a 2-passage marker is {per} tasks)")

    # ================================ phase D ================================

    def phase_d(self) -> None:
        stack = self.stack
        qwen, bge, chat, embedder = "qwen3-reranker", "bge-reranker", "chat", "embedder"

        # ---- D1 ---- (the wait is for every D check: the surfaces are learned by trying)
        seen = self.in_gateway(
            "main",
            {
                qwen: lambda s: s == ["rerank"],
                bge: lambda s: s == ["rerank"],
                embedder: lambda s: s == ["embeddings"],
                chat: lambda s: "chat" in s,
            },
        )
        surf = {n: (seen.get(n, {}).get("x_eugene_plexus") or {}).get("surfaces") for n in
                (qwen, bge, embedder, chat)}
        if wants("D1"):
            check("D1", "GET /v1/models: both sorters are exactly `rerank`, the embedder "
                  "`embeddings`, the chat model not `rerank`",
                  surf[qwen] == ["rerank"] and surf[bge] == ["rerank"]
                  and surf[embedder] == ["embeddings"]
                  and "rerank" not in (surf[chat] or ["?"]) and "chat" in (surf[chat] or []),
                  surf)

        # ---- D2 ----
        if wants("D2"):
            started = time.perf_counter()
            r = self.rerank("main", {"model": qwen, "query": QUERY, "documents": PASSAGES})
            took = time.perf_counter() - started
            body = r.json() if r.status_code == 200 else {}
            by_index = scored(body) if r.status_code == 200 else {}
            order = [x["relevance_score"] for x in body.get("results", [])]
            yes = [by_index.get(i, -1.0) for i in ANSWERING]
            no = [by_index.get(i, 2.0) for i in OTHERS]
            check("D2", "Jina body to Qwen3-Reranker: best first, the passages that answer above "
                  "0.9, the others below 0.1, every score in 0..1",
                  r.status_code == 200 and len(order) == 4
                  and all(a >= b for a, b in zip(order, order[1:], strict=False))
                  and body["results"][0]["index"] in ANSWERING
                  and min(yes) > 0.9 and max(no) < 0.1 and all(0.0 <= s <= 1.0 for s in order),
                  f"HTTP {r.status_code} in {took:.2f} s; answering {yes[0]:.4f}, {yes[1]:.4f}; "
                  f"others {no[0]:.5f}, {no[1]:.6f}" if r.status_code == 200
                  else f"HTTP {r.status_code} {said(r)}")
            usage = body.get("usage") or {}
            check("D2b", "and the envelope: object `list`, id `rerank-...`, model the sorter's "
                  "id, usage with tokens, no `document` unasked",
                  body.get("object") == "list" and str(body.get("id", "")).startswith("rerank-")
                  and body.get("model") == qwen and (usage.get("prompt_tokens") or 0) > 0
                  and all("document" not in x for x in body.get("results", [])),
                  {k: body.get(k) for k in ("object", "id", "model")} | {"usage": usage})

        # ---- D3 ----
        if wants("D3"):
            documents: list[dict[str, Any]] = [
                {"text": PASSAGES[0], "title": "a note", "id": "x-1"},
                {"text": PASSAGES[1]},
                {"text": PASSAGES[2]},
                {"text": PASSAGES[3]},
            ]
            r = self.rerank("main", {"model": qwen, "query": QUERY, "documents": documents,
                                     "return_documents": True, "top_n": 2})
            results = r.json().get("results", []) if r.status_code == 200 else []
            check("D3", "Cohere body, objects (one with an extra field), return_documents, top_n 2: "
                  "two results, the two that answer, each document.text exactly the sent text",
                  r.status_code == 200 and len(results) == 2
                  and {x["index"] for x in results} == set(ANSWERING)
                  and all(x.get("document", {}).get("text") == documents[x["index"]]["text"]
                          for x in results),
                  [(x["index"], round(x["relevance_score"], 4)) for x in results]
                  if r.status_code == 200 else f"HTTP {r.status_code} {said(r)}")

        # ---- D4 ----
        tei = {"model": bge, "query": QUERY, "texts": PASSAGES}
        if wants("D4"):
            r = self.rerank("main", tei)
            body = r.json() if r.status_code == 200 else None
            check("D4a", "TEI body (texts) to bge: a bare array of {index, score}, one for each "
                  "passage, scores in 0..1, no text unasked",
                  r.status_code == 200 and isinstance(body, list) and len(body) == 4
                  and all(set(x) == {"index", "score"} and 0.0 <= x["score"] <= 1.0 for x in body),
                  [(x["index"], round(x["score"], 5)) for x in body] if isinstance(body, list)
                  else f"HTTP {r.status_code} {said(r)}")
            r = self.rerank("main", {**tei, "return_text": True})
            body = r.json() if r.status_code == 200 else None
            check("D4b", "return_text: true adds each passage's text",
                  r.status_code == 200 and isinstance(body, list) and len(body) == 4
                  and all(x.get("text") == PASSAGES[x["index"]] for x in body),
                  f"HTTP {r.status_code}")
            r = self.rerank("main", {**tei, "raw_scores": True})
            body = r.json() if r.status_code == 200 else None
            raws = [x["score"] for x in body] if isinstance(body, list) else []
            check("D4c", "raw_scores: true gives the engine's own logits, some outside 0..1",
                  r.status_code == 200 and len(raws) == 4 and any(not 0.0 <= s <= 1.0 for s in raws),
                  [round(s, 3) for s in raws] if raws else f"HTTP {r.status_code} {said(r)}")

        # ---- D5 ----
        if wants("D5"):
            normal = self.rerank("main", tei)
            raw = self.rerank("main", {**tei, "raw_scores": True})
            ok = normal.status_code == 200 and raw.status_code == 200
            n = scored(normal.json()) if normal.status_code == 200 else {}
            w = scored(raw.json()) if raw.status_code == 200 else {}
            same_order = ok and len(n) == 4 and sorted(n, key=lambda i: -n[i]) == sorted(
                w, key=lambda i: -w[i])
            matches = ok and len(n) == 4 and all(
                abs(n[i] - logistic(w[i])) <= 1e-5 + 1e-4 * logistic(w[i]) for i in n)
            in_range = ok and len(n) == 4 and all(0.0 <= s <= 1.0 for s in n.values())
            check("D5", "bge's scores are 0..1, in the order of its raw logits, each the logistic "
                  "of its raw",
                  in_range and same_order and matches,
                  "raw -> score: " + ", ".join(f"{w[i]:.2f} -> {n[i]:.5f}" for i in sorted(
                      n, key=lambda i: -n[i])) if ok and n and w
                  else f"HTTP {normal.status_code}/{raw.status_code} "
                       f"{said(normal) if normal.status_code != 200 else said(raw)}")

        # ---- D6 ----
        if wants("D6"):
            documents2 = PASSAGES[:2]
            r = self.rerank("main", {"query": QUERY, "documents": documents2})
            message = said(r)
            check("D6a", "model left out with both sorters served to the key: 400 naming both",
                  r.status_code == 400 and qwen in message and bge in message,
                  f"HTTP {r.status_code} {message}")
            r = self.rerank("one", {"query": QUERY, "documents": documents2})
            check("D6b", "a key whose allowlist holds one sorter: answered by it",
                  r.status_code == 200 and r.json().get("model") == qwen,
                  f"HTTP {r.status_code} "
                  f"{r.json().get('model') if r.status_code == 200 else said(r)}")
            r = self.rerank("chatonly", {"query": QUERY, "documents": documents2})
            check("D6c", "a key that may use no sorter: 404 saying none is served to it",
                  r.status_code == 404 and "sorter" in said(r), f"HTTP {r.status_code} {said(r)}")

        # ---- D7 ----
        if wants("D7"):
            r = self.rerank("main", {"model": chat, "query": QUERY, "documents": PASSAGES[:2]})
            message = said(r)
            check("D7", "a chat model named: 400 in the door's words (the model, what it serves, "
                  "the door to use)",
                  r.status_code == 400 and chat in message and "rerank" in message
                  and "/v1/chat/completions" in message, f"HTTP {r.status_code} {message}")

        # ---- D8 ----
        if wants("D8"):
            def empty() -> tuple[httpx.Response, httpx.Response, httpx.Response, httpx.Response]:
                return (
                    self.rerank("main", {"model": qwen, "query": QUERY, "documents": []}),
                    self.rerank("main", {"model": qwen, "query": QUERY, "texts": []}),
                    self.rerank("main", {"model": "no-such-model", "query": QUERY, "documents": []}),
                    self.rerank("main", {"model": chat, "query": QUERY, "documents": []}),
                )

            (docs, texts, unknown, wrong), requests, tasks = self.reached(qwen, qwen, empty)
            docs_body = docs.json() if docs.status_code == 200 else {}
            check("D8a", "an empty `documents`: 200 with no results, and `texts` empty: a bare []",
                  docs.status_code == 200 and docs_body.get("results") == []
                  and docs_body.get("object") == "list" and texts.status_code == 200
                  and texts.json() == [], f"HTTP {docs.status_code}/{texts.status_code}")
            check("D8b", "and no rerank reached the backend (the driver's and the engine's own "
                  "log, current to a marker sent after)",
                  requests == 0 and tasks == 0, self.say_reached(qwen, requests, tasks))
            check("D8c", "after the model resolves: an unknown model is still 404, a chat model "
                  "still 400",
                  unknown.status_code == 404 and wrong.status_code == 400,
                  f"unknown HTTP {unknown.status_code}, chat HTTP {wrong.status_code}")

        # ---- D9 ----
        if wants("D9"):
            def refused() -> tuple[httpx.Response, httpx.Response]:
                return (
                    self.rerank("main", {"model": qwen, "query": QUERY,
                                         "documents": ["a passage"] * 1001}),
                    self.rerank("main", {"model": qwen, "query": QUERY, "documents": [
                        "one", "two", "three", {"title": "no text here"}, "five"]}),
                )

            (many, no_text), requests, tasks = self.reached(qwen, qwen, refused)
            check("D9a", "1,001 passages: 400 naming the limit",
                  many.status_code == 400 and "1,001" in said(many) and "1,000" in said(many),
                  f"HTTP {many.status_code} {said(many)}")
            check("D9b", "documents[3] an object without `text`: 400 naming documents[3]",
                  no_text.status_code == 400 and "documents[3]" in said(no_text),
                  f"HTTP {no_text.status_code} {said(no_text)}")
            check("D9c", "and neither reached a backend",
                  requests == 0 and tasks == 0, self.say_reached(qwen, requests, tasks))
            started = time.perf_counter()
            long = self.rerank("main", {"model": qwen, "query": QUERY,
                                        "documents": ["short", " ".join(["alpha"] * 6000)]})
            took = time.perf_counter() - started
            check("D9d", "a passage longer than the model reads (over the 2,048-token batch): 400 "
                  "naming the limit, not cut, not a server fault",
                  long.status_code == 400 and "2048" in said(long),
                  f"HTTP {long.status_code} in {took:.1f} s: {said(long)}")

        # ---- D10 ----
        if wants("D10"):
            two = PASSAGES[:2]
            r = self.rerank("main", {"model": qwen, "query": QUERY, "documents": two,
                                     "truncate": True, "max_chunks_per_doc": 10,
                                     "rank_fields": ["text"]})
            header = r.headers.get("x-eugene-plexus-ignored-settings")
            check("D10a", "truncate, max_chunks_per_doc and rank_fields sent: the "
                  "x-eugene-plexus-ignored-settings header names exactly those, in that order",
                  r.status_code == 200 and header == "truncate, max_chunks_per_doc, rank_fields",
                  f"HTTP {r.status_code}, header {header!r}")
            r = self.rerank("main", {"model": qwen, "query": QUERY, "documents": two,
                                     "truncate": False})
            check("D10b", "`truncate: false` alone: no header (it is what the door does)",
                  r.status_code == 200 and "x-eugene-plexus-ignored-settings" not in r.headers,
                  f"HTTP {r.status_code}, header {r.headers.get('x-eugene-plexus-ignored-settings')!r}")
            r = self.rerank("main", {"model": qwen, "query": QUERY, "documents": two,
                                     "rank_fields": ["text"], "max_tokens_per_doc": 512,
                                     "max_chunks_per_doc": 3, "truncation_direction": "Left",
                                     "truncate": True})
            header = r.headers.get("x-eugene-plexus-ignored-settings")
            check("D10c", "all five sent: named in the contract's order",
                  r.status_code == 200 and header == "truncate, truncation_direction, "
                  "max_chunks_per_doc, max_tokens_per_doc, rank_fields", f"header {header!r}")

        # ---- D14 ----
        if wants("D14"):
            passage = "a" * 1_000_000
            body = json.dumps({"model": qwen, "query": QUERY, "documents": [passage] * 17}).encode()

            def oversized() -> tuple[httpx.Response | None, str]:
                # A server that answers before it has read the whole body may close the
                # connection while the client is still writing; that is an answer to say, not a
                # crash of this run.
                try:
                    return stack.app.post(
                        f"{stack.gateway}/v1/rerank", content=body,
                        headers={"Authorization": f"Bearer {self.keys['main']}",
                                 "content-type": "application/json"},
                    ), ""
                except httpx.TransportError as exc:
                    return None, f"no HTTP answer: {type(exc).__name__}: {exc}"

            (r, why), requests, tasks = self.reached(qwen, qwen, oversized)
            check("D14a", f"a body of {len(body) / (1 << 20):.1f} MiB, over the embeddings door's "
                  "16 MiB limit: 413 naming the limit",
                  r is not None and r.status_code == 413 and "16 MiB" in said(r),
                  why if r is None else f"HTTP {r.status_code} {said(r)}")
            check("D14b", "and not served: nothing reached the backend",
                  requests == 0 and tasks == 0, self.say_reached(qwen, requests, tasks))

        # ---- D12 (before D11: D11 stops Qwen3-Reranker and starts it again) ----
        if wants("D12"):
            self.replicas()

        # ---- D11 ----
        if wants("D11"):
            self.no_cross_model(qwen, bge)

        # ---- D13 ----
        if wants("D13"):
            self.metrics_rows()

    def replicas(self) -> None:
        """D12: two runtimes of one model under one id."""
        stack = self.stack
        pair = "qwen3-pair"
        file = self.linked["qwen3-reranker"]
        for name in ("pair-a", "pair-b"):
            status, body = stack.declare(runtime_body(stack, name, file, alias=pair))
            if status != 201:
                check("D12", "two runtimes of Qwen3-Reranker under one model id are declared",
                      False, f"{name}: HTTP {status} {str(body)[:200]}")
                return
        up = [stack.status_of(n, "ready") for n in ("pair-a", "pair-b")]
        seen = self.in_gateway("main", {pair: lambda s: s == ["rerank"]}, ready=2)
        listed = (seen.get(pair, {}).get("x_eugene_plexus") or {})
        check("D12a", "the two runtimes are two replicas of one model: one entry, `rerank`, two "
              "backends ready", all(up) and listed.get("ready_backends") == 2
              and listed.get("surfaces") == ["rerank"],
              {k: listed.get(k) for k in ("surfaces", "ready_backends", "drivers")})

        def burst(count: int) -> list[tuple[int, str | None, str | None, int | None]]:
            out = []
            for _ in range(count):
                r = self.rerank("main", {"model": pair, "query": QUERY, "documents": PASSAGES})
                body = r.json() if r.status_code == 200 else {}
                route = body.get("x_eugene_plexus") or {}
                out.append((r.status_code, body.get("model"), route.get("runtime"),
                            route.get("attempts")))
            return out

        warm = burst(6)
        served = Counter(runtime for _s, _m, runtime, _a in warm)
        check("D12b", "both replicas answer while both are up (the balancer alternates)",
              all(s == 200 for s, *_ in warm) and set(served) == {"pair-a", "pair-b"},
              dict(served))

        # The gateway's table is up to `routingRefreshSeconds` behind the agent, so for that long
        # after a replica stops the gateway still lists it and sends it requests: the moment the
        # failover exists for. The harness refreshes every 2 s, which leaves a window of about a
        # second; the table is held for 20 s instead (the setting's own knob, put back below), so
        # that the replica that stops is certain to be tried first by some of the burst.
        self.routing_refresh(20)
        time.sleep(4)
        try:
            # Stopped by the agent, as the console's Stop does.
            stack.lifecycle("pair-b", "stop")
            stack.status_of("pair-b", "stopped", 60)
            after_stop = burst(6)
        finally:
            self.routing_refresh(2)
        runs = Counter(runtime for _s, _m, runtime, _a in after_stop)
        second = [t for t in after_stop if (t[3] or 1) >= 2]
        check("D12c", "one replica stopped, the table still listing it: every rerank is answered "
              "by that model, by the other replica, and at least one was first sent to the "
              "stopped one and failed over (a second attempt, on the same model)",
              all(s == 200 and m == pair for s, m, *_ in after_stop) and set(runs) == {"pair-a"}
              and bool(second),
              f"statuses {[s for s, *_ in after_stop]}, attempts {[a for *_, a in after_stop]}, "
              f"served by {dict(runs)}")
        for name in ("pair-a", "pair-b"):
            stack.remove(name)

    def routing_refresh(self, seconds: int) -> None:
        """Set the gateway's `routingRefreshSeconds` (its own setting, live: it takes effect at
        the loop's next sleep)."""
        patched = self.stack.client.patch(
            "/api/proxy/gateway/v1/config", json={"routingRefreshSeconds": seconds})
        if patched.status_code != 200:
            info(f"could not set routingRefreshSeconds={seconds}: HTTP {patched.status_code} "
                 f"{patched.text[:200]}")

    def no_cross_model(self, qwen: str, bge: str) -> None:
        """D11: a slot's second target is never reached."""
        stack = self.stack
        r = self.rerank("main", {"model": "sorter", "query": QUERY, "documents": PASSAGES})
        check("D11a", "control: a rerank to the slot `sorter` (targets Qwen3-Reranker, bge) is "
              "answered by its first target while it runs",
              r.status_code == 200 and r.json().get("model") == qwen,
              f"HTTP {r.status_code} model {r.json().get('model') if r.status_code == 200 else ''}")
        stack.lifecycle(qwen, "stop")
        stopped = stack.status_of(qwen, "stopped", 60)
        # Whether the gateway has seen the stop is not what is under test (the request fails
        # either way), but a request sent into the gap would be answered by a stale table.
        wait_until("the gateway to see the stop",
                   lambda: not self.ready_backends("main", qwen), 60, 1.0)

        def through_the_slot() -> httpx.Response:
            return self.rerank("main", {"model": "sorter", "query": QUERY, "documents": PASSAGES})

        r, requests, tasks = self.reached(bge, bge, through_the_slot)
        check("D11b", "Qwen3-Reranker stopped: a rerank to the slot fails (not 200), and says why "
              "(the runtime it found stopped)",
              stopped is not None and r.status_code >= 400 and f"{qwen}=stopped" in said(r),
              f"HTTP {r.status_code} {said(r)}")
        check("D11c", "and bge, the slot's next target, received nothing from it (its driver's "
              "and its engine's own log, current to a marker sent straight to it)",
              requests == 0 and tasks == 0, self.say_reached(bge, requests, tasks))
        stack.lifecycle(qwen, "start")
        stack.status_of(qwen, "ready", 120)
        self.in_gateway("main", {qwen: lambda s: s == ["rerank"]})
        r = through_the_slot()
        check("D11d", "and once Qwen3-Reranker runs again the slot answers from it again "
              "(the failure was the stop's)",
              r.status_code == 200 and r.json().get("model") == qwen,
              f"HTTP {r.status_code} model {r.json().get('model') if r.status_code == 200 else ''}")

    def metrics_rows(self) -> None:
        """D13: the gateway's metrics hold every rerank this run served, under door `rerank`."""
        main = self.served["main"]

        def rows() -> list[dict[str, Any]]:
            return [r for r in self.stack.metric_rows()
                    if r.get("door") == "rerank" and r.get("clientKeyName") == MAIN_KEY]

        wait_until("the metrics rows", lambda: len(
            [r for r in rows() if r.get("outcome") == "served"]) >= main, 30, 1.0)
        time.sleep(1.0)
        found = rows()
        served = [r for r in found if r.get("outcome") == "served"]
        failed = [r for r in found if r.get("outcome") == "error"]
        models = Counter(r.get("requestedModel") for r in served)
        check("D13a", f"the gateway's metrics hold one row, door `rerank`, for each of the {main} "
              "reranks this run's key had answered (and none for an empty list)",
              len(served) == main and all((r.get("promptTokens") or 0) > 0 for r in served)
              and all(r.get("completionTokens") == 0 for r in served),
              f"{len(served)} served rows by model {dict(models)}")
        if wants("D9"):
            check("D13b", "and the passage too long for the model is a row too, outcome `error`",
                  len(failed) >= 1, f"{len(failed)} error row(s) under door rerank")

    # ================================ phase O ================================

    def phase_o(self) -> None:
        kit = Kit(self)
        text = Path(self.args.catalogue).read_text(encoding="utf-8") if self.args.catalogue else None
        shipped = kit.manifest(text)
        if shipped is None:
            check("O1", "the catalogue has an `open-webui` entry", False,
                  self.args.catalogue or "shipped")
            return
        if self.args.catalogue:
            info(f"rendering from {self.args.catalogue}, not the shipped catalogue")
        if wants("O8"):
            self.o8()
        if any(wants(f"O{n}") for n in (1, 2, 3, 4, 5, 6, 9)):
            self.o1_to_o6(kit, shipped)
        if wants("O7"):
            self.o7(kit, shipped)
        if wants("O10"):
            self.o10(kit, shipped)

    def o8(self) -> None:
        """O8: the key the registry mints for an app has an app's limits."""
        registry = self.registry_key
        limits = registry["limits"]
        listed = self.stack.client.get("/v1/auth/client-keys")
        keys = listed.json().get("keys", []) if listed.status_code == 200 else []
        minted = next((k for k in keys if k.get("name") == self.owui_key_name), {}).get("limits") or {}
        want = {"maxConcurrentRequests": 8, "requestsPerMinute": 600}
        check("O8", "the key the registry mints for an app has an app's limits, not one person's "
              "client's: 8 requests at once and 600 a minute, beside writeLogs (the request is the "
              "agent's own `_ensure_key`, captured; Open WebUI's key in this run is minted from it, "
              "and the agent lists it with the same limits)",
              all(limits.get(k) == v for k, v in want.items()) and limits.get("writeLogs") is True
              and all(minted.get(k) == v for k, v in want.items())
              and minted.get("writeLogs") is True,
              f"the registry asks for {registry['name']} with {limits}; the agent lists {minted}")

    def o10(self, kit: Kit, shipped: Any) -> None:
        """O10: an app that names {gatewayUrl} is not started without the gateway's address, since
        left unset Open WebUI would use its own default, which is OpenAI's."""
        data_dir = self.stack.work / "owui-data-no-gateway"
        data_dir.mkdir(exist_ok=True)
        refused: str | None = None
        kind = ""
        try:
            kit.render(shipped, data_dir, free_ports(1)[0], gateway_known=False)
        except ValueError as exc:  # what the agent's planner turns into a refused start
            refused, kind = str(exc), type(exc).__name__
        written = sorted(p.name for p in data_dir.iterdir() if p.is_file())
        check("O10", "the entry rendered with no gateway address is not started: the launcher "
              "refuses, in words (the app would use its own default, which is OpenAI's), and "
              "reads and writes nothing in the app's data directory",
              refused is not None and "{gatewayUrl}" in refused and "not started" in refused
              and not written,
              f"{kind}: {refused}" + (f"; written: {written}" if written else ""))

    def settings_of(self, owui: OpenWebUI) -> dict[str, Any]:
        """What an Open WebUI says it is set to, read from its own admin API: the retrieval
        settings, and the address and key of each OpenAI-compatible connection it holds for a
        feature (documents' embeddings, speech-to-text, text-to-speech, images, image edits).
        A key is said only as whether it is the app's own."""

        def fetch(path: str) -> dict[str, Any]:
            got = owui.api("GET", path)
            body = got.json() if got.status_code == 200 else {}
            return body if isinstance(body, dict) else {}

        mine = self.keys["owui"]
        retrieval = fetch("/api/v1/retrieval/config")
        embedding = fetch("/api/v1/retrieval/embedding")
        audio = fetch("/api/v1/audio/config")
        images = fetch("/api/v1/images/config")
        stt, tts = audio.get("stt") or {}, audio.get("tts") or {}
        wired = embedding.get("openai_config") or {}
        connections = {
            "documents' embeddings": (wired.get("url"), wired.get("key") == mine),
            "speech-to-text": (stt.get("OPENAI_API_BASE_URL"), stt.get("OPENAI_API_KEY") == mine),
            "text-to-speech": (tts.get("OPENAI_API_BASE_URL"), tts.get("OPENAI_API_KEY") == mine),
            "images": (images.get("IMAGES_OPENAI_API_BASE_URL"),
                       images.get("IMAGES_OPENAI_API_KEY") == mine),
            "image edits": (images.get("IMAGES_EDIT_OPENAI_API_BASE_URL"),
                            images.get("IMAGES_EDIT_OPENAI_API_KEY") == mine),
        }
        return {
            "RAG_EMBEDDING_ENGINE": embedding.get("RAG_EMBEDDING_ENGINE"),
            "RAG_EMBEDDING_MODEL": embedding.get("RAG_EMBEDDING_MODEL"),
            "RAG_RERANKING_ENGINE": retrieval.get("RAG_RERANKING_ENGINE"),
            "RAG_RERANKING_MODEL": retrieval.get("RAG_RERANKING_MODEL"),
            "RAG_EXTERNAL_RERANKER_URL": retrieval.get("RAG_EXTERNAL_RERANKER_URL"),
            "ENABLE_RAG_HYBRID_SEARCH": retrieval.get("ENABLE_RAG_HYBRID_SEARCH"),
            "the sorter's key is the app's": retrieval.get("RAG_EXTERNAL_RERANKER_API_KEY") == mine,
            #: Absent (None) for a feature whose settings this Open WebUI does not serve.
            "connections": {name: (url, own) for name, (url, own) in connections.items()
                            if url is not None},
        }

    def seeded_as_expected(self, settings: dict[str, Any]) -> bool:
        gateway = self.stack.gateway
        return all(settings[k] == v for k, v in {
            "RAG_EMBEDDING_ENGINE": "openai", "RAG_EMBEDDING_MODEL": "embedder",
            "RAG_RERANKING_ENGINE": "external", "RAG_RERANKING_MODEL": "qwen3-reranker",
            "RAG_EXTERNAL_RERANKER_URL": f"{gateway}/v1/rerank",
            "ENABLE_RAG_HYBRID_SEARCH": True}.items())

    def connections_ok(self, settings: dict[str, Any]) -> bool:
        """Every connection reported is the gateway's, with the app's own key, and none names
        OpenAI; embeddings, speech-to-text and text-to-speech are among them."""
        gateway = f"{self.stack.gateway}/v1"
        connections = settings["connections"]
        return (
            {"documents' embeddings", "speech-to-text", "text-to-speech"} <= set(connections)
            and all(url == gateway and own for url, own in connections.values())
            and not any("api.openai.com" in str(url) for url, _own in connections.values())
        )

    def o1_to_o6(self, kit: Kit, manifest: Any) -> None:
        stack = self.stack
        work = stack.work
        embedder, qwen, chat = "embedder", "qwen3-reranker", "chat"
        data_dir = work / "owui-data"
        data_dir.mkdir(exist_ok=True)
        port = free_ports(1)[0]
        stack.owned_ports.append(port)
        gateway_url = stack.gateway
        key = self.keys["owui"]

        # ---- O1 ----
        argv, env, notes = kit.render(manifest, data_dir, port)
        want = {"RAG_EMBEDDING_MODEL": embedder, "RAG_RERANKING_MODEL": qwen,
                "RAG_RERANKING_ENGINE": "external",
                "RAG_EXTERNAL_RERANKER_URL": f"{gateway_url}/v1/rerank",
                "ENABLE_RAG_HYBRID_SEARCH": "true"}
        got = {name: env.get(name) for name in want}
        said_of_models = [n for n in notes if "embeddingModel" in n or "rerankModel" in n]
        check("O1a", "the launcher's render of Open WebUI's start seeds the search model, the "
              "sorter, its engine, its address (the gateway's /v1/rerank) and hybrid search, "
              "and its notes say nothing of either model being missing",
              got == want and not said_of_models, got if not said_of_models else said_of_models)
        check("O1b", "and the sorter's key is the app's own key (not shown), and Open WebUI's "
              "other connection keys are too",
              env.get("RAG_EXTERNAL_RERANKER_API_KEY") == key and env.get("OPENAI_API_KEY") == key,
              "")

        # A stopped model is still named when it is all there is (Open WebUI keeps what its
        # first start saw), and the note says it is not running.
        stack.lifecycle(embedder, "stop")
        stack.status_of(embedder, "stopped", 60)
        wait_until("the gateway to show the embedder as not ready",
                   lambda: not self.ready_backends("owui", embedder), 60, 1.0)
        _argv, env_stopped, notes_stopped = kit.render(manifest, data_dir, port)
        not_running = [n for n in notes_stopped
                       if re.search(r"not running|is stopped|stopped", n)
                       and ("embeddingModel" in n or "RAG_EMBEDDING_MODEL" in n or embedder in n)]
        check("O1c", "with the embedder stopped, a second render still names it (a stopped model "
              "is chosen when it is all there is: Open WebUI keeps what its first start saw), "
              "the sorter as it was, and says the embedder is not running",
              env_stopped.get("RAG_EMBEDDING_MODEL") == embedder
              and env_stopped.get("RAG_RERANKING_MODEL") == qwen and bool(not_running),
              not_running[:1] or [n for n in notes_stopped if "mbedding" in n][:1]
              or notes_stopped[:2])
        # And with no embedder listed at all (its runtime taken away), nothing is named, and the
        # notes say why.
        stack.remove(embedder)
        wait_until("the gateway to stop listing the embedder",
                   lambda: self.ready_backends("owui", embedder) is None, 60, 1.0)
        _argv, env_none, notes_none = kit.render(manifest, data_dir, port)
        check("O1d", "with no embedder listed at all (its runtime removed), a render leaves "
              "RAG_EMBEDDING_MODEL unset, the sorter as it was, and its notes say why",
              "RAG_EMBEDDING_MODEL" not in env_none and env_none.get("RAG_RERANKING_MODEL") == qwen
              and any("RAG_EMBEDDING_MODEL" in n or "embeddingModel" in n for n in notes_none),
              [n for n in notes_none if "mbedding" in n][:2] or notes_none[:2])
        stack.declare(runtime_body(stack, embedder, self.linked["embedder"]))
        if stack.status_of(embedder, "ready", 120) is None:
            raise SystemExit("the embedder did not start again after O1d")
        self.in_gateway("owui", {embedder: lambda s: s == ["embeddings"]})
        argv, env, notes = kit.render(manifest, data_dir, port)
        for line in notes:
            info(f"launcher note: {line}")

        # ---- O2 ----
        removed = kit.sign_in_for_the_test(env)
        info("the ONLY changes to the rendered environment: ENABLE_LOGIN_FORM=true and "
             "ENABLE_SIGNUP=true (sign-in by Open WebUI's own form, for this test: C4 proved "
             f"sign-in with Eugene), and the OAuth variables dropped: {', '.join(removed)}")
        changed = {n for n in env if n.startswith("ENABLE_") and env[n] != "false"}
        info("Open WebUI's ENABLE_* variables as it is started: "
             + ", ".join(f"{n}={env[n]}" for n in sorted(changed)))
        owui = OpenWebUI(work, port)
        self.owuis.append(owui)
        started = time.perf_counter()
        owui.start(argv, env, data_dir)
        ok = owui.ready(manifest.healthPath or "/ready", 600)
        version = ""
        if ok:
            version = str(owui.http.get("/api/version").json().get("version", ""))
        check("O2", f"Open WebUI {version or '?'} starts from that environment, on a free port, "
              f"its data directory inside this run's own, and answers {manifest.healthPath}",
              ok and version == "0.11.4",
              f"ready in {time.perf_counter() - started:.0f} s on port {port}"
              if ok else owui.tail())
        if not ok:
            return

        # ---- O3 ----
        signup = owui.http.post("/api/v1/auths/signup", json={
            "name": "Acceptance Admin", "email": "admin@mr6.test",
            "password": secrets.token_urlsafe(18), "profile_image_url": "/user.png"})
        owui.token = str(signup.json().get("token", "")) if signup.status_code == 200 else ""
        role = signup.json().get("role") if signup.status_code == 200 else None
        settings = self.settings_of(owui)
        check("O3", "its first user (its admin) signs up through its API, and its retrieval "
              "settings show what was seeded: engine openai, the search model, the external "
              "sorter, its model and address, hybrid search on, and the sorter's key the app's "
              "own (not shown)",
              role == "admin" and self.seeded_as_expected(settings)
              and settings["the sorter's key is the app's"],
              f"role {role}; " + str({k: v for k, v in settings.items()
                                      if k.startswith(("RAG_", "ENABLE_"))}))
        # Open WebUI 0.11.4 does not let its other OpenAI-compatible connections inherit the chat
        # connection's address: each defaults to https://api.openai.com/v1 unless it is told. Every
        # one has to be told, or what it sends leaves the install.
        check("O3b", "and every OpenAI-compatible connection it holds for a feature (documents' "
              "embeddings, speech-to-text, text-to-speech, images) is the gateway's, with the "
              "app's own key (not shown), and none names api.openai.com",
              self.connections_ok(settings),
              {name: url for name, (url, _own) in settings["connections"].items()})

        # A document is not uploaded to an Open WebUI that would send its text outside this
        # install: the check above has said so, and a test does not do what it is there to find.
        embeds_to = settings["connections"].get("documents' embeddings", (None, False))[0]
        if embeds_to != f"{gateway_url}/v1":
            skip("O4", "upload the document, ask about it, stop the sorter and ask again",
                 f"not run: Open WebUI would send the document's text to {embeds_to}, which is "
                 "not this install's gateway (O3b)")
            return

        # ---- O4 ----
        def mine() -> list[dict[str, Any]]:
            return [r for r in stack.metric_rows()
                    if r.get("clientKeyName") == self.owui_key_name]

        def tally(rows: list[dict[str, Any]]) -> Counter[tuple[str, str, str]]:
            return Counter((str(r.get("requestedModel")), str(r.get("door")), str(r.get("outcome")))
                           for r in rows)

        before = tally(mine())
        doc = document_text()
        paragraphs = [p for p in doc.split("\n\n") if p.strip()]
        started = time.perf_counter()
        upload = owui.api("POST", "/api/v1/files/", params={"process": "true",
                                                            "process_in_background": "true"},
                          files={"file": ("skerry-point-notes.txt", doc.encode(), "text/plain")})
        file_id = upload.json().get("id") if upload.status_code == 200 else None

        def processed() -> str | None:
            state = owui.api("GET", f"/api/v1/files/{file_id}/process/status").json()
            return state["status"] if state.get("status") in ("completed", "failed") else None

        final = wait_until("the file processed", processed, 300, 2.0) if file_id else None
        took = time.perf_counter() - started
        time.sleep(1.0)
        after = tally(mine())
        embedded = {k: v - before.get(k, 0) for k, v in after.items() if k[0] == embedder}
        served_embeddings = sum(v for k, v in embedded.items() if k[2] == "served")
        refused_embeddings = sum(v for k, v in embedded.items() if k[2] == "error")
        check("O4a", f"a {len(paragraphs)}-paragraph document ({len(doc)} characters, one holding "
              "the code word) uploads and Open WebUI finishes processing it",
              upload.status_code == 200 and final == "completed",
              f"upload HTTP {upload.status_code}, processing {final} in {took:.1f} s"
              + ("" if final == "completed" else f"; {owui.tail(6)}"))
        check("O4b", "the gateway served /v1/embeddings to Open WebUI's key for it, and refused "
              "none of them",
              served_embeddings >= 1 and refused_embeddings == 0,
              f"{served_embeddings} served, {refused_embeddings} errors, for model {embedder}")
        if final != "completed" or file_id is None:
            return

        # ---- O9: a file of about two hundred passages ----
        # Open WebUI cuts a file into chunks and sends their embeddings as it is set to: with the
        # upload's burst of one request a chunk, a key's allowance is gone in the first second
        # and its first refusal fails the whole file. Set to send at most 32 to a request, one
        # request at a time, the same file is a handful of requests.
        embed_settings = owui.api("GET", "/api/v1/retrieval/embedding")
        embed_settings = embed_settings.json() if embed_settings.status_code == 200 else {}
        batch = embed_settings.get("RAG_EMBEDDING_BATCH_SIZE")
        concurrent = embed_settings.get("RAG_EMBEDDING_CONCURRENT_REQUESTS")
        big = big_document_text()
        before = tally(mine())
        generated_before = len(owui.log_lines("embeddings generated"))
        started = time.perf_counter()
        upload = owui.api("POST", "/api/v1/files/", params={"process": "true",
                                                            "process_in_background": "true"},
                          files={"file": ("skerry-point-log.txt", big.encode(), "text/plain")})
        big_id = upload.json().get("id") if upload.status_code == 200 else None

        def big_processed() -> str | None:
            state = owui.api("GET", f"/api/v1/files/{big_id}/process/status").json()
            return state["status"] if state.get("status") in ("completed", "failed") else None

        final_big = wait_until("the big file processed", big_processed, 600, 2.0) if big_id else None
        took = time.perf_counter() - started
        time.sleep(1.5)
        after = tally(mine())
        embedded = {k: v - before.get(k, 0) for k, v in after.items() if k[0] == embedder}
        requests_served = sum(v for k, v in embedded.items() if k[2] == "served")
        requests_refused = sum(v for k, v in embedded.items() if k[2] == "error")
        said_chunks = owui.log_lines("embeddings generated")[generated_before:]
        found = (re.search(r"embeddings generated (\d+) for (\d+) items", said_chunks[-1])
                 if said_chunks else None)
        chunks = int(found.group(1)) if found else 0
        per_request = batch if isinstance(batch, int) and batch > 0 else 1
        want_requests = -(-chunks // per_request) if chunks else 0
        check("O9a", f"a file of about two hundred passages ({len(big) // 1024} KiB) completes: "
              "Open WebUI is set to send documents' embeddings at most 32 to a request, one request "
              "at a time, and the gateway served exactly that many requests, none refused",
              upload.status_code == 200 and final_big == "completed" and 150 <= chunks <= 260
              and isinstance(batch, int) and 1 <= batch <= 32 and concurrent == 1
              and requests_served == want_requests and requests_refused == 0,
              f"{chunks} chunks, batch {batch}, concurrency {concurrent}: {requests_served} "
              f"requests served ({want_requests} expected), {requests_refused} refused, "
              f"processing {final_big} in {took:.1f} s"
              + ("" if final_big == "completed" else f"; {owui.tail(6)}"))
        before = tally(mine())
        queried = owui.api("POST", "/api/v1/retrieval/query/doc", json={
            "collection_name": f"file-{big_id}", "query": ASKED, "k": 3, "hybrid": True})
        result = queried.json() if queried.status_code == 200 else {}
        big_docs = (result.get("documents") or [[]])[0]
        big_scores = [m.get("score") if isinstance(m, dict) else None
                      for m in (result.get("metadatas") or [[]])[0]]
        time.sleep(1.5)
        after = tally(mine())
        big_reranks = sum(v - before.get(k, 0) for k, v in after.items()
                          if k[1] == "rerank" and k[2] == "served")
        check("O9b", "and over that file Open WebUI's own retrieval finds the chunk with the code "
              "word first, scored by the sorter in 0..1",
              queried.status_code == 200 and bool(big_docs) and CODE_WORD in big_docs[0]
              and bool(big_scores) and all(isinstance(x, int | float) and 0.0 <= x <= 1.0
                                           for x in big_scores)
              and big_reranks == 1,
              f"HTTP {queried.status_code}, {len(big_docs)} chunks, scores "
              f"{[round(x, 4) if isinstance(x, int | float) else x for x in big_scores]}, "
              f"{big_reranks} rerank(s)")

        # ---- O5 ----
        collection = f"file-{file_id}"
        runtime_before = self.backend_counts(qwen)
        before = tally(mine())
        started = time.perf_counter()
        queried = owui.api("POST", "/api/v1/retrieval/query/doc", json={
            "collection_name": collection, "query": ASKED, "k": 3, "hybrid": True})
        took = time.perf_counter() - started
        result = queried.json() if queried.status_code == 200 else {}
        found_docs = (result.get("documents") or [[]])[0]
        found_meta = (result.get("metadatas") or [[]])[0]
        found_scores = [m.get("score") if isinstance(m, dict) else None for m in found_meta]
        scores_ok = bool(found_scores) and all(
            isinstance(s, int | float) and not isinstance(s, bool) and 0.0 <= s <= 1.0
            for s in found_scores)
        wait_until("Open WebUI's rerank in the driver's log",
                   lambda: self.backend_counts(qwen)[0] >= runtime_before[0] + 1, 20, 0.5)
        time.sleep(1.5)
        runtime_after = self.backend_counts(qwen)
        after = tally(mine())
        reranks = {k: v - before.get(k, 0) for k, v in after.items() if k[1] == "rerank"}
        passages = runtime_after[1] - runtime_before[1]
        check("O5a", "Open WebUI's own retrieval over the file (hybrid, its sorter): the chunk with "
              "the code word first, scored by the sorter in 0..1",
              queried.status_code == 200 and bool(found_docs) and CODE_WORD in found_docs[0]
              and scores_ok and found_scores[0] >= max(found_scores),
              f"HTTP {queried.status_code} in {took:.1f} s; {len(found_docs)} chunks, scores "
              f"{[round(s, 4) if isinstance(s, int | float) else s for s in found_scores]}")
        check("O5b", "the gateway served that as one /v1/rerank to Open WebUI's key, of more than "
              "one passage (the sorter's engine ran one task for each)",
              sum(reranks.values()) == 1 and (qwen, "rerank", "served") in reranks
              and runtime_after[0] - runtime_before[0] == 1 and passages > 1,
              f"{dict(reranks)}; the engine ran {passages} tasks for it")

        models = {m["id"] for m in owui.api("GET", "/api/models").json().get("data", [])}
        before = tally(mine())
        started = time.perf_counter()
        asked = owui.api("POST", "/api/chat/completions", json={
            "model": chat, "stream": False, "temperature": 0, "max_tokens": 1024,
            "messages": [{"role": "user", "content": f"{ASKED} /no_think"}],
            "files": [{"type": "file", "id": file_id}]})
        took = time.perf_counter() - started
        body = asked.json() if asked.status_code == 200 else {}
        answer = answer_of(body)
        time.sleep(1.5)
        after = tally(mine())
        delta = {k: v - before.get(k, 0) for k, v in after.items() if v - before.get(k, 0)}
        check("O5c", "asking Open WebUI's chat about the fact with the file attached: the answer "
              "contains the code word",
              asked.status_code == 200 and CODE_WORD.lower() in answer.lower() and chat in models,
              f"HTTP {asked.status_code} in {took:.1f} s: {answer[:160]!r}"
              if asked.status_code == 200 else f"HTTP {asked.status_code} {asked.text[:200]}")
        reranked = sum(v for k, v in delta.items() if k[1] == "rerank" and k[2] == "served")
        chatted = sum(v for k, v in delta.items() if k[0] == chat and k[2] == "served")
        check("O5d", "and for it the gateway served at least one /v1/rerank to Open WebUI's key, "
              "and a chat completion",
              reranked >= 1 and chatted >= 1,
              f"{reranked} rerank(s), {chatted} chat completion(s); all rows {dict(delta)}")
        called = owui.log_lines("ExternalReranker:predict:model")
        check("O5e", "and Open WebUI's own log shows it called its external reranker with the "
              f"sorter's model id ({len(called)} calls)",
              bool(called) and all(qwen in line for line in called),
              called[-1][-160:] if called else "")

        # ---- O6 ----
        stack.lifecycle(qwen, "stop")
        stack.status_of(qwen, "stopped", 60)
        wait_until("the gateway to see the sorter stop",
                   lambda: not self.ready_backends("owui", qwen), 60, 1.0)
        errors_before = len(owui.log_lines("Error in external reranking"))
        before = tally(mine())
        started = time.perf_counter()
        queried = owui.api("POST", "/api/v1/retrieval/query/doc", json={
            "collection_name": collection, "query": ASKED, "k": 3, "hybrid": True})
        result = queried.json() if queried.status_code == 200 else {}
        found_docs = (result.get("documents") or [[]])[0]
        check("O6a", "the sorter stopped: Open WebUI's own retrieval still returns passages, the "
              "chunk with the code word among them (it keeps its own order)",
              queried.status_code == 200 and any(CODE_WORD in d for d in found_docs),
              f"HTTP {queried.status_code}, {len(found_docs)} chunks")
        asked = owui.api("POST", "/api/chat/completions", json={
            "model": chat, "stream": False, "temperature": 0, "max_tokens": 1024,
            "messages": [{"role": "user", "content": f"{ASKED} /no_think"}],
            "files": [{"type": "file", "id": file_id}]})
        answer = answer_of(asked.json() if asked.status_code == 200 else {})
        took = time.perf_counter() - started
        check("O6b", "and its chat still answers (200, not empty)",
              asked.status_code == 200 and bool(answer),
              f"HTTP {asked.status_code} in {took:.1f} s: {answer[:160]!r}"
              + (f" (the code word {'is' if CODE_WORD.lower() in answer.lower() else 'is not'} in it)"
                 if answer else ""))
        time.sleep(1.5)
        errors = owui.log_lines("Error in external reranking")
        new_errors = errors[errors_before:]
        check("O6c", "Open WebUI's own log shows its external reranker failing, and it went on",
              len(new_errors) >= 1, new_errors[0][-200:] if new_errors else "no such line")
        after = tally(mine())
        failed_rows = {k: v - before.get(k, 0) for k, v in after.items()
                       if k[0] == qwen and k[2] == "error" and v - before.get(k, 0)}
        check("O6d", "and the gateway recorded Open WebUI's failed rerank(s) against the sorter, "
              "outcome `error`", sum(failed_rows.values()) >= 1, dict(failed_rows))
        replay = stack.app.post(
            f"{gateway_url}/v1/rerank", headers={"Authorization": f"Bearer {key}"},
            json={"model": qwen, "query": ASKED, "documents": found_docs[:3] or ["x", "y"],
                  "top_n": 3})
        words = said(replay)
        check("O6e", "the gateway's answer to that rerank (the same request, sent again) is a "
              "refusal that names the sorter and what it observed: the runtime is stopped",
              replay.status_code in (404, 502, 503) and qwen in words
              and re.search(r"stopped|not ready|not running", words) is not None,
              f"HTTP {replay.status_code} {words}")

    def o7(self, kit: Kit, shipped: Any) -> None:
        """O7: an install that already started Open WebUI with the entry as it was before this
        change. Its data directory holds what that first start saw (Open WebUI copies its
        settings in once, and its database wins after), so a corrected entry reaches it only
        through the launcher's one-start reset; and the reset must come once, not at every start."""
        stack = self.stack
        work = stack.work
        embedder, qwen = "embedder", "qwen3-reranker"
        # O6 left the sorter stopped: everything runs again, as an install would have it.
        if stack.runtime(qwen)["status"] != "ready":
            stack.lifecycle(qwen, "start")
            stack.status_of(qwen, "ready", 120)
        self.in_gateway("owui", {embedder: lambda s: s == ["embeddings"],
                                 qwen: lambda s: s == ["rerank"]})
        code, old_text = git(self.repos / "agent", "show",
                             f"{PRE_FIX_AGENT}:src/eugene_plexus_agent/apps_catalogue.yaml")
        old = kit.manifest(old_text) if code == 0 else None
        if old is None:
            skip("O7", "an install made before this change is migrated by the launcher",
                 f"the catalogue at agent {PRE_FIX_AGENT} could not be read: {old_text[:120]}")
            return
        data_dir = work / "owui-data-existing"
        data_dir.mkdir(exist_ok=True)
        port = free_ports(1)[0]
        stack.owned_ports.append(port)
        password = secrets.token_urlsafe(18)

        def started(name: str, argv: list[str], env: dict[str, str]) -> OpenWebUI | None:
            kit.sign_in_for_the_test(env)
            instance = OpenWebUI(work, port, name)
            self.owuis.append(instance)
            instance.start(argv, env, data_dir)
            return instance if instance.ready("/ready", 600) else None

        # 1. The entry as it was at the agent's last commit before this change, rendered through
        # today's launcher (so its connection digest is written), started once.
        argv, env, notes = kit.render(old, data_dir, port)
        first = started("open-webui-existing-1", argv, env)
        if first is None:
            check("O7a", "an Open WebUI data directory is started once with the entry as it was "
                  f"at agent {PRE_FIX_AGENT}", False, "it did not become ready")
            return
        signup = first.http.post("/api/v1/auths/signup", json={
            "name": "Existing Admin", "email": "existing@mr6.test", "password": password,
            "profile_image_url": "/user.png"})
        first.token = str(signup.json().get("token", "")) if signup.status_code == 200 else ""
        old_settings = self.settings_of(first)
        first.stop()
        old_addresses = {name: url for name, (url, _own) in old_settings["connections"].items()}
        check("O7a", f"an Open WebUI data directory is started once with the entry as it was at "
              f"agent {PRE_FIX_AGENT} (rendered through today's launcher): what it holds is what "
              "an install made before this change holds, its documents' embeddings and speech "
              "pointed at OpenAI's own address",
              signup.status_code == 200 and not self.connections_ok(old_settings)
              and "api.openai.com" in str(old_addresses.get("documents' embeddings")),
              old_addresses)

        # 2. Stopped; the shipped entry rendered for the next start: the corrected entry is not
        # taken by a database that already has its settings, so the launcher resets it, once.
        argv, env, notes = kit.render(shipped, data_dir, port)
        reset_notes = [n for n in notes if "RESET_CONFIG_ON_START" in n]
        check("O7b", "a render of the shipped entry for that data directory sets "
              "RESET_CONFIG_ON_START=true, with the launcher's note saying why",
              env.get("RESET_CONFIG_ON_START") == "true" and bool(reset_notes),
              reset_notes[:1] or "no such note")

        # 3. Started: the settings are the gateway's now, and the seeded models are in them.
        second = started("open-webui-existing-2", argv, env)
        if second is None:
            check("O7c", "that start comes up", False, "it did not become ready")
            return
        signin = second.http.post("/api/v1/auths/signin", json={
            "email": "existing@mr6.test", "password": password})
        second.token = str(signin.json().get("token", "")) if signin.status_code == 200 else ""
        new_settings = self.settings_of(second)
        second.stop()
        check("O7c", "and Open WebUI, started so, shows the gateway's address and the app's key "
              "for documents, speech and images, none naming api.openai.com, and the seeded "
              "search model and sorter",
              signin.status_code == 200 and self.connections_ok(new_settings)
              and self.seeded_as_expected(new_settings)
              and new_settings["the sorter's key is the app's"],
              {name: url for name, (url, _own) in new_settings["connections"].items()})

        # 4. Stopped again; the same entry rendered once more must not reset it again.
        _argv, env_again, notes_again = kit.render(shipped, data_dir, port)
        check("O7d", "a third render with the same entry does not set the reset (the settings "
              "its admin makes after the one start are kept)",
              "RESET_CONFIG_ON_START" not in env_again
              and not any("RESET_CONFIG_ON_START" in n for n in notes_again),
              [n for n in notes_again if "RESET" in n][:1] or "no reset, no note")

    # ================================ the run ================================

    def finish(self) -> None:
        """S: what the agent's own log says of the whole run."""
        log = self.stack.log.lines()
        gateway_traces = [line for line in log
                          if line.startswith("[gateway]") and "Traceback (most recent call" in line]
        # The replicas D12 stops and kills are the one place a driver is meant to meet an engine
        # that is gone, so theirs are not counted here.
        driver_traces = [line for line in log
                         if line.startswith("[driver:") and "Traceback (most recent call" in line
                         and not line.startswith(("[driver: pair-a-driver]",
                                                  "[driver: pair-b-driver]"))]
        check("S6", "the gateway's log and the drivers' logs hold no traceback",
              not gateway_traces and not driver_traces,
              f"{len(gateway_traces)} in the gateway, {len(driver_traces)} in the drivers")
        # What each driver says it learned of its backend's scores, in its own words.
        for line in log:
            if line.startswith("[driver:") and "reranks, scale:" in line:
                info(line.split("INFO", 1)[-1].strip()[:200] if "INFO" in line else line[:200])
        # The code under test did not move while it ran: another session works in these repos.
        moved = {name: (was, repo_state(self.repos)[name]) for name, was in self.repo_state.items()
                 if repo_state(self.repos)[name] != was}
        check("S9", "no component repo changed under the run (each one's head and changed files are "
              "what they were at its start)", not moved, moved or "")


COMPONENTS = ("gateway", "inference-driver", "agent", "library", "control")


def repo_state(repos: Path) -> dict[str, tuple[str, str]]:
    """Each component repo's head and what is changed in it (tracked files only: the runtime
    files a component leaves untracked are not what is under test)."""
    return {
        name: (git(repos / name, "rev-parse", "--short", "HEAD")[1],
               git(repos / name, "status", "--porcelain", "--untracked-files=no")[1])
        for name in COMPONENTS
    }


def components(repos: Path, allow_dirty: bool) -> dict[str, tuple[str, str]]:
    """S2: each component repo is at or after the commit this acceptance is for, and clean.
    Returns what it found, so the end of the run can say nothing moved under it."""
    required = {
        "gateway": ("a99cabb", None),
        "inference-driver": ("b1d6820", None),
        "agent": (None, "embeddingModel"),
    }
    state = repo_state(repos)
    for name, (commit, text) in required.items():
        repo = repos / name
        head, dirty = state[name]
        if commit is not None:
            code, _ = git(repo, "merge-base", "--is-ancestor", commit, "HEAD")
            reached = code == 0
            what = f"is at or after {commit}"
        else:
            code, found = git(repo, "log", "--oneline", "-S", str(text), "--",
                              "src/eugene_plexus_agent/app_launcher.py")
            reached = code == 0 and bool(found)
            what = f"has the MR6 launcher commit ({found.splitlines()[0] if found else 'none'})"
        clean = not dirty
        check("S2", f"{name} {head} {what}" + ("" if clean else ", and its tree is changed"),
              reached and (clean or allow_dirty),
              "clean" if clean else f"dirty: {dirty.splitlines()[:3]}")
    for name in ("library", "control"):
        info(f"{name} {state[name][0]}" + ("" if not state[name][1] else " (changed)"))
    return state


def main() -> int:
    global ONLY
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--llama-server", type=Path, default=os.environ.get("EP_LLAMA_SERVER"),
                        help="a llama-server build to run on the CPU")
    parser.add_argument("--qwen3-reranker", type=Path, help="the ggml-org Qwen3-Reranker-0.6B Q8_0")
    parser.add_argument("--bge-reranker", type=Path, help="bge-reranker-v2-m3 Q8_0")
    parser.add_argument("--embedding-model", type=Path, help="Qwen3-Embedding-0.6B Q8_0")
    parser.add_argument("--chat-model", type=Path, help="a small chat GGUF (Qwen3-0.6B)")
    parser.add_argument("--open-webui-venv", type=Path, help="a venv with Open WebUI 0.11.4")
    parser.add_argument("--only", default="", help="checks to run, comma separated: D5, D11, O")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run with a component's working tree changed (a sabotage pass)")
    parser.add_argument("--catalogue", type=Path,
                        help="render Open WebUI's start from this copy of the agent's catalogue")
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    args = parser.parse_args()
    # Nothing of the live install's reaches anything this run starts or imports.
    for name in [n for n in os.environ if n.upper().startswith("EUGENE_PLEXUS_")]:
        del os.environ[name]
    ONLY = {part.strip() for part in args.only.split(",") if part.strip()} or None
    if args.llama_server is None or not Path(args.llama_server).is_file():
        print("--llama-server must name a llama-server (or set EP_LLAMA_SERVER)")
        return 2
    files = {
        "qwen3-reranker": args.qwen3_reranker, "bge-reranker": args.bge_reranker,
        "embedder": args.embedding_model, "chat": args.chat_model,
    }
    for label, path in files.items():
        if path is None or not Path(path).is_file():
            print(f"--{label}: {path} is not a file")
            return 2
    if wants_any("O") and (args.open_webui_venv is None or not Path(args.open_webui_venv).is_dir()):
        print("--open-webui-venv must name a venv with Open WebUI (or --only D)")
        return 2

    work = Path(tempfile.mkdtemp(prefix="mr6-rerank-"))
    models = work / "models"
    models.mkdir()
    linked: dict[str, Path] = {}
    for label, path in files.items():
        linked[label] = models / Path(str(path)).name
        link(Path(str(path)), linked[label])
    stack = Stack(work, args)
    stack.write_config(models)
    run = Run(stack, linked, Path(__file__).resolve().parents[2])
    print(f"work {work}\nports: agent {stack.agent_port}, library {stack.library_port}, "
          f"gateway {stack.gateway_port}; runtimes and drivers from {stack.port_base}", flush=True)
    stopped = False
    try:
        provenance(Path(args.llama_server), linked)
        execute(run)
    except SystemExit as exit_:
        stopped = True
        print(f"STOPPED: {exit_}", flush=True)
    except Exception:  # a crash of this script is a failed run, and the teardown still happens
        stopped = True
        print("CRASHED:\n" + traceback.format_exc(), flush=True)
    finally:
        for instance in run.owuis:
            instance.stop()
            instance.http.close()
        stack.stop()
        stack.client.close()
        stack.app.close()
        leaked = [p for p in stack.owned_ports if listening(p)]
        check("S7", "teardown by the agent, and of Open WebUI, leaves no owned port listening",
              not leaked, leaked or f"{len(set(stack.owned_ports))} ports")
        mine = sorted(set(stack.owned_ports))
        live = [p for p in mine if 8079 <= p <= 8190]
        check("S8", "none of the ports this run was given is one the live install uses "
              "(8079-8190)", not live, live or f"{mine[0]}-{mine[-1]}")
        failed = [r for r in RESULTS if not r[2]]
        print(f"\n{len(RESULTS) - len(failed)} PASS, {len(failed)} FAIL, {len(SKIPPED)} SKIP  "
              f"(work {work})", flush=True)
        if args.keep:
            info(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    return 1 if stopped or any(not ok for _label, _claim, ok, _detail in RESULTS) else 0


def execute(run: Run) -> None:
    stack, args = run.stack, run.args
    leaked_env = sorted(k for k in stack.child_environment() if k.upper().startswith("EUGENE_PLEXUS_"))
    check("S1", "the agent is given only its own EUGENE_PLEXUS_* variables, none from the live "
          "install, and this process carries none either", set(leaked_env) == {
              "EUGENE_PLEXUS_AGENT_CONFIG_FILE", "EUGENE_PLEXUS_AGENT_BIND_HOST",
              "EUGENE_PLEXUS_AGENT_BIND_PORT", "EUGENE_PLEXUS_AGENT_ENGINE_ROOT",
              "EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY"} and 8079 not in stack.owned_ports
          and not [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")], leaked_env)
    run.repo_state = components(run.repos, args.allow_dirty)
    stack.start()
    if not wait_until("the agent answers", lambda: stack.client.get("/healthz").status_code == 200, 90):
        raise SystemExit("the agent never became healthy")
    initialised = stack.client.post("/v1/auth/initialize", json={"passphrase": secrets.token_urlsafe(24)})
    stack.client.headers["Authorization"] = f"Bearer {initialised.json()['sessionToken']}"
    up = bool(wait_until("library", lambda: stack.client.get("/api/proxy/library/healthz").status_code == 200, 90)) \
        and bool(wait_until("gateway", lambda: stack.client.get("/api/proxy/gateway/healthz").status_code == 200, 90))
    check("S3", "the library and the gateway are up under the agent", up)
    if not up:
        raise SystemExit("the stack did not come up")

    # The keys, as the agent mints them: this run's own (generous limits, so a burst is not
    # what is under test), one sorter only, none, and Open WebUI's, as the registry mints an
    # app's (writeLogs, the default limits) narrowed to the three models it should use.
    run.keys["main"] = stack.mint(
        MAIN_KEY, {"maxConcurrentRequests": 16, "requestsPerMinute": 3000})
    run.keys["one"] = stack.mint(
        "mr6-one-sorter", {"allowedModels": ["qwen3-reranker"], "maxConcurrentRequests": 8,
                           "requestsPerMinute": 600})
    run.keys["chatonly"] = stack.mint(
        "mr6-chat-only", {"allowedModels": ["chat"], "maxConcurrentRequests": 8,
                          "requestsPerMinute": 600})
    # Open WebUI's: the request the agent's registry itself makes to mint an app's key (its own
    # `_ensure_key`, captured), its name and its limits as they are, narrowed to the three models
    # it should use. What the registry asks for is checked at O8.
    run.registry_key = registry_key_request(stack.work, "open-webui", "mr6-node")
    run.owui_key_name = str(run.registry_key["name"])
    run.keys["owui"] = stack.mint(
        run.owui_key_name,
        {**run.registry_key["limits"], "allowedModels": ["embedder", "qwen3-reranker", "chat"]})
    check("S4", "the agent mints this run's client keys, Open WebUI's from the request its own "
          "registry makes for an app",
          all(run.keys.values()), {k: bool(v) for k, v in run.keys.items()})

    # What the agent's own header reader makes of each sorter's file under `auto`. Qwen3-Reranker
    # names rank pooling and classifier labels, so `auto` starts it as a sorter. This bge GGUF
    # names neither (no pooling type, non-causal attention), so `auto` reads it as an embedder
    # and starts it `--embeddings --pooling mean`: it is declared here with `mode: reranking`,
    # the override a person has for a file the header cannot tell (MR3).
    try:
        from eugene_plexus_agent import gguf_context

        for label in ("qwen3-reranker", "bge-reranker"):
            info(f"the agent's header reader on {run.linked[label].name} (what `auto` goes by): "
                 f"{gguf_context.run_facts(run.linked[label])}")
    except (ImportError, AttributeError, OSError, ValueError) as exc:
        info(f"the agent's header reader could not be asked ({type(exc).__name__}: {exc})")

    # The runtimes, declared as a console declares them, started by the agent.
    declared = {
        "qwen3-reranker": runtime_body(stack, "qwen3-reranker", run.linked["qwen3-reranker"]),
        "bge-reranker": runtime_body(
            stack, "bge-reranker", run.linked["bge-reranker"], mode="reranking"),
        "embedder": runtime_body(stack, "embedder", run.linked["embedder"]),
        "chat": runtime_body(stack, "chat", run.linked["chat"], flags={"contextSize": 8192}),
    }
    statuses = {name: stack.declare(body)[0] for name, body in declared.items()}
    views = {name: stack.status_of(name, "ready") for name in declared}
    check("S5", "the agent starts a sorter (Qwen3-Reranker), a sorter (bge-reranker-v2-m3), a "
          "search model and a chat model on the CPU",
          all(s == 201 for s in statuses.values()) and all(views.values()),
          {n: (v or {}).get("status", "never ready") for n, v in views.items()})
    if not all(views.values()):
        raise SystemExit("a runtime did not start")
    for name, view in views.items():
        info(f"{name} started as: {show(view['argv'])}")

    if wants_any("D"):
        run.phase_d()
    else:
        run.in_gateway("main", {"embedder": lambda s: s == ["embeddings"],
                                "qwen3-reranker": lambda s: s == ["rerank"],
                                "chat": lambda s: "chat" in s})
    if wants_any("O"):
        run.phase_o()
    run.finish()


if __name__ == "__main__":
    sys.exit(main())
