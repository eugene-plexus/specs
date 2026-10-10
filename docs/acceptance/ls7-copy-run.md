# LS7a: a node runs a prepared model from its own copy (2026-10-09 night)

Slice LS7a of [library-sources-and-engines.md](../design/library-sources-and-engines.md)
(§6.8 Troy's principle: the Library is the home of every model file and
config, a node only ever holds a copy; calls B70-B76 in §6.9). Contract
specs `b1a6b06` (`CopyProgress.files`, `filesCopied`).

## The acceptance of record

`scripts/ls7-copy-acceptance.py`, a throwaway agent and Library on free
loopback ports over one Library folder laid out as LS5's preparation leaves
it (a two-shard Flash-Next GGUF in its publisher's folder, `Strata-data`
beside it with a prepared model and setup's unnamed intermediates), LS3's
stand-in Strata server, copying on to a folder of its own. **8 of 8** on
Amish_Station:

| Check | What it proves |
| --- | --- |
| C1 | Run reaches ready on Strata |
| C1 | The whole set is copied with its layout (provenance, configuration, pack, tokenizer, the MTP helper's runtime folder, both GGUF shards: agent#10), and setup's unnamed `tensors/` is not |
| C1 | The runtime opens the copy (`localPathSource: copy`) |
| C1 | Strata was handed the GGUF and pack inside the copy |
| C3 | A copy folder on a share is warned about in Settings |
| C3 | The copy folder's own drive is named, or nothing is claimed |
| C4 | Adopting an engine's files from outside the Library is refused, nothing written |
| C4 | A provenance file written by hand pointing outside is unreadable, saying why |

On a standalone agent no Library-folder rule exists, so a copy keeps the
model's whole path under the copy folder; the layout between its files is
what the run checks. A llama.cpp runtime over a split GGUF was dropped from
the run: with no llama.cpp installed its start never begins, and the set's
two GGUF shards already prove agent#10 end to end (the unit tests cover a
GGUF alone).

## The real-model run

`scripts/ls7-copy-real-run.py` on Amish_Station (Troy allowed real models
tonight): a throwaway agent with the Strata v0.1.39 install kept from LS5's
real run as its engine root, `D:\ls7-share` standing in for the NAS (the
IQ2_XS set as LS5 prepared it: 21 files, 65.6 GB, staged with robocopy at
about 1 GB/s) and a copy folder on C:'s SSD. **7 of 7** on the run of record:

| Check | Result |
| --- | --- |
| R0 | Settings names the copy folder's drive: *On an SSD.* (C: is an NVMe 990 PRO; D: an MP510; both SSDs, as Windows' own inventory says) |
| R1 | Run reaches ready from the copy in **1.4 min**, the 70.4 GB copy (18 files) included |
| R1 | The copy reported the set's files while it ran |
| R1 | Strata opens the copy on C: (`localPathSource: copy`) |
| R2 | Strata answers from the copy, no refusal after ready |
| R3 | Deleting the runtime takes its 70 GB copy with it |

Two earlier attempts failed on the instrument: the first asked for 16
tokens, which this reasoning model spent thinking (`content` null,
`reasoning_content` set); the check now accepts either and asks for 256. The
third started from a copy left current by a crashed attempt and read ready
6 s after start while Strata still said it was loading; the chat request then
got an error page. Not reproduced on the run of record; filed as
[agent#15](https://github.com/eugene-plexus/agent/issues/15). The check now
waits for Strata's own answer and prints any refusal after ready.
