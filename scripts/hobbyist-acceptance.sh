#!/usr/bin/env bash
# The hobbyist budget, counted (hobbyist UX plan, S10).
#
# Design: docs/design/hobbyist-ux.md §1 (the targets) and §7 S10.
#
# **This is the only acceptance script that measures a number the plan
# committed to rather than a behaviour.** §1 says: a first reply in ≤ 6
# clicks with one typed value and NO typed filesystem path; a tool
# connected in ≤ 3 clicks from Home with a key that outlives the
# fortnight; reachable from another device with one switch and one URL.
# §0.2 measured the before: 15 clicks, a typed path, 6 route changes, and
# a 14-day session token as the only key.
#
# So the clicks are counted **in the browser**, by listeners the page
# installs on itself, not by counting the lines of the test. A helper
# that clicks two things in one call would otherwise report one.
#
# The checks:
#   0. isolated: the ambient environment dropped, ports free
#   1. install.ps1 from nothing, into a throwaway prefix, timed
#   2. THE ACCOUNT'S ENVIRONMENT IS PUT BACK -- see the hazard below
#   3. the agent starts from the installed prefix, serving its own UI
#   4. BROWSER: from the wizard to a first reply, counted
#      4a. within the click budget
#      4b. one typed value, and it is the passphrase
#      4c. no filesystem path was typed
#      4d. a reply really arrived
#   5. BROWSER: a tool connected -- three strings, ≤ 3 clicks
#   6. the three strings work in a plain curl, with nothing else
#   7. the key outlives the fortnight
#   8. BROWSER: reachable from another device -- one switch, one URL
#   9. vocabulary and readability on the golden path (S8's instruments)
#  10. teardown by pid; the account's variable restored; no port left
#
# **HAZARD, and the script is built around it: `install.ps1` writes
# `EUGENE_PLEXUS_AGENT_CONFIG_FILE` into the USER environment.** That is
# deliberate -- a logon task inherits the user environment -- but it
# means a second install on the same account silently repoints the
# first. This box IS a worker node of a live two-machine install, so the
# value is captured before the run and restored in the teardown trap,
# and check 2 asserts it came back. Nothing else here writes outside the
# prefix.
#
# **The wizard's proposed models folder is contained too.** It is
# `<home>/Eugene Models`, and the arc must accept it without typing, so
# the agent is started with HOME and USERPROFILE pointed at the throwaway
# prefix. The proposal then lands inside the prefix and the run leaves no
# folder in the operator's home.
#
# **The model is already on disk, and that is a departure worth naming.**
# §1's fourth target -- ten minutes from install to a first token with
# the download included -- needs a real multi-gigabyte download on a real
# line, and it is measured by EP_DOWNLOAD=1 rather than on every run. The
# default seeds the proposed folder with a small GGUF, because the
# subject of the other three targets is the COUNT, and a download changes
# how long the arc takes without changing how many times it is clicked.
#
# Safe beside a live install: the agent is on +100, teardown is by pid,
# and never `pkill -f eugene_plexus_`.
#
# **But only the AGENT is on +100.** First-boot seeding declares the
# gateway, library and control root at the contract's default ports
# (`default_topology.py`: 8080, 8082, 8083) whatever port the agent took,
# so this run binds four ports and not one. They are checked in the
# preflight -- a run that starts on a held port measures whatever holds
# it -- and reclaimed in the teardown, which is safe precisely because
# the preflight proved they were free.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-hobbyist}"
PORT="${EP_AGENT_PORT:-8179}"
# The agent's port, plus the three the first boot seeds at their contract
# defaults. See the note on +100 in the header.
OWNED_PORTS="${EP_OWNED_PORTS:-$PORT 8080 8082 8083}"
BASE="http://127.0.0.1:$PORT"
PASS="hobbyist-$$"
PREFIX_WIN="${EP_PREFIX_WIN:-$LOCALAPPDATA\\EugenePlexusHobbyist}"
PREFIX_UNIX=$(cygpath -u "$PREFIX_WIN" 2>/dev/null || printf '%s' "$PREFIX_WIN")
MODEL_SRC="${EP_MODEL:-$HOME/.eugene-plexus/acceptance-models/Qwen3-0.6B-Q4_K_M.gguf}"
DO_DOWNLOAD="${EP_DOWNLOAD:-0}"

