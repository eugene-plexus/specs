# Backup, restore and failed-update recovery

Use a **stopped-install checkpoint before updating**. The checkpoint pairs state
with the Python version, resolved packages and exact Eugene source revisions that
read it. Installing an older release over newer state is not rollback.

Checkpoints require an A7-capable agent (the quarantine guard introduced in
`253f612`); the helper refuses older installations. For the first upgrade from an
older build, keep a protected, complete cold copy of the stopped installation and
its state, including Python and the virtual environment. Restoring that old copy
requires its original absolute paths. After upgrading, create and rehearse the
portable checkpoint described below. Alpha.1 does not have this tooling or guard;
alpha.2 and A7-capable development builds do.

This is a manual recovery procedure. It never updates or starts another enrolled
node. Coordinate a maintenance window for the root and workers; a checkpoint
cannot include a key revocation or policy change made after it was taken.

## What the checkpoint contains

`scripts/recovery.py` writes format 1 checkpoints. Its authenticated, encrypted
manifest inventories each retained file by path, mode and SHA256. File contents
are encrypted with independent SecretBox nonces; the manifest authenticates their
complete digests, so truncation, reordering and substitution fail verification.
The encryption key is derived from a separately chosen backup password using
Argon2id. Keep that password separately; it is not recoverable from the backup.

| State | Treatment |
| --- | --- |
| Agent/component configuration, model profiles, Library folders and catalog | Retained, including unknown files so an added store is not silently omitted |
| `node.yaml`, trust-root snapshot and complete replication log | Retained; includes private identities, epochs, signing and recovery keys |
| Provider/file-server secrets | Retained in their existing envelopes inside the encrypted backup; verified unlock passphrases are also encrypted in the manifest |
| Client-key policies, revocations, admission accounting and gateway policy caches | Retained; revoked keys stay revoked at the checkpoint's point in time |
| `metrics.sqlite3` and related component stores | Retained; restored SQLite files pass integrity checks |
| Managed engine builds under the state directory | Retained, including build metadata, binaries and companion libraries |
| Model files | External assets: paths, sizes and SHA256; **not copied** |
| `venv`, `pythons`, `bin` | Reconstructed from exact Python/package versions and immutable Eugene archive URLs/hashes |
| `logs`, `.cache`, `__pycache__` | Expendable; excluded |
| OS Credential Manager/Keychain, service registration, firewall rules, mounts | Re-create on the replacement; not portable backup files |
| Active requests, in-memory cooldowns and operator logout sessions | Not restored; clients reconnect and operators sign in again |

This procedure supports the standard installer/container state layout: component
configurations, `control-state`, Library state and gateway databases live under the
agent configuration directory. Custom store paths supplied only through service
environment overrides must be consolidated there first; the backup cannot discover
another process's arbitrary environment. Record the service/container bootstrap
settings before stopping it.

The source must use the normal installed packages, not editable development
checkouts. Source revisions alone are insufficient because all current component
package versions are `0.1.0`. The tool requires immutable source URLs and locks
every resolved Python dependency. Reconstruction needs network access to Python,
PyPI and the recorded GitHub archives; this is not an offline distribution.
Restore on the same OS and architecture. Keep compatible OS/GPU drivers and engine
system libraries. A different platform is a migration, not this restore procedure.

Stop the agent **and its children** before backup. `--stopped` acknowledges that
operator step; it does not stop processes for you. The tool checks for changes
during copying, but cannot turn a running distributed installation into a
consistent snapshot. Do not allow another root or standby to keep writing.

