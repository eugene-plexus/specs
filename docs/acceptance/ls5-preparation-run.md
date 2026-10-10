# LS5: preparation is a job on the engine's node (2026-10-09)

Slice LS5 of [library-sources-and-engines.md](../design/library-sources-and-engines.md)
(§4.6; calls B43-B57 in §6.6). Contract specs `5229a20` + `92e745e`;
library, agent and ui commits are in the pin's message.

## The run of record

`scripts/ls5-preparation-acceptance.py` on Amish_Station (Windows 11, Python
3.14, editable agent and library), **15 of 15**. A throwaway standalone agent
on free loopback ports supervises its own Library over a folder holding the
three shards of the GGUF Strata's list names unsloth-UD-IQ4_XS (headers only).
That is a RAM-budget choice, whose disk by setup's own rule is 8 GB on any
machine. The first CI run used IQ2_XS. On the Windows runner (16 GB of RAM)
that also needs the low-RAM file, 44 GB in all, and the runner's 31 GB free
was refused before setup started. The check was right; the fixture moved. Strata is a
borrowed installation (`strataServer`) whose `setup.py` is a stand-in taking
upstream's arguments and writing what upstream's writes, where it writes it:
the pack, tokenizer and MTP helper (itself a GGUF) into the data folder,
`strata-<tag>.json` with absolute paths and a start script into its own
folder, `.done` marks beside the shards. Its `serve/server.py` answers
`/health` as Strata does and keeps the launch configuration it was handed;
its `.venv` is a real, empty venv, so the stand-in runs through a venv's
launcher as upstream's does. No real Strata, no model, no GPU.

