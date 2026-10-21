# Row 22: re-point a Library entry whose file moved

Lane LIB, low risk, size S. Repos: library and ui. Contract: `library.yaml`.

## 1. What it delivers

- A missing model whose file moved says where the file went: "Missing from D:\models\x.gguf. Found at E:\llm\x.gguf." The button is **Move 2 profiles there**.
- Profiles move only to a file with the same contents. A fingerprint is the proof; a name or a size is not enough.
- A model that went missing before fingerprints existed can still be moved by the person, after Eugene says what it cannot prove.
- A different file is refused, and the refusal says what differs.
- Nothing moves without a click.

## 2. The design

A model's id is the hash of its path (`paths.model_id`). So a move makes a new entry, and the profiles stay on the old `missing` entry.

### The fingerprint

`LibraryModel.fingerprint` is `v1:` plus a SHA-256 over:

- the format;
- each file's role and size;
- the first 1 MiB of each weights file (for safetensors, the whole JSON header, up to 100 MiB);
- eight evenly spaced 64 KiB blocks;
- the last 64 KiB.

That is about 1.6 MiB read per file.

A new `fingerprint.py` computes it. It is called from two places:

- `scan_manager.py`, after `scanner.scan`, for new or changed files, and once for any cached entry that has no fingerprint;
- `downloads.py`, before `add_model`.

The profile document keeps the model record, so a missing entry keeps its fingerprint. A file that cannot be read gets no fingerprint and a warning.

### The contract (`library.yaml`)

- **`LibraryModel.fingerprint`** is read-only.
- **`LibraryModel.movedTo`** is set on a missing entry when exactly one present entry has the same fingerprint. It holds that entry's id.
- **`GET /v1/models/{model_id}/relocate-candidates`** returns `{candidates: [{model, match, differences}]}`. `match` is the enum `RelocateMatch`:
  - `same`: the fingerprints are equal.
  - `likely`: the missing entry has no fingerprint, and these all match: format, every file size, architecture, parameters, quantization and context length.
- **`POST /v1/models/{model_id}/relocate`** takes `{to, confirmLikely?}` and returns `{model, moved, renamed, warnings}`.

### How a relocate runs

All of it happens in one `_profile_transaction`.

1. Check the source and target. The source must be `missing`. The target must be `present` and in the same format.
2. Check the match. `same` needs nothing more. `likely` needs `confirmLikely`.
3. Move the profiles. A name the target already uses gets " (moved)". The target keeps its own default profile.
4. Forget the source entry.
5. Report stale paths. A profile whose `extraArgs` or `env` names the old path moves unchanged and is listed in `warnings`.

The gateway reads the new path at its next cache refresh, within 30 s.

### Failures

Each is a 409 unless noted:

- "This model is still at {path}; there is nothing to move."
- "{path} is no longer there."
- "{path} is a different file: {first difference}."
- "Eugene could not read {path} to check it: {cause}."
- "Eugene cannot prove these are the same file. Confirm to move anyway."
- Profile storage that cannot be written gives a 503 with the stored cause.

### UI (a missing model on the library page)

- **`same`:** "Missing from {old}. Found at {new}." Button: **Move {n} profiles there**. Afterwards: "Profiles moved to {new}."
- **`likely`:** "Missing. A file with the same size and details is at {new}. Eugene cannot prove it is the same file." Button: **Move anyway**. It asks first: "Move {n} profiles to {new}? Their settings will apply to that file."
- **None:** "Missing. No file with the same contents is in your Library folders."
- **Several `same`:** all are listed, and the person picks one.

### Defaults

Nothing happens automatically. Nothing is deleted.

## 3. Repositories and files

- **specs:** `openapi/library.yaml`.
- **library:** new `fingerprint.py`, `scan_manager.py`, `downloads.py`, `store.py`, `routes/models.py`, and tests.
- **ui:** `src/app/library/page.tsx`.

Regenerate library and ui. The gateway's codegen names `library.yaml` but uses none of this, so it is not re-pinned.

## 4. Test that fails before the change

**`library/tests/test_relocate.py::test_moved_file_keeps_its_profiles`**

1. Scan a GGUF in root A and save a profile.
2. Move the file to root B and scan.
3. Relocate from the old id to the new one.

Expected: 200. The profile is on the new id, and the old id is gone. Today the call gets 405, because the route does not exist.

Also `test_different_file_is_refused` (one changed block gives 409) and `test_likely_needs_confirmation`.

## 6. Do not change

- `library/src/eugene_plexus_library/scanner.py` (row 17). The fingerprint is a post-pass in `scan_manager.py`.
- `formats/gguf.py` and `preflight.py` (rows 18, 68).
- `gateway/.../profiles.py` (row 48).

## 7. Size, risks, open questions

**Size S**, about a day.

**Risks:**

- Every file is read once (1.6 MiB each) to fingerprint it, which is slow on a slow disk.
- A sampled fingerprint can collide only between files with the same size, the same header and the same samples.

**Open questions:**

1. **Move a unique `same` match by itself?** Recommend no. A drive that is unplugged makes its models missing. If their profiles moved to a copy, the original would come back without them.
2. **Allow `likely` at all?** Recommend yes, behind the confirmation. Only models that went missing before this ships are affected.

## Calls answered by Troy (2026-10-21)

- **R22-MOVE: Choice 2.** When the fingerprints are equal (`same`), the profiles move to the new file by themselves, and the entry says where they went. A `likely` match still asks first. Built as a follow-up branch after this row merges.
