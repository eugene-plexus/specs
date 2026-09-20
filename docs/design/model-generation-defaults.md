# R8: model profile generation defaults

The gateway must honor the model profile when a caller omits generation
parameters. Inspection for R8 found that the roadmap's premise confused
`RecommendedSampling` (metadata reported from GGUF) with `ModelProfile`:
persisted profiles only held launch settings. Add optional `maxTokens`,
`temperature`, and `topP` to profile create/replace/read and the profile editor.
Author recommendations remain informational and are never silently adopted.

Use the model's **default profile**, not the launch template last copied into
a runtime. Existing runtimes hold no profile reference. Marking a profile
default applies its generation defaults to subsequent requests, after cache
expiry, while launch flags retain their existing copy-at-launch behavior.
Changing one does not restart a model or change its context allocation.

For each actual backend attempt, resolve its runtime by node and driver,
reverse-lookup `Runtime.modelPath` through Library `GET /v1/models?path=...`,
then read `GET /v1/models/{id}/profiles`. Never match by basename or alias, and
never use the Windows local-copy path as a Library path. Replica defaults
share a cache only when their Library model paths are identical. Cross-model
fallback uses the fallback model's defaults. External backends without a
managed runtime retain gateway defaults.

Precedence, independently for each parameter: caller, default profile, gateway
configuration. Explicit zero temperature/top-p and zero seed are preserved.
The gateway has defaults for maximum output tokens and temperature, but does
not invent a top-p value. Tools, stop sequences, seeds, and engine flags do not
gain profile defaults in this slice. Both OpenAI and Anthropic, streamed and
nonstreamed, use the same resolver; Anthropic's required output-token limit
remains the caller's value. Embeddings are unchanged.

The gateway reads through its own agent's Library proxy with its service
credential. No new operator-entered Library URL or signing private key is
needed. Cache successful results (including no model/no default) for
`profileCacheSeconds`, default 30. On transport/status/validation failures,
reuse last-known defaults for at most `profileMaxStaleSeconds`, default 300,
after their fresh lifetime; beyond that use gateway defaults. Log failures
and whether stale or gateway defaults were chosen. Retry failed reads after
five seconds, not on every inference request. A successful deletion clears
the cache immediately at the next refresh. Cache size is bounded and
concurrent reads of one path share a lookup. Configuration is exposed through
the existing schema-driven gateway editor, with zero respected.

Acceptance covers saved profile persistence, default changes and deletion,
request precedence, zeroes, no-profile/cloud paths, alias/replica isolation,
fallback models, both API protocols and streaming, outage/staleness/recovery,
concurrent lookups, and editing defaults through the UI. Run an isolated
gateway/Library/agent-proxy/driver HTTP path and deliberately break the
load-bearing rules to prove the checks detect regressions. Do not edit the
operator's running model or saved profiles to perform acceptance.
