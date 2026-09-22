# Playground action icons and response times

Implemented 2026-09-22: UI `1f38bb0`, packaged UI `1d72fb2`.
Both development installers pin the package. Published alpha assets stay unchanged.

Message actions use pencil, copy and regenerate icons with accessible names and
descriptive tooltips. Clipboard success/failure remains visible and announced.
Hovering an assistant response shows its generation date and time in the browser's
locale/timezone. This is the browser time when the first part of the response
arrived, not a server clock or the completion time. It is retained for partial
responses and survives reloads and Home/Playground navigation. A regenerated
response gets a new time. Older messages without a recorded time say so.

Timestamp metadata is stored with the browser transcript and removed from both
streaming and non-streaming model requests. No wire contract changed.

Verification:

- Lint, typecheck, formatting and production build passed.
- [UI CI](https://github.com/eugene-plexus/ui/actions/runs/35753606033) passed
  the full unit suite, lint/format/type checks, production build, Home browser
  acceptance, wheel packaging and code-generation freshness. The focused
  transcript/Playground/component run passed 38 checks, including timestamp
  persistence and exclusion from request bodies.
- All 195 tracked packaged static files match the tested production export by
  SHA-256; both development installers select that same package revision.
- Isolated Chrome against the production export, with controlled HTTP fixtures:
  icon controls, actual clipboard copy/confirmation, regenerate, new timestamp,
  reload persistence, editing and metadata-free request bodies passed. No page
  exceptions. This exercised the browser, not a live model or the owner's install.

Browser procedure and screenshot retained locally under
`%TEMP%/ep-playground-icons-check.mjs` and the UI checkout's
`test-results/playground-icons/desktop.png`. These are disposable verification
artifacts, not runtime dependencies.
