# LS10: the Library writes a preparation's files

Design: [library-sources-and-engines.md §6.13](../design/library-sources-and-engines.md)
(B101-B108; [agent#16](https://github.com/eugene-plexus/agent/issues/16)).

Found on Troy's live install, 2026-10-10. Amish_Station's Windows service
prepared a GGUF in the NAS container's Library folder over SMB, and setup's
`.done` mark beside the shard was refused (`PermissionError`). The container
writes its downloads 0755/0644, so no other SMB account may add a file
there. Since LS10, a node never writes in a Library folder. It prepares in a
folder of its own and sends the result, and the Library writes it.

## Acceptance of record

`scripts/ls5-preparation-acceptance.py` (LS5's, extended with L1-L5), on
Amish_Station, 2026-10-10: **21/21 PASS**. A throwaway agent and Library ran
on free loopback ports, with a stand-in setup. The GGUF's folder was made one
this account may not add a file to (Windows: `icacls /deny <me>:(WD,AD)`;
POSIX: mode 0555). That reproduces Troy's failure exactly (`Errno 13`
creating the `.done` file); it was checked once by hand. In CI on Linux and
Windows.

```
PASS  E1 Strata is available from its borrowed install and publishes each preparation's disk and contexts
PASS  P1 the run prepares, saying where it is in setup's own words
PASS  P1 then settings, launch and load: ready, on Strata
PASS  P2 setup ran non-interactively for its choice at 32K, text only, with its own settings folder
PASS  P3 Strata-data has the marker and Strata's configuration, paths relative, no cwd
PASS  P3 the expert profile is copied beside the pack, nothing is left in the engine's folder
PASS  P3 the GGUF is unchanged
PASS  L1 the GGUF's folder refuses a write from this account, as a share does a node
PASS  L2 the Library made Strata-data and holds what the model is made of, none of setup's records
PASS  L3 setup's marks are beside this node's links; after listing it keeps only the MTP helper
PASS  L3 the node no longer holds what it sent, but keeps the MTP helper
PASS  P4 the Library lists the prepared model, linked to its GGUF; the MTP helper is not a model
PASS  P4 the run went on with the prepared model, from the GGUF
PASS  P4 its profile is Strata's, its runtime the provenance file, Strata handed the prepared files at 32K
PASS  P5 setup's warnings are kept on the operation
PASS  R1 preparing again with another context replaces its own configuration and provenance
PASS  U1 Strata cannot be uninstalled while it prepares
PASS  C1 cancelling the operation stops setup and what it started
PASS  F1 a setup that stops fails the run at prepare, in setup's own words
PASS  L4 the failed setup's log is sent, and the failure names the Library's copy
PASS  L5 uninstalling Strata takes this node's preparation folders
PASSED: 0 failing check(s)
```

The first run failed P1 at sending: `operation_request` would not take a
caller's `headers` (*got multiple values for keyword argument 'headers'*).
The unit tests' stand-in Library had not shown it. It is fixed, with a unit
test that fails without the fix (`test_admission.py`,
`test_run_work_sends_its_own_headers_beside_the_credential`).

On this machine the account may not make symbolic links, so the shards were
hard links (B102). A Windows service may make symbolic links; Linux CI makes
them.

## The live run

Troy's install, 2026-10-10: the root's Library in the NAS container, and
Amish_Station's service reaching `\\192.168.16.252\downloads\models`, both on
Edge `19fc0f4`. *Prepare for Strata* on the IQ2_XS model the failed run had
downloaded completed, listed the model and started it (Troy: *I seem to have
Strata running*). Per-step timings were not recorded.

The run also found that a llama.cpp model Troy had stopped started again
whenever Amish_Station restarted
([agent#11](https://github.com/eugene-plexus/agent/issues/11)). Strata's
`--expert-cache auto` sizes its GPU cache from the VRAM free at its start,
so it started with what that model left. Setup reads only the card's total
memory (`nvidia-smi --query-gpu=memory.total`), so the preparation itself
does not depend on what else is running; a restart of the Strata runtime
with the card free is enough.

## Unit tests

- library `tests/test_prepared_uploads.py` (27): where the Library writes;
  the person's folder left alone; no write through a link or junction; chunks
  at the offset that arrived; a short or damaged file never put in place;
  sending again; lease, step and Library folder; a chunk over 32 MiB,
  declared or not.
- agent `tests/test_strata_prepare.py` (37): the node's folder laid out as
  the Library folder; nothing written in the Library folder; symbolic links,
  hard links, a junction (Windows) or copies; what is sent and discarded; a
  path outside the model's files refused; the log's place.
- agent `tests/test_run_preparation.py` (20): sent and listed as the Library
  spells it; a slice per tick, carrying on from the Library's count; what the
  Library holds not sent again; damaged sent again; the Library's refusal
  named; the failed log sent and named; uninstall refused while files are
  sent.

Full suites: agent 2,181 passed, library 773 passed.

## Sabotage

`scripts/ls10-sabotage.py`: **36 caught, 0 escaped** (library 13, agent 18,
acceptance 5). Baselines passed and the restored gates passed. Each entry puts
one rule back or takes one check out:

- where the Library writes, how a file arrives, lease, step and folder;
- what the node writes and where, the links, what is sent and kept;
- the sender's resume, skip, resend and slice;
- the credential beside a caller's headers;
- the failed log, and uninstall.

## Commits

library `9493ce7`, agent `0f8b327` (pinned with this record), ui `afbc38f7`
(the vendored contract and types; the console does not call the routes, so
there is no new build and no pin).
