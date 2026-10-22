# Row 52: per-person isolation for local MCP programs

Lane AG2, after row 51 (it shares 51e's AppContainer code). **High risk**
(running third-party code for people who are not the owner). Sources:
`workbench-mcp.md` §C5b ("local servers are owner-only in C5b … all code in
the app's account can read its files, including other people's chats …
per-person process isolation remains later work"), `workbench-files.md`
§Boundary, Workbench `tools.py` (stdio transport, `tools/` directories,
the four-process limit), site-host `folder_linux.py` (Landlock).

## 1. What it delivers

- **The owner can offer a local MCP program to everyone,** not only use it
  alone. Each person's copy runs in a sandbox of its own: it reads and
  writes its own folder for that person, the folders that person was
  granted, and the program's own files, and nothing else of the machine's.
  It cannot read Workbench's store, other people's chats or folders, or
  Workbench's credentials.
- **The owner's own use** can run sandboxed too (a switch, on by default
  for new servers), so a misbehaving program cannot read the store
  whoever runs it.
- Where no sandbox is available (macOS, a per-user install), local programs
  stay owner-only, as today, and the page says why.

## 2. Design

### The sandbox, per platform

| Platform | How | What the program can reach |
|---|---|---|
| Linux (system install) | Landlock (as site-host's `folder_linux.py` uses), `no_new_privs`, its own process group | read and execute: the program's path, `/usr`, `/lib*`, `/etc` (read), `/proc/self`; read and write: its per-person folder and that person's writable grants; read: their read-only grants |
| Windows (service install) | an AppContainer per (server, person), from row 51e's helper, with the `internetClient` capability | read and execute: the program's folder (Program Files grants `ALL APPLICATION PACKAGES` read already; elsewhere the page asks the administrator to grant it, with the exact folder), read and write: its per-person folder and grants, via the container's SID added to each |
| macOS, per-user installs, containers | none | owner-only, as today |

- Network stays open: MCP programs fetch things. A program's reach is the
  network and the files above.
- **The per-person folder** is `tools/<server>/<sha256(person)[:32]>/`, the
  process's home and cache. Deleting a person (row 7) deletes it.
- **Check at start:** before the first real start, Workbench starts a tiny
  probe in the sandbox that tries to open Workbench's store; if it can,
  the sandbox is broken and the server does not start, naming the cause.

### Who may use a local program

- The owner adds the program as today, then chooses **Available to:
  Only me / Everyone / Chosen groups** (row 70's groups).
- A person sees it in Tools and in chat settings like any server; tool
  calls keep C5a's approval rules.
- **Environment values** (tokens the program needs): the owner's values
  are shared with everyone's copies only if the owner ticks "Share my
  values with everyone who uses it" beside each value, with "they act with
  your token" in the line. Otherwise each person enters their own values,
  kept in their own private storage. Call R52-ENV.
- The four-process limit becomes four per person and twelve per machine.

### Contract

None in specs: Workbench's API is its own (`/api/tool-servers` gains
`availableTo`, `sandbox` {kind, ok, detail}, and per-person environment
values).

## 3. Repositories and files

workbench (`tools.py` stdio launch, `tools_api.py`, a new `sandbox.py` for
Landlock and the AppContainer launch, the Tools page), site-host or a
shared module for the AppContainer helper from 51e (copied, not shared:
components share schemas, never code), agent (the Windows service's
account gets the right to create AppContainer profiles if it lacks it; the
installer's check).

## 4. Tests that fail before

- workbench `test_sandbox.py::test_a_sandboxed_program_cannot_read_the_store`
  (Linux CI with Landlock; Windows CI with AppContainer): a fixture stdio
  program that tries to read `workbench.sqlite3`, another person's folder,
  and its own folder.
- workbench `test_tools.py::test_a_server_for_everyone_runs_a_copy_per_person`.
- workbench `test_tools.py::test_owner_values_are_not_shared_unless_ticked`.
- workbench `test_sandbox.py::test_a_broken_sandbox_stops_the_start`.

## 5. Acceptance (CI, Linux and Windows, about 4 minutes)

`specs/scripts/row52-mcp-sandbox-acceptance.py`: Workbench as a system
service, two people, a fixture MCP program offered to everyone:
1. Person A's call reads A's own folder: allowed. It reads the store file,
   B's folder, Workbench's key file: each refused by the OS.
2. B's call runs as B's copy, with B's own environment value.
3. The owner's value ticked "share": both copies see it; unticked: neither.
4. **Sabotage:** skip the Landlock or AppContainer step; step 1's store
   read must succeed and the run must fail.

**The reviewer should attack:** paths the sandbox allows that reach the
store (symlinks, `/proc/<pid>/root`, inherited handles, the working
directory), environment leaking between people, the AppContainer SID left
on a folder after a grant ends, and a program that spawns children
outside the sandbox (they inherit it; check).

## 6. Do not change

- Row 23's folder access code (call it to add the container's SID).
- `ToolContent.tsx` (row 31) and the store migrations other rows hold; this
  row needs one migration for `availableTo` and per-person values (the
  next free number when it starts).

## 7. Size and risks

L, about 4 days, after row 51e. One adversarial review.
Risks:
- **Third-party code for many people:** the sandbox is the boundary; the
  probe at start and the sabotage step are its tests.
- **Program folders outside Program Files** on Windows need an
  administrator's grant for the AppContainer; the page says which folder.
- **Shared tokens** let people act as the owner; off unless ticked, per
  value.

**Calls:** R52-ENV (the owner's environment values are per-person unless
the owner ticks "share" on each).
