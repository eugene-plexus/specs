# Client keys

This describes development builds through A6. The published `v0.1.0-alpha.1`
has its earlier, node-local revocation behavior.

Use **Home → Use it from your apps** to make a named key for each application.
Copy it when it appears: the token is shown once and is not stored for retrieval.
A key lasts one year by default and grants inference access, not operator access.
Use **Turn off** beside its record to revoke it.

On an enrolled install, any node's console manages the same registry at the active
control root. A key works at every gateway, and revocation applies to all of them.
An unenrolled machine manages its own standalone registry; the console names this
scope. Limits apply across every gateway in that scope.

## Permissions and limits

New keys default to **all models, two concurrent requests and 60 requests per
rolling minute**. Set these in the new-key form, or use **Edit limits** beside
an existing key. Saving permissions keeps the same token.

Uncheck **Allow all models** to enter exact model IDs, one per line. An empty
list denies every model. For a routing alias, allow both its name and each target
it may use. Excluded targets are removed before selection, wake and fallback;
model discovery reveals only allowed models and their permitted backends.
“All models” includes future additions; a selected list does not.

Enable **Local-only inference** to exclude cloud and unconfirmed endpoints from
every alias, fallback and wake decision. Models Eugene runs locally qualify
automatically. For another local server, confirm **Endpoint trust** in that
driver's Provider settings and restart the driver. Cloud subscription CLIs
remain external. Update all components before enabling this restriction;
older drivers cannot serve protected requests. See the
[local-only routing guide](design/local-only-routing.md) for the trust boundary
and how stale routing/configuration is handled.

Concurrency includes waiting for a model to wake and the whole response stream.
Accepted requests count toward the rolling-minute limit even when they fail or
are cancelled. Internal backend fallback counts as one request; an application's
new HTTP retry is another request. Refused admission does not join a queue or
consume another rate allowance. HTTP **429** includes **Retry-After**. Wait, cancel
an active request, or edit the key's limits; changing gateways adds no allowance.

Existing keys without a limits record remain **Legacy / unrestricted**: all models
and no per-key concurrency/rate limit. They are visibly labeled. Choose **Set
limits** to constrain one without replacing it. Re-importing its old record does
not undo the operator's limits or revocation.

## Revocation and outages

New inference requests and model discovery need the current admission authority:
the active control root through the local agent, or the standalone agent. If it
cannot answer, client requests receive **503** immediately after the bounded
coordination attempt. Cached authentication policy cannot provide a separate
allowance. Restore connectivity or unlock the root; do not mint replacement keys.
Operator sign-in and management remain available for repair.

An active request holds a renewable 30-second reservation. Disconnect, timeout,
failed wake and completion release it; a dead gateway's reservation expires.
Revocation or a permissions change stops active work at its next renewal. A
renewal failure also cancels upstream work before the reservation can expire.
If streaming has started, the client receives a terminal error event when the
connection permits it. Restarting the authority preserves allowance; time while
it was offline conservatively pauses the rate/lease clock. After recovery it may
take up to one lease/minute window to reuse capacity. UTC changes do not reset it.

Revoked and unregistered keys return **401** on OpenAI-compatible paths and
**403** on Anthropic Messages. Invalid or expired tokens fail authentication.
Model permission refusals return **403**. Limits do not apply to operator or
component credentials: keep those out of ordinary applications.

The existing single-active-control-root rule still applies. Fence the previous
root before promoting a standby; deliberately running two active roots is not a
supported way to distribute admission.

## Attributable usage

**Metrics ? Usage by client key** shows requests, successes, failures, backend
attempts and reported token totals for this gateway. Recent requests identify
the authenticated key. The ID is stable; the name comes from the registry (or the
verified token if admission fails before the registry answers). A caller's `user`
annotation cannot change attribution. Prompts, images and credentials are not
stored to obtain these totals.

Totals cover the selected window within retained raw request history. Expired
history and dropped measurements are called out. Failed or retried backend
attempts may consume tokens without reporting them, so **Incomplete usage** marks
those requests. Token totals count known reports only. These are operational
measurements, not billing or an install-wide aggregate; inspect each gateway when
clients use more than one. Historical rows from before A5 remain unattributed.

## Updating an existing install

Update control components, including any standbys, then every agent and gateway.
An older standby cannot replay the new registry/admission operations. An older
gateway does not enforce A5 limits. Update the whole install before relying on
these controls. Agents automatically register existing
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
[A3 registry design](design/install-wide-client-keys.md) and
[A5 admission design](design/scoped-client-access.md). The
[A5 acceptance run](acceptance/a5-scoped-keys-run.md) uses disposable processes
and counting HTTP backends; no live model or GPU benchmark is needed.
