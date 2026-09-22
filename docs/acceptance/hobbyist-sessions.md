# S10 moderated sessions

Status: **one outside installation reported successful, 2026-09-22; full
moderated sessions still pending**. The report below is distinct from the
session guide and blank recording sheet. Decision #14
accepts Troy's two or three friends; the release gate remains open until their
observations have been recorded and any release-blocking problems addressed.

Allow about twenty minutes per participant. Choose people who want to run a
local model but have not helped build Eugene. Use their own clean machine or
a disposable clean guest, their phone, and an app they actually use. Record the
OS, RAM/GPU, network speed, exact installer/specs commit and UI build. A reused
install is useful for testing later tasks but is not a first-install measurement.

Ask permission before recording their screen or voice. Use participant IDs
rather than names in this repository. Do not record passphrases, client keys,
private prompts or personal paths. Note that a secret was typed, not its value.

## Opening script

“We are testing the software, not you. Please say what you expect to happen,
what you are looking for, and what seems confusing. Work as you normally would.
I will mostly watch. You can stop at any time.”

Use the [installation page](https://eugeneplexus.com/install) for
the current public alpha, recording its exact version. Confirm the page
and linked release are live before inviting participants. Give participants
those instructions and the one-liner appropriate for their OS, recording the
version being tested. A stable release is not required. Do not first explain the tree,
the component names or where the buttons live.
Explain the practical download/time cost before beginning; download waiting
time should be recorded separately from active interaction time.

## Five tasks, in order

1. Get a model answering on this computer.
2. Make it answer from your phone.
3. Connect it to a tool you use.
4. Find out why an answer was slow.
5. Change the context size.

Give one task at a time. Avoid naming the control the participant should use.
If they stall, ask “What are you looking for?” or “What did you expect?” Do not
turn a hint into an unassisted success. Record any help and the time it was given.
If twenty minutes expires, mark unfinished tasks as not attempted or incomplete.

## Recording sheet — copy once per participant

- Participant ID:
- Date, observer, prior local-model experience:
- OS, RAM, GPU and free VRAM, browser, phone OS/browser:
- Network/downstream speed, model and quant:
- Installer/specs commit, UI build, clean or reused install:
- Recording consent (yes/no; no recordings or secrets need enter this repo):

| Task | Start/end | Outcome: unassisted / assisted / incomplete / not attempted | Clicks and typed values, excluding secret contents | Stall, exact words, help given |
| --- | --- | --- | --- | --- |
| First reply | | | | |
| Phone reply | | | | |
| Existing tool | | | | |
| Explain slow answer | | | | |
| Change context | | | | |

- Time spent downloading/installing versus interacting:
- First visible token time, where measurable:
- What surprised them:
- What they believed Eugene did:
- What they would do next without the observer:

## Findings and follow-up

### P01 — Outside Windows installation, reported 2026-09-22

Troy relayed the first installation report from someone other than the project
owner. The tester said installation worked well and the interface was working
smoothly so far. The feedback identifies the Windows elevated-install output;
the exact build, hardware, model and tasks completed were not supplied. This is
a positive self-reported installation/usability observation, not a measured
five-task moderated session or proof of inference/platform coverage.

Two non-blocking wording improvements were requested:

| Observation | Change | Verification |
| --- | --- | --- |
| The Windows guide said to wait for "Eugene is running", but the visible installer says "done." | Match the website instruction to `done.`. | Website type/build checks and all 55 browser checks passed; tester follow-up pending. |
| During elevation, the original terminal displayed only a log path, leaving progress unclear. | Prefix the log message with `Installing now...` (or `Uninstalling now...` for removal). | PowerShell syntax and all 11 existing preflight checks passed; tester follow-up pending. |

The website correction can ship immediately. The installer wording is a source
change for the next release; immutable alpha.2 installer assets are preserved.
No personal paths or participant identity are retained in this record.

For each observed problem, record participant/task, expected and observed
behavior, whether it blocked completion, reproduction steps, fix/issue link,
and verification. Preserve failed attempts. A scripted browser pass does not
replace a participant's experience; a fixed problem needs a follow-up check.

Completion requires two or three actual session records and an explicit review
of the remaining problems. Do not count this guide, a rehearsal by the author,
or the automated acceptance harness as a participant session.
