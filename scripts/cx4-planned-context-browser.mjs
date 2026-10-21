/** CX4 browser half: the one planned context on Home and Discover. Driven by
 * cx4-planned-context-acceptance.py; nothing is intercepted. */
import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
const require = createRequire(new URL("../../ui/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const [settingsFile] = process.argv.slice(2);
const { url, output, passphrase, planned } = JSON.parse(await readFile(settingsFile, "utf8"));
const report = { errors: [] };
const save = () => writeFile(join(output, "browser.json"), JSON.stringify(report, null, 2));
const browser = await chromium.launch({ channel: "chrome", headless: true });
let page;

let token;
async function library(method, path, body) {
  if (!token) {
    const login = await fetch(url + "/v1/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ passphrase }),
    });
    token = (await login.json()).sessionToken;
  }
  const response = await fetch(`${url}/api/proxy/library${path}`, {
    method,
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${await response.text()}`);
  return response.json();
}

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

  // Setup, as a person does it.
  await expect(page.getByRole("heading", { name: "Choose a passphrase", exact: true })).toBeVisible({ timeout: 60000 });
  const fields = page.locator('input[type="password"]');
  await fields.nth(0).fill(passphrase);
  await fields.nth(1).fill(passphrase);
  // Stay on prompt_on_startup: os_keyring would write this disposable
  // install's key into the account's real credential store.
  const unlock = page.getByRole("checkbox", { name: /unlock eugene on its own/i });
  if ((await unlock.count()) && (await unlock.isChecked()) && (await unlock.isEnabled())) await unlock.uncheck();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Where should models live?", exact: true })).toBeVisible({ timeout: 120000 });
  const finish = page.getByRole("button", { name: "Finish", exact: true });
  await expect(finish).toBeEnabled({ timeout: 60000 });
  await finish.click();
  await expect(page.getByTestId("home")).toBeVisible({ timeout: 120000 });

  // The default, then the one setting changed where Settings changes it.
  report.defaultPlanned = (await library("GET", "/v1/config")).guidanceContextLength;
  await library("PATCH", "/v1/config", { guidanceContextLength: planned });

  // Home's first model says it.
  await page.goto(url);
  const homeNote = page.getByTestId("home-first-model").getByTestId("planned-context");
  await expect(homeNote).toContainText("32k", { timeout: 60000 });
  report.homeNote = await homeNote.textContent();

  // Discover starts there; a try is for this visit only.
  await page.goto(url + "/discover");
  const control = page.getByLabel("Context length to score against");
  await expect(control).toHaveValue(String(planned), { timeout: 60000 });
  report.discoverContext = await control.inputValue();
  await control.selectOption("8192");
  await expect(page.getByTestId("planned-context")).toContainText("Trying 8k here only");
  await page.reload();
  await expect(control).toHaveValue(String(planned), { timeout: 60000 });
  report.discoverAfterReload = await control.inputValue();
  await save();
} catch (error) {
  report.failure = String(error?.stack || error);
  if (page) await page.screenshot({ path: join(output, "failure.png"), fullPage: true }).catch(() => {});
  await save();
  process.exitCode = 1;
} finally {
  await browser.close();
}
