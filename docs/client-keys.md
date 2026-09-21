# Client keys

This describes development builds after A3. The published `v0.1.0-alpha.1`
has its earlier, node-local revocation behavior.

Use **Home → Use it from your apps** to make a named key for each application.
Copy it when it appears: the token is shown once and is not stored for retrieval.
A key lasts one year by default and grants inference access, not operator access.
Use **Turn off** beside its record to revoke it.

On an enrolled install, any node's console manages the same registry at the active
control root. A key works at every gateway, and revocation applies to all of them.
An unenrolled machine manages its own standalone registry; the console names this
scope. Per-model permissions, quotas and attributable usage are planned for A5.

## Revocation and outages

With the default settings, gateways refresh policy every 15 seconds. Allow
20 seconds for a healthy install to notice a revocation. Already-running requests
are not cancelled retroactively.

During a brief agent or control-root outage, gateways can use their last policy.
Once it is 60 seconds old, client requests fail with **503 policy unavailable**;
allow up to five additional seconds for clock tolerance. Restarting a gateway
does not make an old policy fresh. Known revoked keys stay refused across restarts.
The gateway needs a fresh policy when its cache is missing, corrupt or belongs to
a different verification key or agent address.

Revoked and unregistered keys return **401** on the OpenAI-compatible paths and
**403** on Anthropic Messages. Invalid or expired tokens fail authentication as
before. A 503 means restore connectivity to the agent and active control root,
or unlock the root if it is locked; it is not a reason to mint replacement keys.
Operator sign-in and management access remain available for repair.

## Updating an existing install

Update control components, including any standbys, then every agent and gateway.
An older standby cannot replay the new registry operations. An older gateway
does not enforce the new outage bound. Agents automatically register existing
unexpired key records, including revocations, with the root using their enrolled
node identities. Existing tokens do not change after a successful import.

The console shows migration status and identifies each migrated record's source
node. Use **Refresh key status** to check progress. Keys from a node that is offline
or has not been updated cannot be used until its records have been imported.

Keep `client_keys.json` beside the originating agent's configuration. If that
file is damaged or missing, restore it from a backup and restart the agent so it
can import the records, or issue replacement keys. A node that predates node
signing identities needs re-enrollment before it can migrate. Never delete the
file as a repair: it includes revocation records as well as active keys.

For the policy format, replication rules and advanced startup settings, see the
[A3 design](design/install-wide-client-keys.md). A3 requires no live model or GPU
benchmark to validate; its [acceptance run](acceptance/a3-client-keys-run.md) uses
disposable component processes.
