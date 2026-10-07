// J14a.3 in the system Chrome, driven by j14a3-browser-check.py, which owns the
// server. Playwright comes from the ui checkout. Prints JSON: checks and any
// problems the page reported.
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";

const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
const require = createRequire(cfg.playwright + "/");
const { chromium } = require(cfg.playwright);
const out = { checks: [], problems: [] };

function check(number, claim, passed, detail = "") {
  out.checks.push([
    number,
    claim,
    Boolean(passed),
    typeof detail === "string" ? detail : JSON.stringify(detail),
  ]);
}

const chrome = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
].find((p) => existsSync(p));
const browser = await chromium.launch({
  executablePath: chrome,
  headless: true,
  args: [
    `--host-resolver-rules=MAP ${cfg.name} 127.0.0.1`,
    `--ignore-certificate-errors-spki-list=${cfg.pin}`,
  ],
});

try {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on("pageerror", (e) => out.problems.push(`pageerror: ${e.message}`));
  const cdp = await context.newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  const { authenticatorId } = await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });
  await page.goto(cfg.base + "/");
  await page.waitForFunction(() => window.ready === true, null, { timeout: 15000 });

  const secure = await page.evaluate(() => window.isSecureContext && window.wb.passkeysHere());
  // 1-3: make, pair with the code as a person types it, and a wrong code.
  const paired = await page.evaluate(
    async ({ site, owner, name }) => {
      const post = async (path, body) =>
        (await fetch(path, { method: "POST", body: JSON.stringify(body ?? {}) })).json();
      // Before any key: one rule on the root's word, so there are rules to approve.
      const unsigned = await post("/manage/settings.set", { ownerInDevMode: true });
      const code = (await post("/code")).code;
      const made = await window.wb.makePasskey({
        rpId: name,
        person: owner,
        name: "ada",
        exclude: [],
      });
      const binding = { site, person: owner, ...made, rpId: name };
      const wrongCode = code.slice(0, -1) + (code.endsWith("0") ? "1" : "0");
      const wrongMac = await window.wb.pairingMac(wrongCode.toLowerCase(), binding);
      const wrong = await post("/manage/passkey.pair", {
        ...made,
        rpId: name,
        label: "Chrome check",
        mac: wrongMac,
      });
      const mac = await window.wb.pairingMac(code.toLowerCase(), binding);
      const pair = await post("/manage/passkey.pair", {
        ...made,
        rpId: name,
        label: "Chrome check",
        mac,
      });
      return { unsigned, code, made, wrong, pair };
    },
    { site: cfg.site, owner: cfg.owner, name: cfg.name },
  );
  check(1, "Chrome made a passkey at an HTTPS name, and the site takes its public key",
    secure && paired.made?.alg === -7 && paired.pair?.status === "done",
    { alg: paired.made?.alg, pair: paired.pair?.status, message: paired.pair?.message });
  check(2, "the MAC Chrome computed from the code typed checks, and the passkey is pinned",
    paired.pair?.status === "done" && paired.pair?.result?.rpId === cfg.name);
  check(3, "one character of the code wrong is refused",
    paired.wrong?.status === "failed" && /does not match/.test(paired.wrong?.message ?? ""),
    paired.wrong?.message ?? "");

  // 4-6: approve the rules, then a held change, then a swapped envelope.
  const approved = await page.evaluate(async ({ name }) => {
    const post = async (path, body) =>
      (await fetch(path, { method: "POST", body: JSON.stringify(body ?? {}) })).json();
    const state = async () => (await fetch("/state")).json();
    const key = (await state()).passkeys[0];
    const sign = async (id, envelope) => ({
      id,
      envelope,
      key: key.id,
      ...(await window.wb.signEnvelope(envelope, key.credentialId, name)),
    });
    const before = (await state()).signing;
    let listed = (await post("/manage/held.list", { key: key.id })).result;
    const rules = listed.items.find((i) => i.id === "rules");
    const rulesAnswer = await post("/manage/held.approve", await sign("rules", rules.envelope));
    const afterRules = (await state()).signing;
    // A reduction applies at once (J51); giving access back is held.
    await post("/manage/settings.set", { ownerInDevMode: false });
    const held = await post("/manage/settings.set", { ownerInDevMode: true });
    listed = (await post("/manage/held.list", { key: key.id })).result;
    const change = listed.items.find((i) => i.id !== "rules");
    // 6 first: a valid assertion over another envelope, sent for this change.
    const other = change.envelope.replace('"ownerInDevMode":true', '"ownerInDevMode":false');
    const swapped = await post("/manage/held.approve", await sign(change.id, other));
    const changeAnswer = await post("/manage/held.approve", await sign(change.id, change.envelope));
    const end = await state();
    return { before, rulesAnswer, afterRules, held, swapped, changeAnswer, end };
  }, { name: cfg.name });
  check(4, "Chrome's assertion over the site's rules approves them",
    approved.before === "unconfirmed" && approved.rulesAnswer?.status === "done" &&
      approved.afterRules === "signed",
    { before: approved.before, answer: approved.rulesAnswer, after: approved.afterRules });
  check(5, "a change that gives access is held, and Chrome's assertion applies it",
    approved.held?.status === "held" && approved.changeAnswer?.status === "done" &&
      approved.end.ownerInDevMode === true && approved.end.signing === "signed",
    { held: approved.held?.status, answer: approved.changeAnswer });
  check(6, "an assertion over another envelope is refused for that reason",
    approved.swapped?.status === "failed" && /differs|something other/.test(approved.swapped?.message ?? ""),
    approved.swapped?.message ?? "");

  // 7: an authenticator that cannot verify the person.
  await cdp.send("WebAuthn.setUserVerified", { authenticatorId, isUserVerified: false });
  const unverified = await page.evaluate(async ({ name }) => {
    const key = (await (await fetch("/state")).json()).passkeys[0];
    try {
      await window.wb.signEnvelope('{"x":1}', key.credentialId, name);
      return "signed";
    } catch (error) {
      return `${error.name}: ${error.message}`;
    }
  }, { name: cfg.name });
  check(7, "Chrome refuses to sign without verifying the person (userVerification: required)",
    unverified !== "signed", unverified);
} catch (error) {
  out.problems.push(`driver: ${error.stack || error}`);
} finally {
  await browser.close();
}
process.stdout.write(JSON.stringify(out));
