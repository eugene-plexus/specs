# Engine overview layout

Implemented 2026-10-15 after Troy's screenshot of the Backends overview showed
engine acquisition controls, long Kev setup instructions and model monitoring
competing for space. This changes presentation only; the existing APIs, engine
capability decisions and machine targeting remain in use.

Each machine starts with its name and hardware budget, then a three-column
model/backend, status and controls layout. The model name leads; engine and
profile sit beneath it. A runtime name that repeats the model is omitted. Status,
loading/copy progress and failure reasons remain visible. Traffic sits with
status; start/stop/restart/remove, logs and autostart sit together. Narrow screens
stack the columns and wrap long names and confirmation messages.

Engine management follows the models in a collapsed Engines section, with
installed/not-installed counts. Expanding it shows separate engine cards with
version, build selection and the existing install/update/uninstall actions.
Manual commands and lengthy setup reasons are behind Setup details. Strata's
usage notes have their own disclosure; its existing model-switch controls remain.
In-progress or failed installations automatically open engine management. Failed
inventory reads show an error while retaining the model controls.

Healthy connection diagnostics are behind Connection details. Connection
warnings and partial-view errors remain visible. Missing-engine messages point
to Engines below. Nothing here starts an install or changes a model merely by
opening a disclosure.

[Acceptance and screenshots](../acceptance/engine-overview-run.md) cover the built
page in Chrome, small screens, themes, controls and temporary-copy mutations.