# §1's targets, as numbers this script can fail on.
BUDGET_CLICKS="${EP_BUDGET_CLICKS:-6}"
BUDGET_CONNECT_CLICKS="${EP_BUDGET_CONNECT_CLICKS:-3}"
KEY_MIN_DAYS="${EP_KEY_MIN_DAYS:-14}"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
skip() { printf '  SKIP  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
win_path() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }

SAVED_CONFIG_VAR=""
A_PID=""
restore_account_env() {
  # The one thing this run can break outside its own prefix. Restored
  # here, and check 2 asserts it, and the teardown does it again.
  powershell.exe -NoProfile -NonInteractive -Command \
    "[Environment]::SetEnvironmentVariable('EUGENE_PLEXUS_AGENT_CONFIG_FILE', '$SAVED_CONFIG_VAR', 'User')" \
    >/dev/null 2>&1
}
teardown() {
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 3; }
  for p in $OWNED_PORTS; do
    for pid in $(listening_pids "$p"); do
      taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
    done
  done
  restore_account_env
  rm -f "$UI_DIR/e2e/hobbyist-live.spec.ts" 2>/dev/null
}

say "preflight"
[ -f "$MODEL_SRC" ] || { bad "no model at $MODEL_SRC (set EP_MODEL)"; exit 1; }
[ -d "$UI_DIR/node_modules/@playwright" ] || { bad "no Playwright in $UI_DIR (npm install)"; exit 1; }
for p in $OWNED_PORTS; do
  [ -n "$(listening_pids "$p")" ] && { bad "port $p in use -- the checks below would be about whatever holds it"; exit 1; }
done
SAVED_CONFIG_VAR=$(powershell.exe -NoProfile -NonInteractive -Command \
  "[Environment]::GetEnvironmentVariable('EUGENE_PLEXUS_AGENT_CONFIG_FILE','User')" 2>/dev/null | tr -d '\r')
ok "ports free ($OWNED_PORTS); the account's config variable saved ('${SAVED_CONFIG_VAR:-<unset>}')"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

# --- 0 -----------------------------------------------------------------------
say "0. isolate this run"
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] && ok "no ambient EUGENE_PLEXUS_* variable" || { bad "leaked"; exit 1; }

# --- 1 -----------------------------------------------------------------------
say "1. install from nothing"
powershell.exe -NoProfile -NonInteractive -Command \
  "if (Test-Path '$PREFIX_WIN') { Remove-Item -Recurse -Force '$PREFIX_WIN' }" >/dev/null 2>&1
T0=$(date +%s)
# `-NoService`: no logon task is registered on this box. The port comes
# from the environment because that is the installer's own knob.
OUT=$(EUGENE_PLEXUS_AGENT_BIND_PORT="$PORT" powershell.exe -NoProfile -NonInteractive \
  -File "$(win_path "$HERE/install.ps1")" -Prefix "$PREFIX_WIN" -NoService 2>&1 | tr -d '\r')
T_INSTALL=$(( $(date +%s) - T0 ))
if printf '%s' "$OUT" | grep -qi "installed\|is running"; then
  ok "install.ps1 completed from nothing in ${T_INSTALL}s"
else
  bad "install.ps1 did not finish"; printf '%s\n' "$OUT" | tail -15 | sed 's/^/      /'; exit 1
fi
AGENT_EXE="$PREFIX_UNIX/venv/Scripts/eugene-plexus-agent.exe"
[ -f "$AGENT_EXE" ] || { bad "no agent console script at $AGENT_EXE"; exit 1; }

# --- 2 -----------------------------------------------------------------------
say "2. the account's environment is put back"
NOW_VAR=$(powershell.exe -NoProfile -NonInteractive -Command \
  "[Environment]::GetEnvironmentVariable('EUGENE_PLEXUS_AGENT_CONFIG_FILE','User')" 2>/dev/null | tr -d '\r')
if [ "$NOW_VAR" != "$SAVED_CONFIG_VAR" ]; then
  note "install.ps1 repointed the account's config variable to '$NOW_VAR' -- restoring"
  restore_account_env
fi
BACK=$(powershell.exe -NoProfile -NonInteractive -Command \
  "[Environment]::GetEnvironmentVariable('EUGENE_PLEXUS_AGENT_CONFIG_FILE','User')" 2>/dev/null | tr -d '\r')
