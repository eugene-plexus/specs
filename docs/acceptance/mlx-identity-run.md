# B1 — the model identity split, live across a two-node install

**Run:** 2026-09-22, `scripts/b1-mlx-identity-acceptance.py`, **11 checks,
zero failures, first full execution** (two harness defects were fixed
before any check ran — see below). Sabotage pass:
`scripts/b1-sabotage.py` — **4 of 4 caught**, restores from byte copies
with a green baseline first. Each sabotage was caught by the check
written for it: the wire carrying the public alias died at the fixture's
400; a translating driver echoing the backend's name failed the
response-identity assertion with `model: default_model` in the body; the
raw stream terminal frame failed the every-frame check with
`{'default_model', 'alias-b'}`; and a gateway routing on the upstream id
collapsed the aliases and never made three models routable. One
harness lesson inside the sabotage pass itself: the working trees are
CRLF on this box, so a multi-line sabotage anchor read from `read_bytes`
never matches — anchors are normalized before matching, restores stay
byte-exact.

**What is real and what is simulated, stated up front.** Real: the
control root, two enrolled agents (two nodes), one gateway, and four
inference-driver processes — every component the identity split crosses
is the shipped code, running as separate processes from its own venv.
Simulated: the four backends are fixtures shaped by the mlx-lm v0.31.3
claims (a hardcoded 200 `/health`, `/v1/models` publishing an absolute
path, completions resolving **only** `default_model`) — because this box
is Windows and `mlx` is Apple-silicon-only. **No result here is evidence
about a physical Mac**; that checklist is in
`docs/design/mlx-engine.md` and stays pending.

## The eleven checks

1. A real driver advertises both halves on `/v1/info`:
   `modelId: alias-a`, `upstreamModelId: default_model`; a pre-split
   driver advertises `modelId` alone.
2. The gateway's model list is exactly the three public aliases; the
   sentinel and the fixture's absolute model path appear nowhere in the
   body.
3. `alias-a` serves from its own backend; the response names `alias-a`.
4. `alias-b` serves from the **other** backend behind the **same**
   sentinel, on the other node — the collision the split exists to
   prevent, not happening.
5. A streamed `alias-b` reply assembles to the right content and every
   frame names the public alias — the backend's `default_model` echo is
   normalized out of the terminal frame too.
6. Asking for `default_model` or the absolute path directly is a 404:
   neither is a model anyone can select.
7. A second driver for `alias-a` on the second node makes **one model
   with two balanced backends**, not two models: the model list is
   unchanged and both fixtures serve traffic.
8. The pre-split configuration (no `upstreamModelId`) still sends its
   public `modelId` verbatim — zero violations at its fixture.
9. A client key scoped to `alias-a` sees only it in discovery, is
   refused `alias-b` with 403, and serves `alias-a` — scopes filter on
   the public identity.
10. `alias-b` survives its driver process being stopped and started:
    unroutable while down, routable and serving again after.
11. Across the whole run, every fixture was asked for exactly the one
    name it resolves — **zero violations** — so the wire never carried a
    public alias to a backend that cannot resolve it, and never carried
    the sentinel anywhere else.

## Two harness defects before the first check, both one lesson

The earlier A-series harnesses ran every component from one Python
environment, and this run cannot: **the gateway and the driver depend on
Pillow** (image content parts) **and the agent's venv does not carry
it**, so both import-crashed at startup with an empty log tail. Each
component now runs from its own checkout's venv
(`EP_DRIVER_PYTHON` / `EP_GATEWAY_PYTHON` override).

And the fixture's `/v1/chat/completions` initially answered 422 to the
real driver: with `from __future__ import annotations`, FastAPI resolves
a handler's `Request` annotation against the function's **globals**, and
a `Request` imported inside the `serve()` closure is invisible there —
the parameter silently degrades to a required query param. The import is
module-level now, which is also why the A5 script always wrote it that
way.

## Not done, named

- Nothing here ran `mlx_lm.server`, loaded an MLX model, or touched
  Apple hardware; the adapter itself is exercised by the agent's own
  suite (26 tests) against the same fixtures-from-source method that
  held for vLLM at M4.
- The agent-side companion mapping (an MLX runtime's companion getting
  `upstreamModelId: default_model` written into its config) is
  unit-tested in the agent repo, not driven here — this run's drivers
  are declared components, because a real supervised runtime would need
  a real engine binary.
- The restart in check 10 restarts the driver *process* the harness
  owns; the agent's supervised stop/restart path is covered by the
  agent's e2e suite.
- The scoped key exercises `allowedModels` only; rate and concurrency
  limits are A5's evidence, unchanged.
