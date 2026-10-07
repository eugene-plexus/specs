// J14a in the system Chrome, driven by j14a-browser-check.py, which owns the
// processes. Playwright comes from the ui checkout. Prints JSON: checks and
// any problems the page reported (a CSP refusal, a page error, a 5xx).
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
const require = createRequire(cfg.playwright + "/");
const { chromium } = require(cfg.playwright);
const out = { checks: [], problems: [] };

function check(number, claim, passed, detail = "") {
  out.checks.push([number, claim, Boolean(passed), typeof detail === "string" ? detail : JSON.stringify(detail)]);
}

const chrome = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
].find((p) => existsSync(p));
const browser = await chromium.launch({ executablePath: chrome, headless: true });

function watch(page, label) {
  page.on("console", (m) => {
    if (/Content Security Policy|Refused/i.test(m.text())) out.problems.push(`${label}: ${m.text()}`);
  });
  page.on("pageerror", (e) => out.problems.push(`${label}: pageerror: ${e.message}`));
  page.on("response", (r) => {
    if (r.status() >= 500) out.problems.push(`${label}: ${r.status()} ${new URL(r.url()).pathname}`);
  });
}

function hold(items) {
  writeFileSync(
    cfg.held,
    JSON.stringify({
      version: 1,
      items: items.map((item, i) => ({
        id: item.id,
        subject: cfg.owner,
        action: item.action,
        arguments: item.arguments,
        names: {},
        heldAt: Date.now() / 1000 - i,
      })),
    }),
  );
}

const state = (page) => page.locator("[data-state]").first();

async function makeKey(page, label) {
  await page.goto(`${cfg.base}/link`);
  await page.waitForSelector("#site-key [data-make]:not([hidden])", { timeout: 15000 });
  await page.click("#site-key [data-make]");
  await page.waitForURL(`${cfg.base}/link/approve`, { timeout: 15000 });
  await page.waitForFunction(() => !/Checking this browser/.test(document.querySelector("[data-state]")?.textContent || ""));
  return state(page).textContent();
}

/** Approve one listed item by its id. The list empties while it reloads, so
 * a count is no signal: the next click waits for its own button. */
async function approve(page, id) {
  await page.click(`[data-approve="${id}"]`, { timeout: 15000 });
  await page.waitForSelector(`[data-approve="${id}"]`, { state: "detached", timeout: 15000 });
}

async function settled(page, pattern) {
  await page.waitForFunction(
    (source) => new RegExp(source).test(document.querySelector("[data-state]")?.textContent || ""),
    pattern.source,
    { timeout: 15000 },
  );
  return state(page).textContent();
}

try {
  // --- an Ed25519 key, the browser's own choice --------------------------------------
  const first = await browser.newContext();
  const page = await first.newPage();
  watch(page, "ed25519");
  const said = await makeKey(page);
  check(1, "Chrome makes a key on the link page, the agent pins it, and the page goes to approvals", /Signing with your key/.test(said), said);
  const titles = await page.locator(".held h2").allTextContents();
  check(
    2,
    "the rules made on the root's word come first, as a whole (J52), then the held change (J50)",
    titles[0] === "Approve this machine's rules" && titles[1] === "A change from Workbench",
    titles,
  );
  const words = await page.locator(".held").first().textContent();
  check(3, "the rules are shown in the site host's own words", /Folder “Notes” \(C:\\Notes\), read only: you \(read\)/.test(words), words);
  const stored = await page.evaluate(async () => {
    const db = await new Promise((resolve, reject) => {
      const r = indexedDB.open("eugene-plexus-site-keys", 1);
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
    const keys = await new Promise((resolve) => {
      const r = db.transaction("keys").objectStore("keys").getAll();
      r.onsuccess = () => resolve(r.result);
    });
    const key = keys[0];
    let exported = "exported";
    try {
      await crypto.subtle.exportKey("pkcs8", key.privateKey);
    } catch (error) {
      exported = error.name;
    }
    return { count: keys.length, alg: key.alg, extractable: key.privateKey.extractable, exported };
  });
  check(
    4,
    "the private half is in IndexedDB, non-extractable: WebCrypto refuses to export it to the page's own script",
    stored.count === 1 && stored.alg === "Ed25519" && stored.extractable === false && stored.exported === "InvalidAccessError",
    stored,
  );
  await approve(page, "rules");
  await approve(page, "a1b2c3d4e5f60718");
  const done = await settled(page, /Nothing is waiting/);
  check(5, "both approved in Chrome and taken by the site host's verifier", /Nothing is waiting/.test(done), done);

  // --- an ECDSA P-256 key, where Ed25519 is withheld -------------------------------------
  hold([
    {
      id: "b1b2c3d4e5f60718",
      action: "folder.people",
      arguments: {
        id: "f".repeat(32),
        people: [
          { subject: cfg.owner, writable: false },
          { subject: "person-bo", writable: false },
        ],
      },
    },
    { id: "c1b2c3d4e5f60718", action: "settings.set", arguments: { ownerInDevMode: true } },
  ]);
  const second = await browser.newContext();
  await second.addInitScript(() => {
    const generate = crypto.subtle.generateKey.bind(crypto.subtle);
    crypto.subtle.generateKey = (algorithm, ...rest) =>
      algorithm && algorithm.name === "Ed25519"
        ? Promise.reject(new DOMException("withheld", "NotSupportedError"))
        : generate(algorithm, ...rest);
  });
  const other = await second.newPage();
  watch(other, "es256");
  await makeKey(other);
  const alg = await other.evaluate(async () => {
    const db = await new Promise((resolve) => {
      const r = indexedDB.open("eugene-plexus-site-keys", 1);
      r.onsuccess = () => resolve(r.result);
    });
    return new Promise((resolve) => {
      const r = db.transaction("keys").objectStore("keys").getAll();
      r.onsuccess = () => resolve(r.result.map((k) => k.alg));
    });
  });
  check(6, "without Ed25519 the page falls back to ECDSA P-256", JSON.stringify(alg) === '["ES256"]', alg);
  const list = await other.locator(".held").allTextContents();
  check(
    7,
    "the change is shown as the site host words it, new people marked",
    list.some((t) => /Who may use “Notes”/.test(t) && /person-bo\): read \(new\)/.test(t)),
    list,
  );
  await approve(other, "b1b2c3d4e5f60718");
  await approve(other, "c1b2c3d4e5f60718");
  const after = await settled(other, /Nothing is waiting/);
  check(8, "WebCrypto's r||s P-256 signatures verify at the site host", /Nothing is waiting/.test(after), after);
  // A turned-down change goes, signs nothing.
  hold([{ id: "d1b2c3d4e5f60718", action: "settings.set", arguments: { ownerInDevMode: true } }]);
  await other.reload();
  await other.waitForSelector("[data-reject]");
  await other.click("[data-reject]");
  await other.waitForFunction(() => /Nothing is waiting/.test(document.querySelector("[data-state]")?.textContent || ""));
  check(9, "a change turned down at the machine is dropped", true);
} catch (error) {
  out.problems.push(`run: ${error && error.stack ? error.stack : error}`);
} finally {
  await browser.close();
}
process.stdout.write(JSON.stringify(out));
