# Windows upgrade refusal before elevation

2026-09-20: updating the existing 5090 node with the default installer produced
only "the elevated install exited with code 1; see its window for why". The
elevated window had closed. Read-only `install.ps1 -Detect` found a scheduled
task pointing to the existing `%LOCALAPPDATA%\EugenePlexus` install, while the
new service default targets `%ProgramData%\EugenePlexus`. The ownership guard
correctly refuses that change without `-Migrate`, but ran after elevation.

Ownership and service-conversion checks now run before elevation, so the caller
sees the existing prefix and the `-NoService` / `-Migrate` choices. The elevated
invocation repeats the checks using its own context. No migration or install
mutation is performed by the preflight.

`scripts/install-preflight.Tests.ps1` executes the real installer through its
read-only prefix, mocks OS discovery, and forbids elevation. Before the fix,
two checks failed because the elevation refusal hid the migration explanation;
afterward all four pass. Coverage includes different-prefix migration,
in-place conversion, an ordinary per-user update, and read-only detection.
Windows CI runs this suite. The local installed node was not modified during
these checks.
