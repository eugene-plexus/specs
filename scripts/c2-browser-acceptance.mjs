// C2 in a real browser: the sign-in page under its own CSP, and the
// console's People page. Driven by c2-browser-acceptance.py, which owns the
// processes and names the ui checkout whose node_modules has Playwright.
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
const require = createRequire(join(cfg.ui, "package.json"));
const { chromium } = require("playwright-core");
const out = { console: [], steps: {} };
const browser = await chromium.launch({
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  headless: true,
});

function watch(page, label) {
  page.on("console", (m) => {
    if (/Content Security Policy|Refused/i.test(m.text())) {
      out.console.push(`${label}: ${m.type()}: ${m.text()}`);
    }
  });
  // Failed requests are reported by URL: in this harness no gateway or
  // library runs, so the shell's reads of those are expected to fail and
  // only the People page's own reads and writes are held to succeed.
  page.on("response", (r) => {
    if (r.status() >= 400) {
      const path = new URL(r.url()).pathname;
      const own = /\/api\/proxy\/control\/v1\/(people|oidc)/.test(path) || path.startsWith("/oidc");
      (own ? out.console : (out.elsewhere ??= [])).push(`${label}: ${r.status()} ${path}`);
    }
  });
  page.on("pageerror", (e) => out.console.push(`${label}: pageerror: ${e.message}`));
}

async function signIn(label, url, fill) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  watch(page, label);
  await page.goto(url);
  const styled = await page.evaluate(
    () => getComputedStyle(document.querySelector("main")).maxWidth,
  );
  await page.screenshot({ path: `${cfg.shots}/${label}-page.png`, fullPage: true });
  await fill(page);
  await Promise.all([
    page.waitForURL((u) => u.toString().startsWith(cfg.callback), { timeout: 15000 }),
    page.click("button[type=submit]"),
  ]);
  const final = page.url();
  await ctx.close();
  return { final, styled };
}

try {
  out.steps.owner = await signIn("owner", cfg.ownerUrl, async (page) => {
    await page.fill("#password", cfg.passphrase);
  });

  // The console's People page, signed in as the operator.
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript((token) => {
    sessionStorage.setItem("eugene-session-token", token);
  }, cfg.operatorToken);
  const page = await ctx.newPage();
  watch(page, "people");
  await page.goto(`${cfg.console}/people`);
  await page.getByTestId("people-add").waitFor({ timeout: 20000 });
  const address = await page.getByTestId("people-sign-in-address-url").textContent();
  await page.getByText("Add a person").click();
  await page.getByTestId("people-add-name").fill("Ada");
  await page.getByTestId("people-add-password").fill(cfg.adaFirst);
  await page.getByTestId("people-add-submit").click();
  await page.getByTestId("person-Ada").waitFor({ timeout: 15000 });
  await page.getByText("Add another app").click();
  await page.getByTestId("sign-in-app-name").fill("Browser app");
  await page.getByTestId("sign-in-app-addresses").fill(`${cfg.callback}`);
  await page.getByTestId("sign-in-app-submit").click();
  const secret = await page.getByTestId("sign-in-app-secret").textContent({ timeout: 15000 });
  await page.screenshot({ path: `${cfg.shots}/people.png`, fullPage: true });
  await page.getByText("I have copied it").click();
  const secretGone = !(await page.content()).includes(secret ?? "never");
  out.steps.people = { address, secretShown: Boolean(secret && secret.length > 20), secretGone };
  await ctx.close();

  // Ada, now on the install, makes her password her own while signing in.
  writeFileSync(cfg.handoff, JSON.stringify({ ready: true }));
  const adaUrl = await (async () => {
    for (let i = 0; i < 100; i++) {
      try {
        const next = JSON.parse(readFileSync(cfg.handoff, "utf8"));
        if (next.adaUrl) return next.adaUrl;
      } catch {}
      await new Promise((r) => setTimeout(r, 100));
    }
    throw new Error("no authorize URL for Ada");
  })();
  out.steps.ada = await signIn("ada", adaUrl, async (page) => {
    await page.fill("#name", "Ada");
    await page.fill("#password", cfg.adaFirst);
    await page.click("summary");
    await page.fill("#new_password", cfg.adaOwn);
    await page.fill("#new_password_again", cfg.adaOwn);
  });
} catch (e) {
  out.error = String(e && e.stack ? e.stack : e);
} finally {
  await browser.close();
  writeFileSync(cfg.result, JSON.stringify(out, null, 2));
}
