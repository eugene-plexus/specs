# LS8 acceptance: Delete a model from the Library, any format

Design: [library-sources-and-engines.md §6.11](../design/library-sources-and-engines.md)
(B87-B94; Troy replaced B27 with a Delete for every model).

## Run of record

`scripts/ls8-delete-acceptance.py`, on Amish_Station (Windows 11, Python
3.14, the repos' working trees at the LS8 pins), 2026-10-10: **7/7 PASS**.
It runs in specs CI on Windows and Ubuntu from the LS8 pins on (D6 is
Windows-only: a POSIX file can be moved while open).

```
PASS  D1 a prepared model's plan: its own files, the MTP helper kept for the other
PASS  D1 a stale plan deletes nothing
PASS  D2 deleted: its files and the model gone, the other and the source kept, and a scan does not bring it back
PASS  D3 a quant keeps the projector the other quant uses
PASS  D4 the GGUF names what was prepared from it; both go, the MTP helper with its last user, setup's intermediates and the marker stay
PASS  D5 a safetensors folder goes whole, and the folders it leaves empty
PASS  D6 a file held open is not deleted, and neither is anything else of it
PASSED: 0 failing check(s)
```

The first attempt stopped before any check: the script wrote GGUFs into
folders it had not made yet (an instrument error).

## Unit tests

- library `tests/test_deletion.py` (10): a prepared model's own files and
  the shared ones kept; the last user takes a shared file; a GGUF names what
  was prepared from it; a split GGUF goes whole and a shared projector
  stays; a safetensors folder goes whole and empty folders go; a file that
  cannot be moved leaves everything; downloads and runs refuse; the routes
  plan, refuse a stale token, delete and drop the model; a refusal holds at
  delete time; a GGUF and both prepared models go together.
- ui `DeleteModel.test.tsx` (3): running and unreachable nodes block; the
  confirmation lists files, kept files and runtimes, sends the token and the
  ticked prepared models, then removes the runtimes; refusals disable it.
  `app/library/page.test.tsx`: Delete on the model page, refused while the
  picked node runs it, then deleting and leaving the page.

## Sabotage

`scripts/ls8-sabotage.py`: **19 caught, 0 escaped** of 19, after one fix. The
first pass let *a safetensors folder's other files are left* escape: the
scan lists a folder's top-level files, so a test with only top-level files
could not tell the folder walk was gone. The test now has a file below the
folder (`images/chart.png`), and the re-run caught it.

Full suites before the push: library 757 passed (ruff, format, mypy clean);
ui 1,827 (tsc, eslint, prettier clean); the LS3 acceptance.
