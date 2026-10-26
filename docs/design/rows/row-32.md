# Row 32: Skills

Lane WB. Sources: `memory-research-2026-10.md` §7.4 ("Skills in the
Anthropic sense … are a later question"), the Agent Skills format that
Claude Code, Claude apps and Codex read (a folder with `SKILL.md`), and
Workbench `conversation.py`, `tools.py`, `files.py`, `store.py`.

## 1. What it delivers

- **A Skills page in Workbench's Toolbox**, beside Tools. A person adds a
  skill by uploading its `.zip` (or one `SKILL.md`), or writes one there:
  a name, a one-line description of when to use it, and the instructions.
  They can read, edit, turn off and delete each skill.
- **The model uses a skill when it fits.** It sees each skill's name and
  description, and loads the instructions only when a request needs them,
  then any reference file the instructions point to. A skill made for
  Claude Code or Codex works unchanged, apart from its scripts (below).
- **The owner can give a skill to everyone** on the install. Each person
  sees it on their Skills page and may turn it off for themselves.

## 2. Design

### What a skill is

The Agent Skills format: a folder whose `SKILL.md` starts with YAML
frontmatter, `name` (lowercase letters, digits and hyphens, at most 64
characters) and `description` (at most 1,024 characters), then Markdown
instructions. Other files in the folder (`references/`, `scripts/`,
`assets/`) are read on demand. Unknown frontmatter keys are kept and shown,
never acted on.

### How the model sees skills

- **A built-in tool, `use_skill`,** offered when the chat has at least one
  skill on. Its description lists each skill as `name: description`. The
  list sits in the tool definition, not the system message, so memory's
  pinned block and the prompt cache are unaffected; the list is a per-chat
  snapshot, taken again only when the person changes their skills.
- `use_skill(name)` returns the instructions (the body of `SKILL.md`, at
  most 32,000 characters) and the skill's other files with their sizes.
  `read_skill_file(name, path)` returns one text file (at most 65,536
  characters, the replay limit). A binary file says what it is and that it
  is not text.
- Both are read-only and never ask for approval, like `search_memory`.
- **The listing is bounded:** at most 32 skills and 8,000 characters of
  names and descriptions per chat. Over that, the Skills page says which
  skills are not listed and why, and the person turns some off.
- **Per chat:** Chat settings gains Skills: "All my skills" (default) or a
  pick of them. Projects keep no skill setting in this row (row 27 owns
  project extras).

### Scripts

Workbench does not run a skill's scripts on the machine Eugene runs on;
there is no sandbox there, and a skill's author is not the person. A script
runs only where commands already run: a Job Site's `run_command`, as the
person, with the site's signature and ask rules. The model copies the
script there with the site's `write_text` and runs it. `use_skill` says so
when the skill has scripts: "This skill has scripts. They run only on a Job
Site that allows commands; this chat has none." (or names the site).

### Where skills come from

- **Upload** (`POST /api/skills`, multipart): a `.zip` or a `SKILL.md`. The
  ZIP reader refuses, each with its cause: more than 512 entries; more than
  20 MiB unpacked or a ratio over 100 to 1; an absolute path, `..`, a drive
  letter or a link; nesting deeper than 8; no `SKILL.md` at the root or in
  one top folder; frontmatter that does not parse or breaks the name and
  description rules. A same-named skill asks: Replace or Keep both (the new
  one gets `-2`).
- **Write** on the page: the form writes `SKILL.md`; files can be added.
- **The owner's skills for everyone:** an owner's skill has a switch "Give
  to everyone on this install". It then shows on everyone's page, marked
  "From the owner", read-only to them, on by default, and each person may
  turn it off (call R32-OWNER). Per-group skills follow when row 70's group
  claims reach Workbench.

### Storage

- A table `skills` (id, owner: the person's `sub` or `install`, name,
  description, enabled, source `upload` or `written`, bytes, created,
  updated) and `skill_off` (person, skill id) for an owner's skills a person
  turned off. One store migration; its number is assigned when the row
  starts (rows/README.md).
- Files unpacked read-only under `<data_dir>/skills/<sha256(sub)[:32]>/<id>/`
  (the install's under `install/`). Per person: at most 200 skills and
  50 MiB.
- **Removal and export:** row 7's person removal deletes the person's
  skills and their `skill_off` rows; Your data's export includes each skill
  as its folder.

### Failures

- A refused archive names the rule and the entry: "Not added: `../x.sh`
  leaves the skill's folder."
- A missing skill at call time (deleted mid-chat): `use_skill` says it was
  removed; the call is not an error.
- Over quota: "Not added: your skills would use 52 MiB; the limit is 50 MiB."

## 3. Repositories and files

Workbench only: `skills.py` (new: store, ZIP reader, frontmatter),
`skills_api.py` (new), `tools.py` (offer and dispatch the two tools),
`conversation.py` (only if the tool snapshot needs it), `store.py` (the
migration), the person-removal and export code, and `web/src`:
`components/Skills.tsx` (new), `App.tsx` (Toolbox tab), `ChatSettings.tsx`.
No contract in specs: Workbench's API is its own.

## 4. Tests that fail before

In a new `tests/test_skills.py`:
- `test_a_skill_zip_is_unpacked_and_listed` and `test_a_single_skill_md_is_a_skill`.
- `test_hostile_archives_are_refused_with_their_cause`: traversal, absolute
  path, link, 513 entries, a 1,000-to-1 entry, no `SKILL.md`, bad name.
- `test_use_skill_returns_the_body_and_file_list` and
  `test_read_skill_file_stays_inside_the_skill` (`../` refused).
- `test_the_listing_is_in_the_tool_not_the_system_message`.
- `test_another_persons_skill_is_invisible` (404 on every route).
- `test_an_owners_skill_reaches_everyone_and_can_be_turned_off`.
- `test_removing_a_person_deletes_their_skills` and
  `test_export_includes_skills`.

## 5. Acceptance (CI, Linux and Windows, about 3 minutes)

`specs/scripts/row32-skills-acceptance.py` on row 2's harness (Workbench,
the gateway and the fixture backend; two people):
1. Person A uploads a skill ZIP with `references/style.md` and a script.
   The fixture backend, scripted to call `use_skill` then
   `read_skill_file`, receives the body and the file; the tool definition
   lists the skill; the system message is byte-identical with and without
   skills.
2. The script line says no Job Site allows commands.
3. Person B sees nothing of A's; the owner's install skill reaches both;
   B turns it off and it leaves B's next chat.
4. Each hostile archive is refused with its cause, and nothing is written
   outside the skills folder (the folder tree is compared before and after).
5. A is removed: the skill folder and rows are gone.

**The reviewer should attack:** the ZIP reader (traversal, links, bombs,
Windows names like `CON` and trailing dots), path checks in
`read_skill_file`, one person reading another's skill by id, and an
install skill a person cannot turn off.

## 6. Do not change

- `context.py` (row 26: add functions only), the memory pinned block
  (`memory.py`), `ToolContent.tsx` (row 31), and the store migrations other
  rows hold (row 70c): take the next number when the row starts.
- `tools.py` is shared with rows 23, 26, 27, 28, 30 and 31: add the two
  tools beside `search_memory`; do not restructure.

## 7. Size and risks

M, about 2 days. **High** (a store migration and an archive reader):
one acceptance run in CI on Linux and Windows and one adversarial review.
Risks:
- **A skill is instructions a stranger wrote.** It reaches the model only
  when the person added it, or the owner gave it; the Skills page shows the
  whole `SKILL.md` before it is turned on. Scripts never run outside a Job
  Site the person controls.
- **Context cost.** A loaded skill's body can be 32,000 characters; the
  rounds limit and the context work in row 26 bound it.

## Calls answered by Troy (2026-10-22)

- **R32-OWNER: Choice 1, with a change of words.** A person may turn off a
  skill the owner gave everyone, and the page marks it **"From Eugene"**,
  not "From the owner".

## What building found (2026-10-26)

Built on `r32-skills` (workbench, specs). Store schema 34.

- **An upload arrives off (default built).** "The Skills page shows the
  whole `SKILL.md` before a skill is turned on" is built literally: an
  uploaded skill is added off, its card opens with the whole `SKILL.md`, and
  its switch is enabled once that has loaded. A replaced skill is off again
  (its words changed). A skill the person writes on the page is on at once.
  A skill Eugene gives everyone is on for everyone, as R32-OWNER says.
- **The listing is the same bytes while the skills are.** No copy is kept
  per chat: `use_skill`'s description is built each answer from the person's
  skills that are on, by name, so it changes only when their skills do,
  which is what a per-chat snapshot retaken on a change gives. The chat's
  pick (`settings.skills`; unset is "All my skills", `[]` is none) narrows it.
- **The reader refuses bzip2 and LZMA entries.** `zipfile` hands each
  compressed piece to those decompressors whole, so an entry whose header
  lies about its size can fill memory before the size is checked; Deflate is
  read a bounded piece at a time. Every skill seen so far uses Deflate.
- **The 100:1 rule applies to entries over 64 KiB.** A short file of
  repeated lines packs past 100:1 and is no bomb; the 20 MiB limit, counted
  on the bytes read, holds for every entry.
- **More Windows and macOS rules than the design listed:** device names with
  any extension (`CON.md`, `COM1`-`COM9`, `LPT1`-`LPT9`, the superscript
  forms, `CONIN$`), `<>:"|?*` and control characters (a `:` would be an NTFS
  stream), names over 255 bytes, paths over 200 characters, and two names
  that differ only in case or Unicode form. A file and a folder of one name,
  and a name twice, are refused too. Depth counts folders on the archive's
  own path, a top folder included. `__MACOSX/`, `.DS_Store`, `Thumbs.db` and
  `desktop.ini` are left out, as nobody wrote them.
- **Two walls.** The writer judges every place again on its words before it
  makes any folder (on Windows a `C:` part in `joinpath` would leave the
  folder), then checks the real path. With the reader's `..` rule sabotaged
  the dot rule still refused `../x.sh`, and the test failed on its message.
- **A person's own skill hides an install skill of the same name** from
  their chats (the page says why), so the names the model sees are unique.
- **Keep both** names the new row `name-2`; its `SKILL.md` is kept as
  written, so its frontmatter still says `name`.
- **Data.** A person's own download holds each of their skills under
  `skills/<name>/`; the owner's download of a removed person does too; the
  owner's download of a person who uses Workbench does not (skills are
  treated as notes are). A skill the owner gave everyone is the install's,
  not theirs: it stays when they are removed, and it is never in a person's
  download. Removal gains a `skills` step for the folder; the rows go with
  `PERSON_TABLES`, `skill_off` by `sub` so the existing seeded purge test
  covers it.
- **What it does not hide.** A skill's tool results replay to later
  requests and show in the owner's read-only view (W4) as any tool's do;
  only notes and past chats are withheld. Calls to the two tools count as
  tool reads for `remember`'s write policy: a skill is a stranger's words.
- PyYAML is now declared by Workbench (the safe loader, aliases refused);
  the requirement is the one other components already declare, so
  `release/requirements.in` is unchanged.
