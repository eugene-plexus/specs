<!-- Thanks for contributing to Eugene Plexus / specs! -->

## Summary

<!-- One or two sentences describing what changes and why. -->

## Type of change

- [ ] New endpoint or schema
- [ ] Refinement to existing schema (tightening types, fixing descriptions, etc.)
- [ ] **Breaking change** (consumer repos must update)
- [ ] New OpenAPI document for a new component
- [ ] Tooling / CI / docs

## Checklist

- [ ] Every commit is signed off (`git commit -s`, or `git rebase --signoff main` for an existing branch). CI will block PRs without DCO sign-offs — see [CONTRIBUTING.md](../CONTRIBUTING.md).
- [ ] Every modified spec validates: `python -m openapi_spec_validator openapi/<spec>.yaml`
- [ ] Redocly lint passes: `npx --yes @redocly/cli@2.30.4 lint openapi/<spec>.yaml`
- [ ] If this is a breaking change, the document's `info.version` is bumped and the breaking change is described in the summary above.
- [ ] For contract changes, affected consumers and codegen input-list changes are identified (agent, control, gateway, inference-driver, library, ui).
- [ ] For docs-only changes, local links and current-state claims are checked; contract validation items above may be marked not applicable.
