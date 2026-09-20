# Windows service migration: host loader and preserved errors

2026-09-20, following the 5090's first explicit `-Migrate` run. The original
generic elevation error hid a real service startup failure. Event IDs 7045 and
7040 show successful registration; 7000 and 7009 show startup failed at
13:01:03. The pywin32 postinstall log reports success. The node's copied state
and installed packages exist in ProgramData; the service is stopped.

An isolated copy of the installed service executable reproduced exit
`0xc0000135` with only System32 on PATH: the managed Python DLL was absent.
Adding that DLL exposed a second failure, `No module named 'servicemanager'`.
Moving the host to `venv/Scripts`, where Python finds the parent `pyvenv.cfg`,
resolved both. The probe named a nonexistent service and reached its expected
missing PythonClass registry-entry error; it never launched the real agent.

Agent `dba78df` stages the host, the loaded Python DLL, the stable-ABI
`python3.dll`, pywintypes and private
CRT dependencies in Scripts, and passes the host's explicit path to pywin32.
It supports an earlier install that moved the wheel's executable to the venv
root, and propagates pywin32's nonzero registration result. Both installers
pin that agent. The Windows installer no longer runs pywin32's global
postinstall inside a venv, consistent with the
[upstream installation guidance](https://github.com/mhammond/pywin32#installing-via-pip).
Service-local environment values supply config, port and managed directories
on the first start, independently of SCM's cached machine environment.

The elevated installer now writes a persistent transcript, prints its path
before launching, and replays the failure tail in the caller. Native failures
include their output and exit code. Parameters travel through a temporary
CLIXML file instead of shell argument splitting; false switches, spaces,
apostrophes and literal shell syntax survive. Parameter values are absent from
the encoded wrapper command/transcript header. Script and parameter files are
removed afterward; the log remains.

Checks: the real loader regression and registration tests pass on Windows
Python 3.12 and 3.14; eight installer tests pass. The full 3.12 agent suite
found one unrelated runtime-supervision timeout, reproduced on untouched
`c5ad280` in a separate checkout. Its failing test is
`test_late_ready_probe_cannot_belong_to_a_replacement`; it is not weakened here.

Windows CI runs the service tests and `scripts/windows-service-smoke.py`.
The first live CI run exposed the stable-ABI DLL dependency missing from the
initial loader repair: `_sodium` failed to import before the agent could open
its log. Windows service event capture identified it; the loader regression
was extended to import both PyNaCl and cryptography, reproduced that failure
locally, and passes after staging `python3.dll`. The complete Python 3.14
agent suite passed (919 tests, four platform skips).
The smoke check requires explicit `EP_SERVICE_SMOKE=1` and an already elevated
CI process, creates a uniquely named LocalSystem service and disposable venv,
checks HTTP health with only System32 on PATH, stops it through SCM, and removes
it. It starts no engines/components and never requests UAC.

The installed 5090 service itself still needs the corrected migration command
rerun by the operator. No local service start, re-enrollment, key rotation or
state deletion was performed during this repair.