Pass `--external PATH` for model/projector folders and custom engine bundles outside
the state directory. Runtime model paths and explicit binaries are discovered
automatically. Keep those assets separately at their recorded paths; restore
verifies their hashes. For an externally managed Python engine such as vLLM or
mlx-lm, preserve its environment and system dependencies separately. A backup of
Eugene does not reconstruct an arbitrary external engine environment. For MLX
that means the `~/eugene-mlx` virtual environment (or wherever `mlxBinary`
points) and any MLX model directories are rebuilt by you, not restored: recreate
the environment with the pinned install command from the engine's own install
notes, and re-download or re-copy the model directories to their recorded paths
before restarting the runtimes that declare them. Kev is the same: its checkout
and `.venv` (`~/eugene-kev`, or wherever `kevPython` points) are rebuilt from the
pinned commit, and a restored runtime also needs its checkpoint directory and the
base model Kev downloaded into the node's Hugging Face cache on first launch.
Restore the checkpoint to its recorded path; without the cached base model the
first start needs network access again, and a launch with `HF_HUB_OFFLINE=1`
fails. Consolidate any
component configuration stored outside the state directory before checkpointing;
the tool refuses that layout instead of omitting it.

## Windows worker

Download [scripts/recovery.py](../scripts/recovery.py) from the release or development revision
you are using. Keep a trusted copy outside the installation. The saved `recover.py`
is a convenience copy, not a signed executable: if backup storage was tampered
with, fetch the helper from trusted source control before entering its password.
Use an Administrator PowerShell for service stop
and later registration. Example paths below assume the service installation.

```powershell
$installRoot = 'C:\ProgramData\EugenePlexus'
$backupRoot = 'D:\EugeneBackups\before-update'
Stop-Service EugenePlexusAgent
& "$installRoot\venv\Scripts\python.exe" .\recovery.py backup `
  --root $installRoot --destination $backupRoot --stopped
```

The command prompts for a **backup encryption password** and each required
agent/control unlock passphrase. It verifies both passphrase hashes and local
encrypted envelopes before reporting success. A remembered OS credential alone
does not satisfy portable recovery. In unattended jobs, password-file arguments
are available; restrict their ACLs and never place their contents on command lines.

The backup directory grants access only to its creator, LocalSystem and local
Administrators. Copy the complete directory to protected backup storage. Preserve
access restrictions there; encryption also protects files if destination storage
does not preserve Windows ACLs. Test the restore before relying on the backup.

Run the normal update only after that checkpoint succeeds. If it fails after
stopping the old environment, leave it stopped. **Do not repair the old environment
in place while depending on it for rollback.** Reconstruct into a new directory:

```powershell
$replacement = 'C:\ProgramData\EugenePlexus-Recovered'
& "$installRoot\venv\Scripts\python.exe" "$backupRoot\recover.py" restore `
  --checkpoint $backupRoot --destination $replacement --uv "$installRoot\bin\uv.exe"
```

If the failed environment's Python no longer works, use a separate Python with
`pyyaml`, `pynacl` and `argon2-cffi` installed to run the saved `recover.py`.
It uses uv to acquire the exact recorded Python and dependencies. No old virtual
environment is copied or relocated: console scripts contain absolute paths.

Restore refuses existing destinations, wrong passwords, missing/changed assets,
unsupported formats and different OS/architecture. An interrupted reconstruction
leaves only the new destination quarantined; keep it for diagnosis and retry into
another empty location. Neither source state nor checkpoint is modified.

The replacement has `state\`, `venv\`, `pythons\`, `requirements.lock`, `recover.py` and private
`recovery.json`. **The latter contains recovered unlock material**; protect the
whole directory. Python's base interpreter is also inside the replacement, so
the service does not depend on the restoring operator's Python cache. The quarantine
prevents startup of the copied identity. Fence
the original from restarting, then activate:

```powershell
& "$replacement\venv\Scripts\python.exe" "$replacement\recover.py" activate `
  --destination $replacement --original-stopped
$env:EUGENE_PLEXUS_AGENT_CONFIG_FILE = "$replacement\state\agent.yaml"
$env:EUGENE_PLEXUS_AGENT_ENGINE_ROOT = "$replacement\state\engines"
& "$replacement\venv\Scripts\python.exe" -m eugene_plexus_agent --unattended
```

Activation validates the exact reconstructed environment and state, then relocates
local component configuration paths. It does not rewrite replicated state,
identities, URLs or external model paths. Sign in with the original passphrase;
check profiles, a previously revoked key, and an actual inference request. Close
the foreground process before registering the replacement as a service.