[ "$BACK" = "$SAVED_CONFIG_VAR" ] \
  && ok "the live install's config path is intact ('${BACK:-<unset>}')" \
  || bad "the account variable is '$BACK', not '$SAVED_CONFIG_VAR' -- the live worker would come back on the wrong config"

# --- 3 -----------------------------------------------------------------------
say "3. the agent, from the installed prefix"
# HOME and USERPROFILE point inside the prefix so the wizard's proposed
# models folder lands there: the arc has to accept it WITHOUT TYPING, and
# the run must not leave a folder in the operator's home.
MODELS_DIR="$PREFIX_UNIX/Eugene Models"
mkdir -p "$MODELS_DIR"
if [ "$DO_DOWNLOAD" = "1" ]; then
  note "EP_DOWNLOAD=1: the arc will fetch the starter model instead of finding one"
else
  cp "$MODEL_SRC" "$MODELS_DIR/" || { bad "could not seed the proposed folder"; exit 1; }
  note "seeded the proposed folder with $(basename "$MODEL_SRC") -- see the header on why"
fi
(exec env -u EUGENE_PLEXUS_AGENT_CONFIG_FILE \
  HOME="$PREFIX_UNIX" USERPROFILE="$PREFIX_WIN" \
  EUGENE_PLEXUS_AGENT_CONFIG_FILE="$PREFIX_WIN\\agent.yaml" \
  EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 \
  EUGENE_PLEXUS_AGENT_BIND_PORT="$PORT" \
  "$AGENT_EXE" --unattended >> "$WORK/agent.log" 2>&1) &
A_PID=$!
wait_healthy "$BASE" 90 || { bad "the installed agent never answered"; tail -20 "$WORK/agent.log"; exit 1; }
curl -fsS -m 5 "$BASE/" | grep -q '<!DOCTYPE html>' \
  && ok "the agent answers on $BASE and serves its own UI" \
  || { bad "the agent serves no UI"; exit 1; }

# --- 4..8 --------------------------------------------------------------------
say "4-8. the browser, counting"
cat > "$UI_DIR/e2e/hobbyist-live.spec.ts" <<'SPEC'
import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";

const BASE = process.env.EP_BASE ?? "http://127.0.0.1:8179";
const PASS = process.env.EP_PASS ?? "";
const OUT = process.env.EP_OUT ?? "hobbyist.json";
const MESSAGE = "Say hello in five words.";

/**
 * The counters, installed in the page rather than kept in the test.
 *
 * §7 S10 asks for "real pointer actions and keystrokes". A helper that
 * clicks two things in one call would report one, and a helper that sets
 * a field's value without typing would report no keystrokes -- so the
 * page counts what the browser actually dispatched, in the capture
 * phase, and the totals survive navigation in sessionStorage.
 */
const COUNTER = `
(() => {
  const read = () => { try { return JSON.parse(sessionStorage.getItem('__ep_count') || '{}'); } catch { return {}; } };
  const write = (o) => { try { sessionStorage.setItem('__ep_count', JSON.stringify(o)); } catch {} };
  const bump = (k, v) => {
    const o = read();
    o[k] = (o[k] || 0) + 1;
    if (v !== undefined) { o.typed = o.typed || []; if (v && !o.typed.includes(v)) o.typed.push(v); }
    write(o);
  };
  if (!window.__epCounting) {
    window.__epCounting = true;
    document.addEventListener('pointerdown', () => bump('clicks'), true);
    document.addEventListener('keydown', (e) => { if (e.key.length === 1 || e.key === 'Enter') bump('keys'); }, true);
    document.addEventListener('change', (e) => {
      const t = e.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA') && typeof t.value === 'string' && t.value !== '') {
        bump('changes', t.value);
      }
    }, true);
  }
})();
`;

async function counters(page: import("@playwright/test").Page) {
  return await page.evaluate(() => {
    try {
      return JSON.parse(sessionStorage.getItem("__ep_count") || "{}") as Record<string, never>;
    } catch {
      return {} as Record<string, never>;
    }
  });
}

/** Anything a person would have had to know their own filesystem to type. */
function looksLikePath(s: string): boolean {
  return /^[A-Za-z]:[\\/]/.test(s) || s.startsWith("\\\\") || s.startsWith("/") || /[\\/]/.test(s);
}

