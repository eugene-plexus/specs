# Workbench installation under the NAS container user — 2026-10-04

Troy updated his nodes, removed Workbench from Amish_Station, and tried installing
it on the NAS. Installation failed before creating the Python environment:
`Failed to initialize cache at /.cache/uv` with permission denied.

AppInstaller already placed its managed Python interpreters on the app volume,
but inherited uv's cache selection. Unraid's uid 99 has no passwd entry or
writable home. Agent `4313920552d59907251b4c8b4cdf3dd2a32e3f76` now gives both
`uv venv` and `uv pip install` an explicit cache under the app root:
`/data/apps/.cache/uv` in the image. Copied package files and the existing
credential boundary remain enforced. No root user, filesystem permission
change, dependency change, or new Workbench package is required.

The real app-install regression first failed at cache initialization with the
previous code, then passed with the fix on Windows and Linux. It supplies an
unusable inherited cache and uses `HOME=/` on Linux, installs a real fixture,
checks its running process and credential boundary, and uninstalls it. The
Windows app/account/helper suite passed 66 tests after the listener regression
below was added. Ruff and type checks passed.

The container publication gate now goes beyond merely starting Eugene as the
NAS user. Check 29 runs `container-workbench-acceptance.py` inside the disposable
uid-99 container, with `HOME=/` and a data volume owned by 99:100. It enrolls the
node, installs the pinned Workbench through the real Apps API, verifies that the
cache is on `/data`, completes Eugene sign-in, restarts Workbench and checks the
saved session. The containing harness checks Workbench's page through a published
TCP port from outside the container. Publication requires this check to pass.

The first container run confirmed installation, sign-in and restart, but caught
a second defect: app binding only widened when the node advertised a LAN
address. It ignored the container's explicit `0.0.0.0` agent listener and left
Workbench on loopback. Agent `0b110afc993c8bc306c55ff21cb578e091ca204f`, the final
release pin, also honors that configured listener when choosing the app bind
address. Regression tests cover loopback and wildcard listeners and prove that
the internal node file helper stays on loopback in both cases. The failed
container candidate was not published.

The release changes only the agent component pin. Workbench, console, control
and the other component packages retain the preceding node-helper release's
pins. Both generated installers use the same manifest; the container is tested
before the workflow publishes its `edge` and commit-specific tags.

The [container guide](../deployment/container.md#hosting-workbench-on-the-nas)
also explains the required Workbench port mapping. The three core Eugene ports
alone do not publish an app's separate listener.
