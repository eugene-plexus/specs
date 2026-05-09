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
- [ ] Redocly lint passes: `npx @redocly/cli@latest lint openapi/<spec>.yaml`
- [ ] If this is a breaking change, the document's `info.version` is bumped and the breaking change is described in the summary above.
