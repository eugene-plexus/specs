# MV2: past chats (run of record, 2026-10-19)

Design: `docs/design/workbench-memory-v2.md` sections 14-26 (MV2). Script:
`workbench/scripts/mv2-past-chats-acceptance.py` (new; it reuses the MV1 script's sign-in stand-in,
proxies and helpers).

**Stack.** A real Workbench process (the MV2 working tree) **starting on a schema 22 store** that
holds three people's chats: Ada's trip chat with two answer versions (the second shown) and her
bicycle chat, Bo's cello chat, and Cy's 400 chats of five exchanges each (2,000). Also: the real
gateway (bac6c51); three real inference-drivers (9ef3e7d), one declaring a real `llama-server`
(b10948, processor, Qwen3 0.6B Q4_K_M, window 8,192) local, one declaring a second `llama-server`
with Qwen3-Embedding 0.6B Q8_0 local (the search model), and one declaring a stub hosted API
external that calls `search_chats` when offered; recording proxies before the gateway and before the
chat engine; a stand-in for Eugene's sign-in. Every ambient `EUGENE_PLEXUS_*` variable was dropped;
ports 8470-8481; teardown by pid.

**Result: 36 PASS, 0 FAIL** (the fourth execution; the first three are below).

| Part | What was observed |
|---|---|
| Migration | Schema 23, the schema 22 file kept beside it first |
| Backfill | Every shown exchange is in its own person's index: Ada's trip at its shown (second) version, not its first; Bo's one; none of anyone's in another's |
| Resume | Workbench was killed 1.8 s in, with 208 of Cy's 2,000 in. Started again, the restart put only what was missing (1,722 plus Ada's and Bo's) and every exchange was in |
| Rate | **1,722 exchanges in 3.7 s, 465 a second** (words; meaning follows in the background) |
| Search chats | By words, the trip at its shown answer, its text read from the store. A search sharing no word with it ("pastry shop recommendations") finds it by meaning. Choosing the first version puts its exchange in and takes the second out, and the hidden version is never returned |
| Use past chats | Off by default: a chat that did not turn it on is sent nothing from her other chats, and its drawer says so. On: her latest message carries the bicycle exchange as data before her words, at both hops. The answer records which exchanges went by chat, never this chat's own, with none of their words. The next turn is chosen again for what it asks |
| `search_chats` | Offered to the outside model once "Send for this chat" is chosen; Workbench ran it and sent the excerpt back as data. With documents set never to leave (MV2-C1), it is not offered, the kept result **and its query** are withheld, and the drawer says why |
| Others | The owner, who may read her chats, searches none of them and reads her chats with past chats as counts only (no excerpt, query or result). Bo finds nothing of hers, and his own |
| Connections | Without the right, `search_chats` is not listed and is refused; with it, her exchange comes back |
| Delete | No exchange, word or signature of the trip chat is left in her index. The kept `search_chats` result is replaced, and the answer that used it keeps only a count. A fresh chat with Use past chats on is not sent it, and Search chats no longer finds it |

**What the first three runs found.**

- **Run 1 (25 of 27, then a script crash).** The Search chats status said nothing was owed while no
  exchange had meaning yet. After a restart, exchanges are left "ready, words only" until a search
  model is seen, and the worker's own count leaves those out. **Product defect, fixed:** the status
  counts every passage without meaning and says when no search model can run. It has a regression
  test. The script also called a missing `Person.put` and over-counted a record.
- **Run 2 (30 of 36).** Those words-only exchanges got meaning only when a new answer woke the
  meaning worker. MV1's notes have the same gap. **Product defect, fixed:** a search of past chats or
  notes, or a look at the past-chats status, wakes the worker when meaning is owed and a local
  search model runs, as a look at the Documents screen does. It has a regression test. Four checks
  were too strict: an exchange from her *other* chat that asked the same question is correctly
  found, and the owner may read a chat's own answers, just not what past chats gave it.
- **Run 3 (35 of 36).** With meaning working, a search for the hidden version's words finds the
  shown version by meaning, which is correct. The check now asserts that the hidden version is never
  returned.

**Observed limits.** The 0.6B chat model returned empty answers to the turns that carried past
chats (its 120-token cap went to thinking). The run checks what reached the model, not what it
made of it. Meaning for Cy's 2,000 exchanges was not timed. The run used the CPU only.
