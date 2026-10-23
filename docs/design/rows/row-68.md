# Row 68: DeepSeek V4.x Flash through Eugene

Lane ENG. Low risk. Source: DI8 in `deepinfer-lessons.md` (the checkpoint
ships no Jinja chat template; tool calls use DeepSeek's DSML format, which
the engine's parser must know; about 110 GB at 3 bits, so a Mac Studio, a
multi-GPU box or a large-RAM box with MoE-aware fit; it drafts five tokens
from its own `nextn` head, which SD1's own-head path covers if the GGUF
keeps it; it needs rented or borrowed hardware). DI-C1 placed it "when
someone asks".

## 1. What it delivers

Everything Eugene's side needs so DeepSeek V4.x Flash runs through it when
the hardware exists: the Library knows the architecture and says what is
missing, a chat template and tool-call parsing are supplied where
upstream lacks them, fit counts it properly, and drafting uses its own
head.

## 2. Design

- **Library:** the V4 architecture in the MLA list (`preflight.py`) and its
  MoE layout in fit (experts in RAM; row 9's cache settings); a model with
  no chat template says so on its page ("This model ships no chat
  template; Eugene supplies DeepSeek V4's") and lists the engines that can
  serve it.
- **Template:** Eugene supplies a reviewed Jinja template for the V4 family
  (from DeepSeek's documented format), applied by the agent with
  llama.cpp's `--chat-template-file` when the GGUF has none; the runtime
  says which template is in effect.
- **Tool calls (DSML):** check llama.cpp's and vLLM's parsers at their
  pinned versions; where one lacks DSML, the gateway parses DSML tool-call
  blocks from the text into tool calls for that model family (the same
  place it handles other model-specific formats), with tests from
  DeepSeek's published examples.
- **Drafting:** the profile's speculation offers the model's own `nextn`
  head (SD1) when the GGUF keeps it, and says so when it does not.

## 3. Repositories

library, agent, gateway, specs (docs; acceptance).

## 4. Tests that fail before

The architecture recognised (a fixture header); "no template" shown and
the supplied template applied in argv; DSML blocks parsed into tool calls
(fixture texts); the own-head drafter offered for a GGUF with `nextn`.

## 5. Acceptance

CI unit and planning tests with fixtures. A real run needs about 110 GB
of memory; the orchestrator runs it if hardware is lent; it is not a
roadmap item otherwise (Troy, 2026-10-21).

## 6. Size and risks

M, about 2 days. Risk: a supplied template that differs from DeepSeek's
own; it cites its source and is replaced when upstream ships one.

**Calls:** none.
