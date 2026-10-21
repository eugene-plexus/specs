/** CX9 browser half: models already in Ollama, as a person sees them. Driven by
 * cx9-ollama-models-acceptance.py. No interception.
 *
 * Sets the install up with no model, writes ready.flag, and waits for
 * http.json (the Python half has put the fake Ollama store in place and run
 * its HTTP checks). Then: Library lists "tiny:q4" with the Ollama badge, and
 * the opened model says "Ollama manages this model." with no Delete button;
 * Folders says "Ollama's models (read-only) · found on this machine". */
import { createRequire } from "node:module";
import { access, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
const require = createRequire(new URL("../../ui/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const [settingsFile] = process.argv.slice(2);
const { url, output, passphrase, modelName } = JSON.parse(await readFile(settingsFile, "utf8"));
const report = { errors: [] };
const save = () => writeFile(join(output, "browser.json"), JSON.stringify(report, null, 2));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const browser = await chromium.launch({ channel: "chrome", headless: true });
let page;
let token;

async function login() {
  const response = await fetch(url + "/v1/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ passphrase }),
  });
  token = (await response.json()).sessionToken;
}
async function get(path) {
  const response = await fetch(url + path, { headers: { authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`GET ${path}: ${response.status}`);
  return response.json();
}
const exists = (path) => access(path).then(() => true, () => false);
const plain = (text) => (text ?? "").replace(/[‘’]/g, "'").replace(/\s+/g, " ").trim();

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
  const passwords = page.locator('input[type="password"]');
  await passwords.nth(0).fill(passphrase);
  await passwords.nth(1).fill(passphrase);
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

  // The library answers before the Python half starts.
  await login();
  await expect(async () => {
    const entry = (await get("/v1/components")).components.find((c) => c.name === "library");
    if (entry?.status !== "running") throw new Error(`library ${entry?.status}`);
    await get("/api/proxy/library/v1/folders");
  }).toPass({ timeout: 180000, intervals: [500, 1000] });
  await writeFile(join(output, "ready.flag"), "ready");
  await save();

  // Wait for the HTTP half: it writes http.json, with an error if it failed.
  const handoffPath = join(output, "http.json");
  for (let i = 0; i < 4000 && !(await exists(handoffPath)); i++) await sleep(500);
  const handoff = JSON.parse(await readFile(handoffPath, "utf8"));
  if (handoff.error) throw new Error(`the HTTP half failed first: ${handoff.error}`);

  // Library: the model, its badge, and Ollama's note in place of Delete.
  await page.goto(url + "/library");
  const list = page.getByTestId("model-list");
  await expect(list.getByText(modelName, { exact: false }).first()).toBeVisible({ timeout: 60000 });
  const badge = page.getByTestId("model-list-ollama").first();
  await expect(badge).toBeVisible();
  report.badgeText = plain(await badge.textContent());
  await list.getByText(modelName, { exact: false }).first().click();
  const note = page.getByTestId("ollama-manages");
  await expect(note).toBeVisible({ timeout: 30000 });
  report.managesText = plain(await note.textContent());
  report.deleteButtons = await page.getByRole("button", { name: /^delete/i }).count();
  await save();

  // Folders: the store, read-only, found on this machine.
  await page.goto(url + "/library/folders");
  const line = page.getByTestId("folder-ollama").first();
  await expect(line).toBeVisible({ timeout: 60000 });
  report.folderLine = plain(await line.textContent());
  await save();
} catch (error) {
  report.failure = String(error?.stack || error);
  if (page) await page.screenshot({ path: join(output, "failure.png"), fullPage: true }).catch(() => {});
  await save();
  process.exitCode = 1;
} finally {
  await browser.close();
}
