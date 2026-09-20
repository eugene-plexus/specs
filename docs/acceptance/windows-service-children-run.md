# Windows service: companion launcher and engine migration

2026-09-20, following the successful host-loader repair. The live LocalSystem
agent answered health checks, but its companion driver repeatedly exited 2.
Its log showed `venv/Scripts/pythonservice.exe -m eugene_plexus_inference_driver`:
the service host embeds Python, but does not accept Python's module arguments.
Agent `61a90c1` selects `venv/Scripts/python.exe` for a service-hosted agent,
and fails explicitly if that interpreter is absent. Console agents keep their
existing interpreter.

The managed llama.cpp builds were still present under the operator's
`~/.eugene-plexus/engines`, outside the old install prefix. The service's
engine store is `ProgramData/EugenePlexus/engines`. `-Migrate` now copies completed
managed builds into it, using staging directories so an interrupted copy is
never published as installed. Existing destination builds and source files are
preserved. The source is captured before elevation and can be selected with
`-MigrateEngineRoot`; recovery also works after an earlier migration already
registered the service at its new prefix.

The NAS itself was healthy. Its component union took 5.19 seconds because
Amish_Station did not answer inbound requests; discovery's five-second read
deadline expired just before that useful partial response. Discovery now allows
ten seconds for a read, retaining the two-second connect deadline, and names
empty HTTP exceptions such as `ReadTimeout`. This accommodates the root's
default five-second node timeout, not every possible custom timeout.

Live network repair used the agent's reach API with its existing advertised
address and `allowFirewall: true`, without restarting the agent. Old Windows
application rules covered only the per-user interpreter. The app added its
Private/Domain TCP allowance for ports 8079 and 8091. Afterwards the root's
component union answered in 0.03 seconds with no unreachable nodes, its registry
reported Amish_Station reachable, and the worker's control proxy answered 200.
No enrollment or signing key was replaced.

Validation:

- 59 targeted supervisor/discovery tests passed on Windows Python 3.14.
- Full Python 3.14 agent suite: 923 passed, four expected skips; lint and
  source type checking passed.
- 65 supervisor/discovery/service tests passed on Windows Python 3.12,
  with two expected platform/dependency skips.
- Deliberately reverting the launcher selection and five-second discovery
  deadline failed their respective new tests. The latter uses a real HTTP
  socket; mock transports would not enforce the read deadline.
- Ten PowerShell installer tests passed, including engine copy, repeat-run
  preservation, and incomplete-build rejection. Omitting the copy in an
  isolated installer made the engine-recovery test fail.
- The disposable LocalSystem CI smoke now also requires an actual companion
  driver to answer health checks. It launches no engine and does not use live
  installation state.

The live service still needs the updated installer to receive the launcher
repair and copy its legacy engines. Model startup and inference must be checked
after that update; agent health alone does not establish either.
