// C3 in a real browser: Workbench's page, under its own Content Security
// Policy, driven the way a person uses it. Driven by
// c3-workbench-acceptance.py --browser, which owns the processes; Playwright
// comes from the ui checkout's node_modules and Chrome is the system one.
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
const require = createRequire(cfg.playwright + "/");
const { chromium } = require(cfg.playwright);
const out = { checks: [], problems: [] };
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

function check(number, claim, passed, detail = "") {
  const said = typeof detail === "string" ? detail : JSON.stringify(detail);
  out.checks.push([number, claim, Boolean(passed), said]);
}

const chrome = [
  cfg.chrome,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].find((p) => p && existsSync(p));
const browser = await chromium.launch({ executablePath: chrome, headless: true });

function watch(page, label) {
  page.on("console", (m) => {
    if (/Content Security Policy|Refused/i.test(m.text())) {
      out.problems.push(`${label}: ${m.type()}: ${m.text()}`);
    }
  });
  page.on("pageerror", (e) => out.problems.push(`${label}: pageerror: ${e.message}`));
  page.on("response", (r) => {
    if (r.status() >= 500) out.problems.push(`${label}: ${r.status()} ${new URL(r.url()).pathname}`);
  });
}

async function mode(value) {
  await fetch(`${cfg.fixture}/mode?value=${value}`, { method: "POST" });
}

const lastAnswer = (page) => page.locator('[data-testid="answer"]').last();

let asked = 0;

/** Sends `text` and remembers how many answers there were before it, so
 * `finished` waits for the new one rather than finding the last one done. */
async function ask(page, text) {
  asked = await page.locator('[data-testid="answer"]').count();
  await page.fill('[data-testid="composer"]', text);
  await page.keyboard.press("Enter");
}

async function finished(page, timeout = 30000) {
  await page.waitForFunction(
    (before) => {
      const all = document.querySelectorAll('[data-testid="answer"]');
      const last = all[all.length - 1];
      return all.length > before && last.getAttribute("data-status") !== "running";
    },
    asked,
    { timeout },
  );
  return lastAnswer(page);
}

/** Waits for the newest answer to show some of its text. */
async function begun(page) {
  const live = Boolean(cfg.live);
  await page.waitForFunction(
    ([before, live]) => {
      const all = document.querySelectorAll('[data-testid="answer"]');
      const text = all[all.length - 1]?.querySelector(".answer")?.textContent ?? "";
      return all.length > before && (live ? text.trim().length > 0 : text.includes("C3-ANSWER"));
    },
    [asked, live],
    { timeout: 120000 },
  );
}

