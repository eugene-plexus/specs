/** CX3 browser half: the engine question at the click, and Escape that only
 * closes. Driven by cx3-ask-first-acceptance.py; nothing is intercepted. */
import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
const require = createRequire(new URL("../../ui/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const [settingsFile] = process.argv.slice(2);
const { url, output, passphrase, waiting, tiny } = JSON.parse(await readFile(settingsFile, "utf8"));
const report = { errors: [], submits: 0 };
const save = () => writeFile(join(output, "browser.json"), JSON.stringify(report, null, 2));
const browser = await chromium.launch({ channel: "chrome", headless: true });
let page;

// The run operation as the library holds it, read apart from the UI.
let token;
async function library(method, id, body) {
  if (!token) {
    const login = await fetch(url + "/v1/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ passphrase }),
    });
    token = (await login.json()).sessionToken;
  }
  const response = await fetch(`${url}/api/proxy/library/v1/run-operations/${id}`, {
    method,
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`${method} ${id}: ${response.status} ${await response.text()}`);
  return response.json();
}
const stepOf = async (id) => (await library("GET", id)).step;

try {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  context.on("request", (request) => {
    if (request.method() === "PUT" && request.url().includes("/api/proxy/library/v1/run-operations/"))
      report.submits++;
  });
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

  // 1. Home's Download and run asks before anything is submitted.
  await page.getByTestId("home-primary").click({ timeout: 120000 });
  const dialog = page.getByTestId("run-dialog");
  await expect(dialog).toContainText("Install llama.cpp too?", { timeout: 30000 });
  report.askedAtTheClick = report.submits === 0;
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await page.waitForTimeout(3000);
  report.submitsAfterEscape = report.submits;

  // 2. A run left waiting for its answer (submitted without the agreement).
  await library("GET", waiting).catch(() => null); // signs in; the run does not exist yet
  const node = (await (await fetch(url + "/v1/node", { headers: { authorization: `Bearer ${token}` } })).json()).name;
  await library("PUT", waiting, { node, download: tiny });
  // A run that ended will never ask: stop there rather than at the deadline.
  for (const until = Date.now() + 900000; ; ) {
    const step = await stepOf(waiting);
    if (step === "awaiting-install") break;
    if (["failed", "cancelled"].includes(step)) throw new Error(`the waiting run went to ${step}, not awaiting-install`);
    if (Date.now() > until) throw new Error(`still ${step} after 15 minutes`);
    await page.waitForTimeout(2000);
  }
  await page.goto(url);
  await expect(dialog).toContainText("Install llama.cpp?", { timeout: 60000 });
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  // Followed from the tray, the row opens the question again; Later closes it.
  const openTray = async () => {
    await page.getByRole("button", { name: /Tasks/ }).first().click();
    await page.getByRole("link", { name: /stories15M/ }).first().click();
  };
  await openTray();
  await expect(dialog).toBeVisible();
  await page.getByTestId("run-later").click();
  await expect(dialog).toBeHidden();
  report.stepAfterLater = await stepOf(waiting);
  await openTray();
  await expect(dialog).toBeVisible();
  report.trayReopened = true;
  await page.getByTestId("run-cancel").click();
  await expect(async () => {
    report.stepAfterCancel = await stepOf(waiting);
    if (report.stepAfterCancel !== "cancelled") throw new Error(report.stepAfterCancel);
  }).toPass({ timeout: 30000, intervals: [500] });
  await save();
} catch (error) {
  report.failure = String(error?.stack || error);
  if (page) await page.screenshot({ path: join(output, "failure.png"), fullPage: true }).catch(() => {});
  await save();
  process.exitCode = 1;
} finally {
  await browser.close();
}
