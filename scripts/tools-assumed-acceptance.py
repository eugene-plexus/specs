#!/usr/bin/env python3
"""Tools are assumed: the gateway and the inference-driver, as the pair that ships.

`docs/design/tools-assumed.md` ("Rounds three to five", "Left for a small round
six"). Round five was reviewed as a pair, with a matrix wired by hand; this is that
matrix as an acceptance, so that the gateway's rule for naming what a backend
ignores and the driver's cannot drift apart again (round four's did, and nothing in
either repository's tests ties the two together).

The real gateway app runs in this process, with real client keys and an operator
session. The real driver app runs once per backend, as its own process, in front of
a stand-in for that provider (a driver runs as a standalone one does, with no trust
bundle: what it is asked is the question here, not who asks).

**Nothing outside this machine is touched.** Every address is loopback on a port the
OS picks, every key is a made-up word, the two subscription CLI engines run this
script as a stand-in that prints a canned answer (never the CLI), no engine and no
GPU is involved, and a connection to anything but loopback, or to a component's
default port, is refused where it is made (where the event loop lets it be seen).
Every ambient `EUGENE_PLEXUS_*` variable is dropped first.

Five checks:

1.  **Header agreement.** For a llama-server-, Strata-, Ollama-, OpenRouter-,
    Gemini-, OpenAI- and subscription-CLI-shaped backend (OpenRouter four ways: a
    model that lists no tools, the eight that list tools without `tool_choice`
    (Amazon Nova), one without `parallel_tool_calls`, and one that lists all
    three), a request carrying `tool_choice` `none`, `required` or a named function,
    `parallel_tool_calls` `false` and their pairs, on the chat, Messages and
    Responses doors, whole and streamed. The gateway's
    `x-eugene-plexus-ignored-settings` must equal the driver's own header for the
    same request, equal what the design says the backend ignores, and agree with
    what the stand-in provider was actually sent (a setting a backend ignores is sent
    and named; one that is withheld is named and never delivered; one honoured by
    sending no tools sends none and names nothing).
1b. **A whole answer is named by the backend that served it**, after a failover
    too; a stream's head by the backend asked first.
2.  **Slots.** In a slot [family, local], every request shape the local model
    serves alone is still served (one refusal is decided: Strata's of a seed of 0).
3.  **Counts.** `/v1/messages/count_tokens` and `/v1/responses/input_tokens` never
    answer a 5xx when the key check fails (an authority that answers a 5xx, hangs or
    hangs up; a key policy that cannot be read), when a driver's listing cannot be
    read (each way a listing fails) or when the backend cannot count.
4.  **A stream's head arrives before its first frame**, on all three doors, with
    the header on it. The backend is held until the head has been seen, so a
    gateway that waited for it would never deliver the head at all.

    python scripts/tools-assumed-acceptance.py [--only header,failover,slots,counts,heads]
                                               [--families strata,or-nova,...] [--keep | --clean]

Run in an environment that has the gateway and the inference-driver installed (CI:
the one that runs every acceptance; here: `agent/.venv`). `EP_GATEWAY_SRC` and
`EP_DRIVER_SRC` name a tree holding the package to run instead of the installed one
(`tools-assumed-sabotage.py` runs a broken copy this way and never touches a
checkout). Exit 0: every check passed. 1: one failed. 2: this script could not run.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import faulthandler
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# Nothing ambient reaches anything started here (specs CLAUDE.md): `install.ps1` sets
# the agent's config file for the whole account, and a gateway or driver would read it.
DROPPED = sorted(
    name for name in os.environ if name.upper().startswith("EUGENE_PLEXUS")
)
for _name in DROPPED:
    del os.environ[_name]

import httpx  # noqa: E402

HERE = Path(__file__).resolve()
HEADER = "x-eugene-plexus-ignored-settings"
GATEWAY_SRC = os.environ.get("EP_GATEWAY_SRC")
DRIVER_SRC = os.environ.get("EP_DRIVER_SRC")
LOOPBACK = ("127.0.0.1", "::1", "localhost")
#: The ports Eugene's components default to, here and on the NAS (+200): the live install holds
#: them, and nothing in this run is ever pointed at one.
DEFAULT_PORTS = {8079, 8080, 8081, 8082, 8083, 8190, 8279, 8280, 8281, 8282, 8283}


def refuse_the_internet() -> None:
    """Make a connection to anything but a stand-in an error, in this process.

    The stand-ins are all that any component here is pointed at. If one ever reached
    for a real provider (a default address a config left out), it would be a request
    to a paid service; or for a component's default port, it would be the live install
    on this machine. It is refused where it is made, and says so. A second line of
    defence, not the first: the addresses are the first, and an event loop that makes
    its connections without `socket.connect` (Windows' default) is not caught here.
    """
    connect = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> None:
        if isinstance(address, tuple):
            host, port = address[0], address[1]
            if isinstance(host, str) and host not in LOOPBACK:
                raise OSError(
                    f"this acceptance does not leave loopback: refused {address!r}"
                )
            if port in DEFAULT_PORTS:
                raise OSError(
                    f"this acceptance never uses a default port: refused {address!r}"
                )
        connect(self, address)

    socket.socket.connect = guarded  # type: ignore[method-assign, assignment]


# --------------------------------------------------------------------------- #
# The requests
# --------------------------------------------------------------------------- #

CHAT = [{"role": "user", "content": "hello there"}]
SCHEMA = {"type": "object", "properties": {"city": {"type": "string"}}}
WEATHER = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Current weather.",
        "parameters": SCHEMA,
    },
}
ANTHROPIC_WEATHER = {
    "name": "get_weather",
    "description": "Current weather.",
    "input_schema": SCHEMA,
}
RESPONSES_WEATHER = {
    "type": "function",
    "name": "get_weather",
    "description": "Current weather.",
    "parameters": SCHEMA,
}
FUNC = {"type": "function", "function": {"name": "get_weather"}}


@dataclass(frozen=True)
class Shape:
    """One request's tool-shaped fields, in the chat door's words."""

    name: str
    fields: dict[str, Any]

    @property
    def tools_key(self) -> bool:
        """The caller sent `tools`, an empty list included."""
        return "tools" in self.fields

    @property
    def has_tools(self) -> bool:
        return bool(self.fields.get("tools"))

    @property
    def tc(self) -> str | None:
        """The tool choice as its mode: auto, none, required, or function for a named one."""
        value = self.fields.get("tool_choice")
        return "function" if isinstance(value, dict) else value

    @property
    def par(self) -> bool | None:
        return self.fields.get("parallel_tool_calls")


def _shape(name: str, **fields: Any) -> Shape:
    return Shape(name, fields)


#: What the review of round five sent, sampled: the tool settings alone and with tools,
#: and the pairs a client sends (Codex sends `auto` and `false` on every request).
SHAPES = [
    _shape("plain"),
    _shape("tc_auto", tool_choice="auto"),
    _shape("par_false", parallel_tool_calls=False),
    _shape("tc_auto+par_false", tool_choice="auto", parallel_tool_calls=False),
    _shape("tc_req+par_false", tool_choice="required", parallel_tool_calls=False),
    _shape("tc_none", tool_choice="none"),
    _shape("T+tc_auto", tools=[WEATHER], tool_choice="auto"),
    _shape("T+tc_none", tools=[WEATHER], tool_choice="none"),
    _shape("T+tc_req", tools=[WEATHER], tool_choice="required"),
    _shape("T+tc_fn", tools=[WEATHER], tool_choice=FUNC),
    _shape("T+par_false", tools=[WEATHER], parallel_tool_calls=False),
    _shape("T+par_true", tools=[WEATHER], parallel_tool_calls=True),
    _shape(
        "T+tc_none+par_false",
        tools=[WEATHER],
        tool_choice="none",
        parallel_tool_calls=False,
    ),
    _shape("T+codex", tools=[WEATHER], tool_choice="auto", parallel_tool_calls=False),
    _shape(
        "T+tc_req+par_false",
        tools=[WEATHER],
        tool_choice="required",
        parallel_tool_calls=False,
    ),
    _shape("[]+tc_auto", tools=[], tool_choice="auto"),
]
#: Not tool settings: what a backend that carries them is sent (Strata's seed rule).
SEEDS = [
    _shape("seed0", seed=0),
    _shape("seed7", seed=7),
    _shape("neg_penalty", frequency_penalty=-0.5),
]
BY_NAME = {s.name: s for s in [*SHAPES, *SEEDS]}
#: What a stand-in is asked about of a request it was sent: the tool fields, and the two others
#: that the design says a backend carries (a seed, a penalty).
SENT_FIELDS = (
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "seed",
    "frequency_penalty",
)

#: The Messages and Responses doors' own spellings of requests above, with the chat
#: shape each means (the same `GenerateRequest` reaches the driver).
MESSAGES: dict[str, tuple[dict[str, Any], str]] = {
    "T+auto": (
        {"tools": [ANTHROPIC_WEATHER], "tool_choice": {"type": "auto"}},
        "T+tc_auto",
    ),
    "T+auto+noparallel": (
        {
            "tools": [ANTHROPIC_WEATHER],
            "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
        },
        "T+codex",
    ),
    "T+any": (
        {"tools": [ANTHROPIC_WEATHER], "tool_choice": {"type": "any"}},
        "T+tc_req",
    ),
    "T+any+noparallel": (
        {
            "tools": [ANTHROPIC_WEATHER],
            "tool_choice": {"type": "any", "disable_parallel_tool_use": True},
        },
        "T+tc_req+par_false",
    ),
    "T+named": (
        {
            "tools": [ANTHROPIC_WEATHER],
            "tool_choice": {"type": "tool", "name": "get_weather"},
        },
        "T+tc_fn",
    ),
    "T+none": (
        {"tools": [ANTHROPIC_WEATHER], "tool_choice": {"type": "none"}},
        "T+tc_none",
    ),
    "plain": ({}, "plain"),
}
RESPONSES: dict[str, tuple[dict[str, Any], str]] = {
    "codex": (
        {
            "tools": [RESPONSES_WEATHER],
            "tool_choice": "auto",
            "parallel_tool_calls": False,
        },
        "T+codex",
    ),
    "T+required": (
        {"tools": [RESPONSES_WEATHER], "tool_choice": "required"},
        "T+tc_req",
    ),
    "T+none+noparallel": (
        {
            "tools": [RESPONSES_WEATHER],
            "tool_choice": "none",
            "parallel_tool_calls": False,
        },
        "T+tc_none+par_false",
    ),
    "T+named": (
        {
            "tools": [RESPONSES_WEATHER],
            "tool_choice": {"type": "function", "name": "get_weather"},
        },
        "T+tc_fn",
    ),
    "plain+codex": (
        {"tool_choice": "auto", "parallel_tool_calls": False},
        "tc_auto+par_false",
    ),
    "plain": ({}, "plain"),
}
DOOR_SHAPES = {"messages": MESSAGES, "responses": RESPONSES}

#: A request that makes a backend that ignores `tool_choice` (Strata) name it, in each door's words.
FORCED: dict[str, dict[str, Any]] = {
    "chat": {"tools": [WEATHER], "tool_choice": "required"},
    "messages": {"tools": [ANTHROPIC_WEATHER], "tool_choice": {"type": "any"}},
    "responses": {"tools": [RESPONSES_WEATHER], "tool_choice": "required"},
}
#: The same, with the parallel switch off too: what Codex-shaped callers add.
FORCED_PAIR: dict[str, dict[str, Any]] = {
    "chat": {**FORCED["chat"], "parallel_tool_calls": False},
    "messages": {
        "tools": [ANTHROPIC_WEATHER],
        "tool_choice": {"type": "any", "disable_parallel_tool_use": True},
    },
    "responses": {**FORCED["responses"], "parallel_tool_calls": False},
}
DOOR_PATH = {
    "chat": "/v1/chat/completions",
    "messages": "/v1/messages",
    "responses": "/v1/responses",
}

#: How a door spells the names a driver's header carries, back to the chat door's.
DOOR_WORDS = {
    "chat": {},
    "messages": {
        "tool_choice.disable_parallel_tool_use": "parallel_tool_calls",
        "stop_sequences": "stop",
        "output_config.format": "response_format",
    },
    "responses": {"max_output_tokens": "max_tokens", "text.format": "response_format"},
}
CAMEL = re.compile(r"(?<=[a-z0-9])([A-Z])")


def canonical(header: str | None, door: str = "chat") -> list[str]:
    """A header's names in one spelling (the chat door's, snake_case), sorted.

    The gateway names a setting the way its door's caller wrote it; the driver names
    it in the contract's camelCase. Both are the same setting, so a comparison reads
    each as the chat door would.
    """
    names = [part.strip() for part in (header or "").split(",") if part.strip()]
    words = DOOR_WORDS[door]
    return sorted(CAMEL.sub(r"_\1", words.get(name, name)).lower() for name in names)


def door_request(
    door: str, model: str, fields: dict[str, Any], stream: bool
) -> tuple[str, dict]:
    if door == "chat":
        body: dict[str, Any] = {"model": model, "messages": CHAT, **fields}
    elif door == "messages":
        body = {"model": model, "max_tokens": 16, "messages": CHAT, **fields}
    else:
        body = {"model": model, "input": "hello there", **fields}
    if stream:
        body["stream"] = True
    return DOOR_PATH[door], body


def stream_failed(door: str, text: str) -> bool:
    """A streamed answer's 200 is long committed: a failure is a frame in the body."""
    if door == "chat":
        return any(line.startswith('data: {"error"') for line in text.splitlines())
    if door == "messages":
        return "event: error" in text
    return "event: response.failed" in text or "event: error" in text


