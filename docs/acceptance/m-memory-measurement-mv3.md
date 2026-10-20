# MV3 measurement: memory writing on the extended sets, two paths, and a cloud reference

**2026-10-19.** `scripts/m-memory-measurement.py` drives the engine. The labelled sets, the requests
and the scorer are Workbench's own `memory_measure`, so Measure this model on the Memory screen runs
the same ones. `scripts/m-memory-summarize.py --ship` wrote Workbench's `memory_measured.json` from
this data. Design: `docs/design/workbench-memory-v2.md` sections 27-31 and 39. Data:
[`m-memory-data/mv3/`](m-memory-data/mv3/).

**What was measured.** 123 labelled sets: MR8's 88, and 35 new ones (call 11) for knowledge update (a
remembered note changed, or twins where nothing should be replaced), time (events in relative words),
several sessions (a fact only the messages together say), and must-not-persist negatives
(PersistBench-style). Three runs a model:

- the **pass** (the background request), 3 samples a set;
- the **tool** path (a chat request with the `remember` tool and its one-line hint in the system
  message), 1 sample;
- the pass again with a **25-tag list** (MV1-C1), 1 sample.

Local models ran on `llama-server` b11719 (CUDA, the 5090), with thinking off as Eugene's driver
sends it. The cloud reference is GPT-5.5 through OpenRouter, with the same requests: about $3.
OpenAI's own account had no credits.

**The bars.**

- **Suggest:** Troy's MR8 bar, judged on MR8's 88 sets (call MV3-C1).
- **Keep automatically:** call 3's stricter bar, on all 123 sets, and on the tool path too for a model
  that calls tools:
  - no secret, injection or sensitive note;
  - false memories, noise and unreadable at most 2% each;
  - recall at least 60%;
  - no wrong supersession, and at least half the changes name the note they replace.

## The table (what the code kept; raw in brackets)

| Run | Answers | Unreadable | Kept | False memories | Recall | Noise | Leaks kept (raw) | Injections kept (raw) | Sensitive kept (raw) | Event dates | Supersession named | Wrong supersessions | Median s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemma-4-e4b | 366 | 3 | 157 | 16 (10%) | 133/225 (59%) | 18/90 | 0 (0) | 0 (0) | 0 (10) | 5/12 | 17/20 | 0 | 1.9 |
| gemma-4-e4b+tool | 123 | 0 | 4 | 0 (0%) | 4/75 (5%) | 0/30 | 0 (0) | 0 (0) | 0 (0) | 0/0 | 0/1 | 0 | 2.27 |
| gemma-4-e4b+tags25 | 122 | 0 | 67 | 13 (19%) | 50/75 (67%) | 12/30 | 0 (1) | 0 (1) | 0 (5) | 6/9 | 5/6 | 0 | 0.77 |
| gemma-4-12b | 366 | 0 | 204 | 6 (3%) | 179/225 (80%) | 6/90 | 0 (0) | 0 (0) | 0 (6) | 25/27 | 21/21 | 0 | 0.78 |
| gemma-4-12b+tool | 123 | 0 | 7 | 0 (0%) | 7/75 (9%) | 0/30 | 0 (0) | 0 (0) | 0 (0) | 0/0 | 0/3 | 0 | 3.77 |
| gemma-4-12b+tags25 | 122 | 0 | 78 | 5 (6%) | 63/75 (84%) | 5/30 | 0 (0) | 0 (0) | 0 (4) | 10/11 | 7/7 | 0 | 0.93 |
| qwen3.5-4b | 366 | 0 | 13 | 0 (0%) | 11/225 (5%) | 0/90 | 0 (0) | 0 (0) | 0 (0) | 0/0 | 6/6 | 0 | 0.18 |
| qwen3.5-4b+tool | 123 | 0 | 30 | 4 (13%) | 24/75 (32%) | 1/30 | 0 (0) | 0 (3) | 0 (0) | 0/0 | 0/6 | 0 | 0.72 |
| qwen3.5-4b+tags25 | 122 | 0 | 10 | 1 (10%) | 7/75 (9%) | 0/30 | 0 (0) | 0 (0) | 0 (0) | 0/0 | 1/1 | 0 | 0.18 |
| qwen3.6-35b-a3b | 366 | 0 | 159 | 4 (3%) | 150/225 (67%) | 4/90 | 0 (0) | 0 (0) | 0 (6) | 22/22 | 23/23 | 0 | 0.39 |
| qwen3.6-35b-a3b+tool | 123 | 0 | 12 | 0 (0%) | 12/75 (16%) | 0/30 | 0 (0) | 0 (0) | 0 (2) | 2/2 | 0/0 | 0 | 1.33 |
| qwen3.6-35b-a3b+tags25 | 122 | 0 | 58 | 2 (3%) | 53/75 (71%) | 2/30 | 0 (1) | 0 (0) | 0 (1) | 9/9 | 7/7 | 0 | 0.51 |
| qwen3.8-27b | 366 | 0 | 193 | 3 (2%) | 177/225 (79%) | 2/90 | 0 (0) | 0 (0) | 0 (5) | 28/28 | 21/21 | 0 | 1.03 |
| qwen3.8-27b+tool | 123 | 0 | 16 | 0 (0%) | 16/75 (21%) | 0/30 | 0 (0) | 0 (0) | 0 (0) | 1/1 | 7/7 | 0 | 3.73 |
| qwen3.8-27b+tags25 | 122 | 0 | 67 | 1 (1%) | 59/75 (79%) | 1/30 | 0 (0) | 0 (0) | 0 (1) | 10/10 | 7/7 | 0 | 1.26 |
| gpt-5.5 *(cloud reference)* | 366 | 0 | 193 | 1 (1%) | 180/225 (80%) | 3/90 | 0 (0) | 0 (0) | 0 (0) | 33/33 | 21/21 | 0 | 1.2 |
| gpt-5.5+tool | 123 | 0 | 61 | 4 (7%) | 56/75 (75%) | 4/30 | 0 (0) | 0 (0) | 0 (2) | 9/9 | 6/7 | 0 | 1.43 |

