# S10: download included, 2026-09-20

**Both automated runs pass the ten-minute target. S10 remains open for the
moderated sessions.** The [session guide and blank recording sheet](hobbyist-sessions.md)
are prepared; no participant results have been reported.

This supplements the [2026-09-16 seeded runs](hobbyist-run.md). It measures the
missing download path using the shipped S9 UI (`94d0ce3`, dist `5306208`) and
the component pins in this commit's installers. No UI/backend changes were
needed. The normal Windows service installation remains covered separately;
these runs use the new explicit disposable-install mode.

## Results

| Measurement | Windows | WSL2 Ubuntu 26.04 |
| --- | ---: | ---: |
| Installer start to first visible assistant text | **485.525 s (8m 5.5s)** | **480.546 s (8m 0.5s)** |
| Installer start to completed browser reply | 486.049 s | 481.133 s |
| Installer execution alone | 11.623 s | 8.987 s |
| Pointer clicks through first reply | **5** | **5** |
| Actual keydown events, including Tab navigation | 91 | 91 |
| Distinct configuration values typed | **1: passphrase** | **1: passphrase** |
| Filesystem paths typed | **0** | **0** |
| Home to connection details | **1 click** | **1 click** |
| Client key lifetime, verified from issued claims | **365 days** | **365 days** |
| Separate curl with Home's address, model and key | Nonempty answer | Nonempty answer |
| Browser page errors | 0 | 0 |
| Total downstream bytes through capped proxy | 5,425,749,805 | 5,439,257,884 |
| Proxy lifetime through reply, curl and teardown (monotonic) | 488.248 s | 483.412 s |

The five clicks are Continue, Finish, Download and run, the engine-install
confirmation, and Send. The passphrase is entered twice and counted as one
configuration value; the chat prompt is excluded from that configuration count
but included in the keystroke count. Tabs reach fields without pointer clicks.
The count does not include opening a terminal or pasting the installer command.

Browser answers were “Hello there, how are you doing?” on Windows and “Hello
there, friend, how are you?” on WSL. The curl answers were “Hello there, how are
you doing?” and “Hello there, how are you doing today?”, respectively. Both
browser streams contained actual assistant content and a final `[DONE]` frame.

## Conditions and limits

- Host: AMD Ryzen 9 9950X, 96 GiB installed RAM. Both runs used CPU inference
  and ran concurrently. WSL had its own Linux installation and processes;
  system Chrome and Node ran on Windows through localhost forwarding.
- Each run used a new prefix, managed Python, empty model directory, empty
  engine store and `UV_NO_CACHE=1`. This is a fresh isolated application install
  on an existing machine, **not a new Windows account or clean OS guest**.
- Workload: the unchanged **8B-class** starter row from the installed library,
  `google/gemma-4-E4B-it`, 7,518,069,290 parameters. The downloaded file was
  `lmstudio-community/gemma-4-E4B-it-GGUF/gemma-4-E4B-it-Q4_K_M.gguf`, exactly
  **5,335,291,936 bytes** on both targets. A single-row starter fixture fixes the
  workload; it does not claim this large-RAM host would otherwise recommend it.
- Hardware probes hide accelerators; normal RAM reporting remains. The product
  downloads its CPU engine (`llama.cpp b11065` on both targets) after the real
  confirmation. Runtime ports are moved
  away from the live worker. Download, fit, launch, auth, routing, UI and inference
  APIs are real, with no browser request interception or canned replies.
- A loopback CONNECT proxy caps each run's aggregate downstream at **100,000,000
  bits/s**, across all connections, with a **256 KiB burst**. Installer packages,
  model and engine downloads traverse it; TLS remains end to end. This is a
  controlled downstream cap, not emulation of a particular ISP's latency or loss.
- The first-text observer uses browser wall time relative to installer-start
  epoch time. Independently, the proxy's monotonic lifetime starts earlier and
  ends after the curl check and shutdown, and is also below 600 seconds on both
  targets. The exact first-token numbers are not monotonic-clock measurements.