# --------------------------------------------------------------------------- #
# What each backend family is, as the design says
# --------------------------------------------------------------------------- #

GAPS_IGNORED = {
    "tool_choice": ("required", "function"),
    "parallel_tool_calls": (False,),
}
GAPS_NOVA = {
    "tool_choice": ("none", "required", "function"),
    "parallel_tool_calls": (False,),
}


@dataclass(frozen=True)
class Fam:
    """A backend family: what its driver lists, and so what must be said and sent.

    `gaps` are the settings its driver says the backend does not honour, by value
    (`capabilities.settingsNotHonoured`). `how` is what is done with them:

    * `sent`: sent as asked and named (Strata and Ollama read neither `tool_choice`
      `required` nor a named function and ignore `parallel_tool_calls: false`);
    * `withheld`: named and not delivered (an OpenRouter model whose listing leaves the
      setting out is asked for only providers that take every parameter it is sent);
    * `native`: named and cannot be carried (Gemini's own API has no such field).

    `none_as_no_tools`: `tool_choice: none` is honoured by sending no tools (and what
    rides with them), which a backend that never reads `tool_choice` is given: its gap
    does not name `none`. Where the gap names it (Nova) the tools are kept and `none`
    is named, because Bedrock refuses a history with tool calls and no definitions.
    """

    key: str
    group: str
    route: str
    tag: str
    tools: bool
    gaps: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    how: str = "sent"
    none_as_no_tools: bool = False
    #: For a model whose tools are off: whether `tools: []` (the key, with nothing in it)
    #: is admitted. False: refused, as the rule says. None: not asserted. Ollama's entry
    #: for a model without tools still lists `tools`, so it is admitted there (left for a
    #: small round six, in `tools-assumed.md`).
    empty_tools_admitted: bool | None = False

    @property
    def withheld(self) -> set[str]:
        return set(self.gaps) if self.how == "withheld" else set()


FAMILIES = [
    # key, the driver it is served by, the model a client sends, what its answer says, tools on?
    Fam("local", "local", "local-model", "from local", True),
    Fam(
        "strata",
        "strata",
        "strata-model",
        "from strata stand-in",
        True,
        gaps=GAPS_IGNORED,
        none_as_no_tools=True,
    ),
    Fam(
        "ollama-tools",
        "ollama",
        "ollama-box/ollama-tools:latest",
        "from ollama stand-in",
        True,
        gaps=GAPS_IGNORED,
        none_as_no_tools=True,
    ),
    Fam(
        "ollama-notools",
        "ollama",
        "ollama-box/ollama-notools:latest",
        "from ollama stand-in",
        False,
        gaps=GAPS_IGNORED,
        none_as_no_tools=True,
        empty_tools_admitted=None,
    ),
    Fam(
        "or-nova",
        "or",
        "or-box/amazon/nova-lite-v1",
        "from OpenRouter stand-in",
        True,
        gaps=GAPS_NOVA,
        how="withheld",
    ),
    Fam(
        "or-nopar",
        "or",
        "or-box/anthropic/claude-haiku-5.5",
        "from OpenRouter stand-in",
        True,
        gaps={"parallel_tool_calls": (False,)},
        how="withheld",
    ),
    Fam(
        "or-all3", "or", "or-box/typesafe/jev-router", "from OpenRouter stand-in", True
    ),
    Fam(
        "or-notools",
        "or",
        "or-box/nvidia/switchyard",
        "from OpenRouter stand-in",
        False,
    ),
    Fam("or-unknown", "or", "or-box/test/unknown", "from OpenRouter stand-in", True),
    Fam(
        "gemini",
        "gemini",
        "gemini-box/gemini-3.5-flash",
        "from gemini stand-in",
        True,
        gaps={"parallel_tool_calls": (False,)},
        how="native",
    ),
    Fam("oai-gpt55", "openai", "oai-box/gpt-5.5", "from openai stand-in", True),
    Fam("oai-gpt6", "openai", "oai-box/gpt-6-astra", "from openai stand-in", False),
    Fam("oai-single-gpt6", "openai", "gpt-6-astra", "from openai stand-in", False),
    Fam("claude-cli", "cli", "claude-review", "from claude stub", False),
    Fam("codex-cli", "cli", "codex-review", "from codex stub", False),
]
FAM = {f.key: f for f in FAMILIES}
#: The families the Messages and Responses doors are run on: every kind of gap, and a
#: model whose tools are off.
DOOR_FAMILIES = (
    "local",
    "strata",
    "ollama-tools",
    "ollama-notools",
    "or-nova",
    "or-nopar",
    "or-all3",
    "or-unknown",
    "gemini",
)
#: Decided, said in plain words, and so not a failure: a seed of 0 or below to Strata
#: (it would ignore it, and the header cannot name a number), by a 400 that names it.
DECIDED_REFUSALS = {
    ("strata", "seed0"): re.compile(r"seed.*Strata|Strata.*seed", re.I | re.S)
}


#: What the refusal of a request that carries tools must say of a model whose tools are off:
#: that its driver reports it (`gateway/capabilities.tools_refused`), which is the observed
#: cause, and not that the model failed or that the request asked for something unlisted.
TOOLS_OFF_WORDS = re.compile(r"reports that tools cannot be carried")


@dataclass
class Expect:
    """What the design says of one request to one family.

    `status`: how it is answered (None: not asserted). `named`: the setting names its header
    carries, in the chat door's words, sorted. `delivered`: what the provider is sent of the
    tool fields (None: not asserted). `words`: what a refusal must say.
    """

    status: int | None
    named: list[str]
    delivered: dict[str, Any] | None
    words: re.Pattern[str] | None = None


def expect(fam: Fam, shape: Shape) -> Expect:
    """What the design says of one request to one family (`tools-assumed.md`).

    The oracle for the three-way agreement: the gateway's header, the driver's own, and
    what the stand-in was sent. Written from the design's words, not from either
    implementation.
    """
    if shape.name in ("seed0", "seed7", "neg_penalty"):
        if fam.key == "strata" and shape.name == "seed0":
            return Expect(400, [], None)
        if fam.key in ("strata", "local"):
            return Expect(200, [], dict(shape.fields))
        return Expect(None, [], None)
    if shape.has_tools and not fam.tools:
        return Expect(
            400, [], None, TOOLS_OFF_WORDS
        )  # tools to a model whose tools are off
    if shape.tools_key and not fam.tools:
        # `tools: []` is the key with nothing in it: refused the same, bar the one entry
        # (Ollama's) whose listing still offers `tools` (a small round six: not asserted).
        return Expect(None if fam.empty_tools_admitted is None else 400, [], None)
    # `tool_choice: none` to a backend that cannot be told it: no tools, nothing named
    stripped = fam.none_as_no_tools and shape.tc == "none"
    named: list[str] = []
    if not stripped:
        for setting, value in (
            ("tool_choice", shape.tc),
            ("parallel_tool_calls", shape.par),
        ):
            if value is not None and value in fam.gaps.get(setting, ()):
                named.append(setting)
    delivered: dict[str, Any] | None
    if fam.how == "native":
        delivered = None
    elif not fam.tools or stripped:
        delivered = {}
    else:
        delivered = {}
        if shape.has_tools:
            delivered["tools"] = ["get_weather"]
        if shape.tc is not None and "tool_choice" not in fam.withheld:
            delivered["tool_choice"] = shape.fields["tool_choice"]
        if shape.par is not None and "parallel_tool_calls" not in fam.withheld:
            delivered["parallel_tool_calls"] = shape.par
    return Expect(200, sorted(named), delivered)


# --------------------------------------------------------------------------- #
# The stand-ins: a provider, the agent beside the gateway, a driver that cannot answer
# --------------------------------------------------------------------------- #