async function signIn(page: import("@playwright/test").Page) {
  await page.goto(`${BASE}/login`);
  const box = page.getByLabel(/passphrase/i).first();
  await box.waitFor({ state: "visible" });
  await expect(async () => {
    await box.fill(PASS);
    expect(await box.inputValue()).toBe(PASS);
  }).toPass({ timeout: 15000 });
  await page.getByRole("button", { name: /unlock|sign in/i }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 20000 });
}

test.describe.configure({ mode: "serial" });

let report: Record<string, unknown> = {};
const save = () => writeFileSync(OUT, JSON.stringify(report, null, 2));

test("from the wizard to a first reply", async ({ page }) => {
  // The arc installs an engine over the network and loads a model, and
  // Playwright's per-test cap overrides every locator timeout under it --
  // the first execution timed out at 180 s inside a `waitFor(900000)`,
  // which reads as the product being slow when it is the harness being
  // short.
  test.setTimeout(1_200_000);
  await page.addInitScript(COUNTER);
  const started = Date.now();
  let offeredRun = false;
  await page.goto(BASE);

  // 1 of 2 -- the passphrase, typed twice because it is a secret. The
  // only value on the whole path that a person invents.
  await expect(page.getByRole("heading", { name: /^Choose a passphrase$/ })).toBeVisible({
    timeout: 60000,
  });
  const fields = page.locator('input[type="password"]');
  await expect(fields).toHaveCount(2);
  await fields.nth(0).fill(PASS);
  await fields.nth(1).fill(PASS);
  await expect(page.getByRole("button", { name: /Continue/ })).toBeEnabled();
  await page.getByRole("button", { name: /Continue/ }).click();

  // 2 of 2 -- where models live. The proposed folder is taken as it
  // stands: no Browse, nothing typed. That is the target.
  await expect(page.getByRole("heading", { name: /^Where should models live\?$/ })).toBeVisible({
    timeout: 120000,
  });
  await expect(page.getByRole("radio", { name: /Make a folder for me/ })).toBeChecked();
  await page.getByRole("button", { name: /^Finish$/ }).click();

  // Home.
  await page.getByTestId("home").waitFor({ state: "visible", timeout: 180000 });

  // One model already on this person's disk, so the card's primary
  // action is Run -- and WHICH action it is is the assertion, not the
  // setup.
  //
  // The third execution clicked `home-primary` and got a 16 GB
  // download, because `home-primary` is the testid of the NO-MODELS
  // branches and the one-model branch renders a `run-button` instead.
  // So a spec that waits for `home-primary` cannot tell "Run was
  // offered" from "Run was not offered": it silently measures the
  // wrong journey. Waiting for the Run button and failing if the
  // download card is what appeared makes the wizard-scan regression a
  // check rather than a surprise.
  const runButton = page.getByTestId("run-button");
  const downloadInstead = page.getByTestId("home-primary");
  await Promise.race([
    runButton.waitFor({ state: "visible", timeout: 120000 }),
    downloadInstead.waitFor({ state: "visible", timeout: 120000 }),
  ]);
  offeredRun = await runButton.isVisible();
  expect(
    offeredRun,
    "Home offered a download beside a folder that already holds a model: " +
      "the wizard did not look in the folder it was just given",
  ).toBe(true);
  await runButton.click();

  // The one question decision #6 asks before installing an engine. On a
  // machine with nothing on it this always appears, and answering it is
  // part of the journey rather than an accident of the harness.
  //
  // **Raced against the composer, not given a fixed window.** The first
  // two executions waited 20 s for the dialog, swallowed the timeout as
  // "llama.cpp was already there", and then waited fifteen minutes for a
  // composer a modal was covering. The check on a fresh install is slower
  // than that, and how long it takes is not the subject -- whether it is
  // asked at all is.
  const dialog = page.getByTestId("run-dialog");
  const composer = page.getByTestId("home-composer");
  await Promise.race([
    dialog.waitFor({ state: "visible", timeout: 300000 }),
    composer.waitFor({ state: "visible", timeout: 300000 }),
  ]);
  const askedAboutEngine = await dialog.isVisible();
  if (askedAboutEngine) await page.getByTestId("run-install").click();

  // Try it, in place on Home. The engine may have to be fetched and the
  // model loaded first, so this is the long wait in the arc.
  await composer.waitFor({ state: "visible", timeout: 900000 });
  await expect(composer).toBeEnabled({ timeout: 900000 });
  await composer.fill(MESSAGE);
  await page.getByRole("button", { name: /^Send$/ }).click();

  // A reply, from a file on their own disk. `home-turn-info` is written
  // when the turn completes, so it is the honest "it answered" signal.
  const turn = page.getByTestId("home-turn-info");
  await turn.waitFor({ state: "visible", timeout: 600000 });
  const transcript = (await page.getByTestId("home-try-it").textContent()) ?? "";
  // The transcript panel holds the chrome, the message and the answer.
  // Taking the message back out leaves what the model said, which is the
  // only part that proves a file on this disk produced a reply.
  const reply = transcript.replace(MESSAGE, "").replace(/\s+/g, " ").trim();

  const c = await counters(page);
  const typed: string[] = (c.typed as unknown as string[]) ?? [];
  // The message is typed, obviously. §1's "one typed value" is about
  // values a person has to KNOW -- a passphrase they invent, a path they
  // do not. So the message is excluded and named here rather than
  // quietly dropped.
  const configValues = typed.filter((v) => v !== MESSAGE);
  report = {
    ...report,
    firstReply: {
      clicks: (c.clicks as unknown as number) ?? 0,
      keystrokes: (c.keys as unknown as number) ?? 0,
      typedValues: configValues.length,
      typed: configValues,
      pathsTyped: typed.filter(looksLikePath),
      askedAboutEngine,
      offeredRun,
      seconds: Math.round((Date.now() - started) / 1000),
      turn: (await turn.textContent())?.trim() ?? "",
      reply: reply.slice(0, 300),
      transcript: transcript.slice(0, 200),
    },
  };
  save();
});