In an elevated shell, set the two bootstrap paths above in Machine environment
using `[Environment]::SetEnvironmentVariable(name, value, 'Machine')`,
then run the replacement Python's `-m eugene_plexus_agent.winservice update`
(or `install` if the failed update removed registration). Also update the service's
own bootstrap environment; Windows' service manager may retain old Machine values
until reboot. Keep the original bind port (8079 below is the default):

```powershell
$serviceKey = 'HKLM:\SYSTEM\CurrentControlSet\Services\EugenePlexusAgent'
$bootstrap = @(
  "EUGENE_PLEXUS_AGENT_CONFIG_FILE=$replacement\state\agent.yaml",
  "EUGENE_PLEXUS_AGENT_ENGINE_ROOT=$replacement\state\engines",
  'EUGENE_PLEXUS_AGENT_BIND_PORT=8079'
)
New-ItemProperty -LiteralPath $serviceKey -Name Environment -PropertyType MultiString `
  -Value $bootstrap -Force | Out-Null
Set-Service EugenePlexusAgent -StartupType Automatic
Start-Service EugenePlexusAgent
```

Preserve any other deliberate bootstrap overrides, including the original Library
default model folder when it was supplied through the service environment rather
than saved in configuration. Record those before updating. Recreate tray/desktop
shortcuts and any required service
permissions separately. Sign in once under the restored service so LocalSystem
can save its own unlock credential. Network share logins in configuration survive,
but share availability and Windows permissions still need checking.

## Container control plane

Keep the exact image digest and the Compose/Unraid settings (ports, mounts, uid,
secret paths and environment) beside the encrypted checkpoint in protected
storage. Pull/save that image before changing it. **Do not use `edge` as a rollback
identifier**, since it moves. Image rollback must also restore its matching `/data`.

Stop the original container. Run a disposable helper from the **recorded image**,
mounting the old data directory read-only and a separate backup directory writable.
Use its `/opt/eugene-plexus/venv/bin/python` to run `recovery.py backup --root /data
--destination /backups/checkpoint --stopped`. Mount all referenced external model
and engine assets read-only at their original container paths. Supply protected
passphrase files or an interactive terminal. uid 10001 must be able to read the
source and write the backup parent.

For a restore rehearsal, first reconstruct into a separate data volume using the
saved helper and uv. This step needs network access to download the recorded Python
and packages; publish no ports and leave the replacement quarantined. Do not start
the recovered agent during reconstruction. Then mount that replacement into a
container using **`--network none`**, with no published ports, for activation and
startup checks. Activate only while the original is stopped, or inside this
disconnected container. Run the agent with its
new `state/agent.yaml`, set the managed engine root to its restored `state/engines`,
and perform checks inside the container over loopback. A loopback listener alone
is **not** network isolation: an enrolled identity can make outbound announcements.

For production replacement, stop/fence the old container, use the same recorded
image and mounts, and point `EUGENE_PLEXUS_AGENT_CONFIG_FILE` at the restored
`state/agent.yaml`. Recreate the control passphrase secret mount when using
`passphrase_file`; OS keyring credentials do not move between containers. Log in
to both agent and control as needed. Start with the original network settings
only after ensuring that no second copy of this identity can advertise.

## Recovery limits and validation

After recovery verify authentication, profile settings, allowed model policy,
local-only policy, revoked-key refusal, engine readiness and an actual completion.
A successful HTTP health check alone is insufficient. The checkpoint predates
later usage and revocations: reconcile any newer security changes before admitting
clients. Restore all relevant nodes from a coordinated checkpoint or explicitly
reconcile their epochs/trust state; do not restore an older root beside newer active
writers and assume they agree.

Keep the old stopped directory until replacement checks pass. Never delete model
folders as part of cleanup. Automatic rollback, automatic service re-registration,
offline bundles and cross-platform migration are outside this procedure.