#: OpenRouter's public list as it answered on 2026-10-12, trimmed to what a driver reads:
#: a model explicitly listing no tools, an unknown listing, and models with tools without `tool_choice` (Amazon
#: Nova is one), one without `parallel_tool_calls`, and one that has all three.
ARCH = {"input_modalities": ["text"], "output_modalities": ["text"]}
OPENROUTER_LISTING = {
    "data": [
        {
            "id": "nvidia/switchyard",
            "name": "NVIDIA: Switchyard",
            "context_length": 1000000,
            "architecture": ARCH,
            "supported_parameters": ["temperature", "max_tokens"],
        },
        {
            "id": "test/unknown",
            "name": "Unknown parameters",
            "context_length": 100000,
            "architecture": ARCH,
            "supported_parameters": [],
        },
        {
            "id": "amazon/nova-lite-v1",
            "name": "Amazon: Nova Lite 1.0",
            "context_length": 300000,
            "architecture": ARCH,
            "supported_parameters": [
                "max_tokens",
                "stop",
                "temperature",
                "tools",
                "top_k",
                "top_p",
            ],
        },
        {
            "id": "typesafe/jev-router",
            "name": "TypeSafe: Jev Router",
            "context_length": 1000000,
            "architecture": ARCH,
            "supported_parameters": [
                "frequency_penalty",
                "include_reasoning",
                "logit_bias",
                "logprobs",
                "max_completion_tokens",
                "max_tokens",
                "min_p",
                "parallel_tool_calls",
                "presence_penalty",
                "reasoning",
                "reasoning_effort",
                "repetition_penalty",
                "response_format",
                "seed",
                "stop",
                "structured_outputs",
                "temperature",
                "tool_choice",
                "tools",
                "top_a",
                "top_k",
                "top_logprobs",
                "top_p",
                "verbosity",
            ],
        },
        {
            "id": "anthropic/claude-haiku-5.5",
            "name": "Anthropic: Claude Haiku 5.5",
            "context_length": 1000000,
            "architecture": ARCH,
            "supported_parameters": [
                "include_reasoning",
                "max_completion_tokens",
                "max_tokens",
                "reasoning",
                "reasoning_effort",
                "response_format",
                "stop",
                "structured_outputs",
                "tool_choice",
                "tools",
                "verbosity",
            ],
        },
    ]
}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class Quiet(BaseHTTPRequestHandler):
    """A stand-in's base: HTTP/1.1, JSON in and out, a record of what it was sent."""

    protocol_version = "HTTP/1.1"
    #: Per stand-in (`handler_for` gives each its own): every POST, as (path, body).
    recorded: list[tuple[str, dict[str, Any]]] = []
    #: When each streamed chat answer began (perf_counter): the stream-head check.
    spoke: list[float] = []
    tag = "stand-in"
    #: When set, a streamed chat answer waits for it before its first frame.
    hold: threading.Event | None = None
    #: A failure for every chat, when set (429: the caller is told to try elsewhere).
    chat_status = 0

    def log_message(self, *_args: object) -> None:
        pass

    def setup(self) -> None:
        super().setup()
        # The headers and the body go out in two writes. Without this the body waits for the
        # client to acknowledge the headers (Nagle's algorithm against a delayed ACK: forty
        # milliseconds on Linux), and every request to a stand-in costs forty more.
        self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def send_json(self, status: int, body: Any) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_text(self, status: int, text: str) -> None:
        raw = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_sse(self, frames: list[str]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for frame in frames:
            self.wfile.write(frame.encode())
            self.wfile.flush()
        self.close_connection = True

    def read_json(self) -> Any:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {"unparsed": raw[:200].decode("utf-8", "replace")}

    def chat_done(self, model: str, stream: bool) -> None:
        """Answer a chat completion `from <tag>`, whole or as SSE."""
        if getattr(self, "loading", False):
            self.send_json(503, {"error": {"message": "Loading model"}})
            return
        if self.chat_status:
            self.send_json(self.chat_status, {"error": {"message": "stand-in failure"}})
            return
        usage = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
        text = f"from {self.tag}"
        if not stream:
            message = {"role": "assistant", "content": text}
            choice = {"index": 0, "message": message, "finish_reason": "stop"}
            self.send_json(
                200,
                {
                    "id": "x",
                    "object": "chat.completion",
                    "model": model,
                    "choices": [choice],
                    "usage": usage,
                },
            )
            return
        # This answer's own record: held past the check that held it, it must not write in the
        # next one's (a check gives the handler a new list each time).
        spoke = self.spoke
        if self.hold is not None:
            self.hold.wait(30)
        spoke.append(time.perf_counter())
        chunk = {
            "id": "x",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}}],
        }
        last = {
            "id": "x",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": usage,
        }
        self.send_sse(
            [
                f"data: {json.dumps(chunk)}\n\n",
                f"data: {json.dumps(last)}\n\n",
                "data: [DONE]\n\n",
            ]
        )


def handler_for(base: type[Quiet], tag: str, **state: Any) -> Any:
    """A stand-in's handler class, with state of its own (its attributes are set live)."""
    return type(
        f"{base.__name__}_{tag}",
        (base,),
        {"recorded": [], "spoke": [], "tag": tag, **state},
    )


class OpenAIWire(Quiet):
    """An OpenAI-compatible server (llama-server, Strata, an OpenAI account) as far as a
    chat and a count go. `models` is what `/v1/models` lists."""

    models: list[str] = []
    count_mode = "ok"

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/v1/models":
            data = [{"id": m, "object": "model"} for m in self.models]
            self.send_json(200, {"object": "list", "data": data})
        else:
            self.send_json(404, {"error": "not here"})

    def do_POST(self) -> None:
        body = self.read_json()
        path = self.path.split("?", 1)[0]
        self.recorded.append((path, body))
        if path == "/v1/chat/completions":
            self.chat_done(str(body.get("model")), bool(body.get("stream")))
        elif path == "/apply-template":
            if self.count_mode == "template500":
                self.send_json(500, {"error": "template is broken"})
            elif self.count_mode == "template_nonjson":
                self.send_text(200, "not json at all")
            elif self.count_mode == "template_missing":
                self.send_json(200, {"unexpected": True})
            elif self.count_mode == "reset":
                self.connection.close()
                self.close_connection = True
            else:
                words = " ".join(
                    str(m.get("content")) for m in body.get("messages", [])
                )
                self.send_json(200, {"prompt": words})
        elif path == "/tokenize":
            if self.count_mode == "tokenize500":
                self.send_json(500, {"error": "tokenizer is broken"})
            elif self.count_mode == "tokenize_nonjson":
                self.send_text(200, "no tokens here")
            else:
                self.send_json(
                    200, {"tokens": list(range(len(str(body.get("content")).split())))}
                )
        else:
            self.send_json(404, {"error": "not here"})


class OpenRouter(Quiet):
    """The parts of OpenRouter a driver reads: its lists, and a chat route."""

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/v1/models/user":
            self.send_json(200, OPENROUTER_LISTING)
        elif path in ("/v1/images/models", "/v1/videos/models"):
            self.send_json(200, {"data": []})
        else:
            self.send_json(404, {"error": {"message": "not here"}})

    def do_POST(self) -> None:
        body = self.read_json()
        path = self.path.split("?", 1)[0]
        self.recorded.append((path, body))
        if path == "/v1/chat/completions":
            self.chat_done(str(body.get("model")), bool(body.get("stream")))
        else:
            self.send_json(404, {"error": {"message": "not here"}})


class Ollama(Quiet):
    """Ollama: its model list, `/api/show` (capabilities), and its OpenAI-compatible chat."""

    capabilities: dict[str, list[str]] = {}

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/api/tags":
            self.send_json(200, {"models": [{"name": n} for n in self.capabilities]})
        else:
            self.send_json(404, {"error": "not here"})

    def do_POST(self) -> None:
        body = self.read_json()
        path = self.path.split("?", 1)[0]
        if path == "/api/show":
            self.send_json(
                200, {"capabilities": self.capabilities.get(str(body.get("model")), [])}
            )
            return
        self.recorded.append((path, body))
        if path == "/v1/chat/completions":
            self.chat_done(str(body.get("model")), bool(body.get("stream")))
        else:
            self.send_json(404, {"error": "not here"})


class Gemini(Quiet):
    """Google's Gemini API as far as a chat goes: a model list and `generateContent`."""

    models: list[str] = []

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] != "/models":
            self.send_json(404, {"error": {"message": "not here"}})
            return
        methods = ["generateContent", "streamGenerateContent", "countTokens"]
        listed = [
            {
                "name": f"models/{m}",
                "baseModelId": m,
                "version": "001",
                "displayName": m,
                "inputTokenLimit": 1048576,
                "outputTokenLimit": 65536,
                "supportedGenerationMethods": methods,
            }
            for m in self.models
        ]
        self.send_json(200, {"models": listed})

    def do_POST(self) -> None:
        body = self.read_json()
        path = self.path.split("?", 1)[0]
        self.recorded.append((path, body))
        if self.chat_status:
            self.send_json(self.chat_status, {"error": {"message": "stand-in failure"}})
            return
        content = {"role": "model", "parts": [{"text": f"from {self.tag}"}]}
        answer = {
            "candidates": [{"content": content, "finishReason": "STOP"}],
            "usageMetadata": {
                "promptTokenCount": 3,
                "candidatesTokenCount": 2,
                "totalTokenCount": 5,
            },
        }
        if path.endswith(":streamGenerateContent"):
            self.send_sse([f"data: {json.dumps(answer)}\n\n"])
        elif path.endswith(":generateContent"):
            self.send_json(200, answer)
        else:
            self.send_json(404, {"error": {"message": "not here"}})