test("a tool connected", async ({ page }) => {
  await page.addInitScript(COUNTER);
  await signIn(page);
  // The count starts at Home, signed in: §1's target is "≤ 3 clicks FROM
  // HOME".
  await page.goto(BASE);
  const card = page.getByTestId("home-use-from-apps");
  await card.waitFor({ state: "visible", timeout: 60000 });
  await page.evaluate(() => sessionStorage.removeItem("__ep_count"));

  await card.getByTestId("make-key").click();
  await card.getByTestId("fresh-key").waitFor({ state: "visible", timeout: 30000 });

  const address = (await card.getByTestId("base-url").textContent())?.trim() ?? "";
  const model = (await card.getByTestId("app-model").first().textContent())?.trim() ?? "";
  const key = (await card.getByTestId("fresh-key").textContent())?.trim() ?? "";
  const cardText = (await card.textContent()) ?? "";

  const c = await counters(page);
  report = {
    ...report,
    connect: {
      clicks: (c.clicks as unknown as number) ?? 0,
      address,
      model,
      key,
      lifetime: /good for a year/i.test(cardText) ? "a year" : "",
    },
  };
  save();
});

test("reachable from another device", async ({ page }) => {
  await signIn(page);
  await page.goto(BASE);
  const card = page.getByTestId("home-reach");
  await card.waitFor({ state: "visible", timeout: 60000 });
  report = {
    ...report,
    reach: {
      switches: await card.getByTestId("reach-switch").count(),
      headline: (await card.getByTestId("reach-headline").textContent())?.trim() ?? "",
    },
  };
  save();
});

test("the words on the golden path", async ({ page }) => {
  await signIn(page);
  // S8's two instruments, run here so S10 has the number S8 must drive
  // down. Only Home is a gate today, because only Home has been written
  // to the rule.
  const BANNED = [
    "companion driver",
    "declaration",
    "admission",
    "epoch",
    "advertiseurl",
    "trust root",
    "topology",
    "routing table",
  ];
  const screens: Record<string, string> = {};
  for (const [name, path] of [
    ["home", "/"],
    ["library", "/library"],
    ["discover", "/discover"],
    ["playground", "/playground"],
  ] as const) {
    await page.goto(`${BASE}${path}`);
    await page.waitForTimeout(3000);
    screens[name] = ((await page.locator("body").textContent()) ?? "").toLowerCase();
  }
  const banned: Record<string, string[]> = {};
  const longSentences: Record<string, number> = {};
  for (const [name, text] of Object.entries(screens)) {
    banned[name] = BANNED.filter((w) => text.includes(w));
    longSentences[name] = text
      .split(/[.!?]\s/)
      .filter((s) => s.trim().split(/\s+/).length > 25).length;
  }
  report = { ...report, words: { banned, longSentences } };
  save();
});
SPEC

