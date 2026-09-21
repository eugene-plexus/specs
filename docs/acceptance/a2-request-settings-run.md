# A2 request settings and compatibility acceptance

Run date: 2026-09-20 (America/Chicago). Uses disposable loopback processes and
fixture HTTP backends; no live NAS, Windows service, GPU workload or paid provider
was used. Troy can accumulate slices before updating the install.

## Regression and captured wire

Extended `scripts/r8-profile-acceptance.py`: real gateway and Library processes,
a persisted model profile containing `maxTokens: 2048`, authenticated HTTP
requests, and fixture agent/driver endpoints that capture each forwarded body.
The fixture's two drivers advertise different models, exercising a configured
cross-model fallback after the first driver returns 503.

Ran the same instrument with the original gateway source
`aa24529c2b0f44f0e314af361aab5ff7d17c9884` in an isolated worktree. It fails the
first `max_completion_tokens: 25` request with this captured driver payload:

```json
{"messages":[{"role":"user","content":"hi"}],"maxTokens":2048,"temperature":0.0,"topP":0.2}
```

The updated gateway passes on Windows and WSL/Linux:

| Public limit | Response mode | Direct driver captures | Cross-model attempt captures |
| --- | --- | --- | --- |
| `max_completion_tokens: 25` | Ordinary | 25 | 25, 25 |
| `max_completion_tokens: 25` | Streaming | 25 | 25, 25 |
| `max_tokens: 25` | Ordinary | 25 | 25, 25 |
| `max_tokens: 25` | Streaming | 25 | 25, 25 |

Every capture also contains `callerSettings: ["maxTokens"]`, preserving explicit
intent across fallback. Additional HTTP checks preserve a strict output JSON
Schema on both paths, and reject conflicting limits, a boolean limit and an
unsupported reasoning setting without any driver call or echoed prompt text.
The existing R8 checks still pass: caller zeroes, profile edits, bounded stale
cache, outage/default fallback, recovery and profile deletion.

Local logs are `%TEMP%/ep-a2-original-failure.log`, `ep-a2-http-windows.log` and
`ep-a2-http-linux.log`. The CI workflow runs the same disposable HTTP instrument
on Windows and Linux against the installer's exact consumer pins.

## Component verification

- Gateway: **455 tests pass** on Windows and Linux. A2 adds 56 route/wire checks,
  including equal/conflicting/null/invalid limits, safe errors, defaults and
  fallback, unknown nested properties, metadata, stop strings, structured output,
  stream usage and Anthropic compatibility warnings. Disconnect tests still pass.
- Inference driver: **456 pass, 3 live-provider/CLI checks skipped** on both OSes.
  Explicit unsupported constraints fail before starting a CLI or making an HTTP
  request. Captured upstream payloads preserve `response_format.json_schema.schema`
  rather than the Python attribute name `schema_`, in both response modes.
- UI: **756 tests pass**, with lint, formatting, TypeScript and production static
  build. Six Chrome acceptance scenarios pass against the packaged assets, with
  six intended submissions and no browser errors. UI source behavior is unchanged;
  generated API types and the distribution are refreshed.
- All **184 static assets** match the staged build, distribution checkout and
  built wheel. S10 installer isolation/bandwidth regressions pass.
- Python lint, formatting and type checks pass. OpenAPI validates; the existing
  contract and profile sabotage instruments still detect their deliberately
  broken implementations.

## Implementation and delivery

The [compatibility matrix](../api-compatibility.md) specifies the supported subset.
Both limit spellings normalize before defaults. Unsupported explicit controls
are refused by adapters that know they cannot honor them; inherited defaults
retain existing adapter behavior. Structured-output schema aliases are preserved
at both transport boundaries. Errors at public chat validation name the field,
without returning Pydantic input values or exception context.

The measured Claude Code hints remain a disclosed exception: `thinking`, cache
hints and `context_management` are accepted without enforcement, and named in
`x-eugene-plexus-ignored-settings` on successful ordinary and streaming responses.
`top_k` and unknown top-level Anthropic settings are now refused. This preserves
the previously captured Claude Code request shapes; it does not claim native
Anthropic thinking budgets or context editing.

| Component | Commit |
| --- | --- |
| Contract | `85b9884ed0b33993181cf7285e8b39cfbf53818d` |
| Gateway | `9f56fbb4ad4563bbe8e1092c93c52dcc9b552382` |
| Inference driver | `aa73b1e04db84592a2cf31124ebfacc48ca5a63f` |
| Agent | `440f6ba9943580d7417a029db420978f09b0fa04` |
| Control | `fda476b2624a7a2a77ab1b5f83fab090396400a5` |
| Library | `6c0f1585718f52e32a8355977c2f9fed30025afe` |
| UI source | `b111cda1639b95207c0c0d4f29e1dd712add553a` |
| UI distribution | `f99e841b80f1b0ea478606b3cf2e7a10a8dc206d` |

Both development installers pin these consumers. No versioned release or alpha
asset is replaced. Update gateway and driver together when adopting these slices;
older drivers do not understand caller-setting provenance.

Delivery verification runs: [gateway CI](https://github.com/eugene-plexus/gateway/actions/runs/35554449329),
[driver CI](https://github.com/eugene-plexus/inference-driver/actions/runs/35554451684),
[UI CI](https://github.com/eugene-plexus/ui/actions/runs/35554472703),
[pinned integration CI](https://github.com/eugene-plexus/specs/actions/runs/35554616645),
and [container acceptance/build](https://github.com/eugene-plexus/specs/actions/runs/35554616764).
The last two use installer commit `1f654f4fffbb463d3851d27a698a169acbf074be`.

This establishes forwarding and refusal behavior, not backend enforcement of a
universal visible/reasoning-token budget. Live provider/CLI behavior, newer client
versions, images (A4), friend sessions and physical platform obligations remain
outside this acceptance.