class Agent(Quiet):
    """The agent beside the gateway: where the drivers are, and the key authority.

    A key CHECK (what a count makes) is answered as `check_mode` and `check_status` say;
    the policy as `policy_status` says.
    """

    components: list[dict[str, Any]] = []
    check_status = 200
    check_mode = "status"  # status | hang | close
    policy_status = 200
    admissions: list[str] = []

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/v1/components":
            self.send_json(200, {"components": self.components})
        elif path == "/v1/runtimes":
            self.send_json(200, {"runtimes": []})
        elif path == "/v1/node":
            self.send_json(200, {"enrolled": False})
        elif path == "/v1/auth/client-keys/policy":
            if self.policy_status != 200:
                self.send_json(
                    self.policy_status, {"detail": "policy is having a moment"}
                )
                return
            expires = time.strftime(
                "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 3600)
            )
            self.send_json(
                200,
                {
                    "authority": "control:acceptance",
                    "generatedAt": time.time(),
                    "keys": [{"id": "key-1", "expiresAt": expires}],
                    "revision": 0,
                },
            )
        else:
            self.send_json(404, {"error": "not here"})

    def do_POST(self) -> None:
        body = self.read_json()
        if self.path.split("?", 1)[0] != "/v1/auth/client-keys/admission":
            self.send_json(404, {"error": "not here"})
            return
        self.admissions.append(str(body.get("action")))
        if body.get("action") == "check":
            if self.check_mode == "hang":
                time.sleep(8)
            elif self.check_mode == "close":
                self.connection.close()
                self.close_connection = True
                return
            elif self.check_status != 200:
                self.send_json(
                    self.check_status, {"detail": "the authority is having a moment"}
                )
                return
        self.send_json(
            200, {"keyId": body["keyId"], "keyName": "acceptance", "leaseSeconds": 30}
        )


class FakeDriver(Quiet):
    """A driver that answers `/healthz` and `/v1/info`, and answers the second in any way a
    listing can fail (`mode`): what the gateway's re-read of a listing is made to meet."""

    info: dict[str, Any] = {}
    mode = "ok"

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self.send_json(200, {"status": "ok"})
            return
        if path != "/v1/info":
            self.send_json(404, {"detail": "not here"})
            return
        if self.mode == "http500":
            self.send_json(500, {"detail": "the driver is having a moment"})
        elif self.mode == "http503":
            self.send_json(503, {"detail": "the driver is starting"})
        elif self.mode == "http404":
            self.send_json(404, {"detail": "no such route"})
        elif self.mode == "http401":
            self.send_json(401, {"detail": "the token is refused"})
        elif self.mode == "nonjson":
            self.send_text(200, "this is not a listing")
        elif self.mode == "notalisting":
            self.send_json(200, {"unexpected": True})
        elif self.mode == "degraded":
            gone = copy.deepcopy(self.info)
            gone["models"] = []
            gone["degraded"] = "could not build its engine: the provider key is missing"
            self.send_json(200, gone)
        elif self.mode == "model_missing":
            gone = copy.deepcopy(self.info)
            gone["models"] = []
            self.send_json(200, gone)
        elif self.mode == "hang":
            time.sleep(7)
            self.send_json(200, self.info)
        elif self.mode == "drop":
            self.connection.close()
            self.close_connection = True
        else:
            self.send_json(200, self.info)

    def do_POST(self) -> None:
        self.read_json()
        self.send_json(503, {"detail": {"title": "never asked", "status": 503}})


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        """A client that hung up (a gateway that gave up on a held stand-in) is not news."""


def serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, int]:
    server = Server(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, int(server.server_address[1])


# --------------------------------------------------------------------------- #
# The real driver, as its own process; the subscription CLIs as a stand-in script
# --------------------------------------------------------------------------- #


def stub_cli(name: str, args: list[str]) -> None:
    """What the subscription CLI engines run here instead of the CLI: reads the prompt on
    stdin and prints a canned answer. It is this script; no CLI is ever started."""
    with contextlib.suppress(Exception):
        sys.stdin.buffer.read()
    if name == "claude":
        if "stream-json" in args:
            delta = {"type": "text_delta", "text": "from claude stub"}
            event = {"type": "content_block_delta", "delta": delta}
            print(json.dumps({"type": "stream_event", "event": event}))
        print(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "from claude stub",
                    "usage": {"input_tokens": 3, "output_tokens": 2},
                    "stop_reason": "end_turn",
                }
            )
        )
        return
    print(json.dumps({"type": "thread.started", "thread_id": "t"}))
    item = {"id": "i", "type": "agent_message", "text": "from codex stub"}
    print(json.dumps({"type": "item.completed", "item": item}))
    print(
        json.dumps(
            {"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": 2}}
        )
    )


def stub_the_clis() -> None:
    """Point the two subscription CLI engines at `stub_cli`, in place of their binary.

    The engines are otherwise the real ones: what they refuse before a process starts,
    what they list and what they drop are theirs. Only the program they would run is
    replaced, so no subscription CLI can ever be started from here.
    """
    from eugene_plexus_inference_driver.engines import (  # type: ignore[import-untyped]
        claude_code_cli,
        codex_cli,
    )

    for engine, name in (
        (claude_code_cli.ClaudeCodeCliEngine, "claude"),
        (codex_cli.CodexCliEngine, "codex"),
    ):

        def build(
            self: Any,
            *args: Any,
            _real: Any = engine._build_argv,
            _name: str = name,
            **kw: Any,
        ) -> list[str]:
            return [
                sys.executable,
                str(HERE),
                "--stub-cli",
                _name,
                *_real(self, *args, **kw)[1:],
            ]

        engine._build_argv = build  # type: ignore[method-assign]


def die_with_the_parent() -> None:
    """Exit when the process that started this one is gone, however it went.

    The parent holds the write end of this process's stdin and never writes to it; when it
    exits, killed or not, the pipe closes and the read below ends. A driver left running by
    a run that crashed would hold a port and a stand-in's address for good.
    """

    def watch() -> None:
        with contextlib.suppress(Exception):
            sys.stdin.buffer.read()
        os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


def run_driver(config: Path, port: int, record: Path, agent_url: str) -> None:
    """The real driver app, over real HTTP, recording what `/v1/generate*` is asked and
    answers (the body, the status, the response headers) without changing what it does."""
    if DRIVER_SRC:
        sys.path.insert(0, DRIVER_SRC)
    refuse_the_internet()
    die_with_the_parent()
    import uvicorn

    import eugene_plexus_inference_driver as package  # type: ignore[import-untyped]
    from eugene_plexus_inference_driver.app import create_app  # type: ignore[import-untyped]
    from eugene_plexus_inference_driver.settings import Settings  # type: ignore[import-untyped]

    (record.parent / "code.txt").write_text(
        str(Path(package.__file__).resolve()), "utf-8"
    )
    stub_the_clis()
    inner = create_app(settings=Settings(config_file=config, agent_url=agent_url))

    async def app(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/v1/generate"):
            await inner(scope, receive, send)
            return
        body = bytearray()
        chunks = bytearray()
        seen: dict[str, Any] = {}

        async def recv() -> Any:
            message = await receive()
            if message["type"] == "http.request":
                body.extend(message.get("body", b""))
            return message

        async def snd(message: Any) -> None:
            if message["type"] == "http.response.start":
                seen["status"] = message["status"]
                seen["headers"] = {
                    k.decode().lower(): v.decode() for k, v in message["headers"]
                }
            elif message["type"] == "http.response.body" and len(chunks) < 4000:
                chunks.extend(message.get("body", b"")[:4000])
            await send(message)

        try:
            await inner(scope, recv, snd)
        finally:
            try:
                parsed = json.loads(bytes(body) or b"{}")
            except ValueError:
                parsed = {"unparsed": True}
            row = {
                "path": scope["path"],
                "body": parsed,
                "answer": bytes(chunks).decode("utf-8", "replace")[:1500],
                **seen,
            }
            with record.open("a", encoding="utf-8") as out:
                out.write(json.dumps(row) + "\n")

    uvicorn.run(
        app, host="127.0.0.1", port=port, log_level="warning", forwarded_allow_ips=[]
    )


class Driver:
    """One real driver app, as a process, and the record of what it was asked."""

    def __init__(
        self, name: str, config: dict[str, Any], tmp: Path, agent_url: str
    ) -> None:
        self.name = name
        self.dir = tmp / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.config = self.dir / "driver.yaml"
        self.config.write_text(json.dumps(config), "utf-8")  # JSON is YAML
        self.record = self.dir / "record.jsonl"
        self.log_path = self.dir / "driver.log"
        self.port = free_port()
        self._rows: list[dict[str, Any]] = []
        self._offset = 0
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.upper().startswith("EUGENE_PLEXUS")
        }
        env["PYTHONUTF8"] = "1"
        for proxy in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
        ):
            env.pop(proxy, None)
        self.log = self.log_path.open("ab")
        self.proc = subprocess.Popen(
            [
                sys.executable,
                str(HERE),
                "--driver",
                str(self.config),
                str(self.port),
                str(self.record),
                agent_url,
            ],
            cwd=self.dir,
            stdin=subprocess.PIPE,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            env=env,
        )
        self.info: dict[str, Any] = {}

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def wait(self, plain: httpx.Client) -> dict[str, Any]:
        """Ready: it answers, and an account has read its provider's list."""
        deadline = time.perf_counter() + 90
        while True:
            try:
                if plain.get(f"{self.url}/healthz").status_code == 200:
                    info = plain.get(f"{self.url}/v1/info").json()
                    catalogue = info.get("catalogue")
                    if (
                        catalogue is None
                        or catalogue.get("refreshedAt")
                        or catalogue.get("error")
                    ):
                        self.info = info
                        return info  # type: ignore[no-any-return]
            except (httpx.HTTPError, ValueError):
                pass
            if self.proc.poll() is not None:
                raise SystemExit(f"driver {self.name} exited:\n{self.tail()}")
            if time.perf_counter() > deadline:
                raise SystemExit(f"driver {self.name} never came up:\n{self.tail()}")
            time.sleep(0.1)

    def tail(self) -> str:
        return self.log_path.read_text("utf-8", "replace")[-2000:]

    def code(self) -> str:
        return (self.dir / "code.txt").read_text("utf-8")

    def rows(self) -> list[dict[str, Any]]:
        """Every `/v1/generate*` the driver has answered, in order (read as it grows)."""
        if self.record.exists():
            with self.record.open("rb") as handle:
                handle.seek(self._offset)
                data = handle.read()
            end = data.rfind(b"\n") + 1  # only whole lines
            for line in data[:end].decode("utf-8").splitlines():
                if line:
                    self._rows.append(json.loads(line))
            self._offset += end
        return self._rows

    def generated_since(self, count: int, *, wait: bool) -> list[dict[str, Any]]:
        """The answers to a generation since `count` rows: waited for when one is certain."""
        deadline = time.perf_counter() + 3
        while True:
            rows = [
                r
                for r in self.rows()[count:]
                if r["path"] in ("/v1/generate", "/v1/generate/stream")
            ]
            if rows or not wait or time.perf_counter() > deadline:
                return rows
            time.sleep(0.005)

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.proc.stdin is not None:
            self.proc.stdin.close()
        self.log.close()


# --------------------------------------------------------------------------- #
# The real gateway, in this process, with real keys
# --------------------------------------------------------------------------- #


