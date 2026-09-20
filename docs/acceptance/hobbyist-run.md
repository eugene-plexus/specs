# The hobbyist budget, counted

Historical seeded-run record, 2026-09-16. The [2026-09-20 S10 download run](s10-download-run.md)
adds actual keystroke and first-visible-token measurements with downloads under
a 100 Mbit/s cap. Its conditions and remaining moderated-session gate supersede
the outstanding timing status below; this earlier record is preserved.

`scripts/hobbyist-acceptance.sh` — **22 checks, zero failures, on both
targets**, 2026-09-16. Windows (RTX 5090, CUDA driver 13.3) on the fourth
execution; **WSL2 Ubuntu 26.04 on the third**, with `EP_TARGET=wsl`.

Design: [`../design/hobbyist-ux.md`](../design/hobbyist-ux.md) §1 (the
targets), §7 S10, §8.1 (the table this run fills in).

This is the only acceptance script in the repo that measures **a number
the plan committed to** rather than a behaviour. Everything else here
asks "does it work"; this asks "how many times did a person have to
click".

---

## 1. The budget, measured

| Measure                               | §0.2 before          | Target | This run                     |
| ------------------------------------- | -------------------- | ------ | ---------------------------- |
| Clicks, wizard → first reply          | 15                   | ≤ 6    | **5**                        |
| Typed values before the first reply   | 3, including a path  | 1      | **1**, the passphrase        |
| Filesystem paths typed                | 1                    | 0      | **0**                        |
| Clicks, Home → a connected tool       | 19 from landing      | ≤ 3    | **1**                        |
| The key's life                        | 14-day session token | > 14 d | **a year**                   |
| Reach switches on Home                | —                    | 1      | **1**                        |
| Banned words on the golden path       | —                    | 0      | **0** across four screens    |
| `install.ps1` from nothing            | —                    | —      | **7 s**                      |
| Wizard → a reply on Home              | —                    | —      | **21 s**                     |

The five clicks: **Continue** past the passphrase, **Finish** on the
models folder, **Run**, **Install the default** in the engine dialog,
**Send**.

The one typed value is `hobbyist-25941` — the passphrase, typed twice
into two fields and counted once because it is one value a person
invents. Nothing else on the path was typed, and no path was typed at
all.

Everything after the wizard came from a real cold install: no llama.cpp
on the machine, no engine store, no config. `askedAboutEngine: true`,
and the agent fetched **b11010** into
`…\EugenePlexusHobbyist\.eugene-plexus\engines\llama_cpp\b11010\` —
taking the CUDA **13.4** build on a **13.3** driver under minor-version
compatibility, the rule M1 learned in S3. The model answered in 0.8 s.

The three strings Home gives — `http://127.0.0.1:8080/v1`,
`Qwen3-0.6B-Q4_K_M`, and a fresh `aud: client` key — worked in a plain
`curl` with nothing else: no session token, no proxy, no UI.
`finish_reason: stop`, content *"Hi there! 😊 What's up?"*.

---

## 2. What the run found, and it was in the shipped build