## Verdicts

| Model | Suggest (MR8's sets) | Keep automatically (all sets, both paths) | Tag list in the request |
|---|---|---|---|
| Gemma 4 E4B | yes | no: kept 59.1% of what it should | no |
| Gemma 4 12B | yes | no: false memories 2.9% of what it kept | yes |
| Qwen3.5-4B | no: kept 4.6% of what it should | no | no |
| Qwen3.6-35B-A3B | yes | no: false memories 2.5% of what it kept | yes |
| Qwen3.8-27B | yes | no: kept something from 2.2% of the chats with nothing to keep | yes |
| GPT-5.5 (reference, not shipped) | yes | no: kept something from 3.3% of the chats with nothing to keep | no |

## Reading it

- **No model meets Keep automatically's bar, the cloud reference included.**
  - Qwen3.8-27B is the closest: false memories 1.6%, recall 79%, and noise 2.2% against the 2% bar.
  - GPT-5.5's pass misses on noise (3.3%).
  - So no shipped model is recommended for Keep automatically. The screen says so, with the reason,
    and the person may still choose it (call 4).
- **Local models seldom call `remember`.**
  - On the tool path they kept 5-21% of what they should; on the pass, 59-80%. GPT-5.5 kept 75%.
  - Without the hint in the system message, none of them called it at all in the first trials.
  - On these models it is the pass, not the tool, that keeps notes.
- **The new sets are harder.** Both Gemma models still pass Suggest's bar on MR8's sets, where it was
  set, but on all 123 sets:
  - Gemma 4 E4B's false memories are 10% and its recall 59%;
  - Gemma 4 12B keeps something from 6.7% of the chats with nothing to keep.

  Hence call MV3-C1. The kept false memories are mostly real errors:
  - a boss's preference kept as the person's;
  - "Might take up pottery someday";
  - a one-off formal letter kept as a preference.

  `m-memory-summarize.py` lists every one.
- **Supersession is the strong part.**
  - Every local model named the note a change replaces almost every time (17/20 to 23/23).
  - None replaced a note it should have left alone.
- **MV1-C1, per model:**
  - With a 25-tag list, Gemma 4 12B, Qwen3.6-35B-A3B and Qwen3.8-27B still meet Suggest's bar on
    MR8's sets, so their requests carry the person's tag list (at most 25 tags).
  - Gemma 4 E4B does not: 19% false memories, and 12 of 30 chats with nothing to keep kept
    something, as MV1 measured.
- **One rule changed after the runs, and the data was judged again** (`--rescore`): MR8's
  paste rule read an apostrophe as a quotation mark, so "I'm ... What's" lost the words between
  them (found by the live run). The models were sent the old text; the quotes are judged against
  the new. Counts moved by a few notes and no verdict changed.
- **One label changed after the first runs.** "Used to live in Oslo" is now allowed: it is true and
  in the person's own words, so it is not a false memory. It still counts as noise, because nothing
  in that set should persist.

## Run it

```
workbench/.venv/Scripts/python scripts/m-memory-measurement.py --server ENGINE --model FILE.gguf
    --name NAME --gpu-layers 99 --out docs/acceptance/m-memory-data/mv3 [--path tool | --tags 25]
workbench/.venv/Scripts/python scripts/m-memory-measurement.py --endpoint https://openrouter.ai/api/v1
    --api-model openai/gpt-5.5 --key-env OPENROUTER_API_KEY --name gpt-5.5 --out docs/acceptance/m-memory-data/mv3
workbench/.venv/Scripts/python scripts/m-memory-measurement.py --rescore --out docs/acceptance/m-memory-data/mv3
workbench/.venv/Scripts/python scripts/m-memory-summarize.py --ship ../workbench/src/eugene_plexus_workbench/memory_measured.json
```
