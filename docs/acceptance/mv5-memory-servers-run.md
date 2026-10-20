# MV5 live run: memory servers

**2026-10-19, run of record: 41 passed, 0 failed.**

- **Script:** `workbench/scripts/mv5-memory-servers-acceptance.py`.
- **Reference server:** `scripts/m-memory-server.py` (this repo), run in its own process with a token,
  and a second copy offering only `recall`.
- **Design:** `docs/design/workbench-memory-v2.md`, sections 46-55.

**What ran.** A throwaway stack on ports 8490-8501, with every `EUGENE_PLEXUS_*` variable dropped and
everything torn down by pid:

- a deterministic model (`Okay.`), answering one driver as a model on the machines and another as an
  outside one;
- a real gateway;
- Workbench from the working tree, **over a schema 23 store**;
- the reference servers over real MCP (streamable HTTP).

| Section | What it showed |
|---|---|
| 1b | The store came through: schema 25, with both new tables |
| 2 | Under the default (`outside`), `127.0.0.1`, `localhost` and this machine's own LAN address were each refused, with the reason. Nothing reached the server |
| 3 | Under `any`, a wrong token is refused by name. The right one connects with every verb found, and the token is never shown. A server with only `recall` connects and lists the four things it cannot do |
| 4 | Under Standard, Ada's own words were sent. The pasted block was not, and neither was the answer or the chat's title. The document is `{chat}:{message}`, with the time she asked. Under Open, the answer and the title went too. A secret-shaped turn was not sent, and was counted. Bo's chat never reached Ada's server |
| 5 | The server's memory reached the latest user turn as data, in its own block. It was asked with her words and a budget. The drawer names the server and what it sent |
| 6 | An outside model (with notes set to always go) was not given the server's memory, and the server was not asked. The drawer says why |
| 7 | A server that took 6 s to recall did not hold the answer up. The drawer says it did not answer in time |
| 8 | Deleting a chat forgot its exchanges at the server, and they are gone from it |
| 9 | The export carries what the server lists |
| 10 | Delete all memory cleared the server and checked it by listing. A server that says it cleared but keeps everything is named ("still lists 1") |
| 11 | With the owner's "never" for outside services, no server may be used, the page says why, and no turn asks it |

## Before the run of record

- **The first run, before the review's fixes, passed 41/41.**
- **The second run failed one check, the run's own:** after the review, the chat's title goes only
  under Open, and the script still expected it under Standard. The check now asserts both sides.

## Sabotage and review

- **Sabotage:** `check-memory-sabotage.py --label MV5`, ten cases, 9/10 caught on the first pass.
  - The case that escaped was "a slow server holds the answer": it lengthened only the outer wait,
    and the call's own two-second limit still held.
  - Rewritten to change `RECALL_SECONDS` itself, it was caught: 1/1.
  - Baseline restored and passing after each pass, with `git diff --stat` unchanged.
- **One adversarial review** (high risk: chats leave for a server Eugene does not control, and a
  person-supplied address is fetched from the host).
  - **Blocker, fixed:** a chat deleted more than a day after its answer was dropped from the forget
    queue without being forgotten. The row now starts its day when the chat is deleted, with a
    regression test.
  - **Fixed:**
    - Compressed bodies are refused, so the size cap counts what is read.
    - The turn's two-second limit holds while a session closes.
    - Eugene's own ports are refused on private addresses, and the host's addresses are re-read
      every 5 minutes.
    - A new token for the same address keeps pending forgets.
    - `forget` is used only when `retain` keeps the id.
    - The chat's title is sent only under Open.
    - A failing row backs off instead of blocking the queue.
    - An exchange sent during its chat's deletion is queued to be forgotten.
    - What waits to be sent is dropped before Delete all clears the server.
    - FastMCP's `result` is read as a list, variation selectors are stripped, the export stops on a
      repeated page, and only the arguments used are kept.
  - **Left, recorded:** a signed-in person can tell an open port from a closed one on a private
    address by the error message. Allowing servers on the LAN implies this.
- **Checks:**
  - 21 MV5 tests, plus the memory, past-chats, chats, config, schema, conversions, documents-store,
    connections and tools suites: 491 passed, 3 skipped (Chrome opt-in). The one failure was a
    key-set assertion missing `memoryServer`; it was updated and passes.
  - ruff, ruff format, mypy (Windows and Linux).
  - Web: tsc, eslint and prettier. Vitest gave 3380 passed and 6 failed: `Memory.test.tsx`
    needed `MemoryServer` stubbed as its siblings are. It was stubbed, and the file passes (77).
