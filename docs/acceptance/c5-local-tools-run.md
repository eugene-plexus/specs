# C5b: local MCP tools in Workbench

2026-10-03. [Design](../design/workbench-mcp.md).

Workbench main `87c815ed07bb1955b2d5cf8677ca112f6c896704`, built dist
`8a4a6a6400a7bad4f4b0b8c4ab9221fa47cc8f4d`. Agent
`a389bcbf62d3da5b756036bd00a81701ef1f5222` pins that archive with
`localActions: true`. Both generated installers take this agent pin from
the release manifest; the dependency lock is unchanged. Agent codegen uses
specs `1f606490222eac467fdd0d12e480b7357f988c0b`, which documents the
app-account launch signal. No live developer install was changed.

## What is built

**Toolbox · Tools** accepts an absolute executable, JSON argument array and
optional environment values. The operator installs the program separately;
Workbench never installs packages or runs a shell command string. Saving
does not start it. **Start and check** discovers its tools, and selecting
it for a chat starts a process for that answer. Calls use C5a's individual
approval, durable dispatch intent, saved results and uncertainty rules.

Local servers are **owner-only**. They are trusted code within Workbench's
OS account and can read its files, chats and app-scoped credentials. The
page says so. Separate working directories are not per-person sandboxes.
Other people cannot list, select, check or execute these servers. Network
connections remain shared. SQLite schema 4 preserves existing HTTP servers.

Local tools require a Windows service or Linux system install, where C1
provides Workbench's own account. The launcher replaces any ambient or
manifest-supplied account signal with the actual supervisor's account kind.
The catalogue refuses C5b on per-user installs; existing C5a installs can
continue there until migrated. A development launch without the signal
still serves chat and HTTP tools, with local starts disabled.

The MCP SDK owns stdio and negotiation. Workbench supplies a clean
environment, a per-connection working/home directory and a four-process
limit. Environment values are never returned by the API, and stderr is
discarded to keep third-party credential output out of shared logs. Tool
processes close on completion, Stop and graceful shutdown; ordinary child
processes are also removed. Data created by a server remains on removal.

## Measured checks

- **111 Python tests passed on Windows, Python 3.12**, including both real
  Chrome flows. **109 passed on Linux under WSL**, with the two Chrome
  tests skipped. **45 frontend tests passed**. Ruff, formatting, mypy,
  ESLint, Prettier, TypeScript, the production build and vendored integrity
  passed.
- Real MCP SDK servers cover HTTP and stdio discovery, calls, approval,
  continuation, Stop before/after dispatch, startup errors, discovery
  timeout, process limits, removed servers and child-process cleanup.
  Schema 1 and 3 upgrades preserve data and complete atomically.
- Chrome creates both kinds of connection, selects one for a chat, reloads
  during approval, approves, closes the tab and reopens the saved answer.
  Phone navigation and horizontal overflow are checked.
- **7/7 sabotage mutations caught:** another person approving a call,
  executing a declined call, executing a removed connection, calling an
  interrupted action successful, starting locally without an app account,
  allowing member access and inheriting ambient credentials. The harness
  restores exact source bytes and rechecks its baseline.
- **81 targeted agent tests passed**, plus 23 catalogue tests after the
  pin. Agent mypy checked 97 source files; lint and vendoring passed.
- **C3 published-archive regression: 42/42**, including Chrome, real Eugene
  sign-in, search, attachments, session isolation, key revocation and
  uninstall. The real catalogue first refuses the unprivileged install.
  The harness then explicitly enables a custom chat-only entry using the
  same archive, verifies local tools are disabled, and exercises the chat
  contract. This does not substitute for the service-install check below.
  A separate development-source run passed 38/38.

- **27/27 local release regression scripts passed**, covering release
  inputs/artifacts, platform vendoring, retained A8 data, starter scoring,
  signing/rotation, scoped keys, profiles, routing/failover, media, search,
  sign-in, recovery, launch boundaries, benchmark cancellation and durable
  run operations. The contract sweep and its sabotage pass also passed.

- **C5 service acceptance: 64/64 on Windows and 64/64 on Ubuntu**, using the
  published catalogue archive, real system installs, app accounts and
  Eugene sign-in. The local tool ran as
  `NT SERVICE\EugenePlexusApp-workbench` on Windows and Workbench's systemd
  dynamic user on Linux. It could not read Eugene's or another app's private
  files, received no Eugene credential environment, used its own working
  home and received its explicitly configured value. Approval, continuation,
  server/ordinary-child cleanup, member refusal, restart persistence and
  removal all passed:
  [run 37155824223](https://github.com/eugene-plexus/specs/actions/runs/37155824223).
  Reports are retained as that run's `c5-windows-latest` and
  `c5-ubuntu-24.04` artifacts. The harness is
  `scripts/c5-local-tools-acceptance.py` at specs `fb40369`; service installs
  are confined to disposable runners, never the developer's machine.

Workbench CI passed on Windows and Ubuntu:
[run 37154871075](https://github.com/eugene-plexus/workbench/actions/runs/37154871075).
Agent CI passed:
[run 37154958362](https://github.com/eugene-plexus/agent/actions/runs/37154958362).
The existing C1 service-account acceptance passed on both platforms:
[run 37155074270](https://github.com/eugene-plexus/specs/actions/runs/37155074270).
The full specs CI passed on both platforms after the C3 harness update:
[run 37155119944](https://github.com/eugene-plexus/specs/actions/runs/37155119944).

## Defects found during acceptance

The Linux process test exposed an SDK 2.3 cleanup gap: a server that exits
normally can leave ordinary children alive. A small POSIX stdio guard now
owns the process group until shutdown and kills the remaining group even
after a normal server exit. The same real child-process test failed before
the guard and passed afterward on Linux; Windows uses the SDK's Job Object.
Programs that deliberately daemonize are outside this supported lifecycle.

The first service runs passed tool execution, account/file/environment
checks, member refusal and child cleanup on both platforms, then failed
when signing in after restart. The new harness had tested the truthiness
of a health-check function instead of calling it. It now requires a new
service PID and a successful health response. Non-chat capability probes
also now receive 404 from the scripted model instead of raising KeyError.
The first probe-filter fix matched one URL exactly and rejected the
driver's prefixed chat path; the fixture now identifies those requests by
their body, verified locally with both paths before the service rerun.
The C3 harness needed to enable its explicit custom chat-only entry; that
was fixed before the passing published-archive run.

## Remaining scope

**C6: folder grants and filesystem tools**, including a design for the
boundary between people's files. Owner-only trusted code does not establish
per-person isolation. Dedicated media screens, local media engine admission,
answer versions and the working animation remain separate slices. MCP
OAuth, resources/prompts and non-text tool results remain unimplemented.
The model in these checks is scripted; this is not a live-model accuracy
benchmark or a test of arbitrary third-party package installations.
