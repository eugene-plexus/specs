/** CX2 browser half: fail the root's initialize, come back, resume. Driven by
 * cx2-setup-resume-acceptance.py; the only interception is that one failure. */
import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
const require = createRequire(new URL("../../ui/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const [settingsFile] = process.argv.slice(2);
const { url, output, passphrase, control } = JSON.parse(await readFile(settingsFile, "utf8"));
const report = { errors: [], agentInitializeCalls: 0, controlInitialized: {} };
const save = () => writeFile(join(output, "browser.json"), JSON.stringify(report, null, 2));
// The root's own answer, not the UI's account of it.
const rootInitialized = async () => (await (await fetch(control + "/v1/auth/status")).json()).initialized;
const browser = await chromium.launch({ channel: "chrome", headless: true });
let page;
function watch(context) {
  context.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/proxy/agent/v1/auth/initialize"))
      report.agentInitializeCalls++;
  });
}
try {
  // 1. A first run whose root initialize fails after the agent's passphrase is set.
  const first = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  watch(first);
  await first.route("**/api/proxy/control/v1/auth/initialize", (route) =>
    route.fulfill({
      status: 500,
      contentType: "application/problem+json",
      body: JSON.stringify({ title: "Injected failure", detail: "CX2 acceptance: the root refused." }),
    }),
  );
  page = await first.newPage();
  page.setDefaultTimeout(30000);
  page.on("pageerror", (error) => report.errors.push(String(error)));
  await expect(async () => {
    const response = await page.goto(url, { timeout: 5000 });
    if (response.status() !== 200) throw new Error(`status ${response.status()}`);
  }).toPass({ timeout: 30000, intervals: [500, 1000] });
  await expect(page.getByRole("heading", { name: "Choose a passphrase", exact: true })).toBeVisible({ timeout: 60000 });
  const fields = page.locator('input[type="password"]');
  await fields.nth(0).fill(passphrase);
  await fields.nth(1).fill(passphrase);
  // Stay on prompt_on_startup: os_keyring would write this disposable
  // install's key into the account's real credential store.
  const unlock = page.getByRole("checkbox", { name: /unlock eugene on its own/i });
  if ((await unlock.count()) && (await unlock.isChecked()) && (await unlock.isEnabled())) await unlock.uncheck();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("button", { name: "Try again", exact: true })).toBeVisible({ timeout: 60000 });
  report.failureMessage = await page.getByRole("alert").textContent();
  report.controlInitialized.afterFailure = await rootInitialized();
  await first.close();

  // 2. Later, a new browser: no session. The console sends it to sign in.
  const later = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  watch(later);
  page = await later.newPage();
  page.setDefaultTimeout(30000);
  page.on("pageerror", (error) => report.errors.push(String(error)));
  await page.goto(url);
  await page.waitForURL(/\/login/, { timeout: 30000 });
  await page.locator("#passphrase").fill(passphrase);
  await page.getByRole("button", { name: "Unlock", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Finish setting up this install", exact: true })).toBeVisible({ timeout: 60000 });
  report.stepsLeft = await page.getByTestId("steps-left").textContent();

  // 3. A wrong passphrase goes nowhere near the root.
  const box = page.getByLabel("Passphrase", { exact: true });
  await box.fill("not-the-passphrase-at-all");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(/not this install's passphrase/i, { timeout: 30000 });
  report.wrongPassphraseMessage = await page.getByRole("alert").textContent();
  report.controlInitialized.afterWrongPassphrase = await rootInitialized();

  // 4. The right one carries on, then Finish.
  await box.fill(passphrase);
  await page.getByRole("button", { name: /^(Continue|Try again)$/ }).click();
  await expect(page.getByRole("heading", { name: "Where should models live?", exact: true })).toBeVisible({ timeout: 120000 });
  const finish = page.getByRole("button", { name: "Finish", exact: true });
  await expect(finish).toBeEnabled({ timeout: 60000 });
  await finish.click();
  await expect(page.getByTestId("home")).toBeVisible({ timeout: 120000 });
  report.reachedHome = true;
  await save();
} catch (error) {
  report.failure = String(error?.stack || error);
  if (page) await page.screenshot({ path: join(output, "failure.png"), fullPage: true }).catch(() => {});
  await save();
  process.exitCode = 1;
} finally {
  await browser.close();
}