def load_gateway() -> Any:
    """The gateway's own modules, from the tree `EP_GATEWAY_SRC` names, else as installed."""
    if GATEWAY_SRC:
        sys.path.insert(0, GATEWAY_SRC)
    # The components are not typed packages: what they hand back is read as it is.
    import eugene_plexus_gateway  # type: ignore[import-untyped]
    from eugene_plexus_gateway import tokens  # type: ignore[import-untyped]
    from eugene_plexus_gateway.app import create_app  # type: ignore[import-untyped]
    from eugene_plexus_gateway.settings import Settings  # type: ignore[import-untyped]

    where = Path(eugene_plexus_gateway.__file__).resolve()
    if GATEWAY_SRC and Path(GATEWAY_SRC).resolve() not in where.parents:
        raise SystemExit(
            f"EP_GATEWAY_SRC is {GATEWAY_SRC} and the gateway came from {where}"
        )
    return type(
        "Gateway",
        (),
        {
            "create_app": create_app,
            "Settings": Settings,
            "tokens": tokens,
            "file": where,
        },
    )


class Trust:
    """A trust bundle as a gateway's agent keeps it, and what its root signs: an operator
    session, a client key, and the gateway's own service token."""

    def __init__(self, directory: Path, mods: Any) -> None:
        tokens = mods.tokens
        self.tokens = tokens
        self.recipient = tokens.node_recipient("gw")
        self.identity = tokens.generate_private_key()
        self.root = tokens.Signer(key=tokens.generate_private_key(), issuer="control")
        self.node = tokens.Signer(
            key=tokens.generate_private_key(), issuer=self.recipient
        )
        bundle = tokens.build_bundle(
            authority=self.identity,
            version=1,
            epoch=1,
            keys=[self.root.trust_key(["authority"]), self.node.trust_key(["node"])],
        )
        directory.mkdir(parents=True, exist_ok=True)
        self.bundle_file = directory / "trust_bundle.json"
        tokens.write_bundle_file(self.bundle_file, bundle)
        self.authority = tokens.public_b64(self.identity)

    def session(self) -> str:
        token, _ = self.root.mint(
            typ=self.tokens.TYP_SESSION,
            sub="operator",
            aud=[self.recipient, "control"],
            ttl_seconds=3600,
        )
        return token

    def client_key(self) -> str:
        token, _ = self.root.mint(
            typ=self.tokens.TYP_CLIENT,
            sub="app",
            aud=["gateway"],
            ttl_seconds=3600,
            jti="key-1",
        )
        return token

    def service(self) -> str:
        token, _ = self.node.mint(
            typ=self.tokens.TYP_SERVICE,
            sub="gateway",
            aud=[self.recipient],
            ttl_seconds=3600,
        )
        return token


def serve_app(app: Any, port: int) -> tuple[Any, threading.Thread]:
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            forwarded_allow_ips=[],
        )
    )
    setattr(
        server, "install_signal_handlers", lambda: None
    )  # older uvicorn installed them here
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.perf_counter() + 30
    while not server.started:
        if time.perf_counter() > deadline:
            raise SystemExit("the gateway never started")
        time.sleep(0.02)
    return server, thread


class Gateway:
    """The real gateway app, on a port of its own, with operator and client-key credentials."""

    def __init__(
        self,
        tmp: Path,
        agent_port: int,
        slots: list[dict[str, Any]],
        trust: Trust,
        mods: Any,
        tag: str,
    ) -> None:
        config = tmp / f"gateway-{tag}.yaml"
        # The routing table is read once: nothing refreshes it in the middle of a check.
        config.write_text(
            json.dumps({"modelSlots": slots, "routingRefreshSeconds": 300}), "utf-8"
        )
        self.app = mods.create_app(
            mods.Settings(
                config_file=config,
                metrics_file=tmp / f"metrics-{tag}.sqlite3",
                agent_url=f"http://127.0.0.1:{agent_port}",
                trust_bundle_file=str(trust.bundle_file),
                trust_authority=trust.authority,
                auth_recipient=trust.recipient,
                service_token=trust.service(),
            )
        )
        self.port = free_port()
        self.server, self.thread = serve_app(self.app, self.port)
        self.operator = {"Authorization": f"Bearer {trust.session()}"}
        self.keyed = {"Authorization": f"Bearer {trust.client_key()}"}
        self.http = httpx.Client(
            base_url=f"http://127.0.0.1:{self.port}", trust_env=False, timeout=120
        )

    def stop(self) -> None:
        self.http.close()
        self.server.should_exit = True
        self.thread.join(timeout=10)


# --------------------------------------------------------------------------- #
# The stack
# --------------------------------------------------------------------------- #


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    text: str

    @property
    def message(self) -> str:
        """What a refusal says, whichever door's envelope it is in."""
        try:
            error = json.loads(self.text)["error"]
            return str(error["message"] if isinstance(error, dict) else error)
        except (ValueError, KeyError, TypeError):
            return self.text[:300]


class Stack:
    """Stand-ins, real drivers and the real gateway, built once."""

    def __init__(self, tmp: Path, families: list[Fam], mods: Any) -> None:
        self.tmp = tmp
        self.mods = mods
        self.fams = {f.key: f for f in families}
        self.drivers: list[Driver] = []
        self.servers: list[ThreadingHTTPServer] = []
        self.by_fam: dict[str, tuple[Any, Driver]] = {}
        self.trust = Trust(tmp / "trust", mods)
        self.gateways: list[Gateway] = []
        try:
            self.build()
        except BaseException:
            self.stop()
            raise

    def _serve(self, handler: Any) -> int:
        server, port = serve(handler)
        self.servers.append(server)
        return port

    def _driver(self, name: str, config: dict[str, Any]) -> Driver:
        driver = Driver(name, config, self.tmp, self.agent_url)
        self.drivers.append(driver)
        return driver

    def stand_in(self, fam: Fam) -> Any:
        return self.by_fam[fam.key][0]

    def driver(self, fam: Fam) -> Driver:
        return self.by_fam[fam.key][1]

    def build(self) -> None:
        groups = {f.group for f in self.fams.values()} | {"local"}
        # The agent first: every driver is told where it is, so none can look for the
        # real one on its default port.
        self.agent_h = handler_for(Agent, "agent", components=[], admissions=[])
        self.agent_port = self._serve(self.agent_h)
        self.agent_url = f"http://127.0.0.1:{self.agent_port}"
        key = "standin-key"

        def base(handler: Any) -> str:
            return f"http://127.0.0.1:{self._serve(handler)}"

        wired: dict[str, tuple[Any, Driver]] = {}
        self.local_h = handler_for(OpenAIWire, "local", models=["local-model"])
        local_url = base(self.local_h)
        self.local = self._driver(
            "local-box",
            {
                "provider": "openai_compat_custom",
                "baseUrl": local_url,
                "modelId": "local-model",
            },
        )
        wired["local"] = (self.local_h, self.local)
        if "or" in groups:
            handler = handler_for(OpenRouter, "OpenRouter stand-in")
            wired["or"] = (
                handler,
                self._driver(
                    "or-box",
                    {"provider": "openrouter", "apiKey": key, "baseUrl": base(handler)},
                ),
            )
        if "strata" in groups:
            handler = handler_for(
                OpenAIWire, "strata stand-in", models=["strata-model"]
            )
            config = {
                "provider": "strata_local",
                "baseUrl": base(handler),
                "modelId": "strata-model",
            }
            wired["strata"] = (handler, self._driver("strata-box", config))
        if "ollama" in groups:
            handler = handler_for(
                Ollama,
                "ollama stand-in",
                capabilities={
                    "ollama-tools:latest": ["completion", "tools"],
                    "ollama-notools:latest": ["completion"],
                },
            )
            wired["ollama"] = (
                handler,
                self._driver(
                    "ollama-box", {"provider": "ollama_local", "baseUrl": base(handler)}
                ),
            )
        if "gemini" in groups:
            handler = handler_for(
                Gemini, "gemini stand-in", models=["gemini-3.5-flash"]
            )
            wired["gemini"] = (
                handler,
                self._driver(
                    "gemini-box",
                    {"provider": "gemini", "apiKey": key, "baseUrl": base(handler)},
                ),
            )
        if "openai" in groups:
            handler = handler_for(
                OpenAIWire, "openai stand-in", models=["gpt-6-astra", "gpt-5.5"]
            )
            url = base(handler)
            account = self._driver(
                "oai-box", {"provider": "openai", "apiKey": key, "baseUrl": url}
            )
            single = self._driver(
                "oai1-box",
                {
                    "provider": "openai",
                    "apiKey": key,
                    "baseUrl": url,
                    "modelId": "gpt-6-astra",
                },
            )
            wired["openai"] = (handler, account)
            wired["openai-single"] = (handler, single)
        if "cli" in groups:
            never = str(
                self.tmp / "no-such-cli"
            )  # the engines run a stand-in, never this
            handler = handler_for(Quiet, "never")
            claude = self._driver(
                "claude-box",
                {
                    "provider": "claude_subscription",
                    "claudeCodeCliPath": never,
                    "modelId": "claude-review",
                },
            )
            codex = self._driver(
                "codex-box",
                {
                    "provider": "chatgpt_subscription",
                    "codexCliPath": never,
                    "modelId": "codex-review",
                },
            )
            wired["claude"] = (handler, claude)
            wired["codex"] = (handler, codex)

        plain = httpx.Client(trust_env=False, timeout=60)
        try:
            for driver in self.drivers:
                driver.wait(plain)
        finally:
            plain.close()
        for fam in self.fams.values():
            name = {
                "oai-single-gpt6": "openai-single",
                "claude-cli": "claude",
                "codex-cli": "codex",
            }.get(fam.key, fam.group)
            self.by_fam[fam.key] = wired[name]
        self.agent_h.components = [
            {
                "name": d.name,
                "kind": "inference-driver",
                "url": d.url,
                "status": "running",
            }
            for d in self.drivers
        ]
        slots = [
            {"model": f"slot-{f.key}", "targets": [f.route, "local-model"]}
            for f in self.fams.values()
            if f.key != "local"
        ]
        if "strata" in self.fams:
            slots.append(
                {
                    "model": "slot-local-first",
                    "targets": ["local-model", FAM["strata"].route],
                }
            )
        self.slots = slots
        self.gw = self.new_gateway(slots, "main")

    def new_gateway(
        self, slots: list[dict[str, Any]], tag: str, agent_port: int | None = None
    ) -> Gateway:
        gateway = Gateway(
            self.tmp, agent_port or self.agent_port, slots, self.trust, self.mods, tag
        )
        self.gateways.append(gateway)
        return gateway

    def retire(self, gateway: Gateway) -> None:
        gateway.stop()
        self.gateways.remove(gateway)

    def stop(self) -> None:
        for gateway in self.gateways:
            gateway.stop()
        for server in self.servers:
            server.shutdown()
        for driver in self.drivers:
            driver.stop()

    # -- asking -----------------------------------------------------------------

    def post(
        self,
        door: str,
        model: str,
        fields: dict[str, Any],
        stream: bool,
        gateway: Gateway | None = None,
    ) -> Reply:
        gateway = gateway or self.gw
        path, body = door_request(door, model, fields, stream)
        with gateway.http.stream(
            "POST", path, json=body, headers=gateway.operator
        ) as response:
            headers = {k.lower(): v for k, v in response.headers.items()}
            text = response.read().decode("utf-8", "replace")
        return Reply(response.status_code, headers, text)

    def sent(self, fam: Fam) -> dict[str, Any] | None:
        """What the stand-in was last sent of the tool fields, or None when it was sent no chat."""
        for path, body in reversed(self.stand_in(fam).recorded):
            if path.endswith("/chat/completions"):
                return {k: body[k] for k in SENT_FIELDS if k in body}
        return None

    def premise(self, fam: Fam) -> list[str]:
        """The listing says what the design says of this family: tools on or off, and its gaps."""
        driver = self.driver(fam)
        name = (
            fam.route.split("/", 1)[1]
            if fam.route.startswith(driver.name + "/")
            else fam.route
        )
        model = next(
            (m for m in driver.info.get("models") or [] if m.get("id") == name), None
        )
        if model is None:
            return [f"{fam.key}: its driver does not list {name!r}"]
        caps = model.get("capabilities") or {}
        problems = []
        if caps.get("toolCalling") is not fam.tools:
            problems.append(
                f"{fam.key}: toolCalling is {caps.get('toolCalling')!r}, the design says {fam.tools}"
            )
        listed = {
            canonical(g["setting"])[0]: tuple(g["values"])
            for g in caps.get("settingsNotHonoured") or []
        }
        if listed != fam.gaps:
            problems.append(
                f"{fam.key}: settingsNotHonoured is {listed}, the design says {fam.gaps}"
            )
        return problems


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #


