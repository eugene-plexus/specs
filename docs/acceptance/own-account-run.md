# Eugene under its own account on Linux (row 2, 2026-09-24)

**The problem.** A program running as the agent's own account can read
the agent's files, its environment and its memory. No file permission
changes that, and the install's signing key is one of those files
(`node.yaml`). Row 1 closed the gap for other accounts on the machine.
Row 2 is the same-account case: an AI agent the person started, running
as the person, on an install that also runs as the person. The fix is
the only one there is: the agent runs as a different account.

**Troy's calls (2026-09-24):**
1. On Linux, the default install runs Eugene under its own account,
   using sudo. `--user` keeps the per-user layout.
2. Eugene's account joins the person's primary group, so it can read
   models in a 0750 home.
3. The agent unlocks from a passphrase file, because a system account
   has no keyring.
4. macOS gets a warning only.

Out of reach and not attempted: root or an administrator.

## What was built

- **Contract** (specs `50f74db`):
  - `securityMode: passphrase_file` is documented on the agent.
  - `AuthStatus.passphraseFile` is new.
- **Agent** (`4f0065d`):
  - `passphrase_file.py` adds the `passphrase_file` unlock.
  - Unlike the control root's mode, where the operator supplies the file,
    the agent writes the file itself. It does so at initialize and at
    every sign-in, the only moments it holds the passphrase. The file is
    0400.
  - At startup it reads the file and checks it against the install's
    hash before deriving anything.
  - The control root on the same host reads the same file through its
    existing mode.
  - `write_private` gains a `mode` that can only narrow permissions, and
    only on POSIX: on Windows a mode without the write bit sets the
    read-only attribute, which then blocks the rename over it.
- **UI** (`ef6a568`, dist `131c206`):
  - The wizard reads `passphraseFile`. It then says the install unlocks
    itself, shows no keyring checkbox, and sets both processes to the
    mode.
  - Screen 2 proposes the folder the installer chose (`GET /v1/folders`)
    before `<home>/Eugene Models`. The library's home is its own
    account's home: `/var/lib/eugene-plexus` here, SYSTEM's profile on
    the Windows service, and nobody's in the container.
- **`install.sh`**:
  - **Default Linux layout:** account `eugene-plexus`, prefix
    `/var/lib/eugene-plexus` (0750), and a system unit with `User=` and
    `SupplementaryGroups=` set to the person's group plus `video` and
    `render` where those groups exist.
  - **Runs as the account:** uv, the venv, the packages, the verify step
    and `join` all run as Eugene's account (`runuser` or `sudo -u`), so
    no package's build step runs as root.
  - **A fresh install** gets `securityMode: passphrase_file` and a
    person-owned `~/Eugene Models`, mode 2775.
  - **Explains, never changes:** a home the group cannot enter, and an
    existing models folder the group cannot write to.
  - **One install per machine:** the system layout refuses to install
    beside a per-user one, and `--user` refuses beside a system one.
  - **Uninstall:** it moves the prefix aside, gives it to root (mode
    0700), and then removes the account. Files left owned by a deleted
    account's uid would belong to whichever system account next gets
    that number.
  - **Per-user layout:** `--user`, `--no-service` and macOS. Installs
    that start a service there now print what running as you costs.
- **`install.ps1`:** a `-NoService` install prints the same sentence and
  names the Windows service as the account-separated alternative.
- **Existing checks:** `r22-install-sh-checks.sh` and
  `install-acceptance.sh` now pass `--user`, because what they test is
  the per-user layout. r22 gives 20 PASS, r37 gives 97 PASS.

## Evidence

**`scripts/row2-system-install-acceptance.sh`: 19 of 19 passed, second
execution.** It ran as root in the WSL2 guest (Ubuntu 26.04, systemd),
invoked the way `sudo sh install.sh` would be. The agent and UI came from
local `git archive`s of their pinned commits, because those commits are
not pushed yet.

- **The account:** `eugene-plexus` is uid 999 with shell
  `/usr/sbin/nologin`. The prefix is `eugene-plexus:eugene-plexus`, 750.
- **The process:** the agent runs as `eugene-plexus` and holds gid 1000,
  the person's group.
- **What the person cannot reach:** they cannot list the prefix, read
  `agent.yaml`, read the passphrase file, or read
  `/proc/<agent>/environ`.
- **The passphrase file:** the agent reports `passphraseFile: true`
  before setup. Setup writes the file as `eugene-plexus`, mode 400. After
  `systemctl restart`, the agent is unlocked with nobody signing in.
- **The models:** `~/Eugene Models` is `tcorbin:tcorbin 2775`. The
  running agent lists a file in it. The library's default folder is that
  folder.
- **Refusals:** `--user` refuses beside the system install and changes
  nothing. A system install refuses beside a per-user one and creates no
  account and no prefix.
- **Uninstall:** it removes the unit, the account and the prefix. The
  old prefix is kept as `root:root 700` with its passphrase file owned by
  root, and the models folder stays.

The first execution passed 18 of 19. The one failure was the instrument:
check 18 required `node.yaml` in the kept prefix, and `node.yaml` only
appears when the wizard enrolls the machine, which this run does not
drive.

**`scripts/row2-sabotage.py --installer`: 16 sabotages, 15 caught, 1
escaped by construction.** The five installer sabotages each ran a full
system install in WSL, and all five were caught:
- the unit running the agent as root;
- the unit not adding the person's group;
- the prefix left at 0755;
- a fresh install left on `prompt_on_startup`;
- a system install starting beside a per-user one.

The escape is "0600 instead of 0400". Its unit check is POSIX-only and
skips on this Windows box. Check 11 of the live run asserts 0400 on the
real file, and Linux CI runs the unit check. The gate first failed its own baseline because Vitest launched
from `d:/…` rather than `D:/…` loads itself twice and finds no suite;
the root path is written in upper case now.

**Also:** the agent suite gives 1152 passed. The UI gives 1124 passed,
typecheck and lint clean.

## Not done

- **Nothing is pushed.** Codegen and CI fetch commits from GitHub, so
  specs `50f74db`, agent `4f0065d`, ui `ef6a568` and dist `131c206` have
  to be pushed in that order before CI can check them.
- **The sudo prompt itself is unexercised.** The run was root with
  `SUDO_USER` set, because sudo in WSL needs a password.
- **No wizard was driven through a browser on a system install**, and
  `node.yaml` protection was not checked after an enrolment. The
  prefix's 0750 is what protects it, and that was checked.
- **No migration from per-user to system:** the installer refuses and
  says how to start fresh. Moving an install across is its own slice.
- **The website's install page** describes the per-user layout of the
  released alpha, which is still true for that release. It needs
  updating when a release ships this installer.
- **A folder the person makes later**, outside `~/Eugene Models`, needs
  group read (and group write for downloads). The library reports an
  unreadable folder, and nothing here explains the group.
- **macOS:** a warning only, as decided.
