# Contributing to Eugene Plexus `specs`

Thanks for your interest. This repo holds the OpenAPI 3.1 schemas that every Eugene Plexus component depends on, so changes here ripple everywhere — please read this before opening a PR.

## Developer Certificate of Origin (DCO)

Eugene Plexus uses the [Developer Certificate of Origin](https://developercertificate.org/) instead of a CLA. By signing off on a commit, you certify that you wrote the change, or otherwise have the right to submit it under the project's open-source license.

**Every commit must be signed off.** Use `git commit -s` (or `git commit --signoff`):

```bash
git commit -s -m "Add a gateway schema field"
```

This appends a line to your commit message:

```
Signed-off-by: Your Name <your.email@example.com>
```

The name and email must match your `git config user.name` and `git config user.email`. Anonymous or pseudonymous sign-offs are not accepted.

If you forgot to sign off, fix the most recent commit with:

```bash
git commit --amend -s --no-edit
```

…or for a whole branch:

```bash
git rebase --signoff main
```

CI will block PRs whose commits are missing sign-offs.

### Full DCO text

```
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.


Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```

## Scope of changes

This repo owns shared contracts, architecture/design documentation, cross-component
release notes and acceptance records/scripts. Application implementation lives in
the six active consumers: `agent`, `control`, `gateway`, `inference-driver`,
`library`, and `ui`.

A PR here should be one of:

- **Add a new endpoint or schema** to an existing OpenAPI document.
- **Refine a schema** — tighten types, add constraints, fix descriptions.
- **Add a new component-level OpenAPI document** for a new component.
- **Bump the document version** to reflect a breaking change.
- **Maintain documentation and acceptance tooling** for cross-component behavior.

Out of scope: application implementation and generated consumer models. Historical
consciousness and training components are not targets for new contracts.

## Style

- **OpenAPI 3.1** — not 3.0. We use JSON Schema 2020-12 features.
- **YAML, two-space indent**, no tabs.
- **kebab-case** for path segments and filenames; **camelCase** for query and JSON body fields; **PascalCase** for schema names. The gateway's OpenAI-compatible `/v1/chat/completions` and `/v1/models` deliberately use OpenAI's snake_case and error envelope.
- Every schema and operation has a `description`. Other contributors will read these without context.
- Prefer `$ref` to shared components in `openapi/components/common.yaml` over duplicating types across documents.
- Use `oneOf` + `discriminator` for tagged unions, not raw `anyOf`.

## Breaking changes

Pre-1.0, breaking changes are allowed but require:

1. A migration note in [CHANGELOG.md](CHANGELOG.md).
2. A bump to the document's `info.version`.
3. A heads-up in the issue tracker so consumer repos can plan their update.

After 1.0, breaking changes require a major version bump.

## Consumer Updates

Publish the specs commit first. Each affected consumer then updates `SPECS_REF`
and commits regenerated output with that pin. There are **six** consumers,
including the TypeScript UI. No re-pin is needed for documentation-only changes.

- Audit each consumer's codegen input list: a document rename or addition must
    move with a pin at which the path exists.
- Generate both revisions and compare output; counting `$ref`s does not establish
    whether a shared-schema change affects generated models.
- `control` generates from both `control.yaml` and `agent.yaml`; the UI generates
    all five top-level API documents.
- Keep `SPECS_REF` plain UTF-8 without a BOM. Windows PowerShell 5.1's
    `Set-Content -Encoding utf8` adds a BOM and breaks archive URLs.

External contributions use PRs. The solo-maintainer workflow lands signed-off
commits directly on `main`, with CI checked after pushing. Do not force-push or
create branches as a side effect of a routine documentation update.

## Validation

Before opening a PR, validate the spec locally:

```bash
# Python — using openapi-spec-validator
pip install openapi-spec-validator==0.8.5
python -m openapi_spec_validator openapi/gateway.yaml

# Also run Redocly with the CI version
npx --yes @redocly/cli@2.30.4 lint openapi/gateway.yaml openapi/inference-driver.yaml openapi/library.yaml openapi/agent.yaml openapi/control.yaml
```

CI runs both validators and a secret scan on pushes and PRs; PRs also check DCO
sign-offs. Documentation-only changes should check links and whitespace without
regenerating consumers. Never stage secret-bearing runtime configs.

## Reporting issues

File issues at [github.com/eugene-plexus/specs/issues](https://github.com/eugene-plexus/specs/issues). Useful issues include:

- Concrete schema mismatches between repos.
- Ambiguous or under-specified endpoints causing implementation drift.
- Proposals for new endpoints, with a use case described.

Cross-component architecture questions belong in [specs issues](https://github.com/eugene-plexus/specs/issues), next to the design documents. Component-specific bugs belong in the owning repo.
