# Contributing to Eugene Plexus `specs`

Thanks for your interest. This repo holds the OpenAPI 3.1 schemas that every Eugene Plexus component depends on, so changes here ripple everywhere — please read this before opening a PR.

## Developer Certificate of Origin (DCO)

Eugene Plexus uses the [Developer Certificate of Origin](https://developercertificate.org/) instead of a CLA. By signing off on a commit, you certify that you wrote the change, or otherwise have the right to submit it under the project's open-source license.

**Every commit must be signed off.** Use `git commit -s` (or `git commit --signoff`):

```bash
git commit -s -m "Add foo to orchestrator schema"
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

This repo is *only* schemas. Implementation lives in the consumer repos (`orchestrator`, `hemisphere-driver`, `memory`, `ui`, …).

A PR here should be one of:

- **Add a new endpoint or schema** to an existing OpenAPI document.
- **Refine a schema** — tighten types, add constraints, fix descriptions.
- **Add a new component-level OpenAPI document** for a new component.
- **Bump the document version** to reflect a breaking change.

Out of scope: implementation code, tests against running services, deployment configs.

## Style

- **OpenAPI 3.1** — not 3.0. We use JSON Schema 2020-12 features.
- **YAML, two-space indent**, no tabs.
- **kebab-case** for path segments and filenames; **camelCase** for query and JSON body fields; **PascalCase** for schema names.
- Every schema and operation has a `description`. Other contributors will read these without context.
- Prefer `$ref` to shared components in `openapi/components/common.yaml` over duplicating types across documents.
- Use `oneOf` + `discriminator` for tagged unions, not raw `anyOf`.

## Breaking changes

Pre-1.0, breaking changes are allowed but require:

1. A note in the changelog (or PR description, until we have a CHANGELOG file).
2. A bump to the document's `info.version`.
3. A heads-up in the issue tracker so consumer repos can plan their update.

After 1.0, breaking changes require a major version bump.

## Validation

Before opening a PR, validate the spec locally:

```bash
# Python — using openapi-spec-validator
pip install openapi-spec-validator
openapi-spec-validator openapi/orchestrator.yaml

# Or — using redocly CLI
npx @redocly/cli@latest lint openapi/orchestrator.yaml
```

CI will run the same validators on every PR.

## Reporting issues

File issues at [github.com/eugene-plexus/specs/issues](https://github.com/eugene-plexus/specs/issues). Useful issues include:

- Concrete schema mismatches between repos.
- Ambiguous or under-specified endpoints causing implementation drift.
- Proposals for new endpoints, with a use case described.

For broader architectural questions about Eugene Plexus, file the issue on the [orchestrator repo](https://github.com/eugene-plexus/orchestrator) instead.