@dataclass
class Result:
    key: str
    name: str
    problems: list[str]
    detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class Tally:
    """What the requests of a check came to, so that a green line is seen to have said something."""

    served: int = 0
    refused: int = 0
    named: int = 0  #: served, and the header named at least one setting

    def __str__(self) -> str:
        return (
            f"{self.served} served ({self.named} naming what the backend ignores), "
            f"{self.refused} refused in plain words"
        )


def compare(
    stack: Stack,
    fam: Fam,
    door: str,
    sent: Shape,
    like: Shape,
    stream: bool,
    tally: Tally,
) -> list[str]:
    """One request to one family: status, who answered, and the three names for it."""
    exp = expect(fam, like)
    label = f"{fam.key} {door} {sent.name} {'stream' if stream else 'whole'}"
    driver = stack.driver(fam)
    stack.stand_in(fam).recorded.clear()
    before = len(driver.rows())
    reply = stack.post(door, fam.route, sent.fields, stream)
    # A stream's 200 is committed before a backend is asked: its failure is a frame in the body.
    failed = reply.status != 200 or (stream and stream_failed(door, reply.text))
    words = reply.message if reply.status != 200 else reply.text
    rows = driver.generated_since(before, wait=not failed)
    problems: list[str] = []
    refusal = DECIDED_REFUSALS.get((fam.key, sent.name))
    tally.refused += failed
    tally.served += not failed
    if exp.status == 200 and failed:
        problems.append(
            f"{label}: refused ({reply.status}), the design says served: {words[:200]!r}"
        )
    if exp.status is not None and exp.status != 200 and not failed:
        problems.append(f"{label}: served, the design says {exp.status}")
    if failed:
        if not words.strip():
            problems.append(f"{label}: a refusal that says nothing")
        if rows and not refusal:
            statuses = [r.get("status") for r in rows]
            problems.append(
                f"{label}: admitted by the gateway, then refused {statuses} by its driver: "
                f"{rows[-1].get('answer', '')[:200]!r}"
            )
        if refusal and not refusal.search(words):
            problems.append(
                f"{label}: the decided refusal does not name its cause: {words[:200]!r}"
            )
        if exp.words is not None and not exp.words.search(words):
            problems.append(
                f"{label}: the refusal of tools does not say that its driver reports they "
                f"cannot be carried (its observed cause): {words[:200]!r}"
            )
        if not refusal and sent.tools_key and not re.search(r"tools", words, re.I):
            problems.append(
                f"{label}: a refusal of tools that does not say so: {words[:200]!r}"
            )
        return problems
    if fam.tag not in reply.text:
        problems.append(
            f"{label}: answered, but not by {fam.tag!r}: {reply.text[:160]!r}"
        )
    if not rows:
        problems.append(f"{label}: answered, with no record that its driver was asked")
        return problems
    gateway_names = canonical(reply.headers.get(HEADER), door)
    driver_names = canonical(rows[-1].get("headers", {}).get(HEADER))
    tally.named += bool(gateway_names)
    if driver_names != gateway_names:
        problems.append(
            f"{label}: the gateway names {gateway_names}, its driver names {driver_names}"
        )
    if gateway_names != exp.named:
        problems.append(f"{label}: named {gateway_names}, the design says {exp.named}")
    if exp.delivered is not None:
        got = stack.sent(fam) or {}
        if (
            got.get("tools") is not None
        ):  # the tools by name: their schemas are not the question
            got = {**got, "tools": [t["function"]["name"] for t in got["tools"]]}
        if got != exp.delivered:
            problems.append(
                f"{label}: the provider was sent {got}, the design says {exp.delivered} (named {gateway_names})"
            )
    return problems


def check_header(stack: Stack, only: set[str] | None) -> Result:
    problems: list[str] = []
    tally = Tally()
    fams = [f for f in stack.fams.values() if only is None or f.key in only]
    for fam in fams:
        problems += stack.premise(fam)
    for fam in fams:
        for shape in SHAPES + (SEEDS if fam.key in ("local", "strata") else []):
            for stream in (False, True):
                problems += compare(stack, fam, "chat", shape, shape, stream, tally)
    for fam in fams:
        if fam.key not in DOOR_FAMILIES:
            continue
        for door, shapes in DOOR_SHAPES.items():
            for name, (fields, chat_shape) in shapes.items():
                for stream in (False, True):
                    sent = Shape(f"{door}:{name}", fields)
                    problems += compare(
                        stack, fam, door, sent, BY_NAME[chat_shape], stream, tally
                    )
    doors = len([f for f in fams if f.key in DOOR_FAMILIES])
    detail = (
        f"{len(fams)} families x {len(SHAPES)} shapes (+{len(SEEDS)} for Strata and the llama) whole and "
        f"streamed on the chat door, {doors} on Messages and Responses: {tally}"
    )
    return Result(
        "header",
        "header agreement: gateway, driver and provider say the same",
        problems,
        detail,
    )


def check_failover(stack: Stack) -> Result:
    """A whole answer is named by the backend that served it; a stream's head by the first asked."""
    strata, local = FAM["strata"], FAM["local"]
    problems: list[str] = []
    named = {"strata": sorted(["tool_choice", "parallel_tool_calls"]), "local": []}
    asked = 0

    def ask(first: Fam, door: str, slot: str, stream: bool) -> Reply | None:
        """One request, to a gateway that has asked nobody yet: a failure opens its backend's
        circuit for longer each time, so each request gets a gateway of its own, and the
        backend that must fail is the one asked first."""
        nonlocal asked
        gateway = stack.new_gateway(stack.slots, f"failover-{asked}")
        try:
            stack.stand_in(first).recorded.clear()
            reply = stack.post(door, slot, FORCED_PAIR[door], stream, gateway)
        finally:
            stack.retire(gateway)
        if not any(
            p.endswith("/chat/completions") for p, _ in stack.stand_in(first).recorded
        ):
            problems.append(f"{slot} {door}: {first.key} was never asked first")
            return None
        asked += 1
        return reply

    try:
        for first, second, slot in (
            (strata, local, "slot-strata"),
            (local, strata, "slot-local-first"),
        ):
            stack.stand_in(first).chat_status = 429
            try:
                for door in ("chat", "messages", "responses"):
                    label = f"{first.key} fails, {second.key} serves, {door}"
                    before = len(stack.driver(second).rows())
                    reply = ask(first, door, slot, False)
                    if reply is None:
                        continue
                    rows = stack.driver(second).generated_since(before, wait=True)
                    if reply.status != 200 or second.tag not in reply.text:
                        problems.append(
                            f"{label}: answered {reply.status}: {reply.text[:200]!r}"
                        )
                        continue
                    if not rows:
                        problems.append(
                            f"{label}: answered, with no record that {second.key}'s driver was asked"
                        )
                        continue
                    got = canonical(reply.headers.get(HEADER), door)
                    own = canonical(rows[-1].get("headers", {}).get(HEADER))
                    if got != named[second.key]:
                        problems.append(
                            f"{label}: a whole answer is named {got}; {second.key} served it and its listing says "
                            f"{named[second.key]} ({first.key}, asked first, says {named[first.key]})"
                        )
                    if got != own:
                        problems.append(
                            f"{label}: named {got}, the driver that served it names {own}"
                        )
                # a stream: the head is on the wire before any backend is asked
                label = f"{first.key} fails, {second.key} serves, chat stream"
                reply = ask(first, "chat", slot, True)
                if reply is not None:
                    got = canonical(reply.headers.get(HEADER))
                    if second.tag not in reply.text or stream_failed(
                        "chat", reply.text
                    ):
                        problems.append(
                            f"{label}: not served by {second.key}: {reply.text[:200]!r}"
                        )
                    if got != named[first.key]:
                        problems.append(
                            f"{label}: a stream's head is named {got}; the backend asked first ({first.key}) says "
                            f"{named[first.key]}"
                        )
            finally:
                stack.stand_in(first).chat_status = 0
    finally:
        strata_h, local_h = stack.stand_in(strata), stack.stand_in(local)
        strata_h.chat_status = local_h.chat_status = 0
    detail = f"two slots x three doors whole, and a stream each; {asked} requests that failed over"
    return Result(
        "failover",
        "a whole answer is named by the backend that served it",
        problems,
        detail,
    )


