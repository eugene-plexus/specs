# MR9b: connections from other apps (run of record, 2026-10-18)

Design: `docs/design/workbench-memory-and-documents.md` sections 10.3 and 10.7; Troy's calls MRC29 to
MRC31. Script: `workbench/scripts/mr9-connections-acceptance.py`.

**Stack.** A real Workbench process (the MR9b working tree), the real gateway and inference-driver, a
real `llama-server` (b10948, processor) serving Qwen3-Embedding 0.6B Q8_0, recording proxies before the
gateway (whose proof each embeddings request carried) and before the engine, a stand-in for Eugene's
sign-in that can refuse a person at a refresh, two people (Ada, Bo) and the install's owner with
`ownerReadsChats` on, and the official MCP SDK 2.3 Streamable HTTP client. Every ambient
`EUGENE_PLEXUS_*` variable dropped; ports 8470-8477.

**Result: 47 PASS, 0 FAIL.**

| Part | What was observed |
|---|---|
| Rights | Every right: the four tools; notes only: `search_notes` alone, and `search_documents` called anyway is refused |
| Her own, by meaning | Her note found from a query sharing none of its words (`how: meaning and words`), her instruction first; her passage with its code word found by meaning; Bo's of neither |
| Her proof | Every embeddings request her searches caused carried her own person token at the gateway, never another's; the engine answered them |
| Isolation | Bo's connection finds none of her passages or notes; her document's id answers him as a missing document, word for word |
| Suggestions | `suggest_note` waits in her inbox named by its connection and is in no section of kept notes; a secret is refused; Bo's inbox has nothing of hers |
| The owner | Lists none of her connections, cannot revoke one (404), reads none of her notes |
| The door | A token in the address 400; a foreign `Origin` 403; her cookie and page secret alone 401; a made-up, a malformed and a missing token one 401 with one text |
| Revoking | The next call gets the made-up token's answer; its unkept suggestion is gone |
| Sign-in | A fresh connection works while Eugene accepts her and stops, with words, at the next check after Eugene turns her off |
| Install switch | Off: every connection 403 with words; back on: it works |
| Kept and logged | No token in the database (main file and WAL); Workbench's log has no query, note, document or secret words and no token |

**What the first run found (harness, not product).** The first execution passed 43 of 47: the
harness's gateway proxy forwarded the person token, and a standalone gateway (no root to check it
against) refuses a person token that comes without an app key, so Workbench fell back to words and
said why. MR8's proxy drops that header; this one now records it and drops it. That the gateway checks
the proof with the root is U3's acceptance (`u3-person-access-2026-10-16.md`), not this run's.

**Review.** One adversarial review of the diff found no blocker. Its three should-fixes were made
before this run: a suggestion's write checks that the connection is still live (a call let in before
Revoke left a suggestion behind; regression test added), any failure but a refusal is said in fixed
words, and the per-connection limits come before the sign-in check.

**Sabotage.** `workbench/scripts/mr9-connections-sabotage.py`, each mutation restored from a copy:
**13 of 13 caught** (rights, token lookup, sign-in binding, Origin, token in the address, install switch, expiry, pending, revoke's suggestions, the live check in the write, owner-only revoke and list, the secret check). The first pass caught 12: nothing sent a made-up token while a real one was live, so a lookup that answered with any connection passed; that check was added.

Workbench checks: `tests/test_connections.py` 13 (14 checks after the sabotage gap), and the memory, config, sign-in, store and schema
files, 378 passed; the web suite 3,269 passed; ruff, ruff format, mypy (win32 and linux), tsc, eslint
and prettier clean.

**Limits.** A real Claude Code was not connected in this run (the SDK's client speaks the same
transport). Codex's and Open WebUI's own settings formats were not checked.

## A real Claude Code, 2026-10-19

On Amish_Station against Troy's live Workbench (`https://workbench.screamingamish.com/mcp`,
public HTTPS), with a connection he made on the Memory page with `suggest_note` on:

- **Setup format.** Workbench's Claude Code command (`claude mcp add --transport http workbench
  <address> --header "Authorization: Bearer <token>"`), run as shown, added the server at local
  scope; it prints nothing on success. `claude mcp list` then showed it `✔ Connected`.
- **Tools.** A real Claude Code (`claude -p`, Haiku) listed all four: `search_notes`,
  `search_documents`, `read_document`, `suggest_note`.
- **Suggestion, then search.** `suggest_note` answered `waiting in the person's inbox`; Troy kept
  it, and `search_notes` then found it word for word.
- **Documents.** After he added a Markdown document, `search_documents` found it with a passage and
  `read_document` returned its text, cut at about 11,400 characters with `"cut": true`. The
  queries `the` and `document` were refused as having nothing to search for.
- **Revoking.** After he revoked the connection, `claude mcp list` showed `✘ Failed to connect`
  with Workbench's 401 words, the model said the tool was unavailable, and a direct `initialize`
  with the old token got 401 and the made-up token's text.

Limits: one person, one client, Claude Code's CLI; the VS Code extension shares its config but
was not restarted to use the server. `claude mcp add` keeps the token in plain text in
`~/.claude.json`. Codex's and Open WebUI's formats remain unchecked.
