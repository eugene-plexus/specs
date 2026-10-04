# Central Workbench and node folders — 2026-10-04

Troy approved central or personal Workbench hosting with one enrolled Eugene
node installation providing inference, file access, or both, and authorized an
Edge release so he can try it on his own machines.

## What ships

People → Files on your machines enables the bundled helper, registers existing
folders, and assigns each person read or text-write access. The owner also needs
an explicit folder grant. Workbench discovers those folders through Eugene,
selects them per chat, and asks for approval for each file operation. Node helpers
connect outbound; browsers do not need a route to the file-serving machine.

The Workbench core can run on Docker, macOS, or a per-user installation. File
helpers currently require a Windows system service or Linux system service with
Landlock ABI 3+. Folder OS permissions must be provisioned explicitly; registering
a folder does not change them. Existing Workbench-host folder grants remain valid.
The [setup guide](../design/node-file-helpers.md#using-it) covers these steps.

This release retains separate Workbench and administration origins. It does not
install a public HTTPS reverse proxy. There is no remote shell, binary editing,
delete, rename, or file synchronization feature.

## Evidence

- Control CI: [permissions, recovery, types and generated contracts](https://github.com/eugene-plexus/control/actions/runs/37223576281).
- Agent CI: [bundled worker, lifecycle, updates and types](https://github.com/eugene-plexus/agent/actions/runs/37223697396).
- Workbench CI: [Windows/Linux server tests, frontend and generated contracts](https://github.com/eugene-plexus/workbench/actions/runs/37223580513).
- Console CI: [People UI tests and production package](https://github.com/eugene-plexus/ui/actions/runs/37223583128).
- [C1 account isolation](https://github.com/eugene-plexus/specs/actions/runs/37223879733)
  passed on Windows and Linux with the candidate agent and control.
- [Node helper protocol and service acceptance](https://github.com/eugene-plexus/specs/actions/runs/37224076879)
  runs the published candidate packages on disposable Windows/Linux runners.

The protocol harness builds and installs the bundled worker into a clean
environment, uses real control enrollment and sign-in, and drives the actual
agent relay and file worker. It checks that file contents never enter replicated
state. Focused suites cover node replacement, cross-person denial, app and sign-in
revocation, cancellation, replay, expiry and independent worker containment.

The service harness installs Eugene as a real machine service, runs the C1
account probes and existing C5/C6 local tools, then enables node file support.
It provisions only a test folder's OS permissions, verifies the helper's service
identity, reads and edits through signed-in Workbench and per-call approvals,
rejects private paths and traversal, revokes a pending write, and verifies that
disabling file support stops its service. All machines are disposable runners;
Troy's live installations were not changed.

Release preparation corrected three acceptance assumptions: Windows Git checkout
line endings must be normalized when comparing the two safe-file source copies;
OpenAPI schema fragments are validated through their consuming documents; and
the core Workbench catalogue no longer requires local actions, while its local
tools still require actual OS account isolation. These changes do not relax file
permissions or skip the service boundary checks.

Both published UI archives were downloaded and checked for their built page,
source provenance in BUILD_INFO, and their own distribution commit stamp.
The dependency lock is unchanged: the helper uses the standard library and all
other runtime dependencies were already in the release.

## Release inputs

| Component | Commit |
| --- | --- |
| Control | `6f3686f87655b8eed18f198477f413b43f739fcc` |
| Agent and app catalogue | `c854b22b4a72afe55cd2062ee729e5fa86ca77b8` |
| Workbench source | `c08ca0af34f1bd7c8c5e4611921cdfbb9058db70` |
| Workbench distribution | `32aa0cd270d678b4478fa8857e2f38ebb2c80980` |
| Console source | `2240899e2579d6c458b308345081e2cab4c0755f` |
| Console distribution | `edd2c2044078cc5ca0053755020c7f190203765c` |

The release manifest and both generated installers pin these control, agent and
console builds. The agent catalogue pins the Workbench distribution. Edge's
native updater offers the release after its push workflows pass. The container
workflow builds, exercises Compose and recovery, then publishes the tested image
as `ghcr.io/eugene-plexus/control-plane:edge` and a commit-specific tag.

Update the control root and standbys, node agents and Workbench together. Update
an already installed Workbench from Apps so it receives the new folder support.
Stable release tags remain unchanged.