try {
  const context = await browser.newContext();
  let page = await context.newPage();
  watch(page, "owner");

  // 1. Sign in with Eugene, with the passphrase, on Eugene's own page.
  await page.goto(cfg.ui + "/");
  await page.waitForSelector('[data-testid="sign-in"]');
  await page.screenshot({ path: `${cfg.shots}/1-sign-in.png` });
  await page.click('[data-testid="sign-in"]');
  await page.waitForSelector('input[name="password"]');
  // With people on the install the page asks for a name too; the owner's
  // is `operator` (C2 D4).
  if (await page.locator('input[name="name"]').count()) {
    await page.fill('input[name="name"]', "operator");
  }
  await page.fill('input[name="password"]', cfg.passphrase);
  await Promise.all([
    page.waitForURL((u) => u.toString().startsWith(cfg.ui), { timeout: 20000 }),
    page.click("button[type=submit]"),
  ]);
  await page.waitForSelector('[data-testid="me"]', { timeout: 20000 });
  const me = await page.textContent('[data-testid="me"]');
  check("B1", "Chrome signs in with Eugene's passphrase and comes back to Workbench signed in",
    /\(owner\)/.test(me ?? "") && !page.url().includes("#"), me);
  await page.screenshot({ path: `${cfg.shots}/2-signed-in.png` });

  // 2. A chat streams.
  await page.click('[data-testid="new-chat"]');
  await page.waitForURL(/\/chats\//);
  const chatUrl = page.url();
  await ask(page, cfg.live ? "Say hello in one short sentence." : "Hello from Chrome");
  let answer = await finished(page, 120000);
  const said = (await answer.locator(".answer").textContent().catch(() => "")) ?? "";
  check("B2", "a message sent with Enter gets the model's answer, rendered",
    cfg.live ? said.trim().length > 0 : /C3-ANSWER/.test(said), said.slice(0, 60));

  // 3. An image the answer names is a link and is never fetched (W5).
  if (!cfg.live) {
  await mode("image");
  await ask(page, "Show me a diagram");
  answer = await finished(page);
  const images = await answer.locator("img").count();
  const link = await answer.locator("a", { hasText: "[Image: a diagram]" }).count();
  check("B3", "an image an answer names is shown as a link, and no <img> is made for it",
    images === 0 && link === 1, { images, link });
  await mode("plain");

  // 4. An attachment, sent and shown back from a blob: address.
  await page.setInputFiles('[data-testid="attach-input"]', {
    name: "dot.png", mimeType: "image/png", buffer: PNG,
  });
  await page.waitForSelector('ul[aria-label="Attached"] li');
  await ask(page, "What is in this picture?");
  answer = await finished(page);
  const thumb = await page.locator('[data-testid="user-message"] img').last().getAttribute("src");
  check("B4", "an attached image reaches the model, and the page shows it from a blob: address",
    /C3-SAW-IMAGE/.test((await answer.textContent()) ?? "") && /^blob:/.test(thumb ?? ""), thumb);
  }

  // 5. Search the web.
  const toggle = page.locator('[data-testid="search-switch"]');
  const enabled = await toggle.isEnabled();
  if (enabled) await toggle.check();
  await ask(page, cfg.live
    ? "What is Eugene Plexus? Search the web, then answer in two sentences and cite the page."
    : "What is Eugene Plexus?");
  answer = await finished(page, 180000);
  const sources = await answer.locator('[data-testid="sources"] a').count();
  const searched = (await answer.locator('[data-testid="sources"]').textContent().catch(() => "")) ?? "";
  check("B5", cfg.live
    ? "with Search the web on, the answer says it searched, and lists what it cites"
    : "with Search the web on, the answer lists its sources as links",
    enabled && (cfg.live ? /search/.test(searched) : sources >= 1), { enabled, sources, searched });
  await page.screenshot({ path: `${cfg.shots}/3-searched.png`, fullPage: true });
  if (enabled) await toggle.uncheck();

  // 6. Stop.
  await mode("slow");
  await ask(page, cfg.live ? "Write a long story about a carpenter." : "Take your time");
  await page.waitForSelector('[data-testid="stop"]');
  await begun(page);
  await page.click('[data-testid="stop"]');
  answer = await finished(page);
  check("B6", "Stop ends an answer and says so", (await answer.getAttribute("data-status")) === "stopped",
    await answer.locator('[data-testid="answer-status"]').textContent().catch(() => ""));

  // 7. Close the tab mid-answer; another tab finds it finished (W1).
  await ask(page, cfg.live ? "Nobody is watching. Say hi." : "Keep going without me");
  await begun(page);
  const before = asked;
  await page.close();
  await new Promise((r) => setTimeout(r, 6000));
  page = await context.newPage();
  watch(page, "reopened");
  await page.goto(chatUrl);
  asked = before;
  answer = await finished(page, 180000);
  const text = (await answer.textContent()) ?? "";
  check("B7", "an answer whose tab was closed mid-way is whole when the chat is opened again",
    (await answer.getAttribute("data-status")) === "done"
      && (cfg.live ? text.trim().length > 0 : text.includes("fixture model.")), text.slice(0, 80));
  await mode("plain");

  // 8. Nothing the policy refused, no page error.
  check("B8", "no Content Security Policy refusal, page error or server error in any tab",
    out.problems.length === 0, out.problems.slice(0, 5));

  // 10. Sign out.
  await page.click("text=Sign out");
  await page.waitForSelector('[data-testid="sign-in"]');
  check("B10", "Sign out returns to the sign-in screen, saying so",
    (await page.textContent("main"))?.includes("You signed out."), "");
  await page.screenshot({ path: `${cfg.shots}/4-signed-out.png` });
} catch (error) {
  out.error = String(error?.stack ?? error);
  for (const open of browser.contexts().flatMap((c) => c.pages())) {
    await open.screenshot({ path: `${cfg.shots}/failed-${Date.now()}.png` }).catch(() => undefined);
  }
} finally {
  await browser.close();
  writeFileSync(cfg.result, JSON.stringify(out, null, 2));
}
