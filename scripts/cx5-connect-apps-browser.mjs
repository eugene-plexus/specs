/** CX5 browser half: a fresh install with no model; Connect apps still
 * shows the address and manages keys, and Home, Settings and the old anchor
 * lead there. Driven by cx5-connect-apps-acceptance.py. No interception. */
import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
const require = createRequire(new URL("../../ui/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const [settingsFile] = process.argv.slice(2);
const { url, output, passphrase } = JSON.parse(await readFile(settingsFile, "utf8"));
const report = { errors: [] };
const save = () => writeFile(join(output, "browser.json"), JSON.stringify(report, null, 2));
const browser = await chromium.launch({ channel: "chrome", headless: true });
let page;
try {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  page = await context.newPage();
  page.setDefaultTimeout(30000);
  page.on("pageerror", (error) => report.errors.push(String(error)));
  // Every refused request, with the component's own reason: a 401 on a
  // session clears it, so the reason is the evidence (library#15).
  report.refused = [];
  page.on("response", async (response) => {
    if (response.status() !== 401) return;
    const entry = { at: new Date().toISOString(), url: response.url(), status: 401 };
    report.refused.push(entry);
    entry.body = await response.text().catch((error) => `unreadable: ${error.message}`);
  });
  await expect(async () => {
    const response = await page.goto(url, { timeout: 5000 });
    if (response.status() !== 200) throw new Error(`status ${response.status()}`);
  }).toPass({ timeout: 30000, intervals: [500, 1000] });

  // Set up with no model: a passphrase, then Finish on the proposed folder.
  await expect(page.getByRole("heading", { name: "Choose a passphrase", exact: true })).toBeVisible({ timeout: 60000 });
  const fields = page.locator('input[type="password"]');
  await fields.nth(0).fill(passphrase);
  await fields.nth(1).fill(passphrase);
  const unlock = page.getByRole("checkbox", { name: /unlock eugene on its own/i });
  if ((await unlock.count()) && (await unlock.isChecked()) && (await unlock.isEnabled())) await unlock.uncheck();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Where should models live?", exact: true })).toBeVisible({ timeout: 120000 });
  const finish = page.getByRole("button", { name: "Finish", exact: true });
  await expect(finish).toBeEnabled({ timeout: 60000 });
  await finish.click();
  await expect(page.getByTestId("home")).toBeVisible({ timeout: 120000 });

  // Home: the line is there with no model, and leads to Connect apps.
  const line = page.getByTestId("home-connect-apps");
  await expect(line).toBeVisible({ timeout: 30000 });
  report.homeLine = await line.textContent();
  await line.getByRole("link", { name: /Connect apps/ }).click();
  await page.waitForURL(/\/connect/);

  // Connect apps with nothing served: says so, shows and checks the address.
  await expect(page.getByTestId("connect-no-model")).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId("base-url")).toHaveText(/\/v1$/, { timeout: 30000 });
  report.address = await page.getByTestId("base-url").textContent();
  await expect(page.getByTestId("base-url-verdict")).not.toHaveAttribute("data-verdict", "checking", { timeout: 30000 });
  report.verdict = await page.getByTestId("base-url-verdict").getAttribute("data-verdict");

  // Make a key, then turn it off, with no model running.
  await page.getByTestId("key-name").fill("CX5 acceptance key");
  await page.getByTestId("make-key").click();
  await expect(page.getByTestId("fresh-key")).toBeVisible({ timeout: 30000 });
  report.keyMade = true;
  const row = page.getByTestId("key-list").locator("li", { hasText: "CX5 acceptance key" });
  await row.getByRole("button", { name: "Turn off" }).click();
  await row.getByRole("button", { name: "Turn off" }).click();
  await expect(page.getByTestId("key-list").locator("li", { hasText: "CX5 acceptance key" })).toHaveCount(0, { timeout: 30000 });
  report.keyTurnedOff = true;

  // The old anchor on Home goes to Connect apps.
  await page.goto(url + "/#use-from-apps");
  await page.waitForURL(/\/connect/, { timeout: 30000 });
  report.oldAnchorRedirects = true;
  await save();
} catch (error) {
  report.failure = String(error?.stack || error);
  if (page) await page.screenshot({ path: join(output, "failure.png"), fullPage: true }).catch(() => {});
  await save();
  process.exitCode = 1;
} finally {
  await browser.close();
}