def check_slots(stack: Stack, only: set[str] | None) -> Result:
    """In a slot [family, local], what the local model serves alone is still served."""
    problems: list[str] = []
    local = FAM["local"]
    shapes = [*SHAPES, *SEEDS]
    served: dict[tuple[str, bool], bool] = {}
    requests = 0
    for shape in shapes:
        for stream in (False, True):
            reply = stack.post("chat", local.route, shape.fields, stream)
            served[(shape.name, stream)] = reply.status == 200 and not (
                stream and stream_failed("chat", reply.text)
            )
            if not served[(shape.name, stream)]:
                # The slots below are measured against it, so a local model that serves
                # less than everything makes them say nothing.
                problems.append(
                    f"the local model alone does not serve {shape.name} "
                    f"{'stream' if stream else 'whole'}: {reply.status} {reply.text[:200]!r}"
                )
    for fam in [
        f
        for f in stack.fams.values()
        if f.key != "local" and (only is None or f.key in only)
    ]:
        for shape in shapes:
            for stream in (False, True):
                requests += 1
                reply = stack.post("chat", f"slot-{fam.key}", shape.fields, stream)
                ok = reply.status == 200 and not (
                    stream and stream_failed("chat", reply.text)
                )
                label = f"slot [{fam.key}, local] {shape.name} {'stream' if stream else 'whole'}"
                refusal = DECIDED_REFUSALS.get((fam.key, shape.name))
                if ok or not served[(shape.name, stream)]:
                    continue
                if refusal is not None and refusal.search(reply.text):
                    continue  # decided: refused in plain words, naming its cause
                problems.append(
                    f"{label}: not served, though the local model serves it alone: {reply.status} {reply.text[:200]!r}"
                )
    detail = f"{requests} requests: every family in a slot with the local model, {len(shapes)} shapes, whole and streamed"
    return Result(
        "slots",
        "slots: what the local model serves alone is still served",
        problems,
        detail,
    )


# -- 3. counts --------------------------------------------------------------------

AUTHORITY: list[tuple[str, dict[str, Any]]] = [
    ("authority ok", {}),
    ("check 500", {"check_status": 500}),
    ("check 502", {"check_status": 502}),
    ("check 503", {"check_status": 503}),
    ("check 504", {"check_status": 504}),
    ("check 404", {"check_status": 404}),
    ("check 401", {"check_status": 401}),
    ("check 403", {"check_status": 403}),
    ("check 409", {"check_status": 409}),
    ("check 429", {"check_status": 429}),
    ("check hangs", {"check_mode": "hang"}),
    ("check drops the connection", {"check_mode": "close"}),
]
POLICY = [
    ("policy 500", {"policy_status": 500}),
    ("policy 503", {"policy_status": 503}),
]
BACKEND = [
    "ok",
    "template500",
    "template_nonjson",
    "template_missing",
    "tokenize500",
    "tokenize_nonjson",
    "reset",
]
#: What the generating doors answer of the same states (`tools-assumed.md`, "Failures"): a 503
#: with `Retry-After` where waiting can clear it (a 5xx, the model missing for now, a dropped
#: or refused connection), a 502 without one, naming the driver, where it cannot (a 404, a
#: refused credential, a body that is not a listing, a driver that says it serves nothing).
LISTING_STATUS = {
    "http500": 503,
    "http503": 503,
    "model_missing": 503,
    "drop": 503,
    "gone": 503,
    "http404": 502,
    "http401": 502,
    "nonjson": 502,
    "notalisting": 502,
    "degraded": 502,
}
LISTING = [
    "http500",
    "http503",
    "http404",
    "http401",
    "nonjson",
    "notalisting",
    "degraded",
    "model_missing",
    "drop",
    "hang",
    "gone",
]


def count_bodies(model: str, tools: bool) -> list[tuple[str, str, dict[str, Any]]]:
    anthropic: dict[str, Any] = {"model": model, "messages": CHAT}
    responses: dict[str, Any] = {"model": model, "input": "hello there"}
    if tools:
        anthropic.update(tools=[ANTHROPIC_WEATHER], tool_choice={"type": "auto"})
        responses.update(tools=[RESPONSES_WEATHER])
    return [
        ("messages", "/v1/messages/count_tokens", anthropic),
        ("responses", "/v1/responses/input_tokens", responses),
    ]


def check_counts(stack: Stack) -> Result:
    """A count is a 400 and never a 5xx, whichever way the key check, a listing or the backend fails.

    Each failure is made to happen (a count that is answered 200 or 5xx where a 400 is the rule
    says so: nothing is counted when the key cannot be checked), and the same state is shown
    to be a failure by what the other doors do with it.
    """
    problems: list[str] = []
    seen = 0
    local = FAM["local"]
    agent = stack.agent_h

    def reset() -> None:
        agent.check_status, agent.check_mode, agent.policy_status = 200, "status", 200
        stack.local_h.count_mode = "ok"

    def count(
        gw: Gateway,
        label: str,
        creds: dict[str, str],
        tools: bool,
        model: str = local.route,
    ) -> list[Reply]:
        """Both doors' counts at once: a hung authority or listing is waited on for four
        seconds, and the two doors are two requests that can wait together."""
        nonlocal seen

        def one(door: str, path: str, body: dict[str, Any]) -> Reply | None:
            try:
                response = gw.http.post(path, json=body, headers=creds, timeout=30)
            except httpx.HTTPError as exc:
                problems.append(
                    f"{label} {door} tools={tools}: no answer: {type(exc).__name__}"
                )
                return None
            reply = Reply(response.status_code, dict(response.headers), response.text)
            if reply.status >= 500:
                problems.append(
                    f"{label} {door} tools={tools}: HTTP {reply.status}: {reply.message[:200]!r}"
                )
            return reply

        bodies = count_bodies(model, tools)
        seen += len(bodies)
        with ThreadPoolExecutor(len(bodies)) as pool:
            replies = list(pool.map(lambda b: one(*b), bodies))
        return [r for r in replies if r is not None]

    def want(
        label: str, replies: list[Reply], statuses: range | tuple[int, ...], why: str
    ) -> None:
        bad = [r.status for r in replies if r.status not in statuses]
        if bad:
            problems.append(
                f"{label}: {why}, and the statuses were {[r.status for r in replies]}"
            )

    slots = [{"model": "slot-x", "targets": ["local-model"]}]
    gw = stack.new_gateway(slots, "counts-check")
    # the key check: the authority answers every way it can
    cannot_check = {"check 500", "check 502", "check 503", "check 504", "check 404"}
    for label, attrs in AUTHORITY:
        reset()
        for name, value in attrs.items():
            setattr(agent, name, value)
        hangs = attrs.get("check_mode") == "hang"
        for creds_name, creds in (("key", gw.keyed), ("operator", gw.operator)):
            if hangs and creds_name == "operator":
                continue
            for tools in (False, True) if not hangs else (False,):
                where = f"{label} {creds_name} tools={tools}"
                replies = count(gw, f"{label} {creds_name}", creds, tools)
                if label == "authority ok" or creds_name == "operator":
                    # a key that is fine, and an operator whom no key check concerns, are counted
                    want(where, replies, (200,), "the count is given")
                elif (
                    label in cannot_check
                    or hangs
                    or label == "check drops the connection"
                ):
                    want(
                        where,
                        replies,
                        (400,),
                        "the key cannot be checked, so nothing is counted: a 400",
                    )
                else:
                    want(
                        where,
                        replies,
                        range(400, 500),
                        "the authority refused the key: that refusal",
                    )
    # the key policy cannot be read at all
    for label, attrs in POLICY:
        reset()
        for name, value in attrs.items():
            setattr(agent, name, value)
        fresh = stack.new_gateway(slots, f"counts-{label.replace(' ', '-')}")
        for tools in (False, True):
            replies = count(fresh, f"{label} key", fresh.keyed, tools)
            want(
                f"{label} key tools={tools}",
                replies,
                (400,),
                "the policy cannot be read: a 400",
            )
    reset()
    # the backend cannot count
    for mode in BACKEND:
        stack.local_h.count_mode = mode
        for tools in (False, True):
            replies = count(gw, f"backend {mode}", gw.keyed, tools)
            if mode == "ok":
                want(f"backend ok tools={tools}", replies, (200,), "the count is given")
            else:
                want(
                    f"backend {mode} tools={tools}",
                    replies,
                    (400,),
                    "the backend cannot count: a 400",
                )
    reset()
    # a listing cannot be read: the same state that refuses a chat request with a 503 or a 502
    ways = check_listing_counts(stack, count, want, problems)
    detail = (
        f"{seen} counts: {len(AUTHORITY) + len(POLICY)} ways the key check or the key policy "
        f"fails, {len(BACKEND)} backend failures, {ways} ways a driver's listing fails, each a "
        "400 and no 5xx"
    )
    return Result("counts", "counts: a count never answers a 5xx", problems, detail)


def check_listing_counts(
    stack: Stack,
    count: Callable[..., list[Reply]],
    want: Callable[..., None],
    problems: list[str],
) -> int:
    """Each way a driver's listing fails (the gateway re-reads it for a request that carries
    tools): the count is a 400, where the same request to the chat door is a 503 or a 502."""
    local = stack.driver(FAM["local"])
    info = copy.deepcopy(local.info)
    info["models"][0]["id"] = "fake-model"
    handler = handler_for(FakeDriver, "fake", info=info)
    server, port = serve(handler)
    components = [
        {
            "name": "fake-box",
            "kind": "inference-driver",
            "url": f"http://127.0.0.1:{port}",
            "status": "running",
        }
    ]
    agent_server, agent_port = serve(
        handler_for(Agent, "fake-agent", components=components, admissions=[])
    )
    gw = stack.new_gateway([], "counts-listing", agent_port)
    ways = 0
    try:
        for mode in LISTING:
            ways += 1
            handler.mode = "drop" if mode == "gone" else mode
            if mode == "gone":  # nothing listens: the connection is refused
                server.shutdown()
                server.server_close()
            for tools in (True, False) if mode == "gone" else (True,):
                replies = count(gw, f"listing {mode}", gw.operator, tools, "fake-model")
                want(
                    f"listing {mode} tools={tools}",
                    replies,
                    (400,),
                    "a listing or a driver that cannot be read: a 400",
                )
            if mode == "hang":
                continue  # four seconds a request, and the contrast below would be four more
            body = {"model": "fake-model", "messages": CHAT, "tools": [WEATHER]}
            chat = gw.http.post("/v1/chat/completions", json=body, headers=gw.operator)
            wanted = LISTING_STATUS[mode]
            retry = chat.headers.get("retry-after")
            if chat.status_code != wanted:
                problems.append(
                    f"listing {mode}: the chat door, asked the same, answered {chat.status_code}, not the "
                    f"{wanted} this state is (so the failure did not happen, or is told another way)"
                )
            elif (retry is not None) != (wanted == 503):
                problems.append(
                    f"listing {mode}: the chat door answered {wanted} with Retry-After {retry!r}: only "
                    "a state that waiting can clear says to try again"
                )
            elif "fake-box" not in chat.text:
                problems.append(
                    f"listing {mode}: the chat door's {wanted} does not name the driver: {chat.text[:200]!r}"
                )
    finally:
        handler.mode = "ok"
        with contextlib.suppress(Exception):
            server.shutdown()
        agent_server.shutdown()
    return ways


