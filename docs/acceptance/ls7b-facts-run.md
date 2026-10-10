# LS7b acceptance: the Library says what is known of a prepared model

Design: [library-sources-and-engines.md §6.10](../design/library-sources-and-engines.md)
(B77-B86; Troy's B22 replacement, B26, B30, the source list's order).

## Run of record

`scripts/ls7b-facts-acceptance.py`, on Amish_Station (Windows 11, Python 3.14,
the repos' working trees at the LS7b pins), 2026-10-10: **8/8 PASS**. It runs
in specs CI on Windows and Ubuntu from the LS7b pins on.

```
PASS  F1 Strata's configuration read back: its list entry, context, mode and source
PASS  F1 every file beside the source, sized, the MTP helper shared, setup's intermediates and the GGUF shards left out
PASS  F2 added with the draft: the provenance file records what Strata read
PASS  F2 the Library lists it with its title, context and measured files, its source linked and that model's architecture, nothing missing
PASS  F3 one that records nothing names each missing fact, with why
PASS  F4 a file Strata did not write is refused, naming why; one outside the Library's folders is not read
PASS  F5 B30: Strata v0.1.37 here is older than UD-IQ4_XS needs (v0.1.38), and says so on that entry only
PASS  F6 results come in the list's order, whatever a source's kind
PASSED: 0 failing check(s)
```

The first run failed F5 on the instrument: the agent writes absent fields
of `/v1/engines` as `null`, and the check asked for them to be missing.

## On a file real Strata wrote

The configuration Strata v0.1.39's own setup wrote on Amish_Station in LS7a's
real run (`D:\ls7-share\Strata-data\strata-iq2_xs.json`, an IQ2_XS
preparation at 131,072 tokens), read by the adapter as the inspect route
reads it:

```
title          Qwen3.8-Flash-Next IQ2_XS
architecture   qwen4exp
quantization   IQ2_XS
contextLength  131072
mode           every expert in RAM
source.path    D:\ls7-share\ISTA-DASLab\Qwen3.8-Flash-Next-GSQ-RCO-GGUF\Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf
source.repoId  ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF
files          15 (2.37 GB): the configuration, the pack and its tokenizer;
               shared: mtp/rt/dense.bin, dense.txt, draft_vocab.bin, experts.bin
```

The source's two shards (about 68 GB) are not among them, and neither are
setup's intermediates the configuration does not name (`mtp/tensors/`).

## Unit tests

- agent `tests/test_ls7b_facts.py` (13): the reading, a missing file named, a
  non-Strata file refused, a source off the list, the four modes, the
  Library's spelling of paths (POSIX and Windows), files relative to the
  provenance folder, version comparison, B30 per installed version, the
  route (200, 422, an engine with no preparation, 404). Also
  `test_strata_prepare.py` (a preparation records the facts) and
  `test_run_preparation.py` (the worker sends them).
- library `tests/test_prepared.py` (facts measured, inherited, missing named;
  adoption elsewhere rebases files), `test_catalogue_sources.py` (list order,
  the default list, the old file's hub), `test_settings_truth.py`.
- ui `AddPreparedModel.test.tsx` (a refused file blocks adding),
  `PrepareModel.test.tsx` (B30 line), `CatalogueSources.test.tsx` (move up
  and down), `app/library/page.test.tsx` (the form uses the inspect answer
  and chooses *Made from*; the model page names missing facts).

## Sabotage

`scripts/ls7b-sabotage.py`: **36 caught, 0 escaped** of 36 sabotages of the
changed code across the agent, library, ui and acceptance gates; every gate
passed at baseline and again after each file was restored from its copy.

Full suites before the push: agent 2,178 passed (ruff, format, mypy for
Windows and Linux clean); library 747; ui 1,823 (tsc, eslint, prettier
clean); the LS3, LS4 (updated for list order), LS5, LS6 and LS7a
acceptances; the run-protocol check; the vendored-file check.