REPORT="$WORK/hobbyist.json"
(cd "$UI_DIR" && EP_BASE="$BASE" EP_PASS="$PASS" EP_OUT="$(win_path "$REPORT")" \
  npx playwright test e2e/hobbyist-live.spec.ts --reporter=line > "$WORK/e2e.log" 2>&1)
PW=$?
echo "  $(grep -E 'passed|failed' "$WORK/e2e.log" | tail -1)"
[ "$PW" = "0" ] || { bad "the browser arc did not complete"; tail -40 "$WORK/e2e.log"; }
[ -f "$REPORT" ] || { bad "no measurement written"; exit 1; }

# --- 4 -----------------------------------------------------------------------
say "4. a first reply in the browser"
CLICKS=$(jq_ "d['firstReply']['clicks']" < "$REPORT")
KEYS=$(jq_ "d['firstReply']['keystrokes']" < "$REPORT")
NTYPED=$(jq_ "d['firstReply']['typedValues']" < "$REPORT")
PATHS=$(jq_ "len(d['firstReply']['pathsTyped'])" < "$REPORT")
SECS=$(jq_ "d['firstReply']['seconds']" < "$REPORT")
TEXT=$(jq_ "d['firstReply']['reply']" < "$REPORT")
[ "$CLICKS" -le "$BUDGET_CLICKS" ] \
  && ok "4a. $CLICKS clicks from the wizard to a reply (budget $BUDGET_CLICKS; §0.2 measured 15)" \
  || bad "4a. $CLICKS clicks, over the budget of $BUDGET_CLICKS"
[ "$NTYPED" -le 1 ] \
  && ok "4b. one typed value ($KEYS keystrokes), and it is the passphrase" \
  || bad "4b. $NTYPED distinct values typed: $(jq_ "d['firstReply']['typed']" < "$REPORT")"
RANIT=$(jq_ "d['firstReply']['offeredRun']" < "$REPORT")
[ "$RANIT" = "True" ] \
  && ok "4e. Home offered to RUN the model already on disk, not to download one" \
  || bad "4e. Home offered a download beside a folder holding a model -- the wizard did not look in the folder it was given"
[ "$PATHS" = "0" ] \
  && ok "4c. no filesystem path was typed" \
  || bad "4c. a path was typed: $(jq_ "d['firstReply']['pathsTyped']" < "$REPORT")"
[ -n "$TEXT" ] \
  && ok "4d. a model on this person's own disk replied in ${SECS}s: '$(printf '%s' "$TEXT" | head -c 60)'" \
  || bad "4d. no reply text"

# --- 5 -----------------------------------------------------------------------
say "5. a tool connected"
CCLICKS=$(jq_ "d['connect']['clicks']" < "$REPORT")
ADDR=$(jq_ "d['connect']['address']" < "$REPORT")
MODEL_ID=$(jq_ "d['connect']['model']" < "$REPORT")
KEY=$(jq_ "d['connect']['key']" < "$REPORT")
EXPIRY=$(jq_ "d['connect']['lifetime']" < "$REPORT")
[ "$CCLICKS" -le "$BUDGET_CONNECT_CLICKS" ] \
  && ok "5. $CCLICKS clicks from Home to address + key + model (budget $BUDGET_CONNECT_CLICKS; §0.2 measured 19)" \
  || bad "5. $CCLICKS clicks, over the budget of $BUDGET_CONNECT_CLICKS"

