# C5a: network MCP tools in Workbench

2026-10-03. [Design](../design/workbench-mcp.md).

Workbench main `b567d505b2bed6ae515bb2638a6f1efaaefbc33a`, built dist
`8d7002dc4253956cde129a3cbe7b751a91d584c6`. Agent
`80eae52bf518a88ed8ff358bb566f01dca21f25f` pins that archive. Both installers
take the agent pin and the regenerated dependency lock from the release
manifest. No shared public API contract changed and no consumer codegen
pin moves for this slice.

## What is built

**Toolbox · Tools** starts the workshop vocabulary at the second tool, as
chosen in C3. The owner adds shared Streamable HTTP connections with optional
bearer credentials. A chat chooses connections, then its owner approves or
declines exact tool calls. Credentials never go to the browser or model.
Namespaced functions travel through the public chat/completions door.

SQLite schema 3 keeps tool requests, states and results with the answer.
Dispatch intent is saved first. A stopped or interrupted dispatched call is
uncertain, never replayed. A pending call is cancelled on interruption and
expires after 30 minutes otherwise. Removing a server prevents pending calls
from executing. Output is bounded and rendered as text. MCP continuation
keeps the first round's search count without forcing another web search.

Chrome exposed an existing narrow-screen problem: the fixed sidebar crowded
out chat and its model picker. Chats now opens the sidebar on phones and a
selection returns to the conversation.

## Measured checks

- **92 Python checks passed on Windows, Python 3.12.14**, including the opt-in
  system Chrome check. The ordinary CI run has 91 passes and skips that
  browser check. **42 browser component/copy checks passed**; typecheck,
  lint, formatting, production page build and vendored integrity passed.
- **Real MCP SDK 2.3.0 server over HTTP**, with both JSON and SSE responses,
  current negotiation and the legacy handshake: discovery, fragmented
  calls, approval/decline, continuation and later history. The model is a
  scripted gateway fixture; this does not claim live-model tool accuracy.
- Credentials, ownership, removed connections, malformed/unknown/truncated
  calls, expiration, Stop during execution, restart, oversized results,
  refusal and redirect handling are exercised through authenticated HTTP.
- **Chrome** adds a server, checks it, selects it for a chat, reloads while
  approval is pending, approves once, closes the tab, and returns to the
  saved answer. Phone navigation and horizontal overflow are checked.
- **4/4 sabotages caught**: remove chat ownership, execute a declined call,
  execute against a removed server, and mark an interrupted action successful.
  The instrument restores exact saved bytes and checks its baseline again.
- **23 agent app checks passed** for the catalogue update.
- **C3 catalogue acceptance: 38/38**, installing the published Workbench
  archive through another node's console, including Chrome, real Eugene
  sign-in, search, attachments, session isolation, key revocation and
  uninstall. The initial `--source` development run hit its pre-existing
  duplicate-catalogue-ID refusal; that is not counted as acceptance.
- Release-input generation, platform vendoring, release artifact bytes,
  S10 instruments, retained A8 measurements, and the contract sweep over
  **300 consumer source files** passed. Contract sabotage: **11/11**.
  POSIX installer fixtures in WSL: **141/141**, sabotage **19/19**.
- The broader 21-script release sweep passed 20 on its first run. A5's
  immediate fallback check after a key-policy edit failed once; an unchanged
  runtime rerun passed. Its assertion now includes response status and body
  so a recurrence has a diagnosis. The cause is not established and no
  rate-policy repair is claimed here. Every script has a passing run.

Workbench CI is green on Windows and Ubuntu, including the final vocabulary:
[run 37148691556](https://github.com/eugene-plexus/workbench/actions/runs/37148691556).
The agent catalogue commit is also green:
[run 37148755622](https://github.com/eugene-plexus/agent/actions/runs/37148755622).

## Remaining scope

**Update 2026-10-03:** C5b is now built and pinned, with owner-only local
processes; see [its acceptance record](c5-local-tools-run.md). The paragraph
below records the scope remaining at the end of C5a.

C5b: local stdio processes under the app's account, process provisioning,
and per-person access. Then folder grants/filesystem tools, dedicated media
screens, local media engine admission, answer versions and the working
animation. OAuth to MCP servers, MCP resources/prompts, and non-text tool
results are not implemented in C5a. No live install was changed by this run.