**The third execution clicked a 16 GB download beside a folder that
already held a model.** That is the defect
[`ui` f267fbd](https://github.com/eugene-plexus/ui/commit/f267fbd) was
written to fix, hours earlier — the library boots with no roots and
skips its startup scan, the wizard writes the folder with a `PATCH` that
deliberately never scans, and nothing goes back to look.

**The fix was on `main` and in no build.** `dist` was at `893b669`, the
export of ui@`70dd910`; f267fbd is a child of that commit and was never
exported. Both installers pin `dist`. So the fix could not ship, and
this run — which is an **installer** test — measured a UI without it.

Proof rather than suspicion: the string `"library","/v1/scan"` appears
in **five** chunks of a build of ui@f267fbd and in **zero** chunks of
`893b669`.

This is the S3 trap one layer over. There, the agent venv served a
**wheel** while the script asserted about a **staged** directory — four
runs measured a build no browser saw. Here it is a commit on `main` that
no `dist` build carries, and the installer is the thing that notices,
because the installer is the only consumer of `dist`.

Fixed: `dist` rebuilt as
[`50e0248`](https://github.com/eugene-plexus/ui/commit/50e0248) (export
of ui@f267fbd), both installers re-pinned, and **the pinned archive was
downloaded, unpacked and grepped** for the scan call before the re-run —
the precaution S7 introduced for exactly this.

---

## 3. Three harness defects, two of which passed while broken

**A spec that could not tell the two journeys apart.** The arc waited
for `data-testid="home-primary"` and clicked it. But `home-primary` is
the testid of the **no-models** branches of `FirstModelCard`; the
one-model branch renders a `run-button` and carries no `home-primary`
at all. So the spec could only ever match the state where Home has
nothing, and it reported that state as a pass. It did not detect the
missing fix — **it depended on it.** With the fix in place the old spec
would have hung for two minutes on a testid that no longer renders.

The arc now waits on `run-button`, **races the download card against
it**, and fails if the download is what appeared. Check 4e is that
assertion in the shell. Same family as M10's check 7 and the tree
slice's *"a driver sits under its machine"*: an assertion about a
surface that cannot distinguish the failure it exists to catch.

**Two checks read keys the spec never wrote.** The shell read
`firstReply.text` and `connect.expiry`; the spec writes `turn`,
`transcript` and `lifetime`. `jq_` raises, the substitution captures
empty, and with no `set -e` both checks report failure — so checks 4d
and 7 were **guaranteed to fail** on any run, green install or not.
Caught by reading the two halves against each other before the third
execution rather than by running it.

**Sixteen tokens is not a budget an answer fits in.** Check 6 asked for
`max_tokens: 16` and got a `200` with an empty `content` — the starter
models are hybrid reasoning models whose first tokens are a thinking
block the gateway strips, so the budget was spent before a word of the
answer. The check would have read a working install as a broken one.
256 now, with `finish_reason` printed on failure.

**And the run binds four ports, not one.** The header claimed "+100" and
the preflight checked one port. First-boot seeding declares the gateway,
library and control root at the contract's defaults — 8080, 8082, 8083 —
whatever port the agent took (`default_topology.py`). All four are
checked in the preflight and reclaimed in the teardown now, which is
safe *because* the preflight proved they were free.

---

## 4. The hazard this script is built around

`install.ps1` writes `EUGENE_PLEXUS_AGENT_CONFIG_FILE` into the **USER**
environment, deliberately, because a logon task inherits the user
environment. This box is a worker node of the live two-machine install,
so a second install on the same account silently repoints the first.

The run saves the value before installing, restores it in the teardown
trap, and **check 2 asserts it came back**. Both executions recorded the
`NOTE` that the installer had repointed it and then the `PASS` that it
was put back. Check 10 asserts it again after teardown.

`HOME` and `USERPROFILE` point inside the throwaway prefix so the
wizard's proposed `<home>/Eugene Models` lands there: the arc must accept
the proposal **without typing**, and the run must leave nothing in the
operator's home.

---

## 4b. WSL2, and the product defect it found

`EP_TARGET=wsl` installs with **`install.sh` inside the guest** and drives
the same browser arc against it from Windows, because WSL2 forwards a
guest listener on `127.0.0.1:8179` to the same port here. The guest has
`uv`, `python3`, `curl` and `git` and **no Node and no browser** — `npm`
there is the *Windows* npm reached over interop, answering `--version`
while `node` does not exist, which is the trap `bootstrap.sh` already
paid for. Installing Playwright into it would change the machine to
prove something the UI does not depend on: the UI is one static export,
so the browser's OS is not what WSL2 tests. What WSL2 tests is
`install.sh`.

| | Windows | WSL2 |
| --- | --- | --- |
| install from nothing | 7 s | **4 s** |
| clicks, wizard → reply | 5 | **5** |
| typed values / paths | 1 / 0 | **1 / 0** |
| clicks, Home → a tool | 1 | **1** |
| wizard → a reply | 21 s | **39 s** |

**One platform difference is a finding rather than a skip.** The account
hazard is a property of `install.ps1`, not of installing: `install.sh`
writes the config path into the systemd unit it generates, so a second
Linux install cannot repoint a first one through the environment. Check
2 asserts that on both targets — on Linux, that the Windows account
variable was untouched and that `--no-service` wrote no unit.

### The run found a product defect, and the fix was not the one on file

The first WSL2 execution reached one-click Run and stopped:

> *"llama.cpp publishes no prebuilt CUDA build for Linux… A Vulkan build
> would install cleanly and run on this card, but it is materially slower
> at prompt processing and we will not substitute it for CUDA without
> being asked."*

That is M1's deliberate refusal, and
`install-paths-and-distribution.md` **decision #2 — "ship Vulkan, badge
it permanently", DECIDED 2026-09-11** — was the agreed answer. It had
never been built: `grep -ri vulkan` over the agent returned zero hits,
and the only occurrence anywhere was a test asserting the refusal.

**Checking upstream before building it showed the premise had already
changed.** §7 says the refusal "was re-verified against upstream on
2026-09-11, not taken from the code comment"; re-verifying it again five
days later, b11010 publishes `ubuntu-cuda-12.8-x64`,
`ubuntu-cuda-13.3-x64` and `ubuntu-cuda-13.3-arm64`. **Decision #2 was a
workaround for a missing asset that now exists.** So the fix was to map
the Linux CUDA variants (agent `b4c0679`), not to ship a degraded engine.

**A second trap in the same change would have shipped a server that
could not start.** The two companion archives are not named alike:

```
cudart-llama-bin-win-cuda-13.4-x64.zip                no build number
cudart-llama-b11010-bin-ubuntu-cuda-13.3-x64.tar.gz   has one
```

`_CUDART_RE` required the Windows shape, and the companion is only
*demanded* for a variant the matcher recognises — so a Linux CUDA install
would have fetched the server, reported success, and died at load on a
missing libcudart.

**Proved end to end, not inferred from a green run.** A 0.6B runs fine on
a CPU, so "it answered" is not evidence of a CUDA install. The guest's
`install.json` reads `"variant": "ubuntu-cuda-13.3-x64"` with the cudart
companion unpacked beside it, and the installed binary answers:

```
$ llama-server --list-devices
Available devices:
  CUDA0: NVIDIA GeForce RTX 5090 (32606 MiB, 30927 MiB free)
```

Linux + NVIDIA — in §7's own words *"the most common serious setup, and
the one where differentiator #1 is currently false"* — works through the
product's own acquisition path now. It was false for five days longer
than it needed to be because **nothing had ever walked the install path
on Linux with an NVIDIA card**; this run was the first.

### Two harness defects on the way

**`setsid nohup` does not survive `wsl.exe -e`.** The agent was started
and backgrounded inside the guest; the interop session ends when that
command returns and takes the agent with it. The symptom was a
**zero-byte log and nothing listening** — no error, because nothing got
far enough to write one. It is backgrounded from the Windows side now: a
`wsl.exe` left running holds the session open, gives teardown a pid
symmetric with the Windows path, and puts the log where the failure
paths already look.

**Windows `netstat` sees a forwarded guest port, but the pid is the
relay.** `taskkill` on it leaves the real process running, so ports are
reclaimed inside the guest with `fuser`, and check 10 treats the guest as
the authority rather than the forwarder, which can linger a moment.

## 5. What this run does not prove

- **A browser running on Linux.** The guest install is genuine; the
  Chrome driving it is the Windows one. A Linux-native browser, a
  systemd-supervised agent and the macOS/launchd path are all untested.
- **The ten-minute target.** §1's fourth number — install to first token
  **with the download included** — needs `EP_DOWNLOAD=1` and has not been
  measured. The default seeds a small GGUF, because the subject of the
  other three targets is the count and a download changes how long the
  arc takes without changing how many times it is clicked. (The third
  execution accidentally measured something adjacent: it downloaded a 27B
  and reached a reply in 261 s. That was the wrong build and the wrong
  model, so it is an anecdote, not the measurement.)
- **Moderated sessions with strangers** (§8.4). Needs real people.
- **The keystroke count is not a measurement.** Playwright's `fill()`
  sets a value and dispatches `change` without individual `keydown`
  events, so the run reports `0 keystrokes` while a person would type
  about thirty. The claim §1 actually makes is *one typed **value***, and
  that is what the `change` listener measures. The keystroke number is
  the counter's blind spot and is not evidence of anything.
- **Reading grade** (§8.1) is still unmeasured; the run reports sentences
  over 25 words (Home 6, Discover 5, Library 2, Playground 2) as the
  number S8 has to drive down.
- **One box, one account.** A clean Windows *user profile* — what
  `install-acceptance.sh` uses — is not what this run gets; it gets a
  clean *prefix* on a dirty account, with the ambient `EUGENE_PLEXUS_*`
  dropped at check 0.

---

## 6. Reproducing it

```bash
cd specs && bash scripts/hobbyist-acceptance.sh
```

~2 minutes with a seeded model; it really installs llama.cpp over the
network. `EP_DOWNLOAD=1` fetches the starter model instead.
`$LOCALAPPDATA\EugenePlexusHobbyist` is the throwaway prefix.

**Never run it while the live worker agent holds 8079** — it uses 8179,
but check 2's hazard is about the account, not the port.