# --- 6 -----------------------------------------------------------------------
say "6. the three strings, in a plain curl"
# Nothing else: no session token, no proxy, no UI. What a person pastes
# into Continue or Cline is these three values and nothing more.
if [ -n "$ADDR" ] && [ -n "$KEY" ] && [ -n "$MODEL_ID" ]; then
  # **256, not 16.** The third execution asked for 16 and got a 200 with
  # an empty `content`: the starter models are hybrid reasoning models,
  # whose first tokens are a thinking block the gateway strips, so a
  # budget that small can be spent before a single word of the answer
  # arrives. The check would have read a working install as a broken
  # one. The subject here is whether the three strings Home gave are
  # enough on their own -- not how terse the model can be.
  R=$(curl -s -m 180 "$ADDR/chat/completions" -H "Authorization: Bearer $KEY" \
      -H 'content-type: application/json' \
      -d "{\"model\":\"$MODEL_ID\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hi.\"}],\"max_tokens\":256}")
  CONTENT=$(printf '%s' "$R" | jq_ "d['choices'][0]['message']['content']" 2>/dev/null)
  FINISH=$(printf '%s' "$R" | jq_ "d['choices'][0]['finish_reason']" 2>/dev/null)
  [ -n "$CONTENT" ] \
    && ok "6. curl with only those three strings got ($FINISH): '$(printf '%s' "$CONTENT" | tr -d '\n' | head -c 60)'" \
    || bad "6. the three strings did not work (finish_reason=$FINISH): $(printf '%s' "$R" | head -c 400)"
else
  bad "6. Home did not give all three strings (address='$ADDR' model='$MODEL_ID' key='${KEY:0:8}...')"
fi

# --- 7 -----------------------------------------------------------------------
say "7. the key outlives the fortnight"
# §0.2's complaint: the only key was the 14-day session token, so every
# tool a person connected stopped working inside a fortnight.
if printf '%s' "$EXPIRY" | grep -qiE "year|month|[0-9]{3,} days"; then
  ok "7. the key is described as '$EXPIRY' -- past the $KEY_MIN_DAYS-day session token"
else
  bad "7. the key's lifetime reads '$EXPIRY', which does not clear $KEY_MIN_DAYS days"
fi

# --- 8 -----------------------------------------------------------------------
say "8. reachable from another device"
SWITCHES=$(jq_ "d['reach']['switches']" < "$REPORT")
HEADLINE=$(jq_ "d['reach']['headline']" < "$REPORT")
[ "$SWITCHES" = "1" ] \
  && ok "8. one switch, and it says: '$(printf '%s' "$HEADLINE" | head -c 80)'" \
  || bad "8. Home offers $SWITCHES reach switches, not one"

# --- 9 -----------------------------------------------------------------------
say "9. the words on the golden path (S8's instruments)"
BANNED_TOTAL=$(jq_ "sum(len(v) for v in d['words']['banned'].values())" < "$REPORT")
HOME_BANNED=$(jq_ "len(d['words']['banned']['home'])" < "$REPORT")
[ "$HOME_BANNED" = "0" ] \
  && ok "9. Home uses none of the banned words" \
  || bad "9. Home uses: $(jq_ "d['words']['banned']['home']" < "$REPORT")"
# S8 is not built, so the rest is a measurement rather than a gate: this
# is the number S8 has to drive to zero.
note "banned words across Home/Library/Discover/Playground: $BANNED_TOTAL -- $(jq_ "d['words']['banned']" < "$REPORT")"
note "sentences over 25 words: $(jq_ "d['words']['longSentences']" < "$REPORT")"

# --- 10 ----------------------------------------------------------------------
say "10. teardown"
teardown; A_PID=""
STILL=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && STILL="$STILL $p"; done
[ -z "$STILL" ]   && ok "10. none of the four ports this run owned is still listening ($OWNED_PORTS)"   || bad "10. still held:$STILL"
BACK=$(powershell.exe -NoProfile -NonInteractive -Command \
  "[Environment]::GetEnvironmentVariable('EUGENE_PLEXUS_AGENT_CONFIG_FILE','User')" 2>/dev/null | tr -d '\r')
[ "$BACK" = "$SAVED_CONFIG_VAR" ] \
  && ok "10. the account's config variable is as it was" \
  || bad "10. the account variable is '$BACK', not '$SAVED_CONFIG_VAR'"

say "the budget"
printf '  install           %ss\n' "$T_INSTALL"
printf '  first reply       %s clicks, %s keystrokes, %s typed value(s), %ss\n' "$CLICKS" "$KEYS" "$NTYPED" "$SECS"
printf '  tool connected    %s clicks from Home\n' "$CCLICKS"
printf '  reach             %s switch\n' "$SWITCHES"

say "done"
if [ "$FAILURES" -eq 0 ]; then printf '\nALL CHECKS PASSED\n'; else printf '\n%s CHECK(S) FAILED\n' "$FAILURES"; exit 1; fi