- Windows uses `-NoService -NoStart -Isolated`; Linux uses `--no-service
  --no-start`. UAC, service registration and reboot behavior are outside this
  timed run. Windows live service identity/state/PID and persistent Eugene user
  and machine environment values matched before and after. Linux has no
  equivalent Windows registry/service snapshot; its old report's `true` field
  was vacuous and the runner now writes `null` there.
- The run sees one Reach switch but does **not** exercise phone connectivity.
  The existing Reach acceptance and the pending participant phone task remain
  separate evidence. Likewise, this does not replace physical 8 GB GPU testing
  or the Mac verification still listed in the roadmap.

## Instrument corrections and checks

The old `EP_DOWNLOAD=1` branch emptied the model folder but still required an
existing-model Run button. Its field fills generated no real keydown events,
and it timed the completed answer rather than the first visible assistant text.
The maintained entry point now delegates to `s10-acceptance.py` and
`s10-browser-acceptance.mjs` for both seeded and download modes.

Windows `-Isolated` requires a new explicit prefix, `-NoService` and `-NoStart`;
it refuses migration/join/maintenance and overlap with the existing install.
It skips global autostart removal and persistent environment writes. Ordinary
installer behavior is retained. Actual guard blocks run against side-effect
spies; deliberately permitting startup, prefix overlap, autostart removal,
config-path writes or port writes causes failure. Breaking the shared bandwidth
cap also fails. All **six Windows mutations** were caught and restored; Linux
caught the cap mutation. CI runs these checks on both platforms.
The existing Windows installer migration/preflight suite also passes all
**11 tests**.

Before the recorded runs, a seeded Windows rehearsal reached its first reply
in 45.912 s but its curl prompt exhausted a 256-token reasoning budget without
content. The curl check now uses 1,024 tokens and `/no_think` and still requires
nonempty content. An earlier Windows download was stopped because per-packet
sleep rounding accidentally imposed roughly 30 Mbit/s; the bounded token bucket
corrects that. WSL rehearsals exposed CRLF in the shell installer copy and a
localhost-forwarding startup race; normalized LF and a bounded browser retry
fixed those instrument problems. None of these attempts is counted as a pass.

The S8 vocabulary suite still passes **26 tests**. Golden-path copy is unchanged
from its [Hemingway Grade 6 acceptance](s8-vocabulary-run.md).

## The 8 GB GPU / 16 GB RAM starter check

`s10-starter-check.py` scores the actual shipped starter set, reviewed 2026-09-16,
at 8,192 context and f16 KV. Both decimal GB and binary GiB capacity fixtures
recommend the 8B-class model with **6,680,614,944 required bytes**. The 4B candidate
fits at 4,083,115,168 bytes; 14B and 30B return `split` at 8,665,365,312 and
18,075,052,960 bytes. CI repeats the capacity check on both platforms. These
fixtures assume the stated memory is free; they are not physical-card results.

## Reproduction and local artifacts

Dependencies: a driving Python with `httpx` and `PyYAML`, Windows Node and Chrome,
and `npm ci` in the sibling `ui` checkout. WSL requires its own driving Python.
Allow at least 7 GB free disk per download run. Every output directory must be
new; the scripts do not delete an existing install or output directory.

From Git Bash, set `EP_TEST_PY` to that Windows Python and run:

```bash
EP_DOWNLOAD=1 bash scripts/hobbyist-acceptance.sh
EP_TARGET=wsl EP_TEST_PY_WSL=/path/to/wsl/python EP_DOWNLOAD=1 bash scripts/hobbyist-acceptance.sh
```

Alternatively, run the relevant Python directly with
`scripts/s10-acceptance.py --output <new-directory> --download` inside the target
OS. Omit `--download` and supply `--model <small-gguf>` for a seeded rehearsal.
The fast instrument checks are `python scripts/s10-checks.py`; the starter check
also needs the pinned Library package installed.

Local evidence is retained in `%TEMP%/ep-s10-windows-download-2` and
`/home/tcorbin/.cache/ep-s10-wsl-download-3`: installer/agent/browser logs,
`result.json`, `browser.json`, `network.json`, and `first-reply.png`. Disposable
credentials and installed files remain local; **do not publish `connection.json`
or the install directory**. The public measurements above contain no credentials.