| Check | What it proves |
| --- | --- |
| E1 | The node's Strata publishes, per model on its list, the disk its setup needs on this node and the contexts it offers |
| P1 ×2 | *Prepare for Strata* (32K) goes checking, preparing (said in setup's own words, with what it expects to write), settings, launching, loading, ready |
| P2 | Setup ran non-interactively (`--yes --no-start`), for IQ2_XS at 32K, text only, speed projection off, with a settings folder of its own that is gone afterwards |
| P3 ×3 | `Strata-data` holds the marker and Strata's configuration with relative paths and no `cwd`; the expert profile is copied beside the pack; nothing is left in the engine's folder; the GGUF is unchanged |
| P4 ×3 | The Library lists the prepared model linked to its GGUF, and not the MTP helper; the run went on with the prepared model; its profile is Strata's, its runtime the provenance file, and Strata was handed the prepared files at 32K |
| P5 | Setup's `[!]` warnings are kept on the operation |
| R1 | Preparing again at 8K replaces its own configuration and provenance; one model of that name |
| U1 | Uninstalling Strata is refused (409) while it prepares |
| C1 | Cancelling the operation stops setup and what it started (the venv launcher's child too) |
| F1 | A setup that stops fails the run at *prepare*, in setup's own words |

Its first full run failed one check, not kept (the output was cut to its last
lines); four runs after it passed. The likely cause was P1's timing: the
stand-in's prepare step lasted 3 s against the worker's ~2 s report, so the
step could finish between two reports. The stand-in's step is now 6 s.

## Unit tests and sabotage

- library: `tests/test_run_preparation.py` (13: the intent, `/prepared`
  lists the model and the run goes on with it, a run cannot reach settings
  unlisted, its own file is replaced and no other, three refusals that write
  nothing, the lease and the step, a plain run cannot use it, no *skip*,
  progress kept, failure, the scan's engine folder) and
  `tests/test_catalogue_sources.py` (a search asks for the most downloaded
  first). Full suite, before the Discover fix: 722 passed,
  25 skipped (`test_routes.py::test_a_mixed_tree_end_to_end` failed once in
  the first full run and passed in two full reruns and alone; cause unknown);
  ruff, mypy both platforms, vendored check clean.
- agent: `tests/test_strata_prepare.py` (30: setup's names and sizes, the
  disk rule, the node's list, the file match, five refusals before anything
  starts, the arguments, a whole run against a stand-in setup, setup's
  failure in its words, an unlaunchable configuration, cancel, the tools'
  unpacking and verification, one GPU, the contexts),
  `tests/test_run_preparation.py` (14: the run worker's steps, the entry as
  the Library spells it, refusals, an unreachable Library folder, a lost
  checkpoint, cancel, the uninstall
  guard), `tests/test_engines.py` updated. Full suite, before the unreachable
  folder check: 2,124 passed, 17
  skipped; ruff, mypy both platforms, vendored check clean.
- ui: `PrepareModel.test.tsx` (4), `oneClickRun.prepare.test.ts` (5),
  `RunDialog.test.tsx` (no *Skip*), the Library page (3) and Discover (1).
  Full suite 1,802 passed; tsc, eslint, prettier clean.
- Sabotage of the changed code (`scripts/ls5-sabotage.py`), each restored
  from a copy: **63 of 63 caught** (library 13, agent 41, ui 9). The first
  pass caught 58 of 60. One Library test passed for the wrong reason: its
  entry *outside every Library folder* did not exist, so *not there*
  answered first. It now exists, and the refusal names the folder. One
  sabotage was dropped: taking `/T` out of the cancel's `taskkill`. CPython's
  venv launcher puts its child in a kill-on-close job, so ending the
  launcher alone ends setup too; no check can tell the two apart. Two
  entries came later: an unreachable Library folder and the Discover fix
  below.

## Found on the live install meanwhile (LS4)

Troy, after updating his machines to Edge (2026-10-09): Discover showed
*"Hugging Face: Upstream returned 400 for the model search: Invalid sort
direction, only descending sort is supported for downloads."* The search
request's generated default direction is the plain string `"desc"`. The
route compared it with the enum member by identity, which is always false.
So since LS4, every Discover search asked each hub for ascending order,
the least downloaded first. Hugging Face used to answer that silently; it
now refuses it. Fixed in the Library: the value is compared, not the
member. The test hub now refuses ascending downloads as Hugging Face does,
and a new test asks that a search sends `direction=-1`. LS4's acceptance
never saw this: its fake hubs answered any direction. That one plain-string
default (`CatalogueSearchRequest.direction`) is the only enum field with a
string default in the Library's or the agent's generated models.

## The real-model run (Troy's go, 2026-10-09)

`scripts/ls5-strata-real-run.py --folder C:\ls5-strata` on Amish_Station:
RTX 5090 (32 GB), 93.6 GiB RAM, the 990 PRO NVMe. A throwaway agent and
Library on free ports; the live install untouched. Troy stopped the live
install's llama.cpp model first: it held 30.5 GB of VRAM. The baseline after
that was 2.3 GB of VRAM and 65 GB of RAM free. **18 of 19** checks passed,
18:30 to 19:18.

| | Measured |
| --- | --- |
| I1 install (real recipe, from upstream) | 24 s |
| D1 IQ2_XS: download (68 GB, pinned revision) | 13.7 min |
| D1 preparing (setup: tools, packages, pack, the 5 GB MTP helper) | 6.7 min; Strata-data 7.9 GB (setup's rule: 8) |
| D1 settings to ready | 30 s |
| Setup's own choices for this PC | 128K context, 8-bit KV, KV streaming, one GPU; no warnings |
| G1 short answer (17 × 23) | 391, 1.2 s |
| G1 long streamed answer | 1,500 tokens in 17.1 s: **87.8 tok/s**, first token 0.48 s, no repetition |
| G1 MTP (Strata's `/v1/status`) | 791 of 1,229 drafted tokens accepted (64%) |
| G1 cancelled stream, then a prompt | answered in 0.56 s |
| Loaded | VRAM 31.9 GB; RAM free 27.8 GiB |
| S1 the Coder IQ1_M: download (58 GB) / preparing / to ready | 23.9 min / **15 s** (MTP helper shared) / 21 s |
| S1 switching (stop one, start the other) | Coder to IQ2_XS 18 s, back 15 s; the stopped one's processes gone each time |
| F1 a prepared model with an empty pack | fails before ready, and the run says so |
| X1 stop | server and native engine gone; VRAM 31.4 GB to 1.6 GB |
| U1 | uninstall refused while running; after a stop it removes the engine and keeps the prepared files; reinstall runs the same model again |

**The one failure (S1, first stop):** the runtime read *stopped* while the
native `strata.exe` was still exiting. It was gone moments later (X1, after
five seconds, found nothing left), and both switches loaded fine.
[agent#13](https://github.com/eugene-plexus/agent/issues/13): the supervisor
waits only for the process it started, a venv launcher two levels above the
engine.

**Found and fixed: a failed start did not say why** (agent `e03ea78`). F1's
runtime said only *"exited with code 1"*. Eugene's launch configuration named
no `log`, so Strata's server sent the native engine's error output to
`DEVNULL`. It now names a log beside the launch configuration. Strata's error
then ends *"the engine log's last lines: strata generate: cannot open
...\empty-pack/index.txt"*, checked by running the real server on F1's
configuration, and the adapter's `explain_exit` makes that the runtime's
`lastError`. Two more sabotages, both caught (63 of 63).

## Not covered

- Preparation and running through the live install's console. Its Library
  folder is on the NAS, so this would be the network case (agent#12).
- A Library folder on another machine: works, slowly (agent#12).
- Setup's tuning (`--calibrate`), vision, several GPUs (not offered: B49).
