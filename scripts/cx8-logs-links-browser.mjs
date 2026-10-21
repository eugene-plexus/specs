/** CX8 browser half: a failure links to the log lines about it, and Routing
 * says what is true. Driven by cx8-logs-links-acceptance.py. No interception.
 *
 * Sets the install up with no model, writes ready.flag, and waits for
 * http.json: the Python half makes one request fail over from cx8-primary to
 * cx8-backup and reports its id. Then: Metrics shows "Logs →" on that request
 * and the click opens Logs on the id; /logs?q= with text that matches nothing
 * says so and offers Clear; Routing's Save reads "Saved. The gateway uses
 * these lists now". */
import { createRequire } from "node:module";
import { access, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
const require = createRequire(new URL("../../ui/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const [settingsFile] = process.argv.slice(2);
const { url, output, passphrase, alias } = JSON.parse(await readFile(settingsFile, "utf8"));
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
  const unlock = page.getByRole("checkbox", { name: /unlock eugene on its own/i });
  if ((await unlock.count()) && (await unlock.isChecked()) && (await unlock.isEnabled())) await unlock.uncheck();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Where should models live?", exact: true })).toBeVisible({ timeout: 120000 });
  const finish = page.getByRole("button", { name: "Finish", exact: true });
  await expect(finish).toBeEnabled({ timeout: 60000 });
  await finish.click();
  await expect(page.getByTestId("home")).toBeVisible({ timeout: 120000 });

  // The gateway answers before the Python half starts.
  await login();
  await expect(async () => {
    const entry = (await get("/v1/components")).components.find((c) => c.name === "gateway");
    if (entry?.status !== "running") throw new Error(`gateway ${entry?.status}`);
    await get("/api/proxy/gateway/v1/config");
  }).toPass({ timeout: 180000, intervals: [500, 1000] });
  await writeFile(join(output, "ready.flag"), "ready");
  await save();

  // Wait for the failover: Python writes http.json, with an error if it failed.
  const handoffPath = join(output, "http.json");
  for (let i = 0; i < 1500 && !(await exists(handoffPath)); i++) await sleep(500);
  const handoff = JSON.parse(await readFile(handoffPath, "utf8"));
  if (handoff.error || !handoff.requestId) throw new Error(`no failover to look at: ${handoff.error ?? "no request id"}`);
  const id = handoff.requestId;
  report.requestId = id;

  // 2. Metrics: "Logs →" on that request, then the click.
  await page.goto(url + "/metrics");
  const row = page.locator("li", { hasText: `Request ${id}` }).first();
  const link = row.getByTestId("metrics-request-logs");
  await expect(async () => {
    if (!(await link.count())) {
      await page.reload();
      throw new Error("the request's row has no Logs link yet");
    }
  }).toPass({ timeout: 90000, intervals: [2000] });
  await expect(link).toBeVisible();
  report.linkShown = true;
  report.linkText = (await link.textContent())?.trim();
  report.linkHref = await link.getAttribute("href");
  report.linkHrefOk = report.linkHref === `/logs?q=${encodeURIComponent(id)}`;
  await link.click();
  await page.waitForURL(/\/logs/);
  const opened = { onLogs: new URL(page.url()).pathname === "/logs" };
  const box = page.getByTestId("logs-filter");
  await expect(box).toBeVisible({ timeout: 60000 });
  opened.boxValue = await box.inputValue();
  opened.boxHoldsId = opened.boxValue === id;
  // Lines are asked for with the id at once; wait for them.
  const lines = page.getByTestId("log-line");
  await expect(lines.first()).toBeVisible({ timeout: 60000 });
  opened.lines = await lines.count();
  const texts = await lines.allTextContents();
  opened.someLineHasId = texts.some((t) => t.toLowerCase().includes(id.toLowerCase()));
  report.opened = opened;
  await save();

  // 3. Text that matches nothing: the sentence and Clear.
  const nothing = `cx8-matches-nothing-${Date.now()}`;
  await page.goto(url + `/logs?q=${encodeURIComponent(nothing)}`);
  const empty = page.getByTestId("logs-empty");
  await expect(empty).toContainText("No line contains", { timeout: 60000 });
  const message = (await empty.textContent())?.replace(/\s+/g, " ").trim() ?? "";
  const clear = page.getByTestId("logs-clear-filter");
  const nomatch = {
    message,
    messageOk: message.includes(`No line contains “${nothing}”.`),
    clearShown: await clear.isVisible(),
  };
  await clear.click();
  await expect(page.getByTestId("log-line").first()).toBeVisible({ timeout: 60000 });
  nomatch.linesAfterClear = await page.getByTestId("log-line").count();
  report.nomatch = nomatch;
  await save();

  // 4. Routing: move a target, Save, read the saved line.
  await page.goto(url + "/routing");
  await expect(page.getByTestId("routing-slot").first()).toBeVisible({ timeout: 60000 });
  await page.getByRole("button", { name: "Try cx8-primary later", exact: true }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const applied = page.getByTestId("save-applied");
  await expect(applied).toBeVisible({ timeout: 60000 });
  const savedText = (await applied.textContent())?.replace(/\s+/g, " ").trim() ?? "";
  const doc = await get("/api/proxy/gateway/v1/config");
  const mine = (doc.modelSlots ?? []).find((s) => s.model === alias);
  report.routing = {
    savedText,
    savedLineOk: savedText.startsWith("Saved. The gateway uses these lists now"),
    oldWordingGone: !savedText.includes("next routing refresh"),
    savedOrder: mine?.targets ?? null,
    orderSaved: JSON.stringify(mine?.targets) === JSON.stringify(["cx8-backup", "cx8-primary"]),
  };
  await save();
} catch (error) {
  report.failure = String(error?.stack || error);
  if (page) await page.screenshot({ path: join(output, "failure.png"), fullPage: true }).catch(() => {});
  await save();
  process.exitCode = 1;
} finally {
  await browser.close();
}
