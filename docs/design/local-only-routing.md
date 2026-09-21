# Local-only routing

A6 adds `limits.localOnly` to client keys. Enable **Local-only inference**
under Home → Use from apps when creating a key, or edit an existing key's
limits. The setting is shared by the active key authority, like model scope
and request limits. Legacy keys remain unrestricted until edited. Update all
components before relying on this policy; older drivers are ineligible.

The gateway must satisfy both model permissions and locality. Aliases do not
authorize their cloud fallbacks. Local replicas remain eligible across nodes;
"local" means inside the configured installation's trust boundary, not "on
the gateway's own computer." Operator requests retain their existing access.
Request bodies cannot relax a key's policy.

## Classification

- A driver resolving a supervised local runtime classifies that engine local.
- Named cloud APIs and subscription CLIs remain external, including CLIs whose
  processes run on a local machine.
- Custom HTTP, Ollama and LM Studio endpoints default to unknown. An operator
  can set **Endpoint trust** in the driver's Provider settings to **Confirmed
  local**, **External / cloud**, or **Unknown**. A loopback proxy can forward to
  cloud, so a URL or provider label alone is insufficient.
- Classification belongs to the active engine and changes when the driver is
  restarted with its new configuration. Saved settings do not relabel an old
  engine still serving requests. An unconstructed/degraded engine is unknown.

`GET /v1/info` reports `locality` and `localOnlyEnforced`. Both an explicit local
classification and enforcement support are required. Unknown/absent metadata
fails closed for a local-only key. Unrestricted keys can still use those
endpoints normally.

## Execution checks

Before selection or wake, a protected request re-reads eligible drivers' info
without supplying application content. It excludes external, unknown,
unreachable and non-enforcing drivers, then balances the remaining local
replicas. A changed runtime association cannot reuse stale wake facts.
Discovery filters the cached model list by the same eligibility rule; actual
execution always reconfirms. A changed key policy stops lease renewal.

The gateway also carries `localOnly: true` on each internal generation or
embedding request. Immediately before using its active engine, the driver
refuses an external/unknown engine with 403. This closes the race between a
metadata probe and an engine replacement. The policy field is never sent to
the upstream model API. Both chat APIs, streaming, tool-bearing requests,
images and embeddings use this boundary.

If nothing qualifies, the caller receives a local-only refusal. No prohibited
backend is woken or receives application content. Existing response diagnostics
identify the serving model, driver and node for successful requests.

## Trust boundary and limits

This is routing enforcement among trusted, updated Eugene components. An
operator's custom-endpoint declaration must be accurate: the driver cannot
inspect a remote server to prove it never forwards traffic. It does not sandbox
a malicious backend, administrator, DNS configuration or host. Where stronger
isolation is required, restrict the inference hosts' outbound network access
to the approved local services as well.

Driver discovery can perform its existing model/capability probes, including
the fixed one-character embedding probe. These contain no application content.
The acceptance fixture distinguishes these from protected application requests.
No external inference service or live model is required for this acceptance.