# -- 4. heads ---------------------------------------------------------------------


def check_heads(stack: Stack) -> Result:
    """A stream's head arrives before its first frame, with the header on it, on every door.

    The backend (Strata, which makes the header say something) is held until the head has been
    seen: a gateway that waited for the backend's first frame before sending the head would
    never send one, and the read below would time out.
    """
    fam = FAM["strata"]
    handler = stack.stand_in(fam)
    problems: list[str] = []
    arrived: dict[str, float] = {}
    try:
        for door in ("chat", "messages", "responses"):
            gate = threading.Event()
            handler.hold = gate
            handler.spoke = []
            path, body = door_request(door, fam.route, FORCED[door], True)
            label = f"{door} stream"
            lines: list[str] = []
            released = False
            began = time.perf_counter()
            try:
                timeout = httpx.Timeout(10.0, read=8.0)
                with stack.gw.http.stream(
                    "POST", path, json=body, headers=stack.gw.operator, timeout=timeout
                ) as response:
                    arrived[door] = (time.perf_counter() - began) * 1000
                    names = canonical(response.headers.get(HEADER), door)
                    spoken = bool(handler.spoke)
                    if response.status_code != 200:
                        problems.append(f"{label}: the head was {response.status_code}")
                    if spoken:
                        problems.append(
                            f"{label}: the backend had already spoken when the head came: the held backend is not held"
                        )
                    if names != ["tool_choice"]:
                        problems.append(
                            f"{label}: the head names {names}, a backend that ignores `required` says ['tool_choice']"
                        )
                    if door != "responses":
                        gate.set()
                        released = True
                    for line in response.iter_lines():
                        lines.append(line)
                        if (
                            door == "responses"
                            and not released
                            and "event: response.created" in line
                        ):
                            if handler.spoke:
                                problems.append(
                                    f"{label}: response.created came after the backend spoke"
                                )
                            gate.set()
                            released = True
            except httpx.TimeoutException as exc:
                waited = (
                    f"{type(exc).__name__} after {time.perf_counter() - began:.1f} s"
                )
                if door in arrived:
                    problems.append(
                        f"{label}: the head came, then nothing while the backend was held ({waited}): "
                        "the stream's own opening, response.created, waits for the backend's first frame"
                    )
                else:
                    problems.append(
                        f"{label}: no head came while the backend was held ({waited}): the head waits "
                        "for the backend's first frame"
                    )
            finally:
                gate.set()
            text = "\n".join(lines)
            if not problems_for(problems, label) and (
                fam.tag not in text or stream_failed(door, text)
            ):
                problems.append(
                    f"{label}: after the backend was let go the stream did not finish: {text[-200:]!r}"
                )
    finally:
        handler.hold = None
    detail = "Strata held until the head was seen: " + ", ".join(
        f"{d} {ms:.0f} ms" for d, ms in arrived.items()
    )
    return Result(
        "heads", "a stream's head arrives before its first frame", problems, detail
    )


def check_loading(stack: Stack) -> Result:
    """A loading backend is tried on every call, then serves as soon as ready."""
    primary = stack.stand_in(FAM["strata"])
    problems: list[str] = []
    for stream in (False, True):
        gateway = stack.new_gateway(stack.slots, f"loading-{stream}")
        primary.recorded.clear()
        primary.loading = True
        try:
            for attempt in range(4):
                reply = stack.post("chat", "slot-strata", {}, stream, gateway)
                if reply.status != 200 or "from local" not in reply.text:
                    problems.append(
                        f"stream={stream} loading attempt {attempt}: {reply.text[:200]}"
                    )
            asked = len(
                [p for p, _ in primary.recorded if p.endswith("/chat/completions")]
            )
            if asked != 4:
                problems.append(
                    f"stream={stream}: loading backend was asked {asked} times, wanted 4"
                )
            primary.loading = False
            reply = stack.post("chat", "slot-strata", {}, stream, gateway)
            if reply.status != 200 or FAM["strata"].tag not in reply.text:
                problems.append(
                    f"stream={stream}: ready backend still unavailable: {reply.text[:200]}"
                )
        finally:
            primary.loading = False
            stack.retire(gateway)
    return Result(
        "loading",
        "loading does not open a circuit",
        problems,
        "4 loading refusals then immediate recovery, whole and streamed",
    )


def problems_for(problems: list[str], label: str) -> bool:
    return any(p.startswith(label) for p in problems)


# --------------------------------------------------------------------------- #
# Running it
# --------------------------------------------------------------------------- #

CHECKS = {
    "header": "1",
    "failover": "1b",
    "slots": "2",
    "counts": "3",
    "heads": "4",
    "loading": "5",
}
#: Which families each check needs built (header and slots take `--families`).
NEEDS = {
    "failover": {"strata", "local"},
    "heads": {"strata", "local"},
    "loading": {"strata", "local"},
    "counts": {"local"},
}


def show_families(stack: Stack) -> None:
    for fam in stack.fams.values():
        driver = stack.driver(fam)
        name = (
            fam.route.split("/", 1)[1]
            if fam.route.startswith(driver.name + "/")
            else fam.route
        )
        listed: list[dict[str, Any]] = driver.info.get("models") or []
        model: dict[str, Any] = next((m for m in listed if m.get("id") == name), {})
        caps = model.get("capabilities") or {}
        gaps = {
            canonical(g["setting"])[0]: g["values"]
            for g in caps.get("settingsNotHonoured") or []
        }
        print(
            f"  {fam.key:<16} toolCalling={caps.get('toolCalling')!s:<5} not honoured={json.dumps(gaps) if gaps else '-'}"
        )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[0] if __doc__ else None
    )
    parser.add_argument("--only", help="comma-separated checks: " + ", ".join(CHECKS))
    parser.add_argument(
        "--families", help="comma-separated families for the header and slots checks"
    )
    parser.add_argument("--keep", action="store_true", help="keep the temporary tree")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove the temporary tree even when a check failed (a sabotage run expects to)",
    )
    args = parser.parse_args(argv)
    wanted = [c for c in (args.only.split(",") if args.only else CHECKS) if c]
    unknown = [c for c in wanted if c not in CHECKS]
    if unknown:
        parser.error(f"no such check: {', '.join(unknown)}")
    only = set(args.families.split(",")) if args.families else None
    if only and (bad := only - set(FAM)):
        parser.error(f"no such family: {', '.join(sorted(bad))}")

    refuse_the_internet()
    # A run that hangs says where, and ends: its drivers end with it (`die_with_the_parent`).
    faulthandler.dump_traceback_later(540, exit=True)
    getattr(sys.stdout, "reconfigure")(encoding="utf-8", errors="replace")
    mods = load_gateway()
    needs: set[str] = set()
    for check in wanted:
        needs |= NEEDS.get(check, set(only) if only else set(FAM))
    needs.add("local")
    families = [f for f in FAMILIES if f.key in needs]
    tmp = Path(tempfile.mkdtemp(prefix="tools-assumed-"))
    # What the gateway warns of while it is made to fail, on purpose, goes to a file in the tree.
    logging.basicConfig(
        filename=tmp / "gateway.log", level=logging.WARNING, encoding="utf-8"
    )
    print(f"python {sys.version.split()[0]} on {sys.platform}")
    print(f"gateway source: {mods.file.parent}")
    print(f"temporary tree: {tmp}")
    if DROPPED:
        print(f"dropped {len(DROPPED)} ambient EUGENE_PLEXUS_* variable(s)")
    started = time.perf_counter()
    stack = Stack(tmp, families, mods)
    results: list[Result] = []
    try:
        codes = {d.code() for d in stack.drivers}
        print(f"driver source: {', '.join(sorted(str(Path(c).parent) for c in codes))}")
        if DRIVER_SRC and any(
            Path(DRIVER_SRC).resolve() not in Path(c).parents for c in codes
        ):
            raise SystemExit(
                f"EP_DRIVER_SRC is {DRIVER_SRC} and a driver came from elsewhere"
            )
        print(
            f"stack up in {time.perf_counter() - started:.1f} s; what each driver says of its tools:"
        )
        show_families(stack)
        for check in wanted:
            began = time.perf_counter()
            if check == "header":
                result = check_header(stack, only)
            elif check == "failover":
                result = check_failover(stack)
            elif check == "slots":
                result = check_slots(stack, only)
            elif check == "heads":
                result = check_heads(stack)
            elif check == "loading":
                result = check_loading(stack)
            else:
                result = check_counts(stack)
            results.append(result)
            status = "PASS" if result.ok else "FAIL"
            print(
                f"{status}  {CHECKS[check]:>2}. {result.name} -- {result.detail} ({time.perf_counter() - began:.0f} s)"
            )
            for problem in result.problems[:25]:
                print(f"        - {problem}")
            if len(result.problems) > 25:
                print(f"        ... and {len(result.problems) - 25} more")
    finally:
        stack.stop()
    failed = [r for r in results if not r.ok]
    print(
        f"{'ALL PASS' if not failed else 'FAILED'}: {len(results) - len(failed)} of {len(results)} checks passed in {time.perf_counter() - started:.0f} s"
    )
    if failed and not args.clean:
        show_logs(tmp)  # a runner's temporary tree is gone with the job
    if args.keep or (failed and not args.clean):
        print(f"kept {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failed else 0


def show_logs(tmp: Path) -> None:
    """What the gateway warned of and what each driver logged, when a check failed."""
    for name, lines in [
        ("gateway.log", 30),
        *[(f"{p.name}/driver.log", 12) for p in sorted(tmp.glob("*-box"))],
    ]:
        path = tmp / name
        if path.exists():
            tail = path.read_text("utf-8", "replace").splitlines()[-lines:]
            print(f"--- {name} (last {len(tail)} lines)")
            for line in tail:
                print(f"    {line[:300]}")


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--stub-cli":
            stub_cli(sys.argv[2], sys.argv[3:])
            sys.exit(0)
        if len(sys.argv) > 1 and sys.argv[1] == "--driver":
            run_driver(
                Path(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]), sys.argv[5]
            )
            sys.exit(0)
        sys.exit(main(sys.argv[1:]))
    except SystemExit as stop:
        if isinstance(
            stop.code, str
        ):  # this script could not run: say so, and not as a failed check
            print(stop.code, file=sys.stderr)
            sys.exit(2)
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(2)
