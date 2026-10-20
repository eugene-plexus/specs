/** CX7 browser half: Save says it restarts, and Save all restarts the
 * gateway once. Driven by cx7-save-restart-acceptance.py. No interception.
 *
 * Two gateway fields with `requiresRestart: true` that Settings files under
 * two different topics are changed, saved with Save all, then put back the
 * same way. The restarts are counted from the agent's GET /v1/components
 * (the gateway entry's pid and lastRestart), sampled every 100 ms. */
import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
const require = createRequire(new URL("../../ui/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const [settingsFile] = process.argv.slice(2);
const { url, output, passphrase } = JSON.parse(await readFile(settingsFile, "utf8"));
const report = { errors: [] };
const save = () => writeFile(join(output, "browser.json"), JSON.stringify(report, null, 2));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const browser = await chromium.launch({ channel: "chrome", headless: true });
let page;

// The topic a gateway field is filed under: ui/src/lib/settingsTopics.ts
// (BY_KEY, then BY_CATEGORY.gateway), copied here so the harness chooses
// from the schema; the page's own data-topic is checked against it below.
const GATEWAY_TOPIC = {
  generation: "answers",
  routing: "serving",
  lifecycle: "serving",
  metrics: "metrics-logs",
  logging: "metrics-logs",
  clients: "access",
};
const topicOf = (field) =>
  field.key === "controlUrl" ? "machines" : (GATEWAY_TOPIC[field.category] ?? field.category);
// Harmless to change; tried in this order, one per topic.
const PREFER = ["logLevel", "requestTimeoutSeconds", "metricsRetentionDays", "swapWaitSeconds"];

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
const gatewayEntry = async () =>
  (await get("/v1/components")).components.find((c) => c.name === "gateway");
const generationOf = (entry) => `${entry?.pid ?? ""}@${entry?.lastRestart ?? ""}`;

// Samples the gateway entry until stopped.
function watchGateway() {
  const samples = [];
  let running = true;
  const loop = (async () => {
    while (running) {
      const at = performance.now();
      try {
        const entry = await gatewayEntry();
        samples.push({ at, pid: entry?.pid ?? null, key: generationOf(entry), status: entry?.status });
      } catch {
        samples.push({ at, pid: null, key: "", status: "unreachable" });
      }
      await sleep(100);
    }
  })();
  return {
    samples,
    stop: async () => {
      running = false;
      await loop;
    },
  };
}

// Waits for the gateway to answer through the agent's proxy as a new process.
async function waitBack(previousKey, timeoutMs) {
  const deadline = performance.now() + timeoutMs;
  while (performance.now() < deadline) {
    try {
      const entry = await gatewayEntry();
      if (entry?.pid && generationOf(entry) !== previousKey && entry.status === "running") {
        const response = await fetch(url + "/api/proxy/gateway/v1/config", {
          headers: { authorization: `Bearer ${token}` },
        });
        if (response.ok) return true;
      }
    } catch {
      // The agent answers throughout; the gateway behind it may not.
    }
    await sleep(250);
  }
  return false;
}

const sameValue = (a, b) => String(a) === String(b);

// Edit one field in its section: open Customize if the section folds it.
async function sectionOf(topic) {
  const section = page.locator(
    `[data-testid="settings-card"][data-topic="${topic}"] ` +
      `[data-testid="settings-section"][data-target="gateway"]`,
  );
  await expect(section).toBeVisible({ timeout: 60000 });
  return section;
}
async function setField(section, field, value) {
  const fold = section.getByRole("button", { name: /^Customize/ });
  if (await fold.count()) await fold.click();
  if (field.enumValues?.length) {
    const select = section.getByRole("combobox", { name: field.label, exact: true });
    await expect(select).toBeVisible();
    await select.selectOption(String(value));
  } else {
    const input = section.getByRole("spinbutton", { name: field.label, exact: true });
    await expect(input).toBeVisible();
    await input.fill(String(value));
  }
}

// One pass: open Settings, edit both fields to `values`, Save all, observe.
async function pass(name, fields, values, checkWording) {
  const seen = {};
  await page.goto(url + "/config");
  const sections = [];
  for (const field of fields) sections.push(await sectionOf(field.topic));
  if (checkWording) {
    // Both sections on the page, neither with buttons while clean.
    for (const section of sections) await expect(section.getByTestId("section-actions")).toHaveCount(0);
  }

  await setField(sections[0], fields[0], values[fields[0].key]);
  if (checkWording) {
    const actions = sections[0].getByTestId("section-actions");
    const button = actions.getByRole("button", { name: /^Save/ });
    seen.sectionButton = (await button.textContent())?.trim();
    const note = sections[0].getByTestId("restart-note");
    seen.sectionNoteShown = await note.isVisible();
    seen.sectionNote = (await note.textContent())?.trim();
  }
  await setField(sections[1], fields[1], values[fields[1].key]);

  const bar = page.getByTestId("save-all-bar");
  await expect(bar).toBeVisible();
  if (checkWording) {
    seen.saveAllButton = (await page.getByTestId("save-all").textContent())?.trim();
    const restarts = (await page.getByTestId("save-all-restarts").textContent())?.trim() ?? "";
    seen.saveAllRestarts = restarts;
    const label = (await sections[0].locator("h3").first().textContent())?.trim() ?? "";
    seen.gatewayLabel = label;
    // Named once: two sections, one process.
    seen.saveAllNamesGateway = label.length > 0 && restarts.split(label).length === 2;
  }

  // Count restarts from before the click.
  const before = generationOf(await gatewayEntry());
  const watcher = watchGateway();
  const clickedAt = performance.now();
  await page.getByTestId("save-all").click();
  const back = await waitBack(before, 240000);
  // Settle: a second restart would begin soon after the first one's save.
  await sleep(20000);
  await watcher.stop();
  seen.backAfterSave = back;
  const after = watcher.samples.filter((s) => s.at >= clickedAt);
  const generations = new Set(after.filter((s) => s.pid).map((s) => s.key));
  generations.delete(before);
  seen.newGenerations = generations.size;
  let gap = 0;
  for (let i = 1; i < after.length; i++) gap = Math.max(gap, after[i].at - after[i - 1].at);
  seen.maxSampleGapMs = Math.round(gap);
  seen.samples = after.length;
  // Sampling gaps over 3 s make the count unobserved: null, never a pass.
  seen.restartedOnce = !back || seen.maxSampleGapMs > 3000 ? (back ? null : false) : generations.size === 1;

  // In effect: the saved document and the schema's pending flags.
  const doc = await get("/api/proxy/gateway/v1/config");
  const schema = await get("/api/proxy/gateway/v1/config/schema");
  seen.valuesInEffect = fields.every((f) => sameValue(doc[f.key], values[f.key]));
  seen.docValues = Object.fromEntries(fields.map((f) => [f.key, doc[f.key]]));
  seen.nothingPending = !schema.fields.some((f) => f.pendingRestart);

  // The page: the bar is gone, and no "Restart needed" line, before and after a reload.
  await expect(bar).toBeHidden({ timeout: 60000 });
  const restartNeeded = page.getByText(/Restart needed/);
  const onPage = await restartNeeded.count();
  await page.reload();
  await sectionOf(fields[0].topic);
  const afterReload = await restartNeeded.count();
  seen.restartNeededLines = { onPage, afterReload };
  seen.noRestartNeededLine = onPage === 0 && afterReload === 0;
  report[name] = seen;
  await save();
  return seen;
}

try {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  page = await context.newPage();
  page.setDefaultTimeout(30000);
  page.on("pageerror", (error) => report.errors.push(String(error)));
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

  // The gateway is running before anything is changed.
  await login();
  await expect(async () => {
    const entry = await gatewayEntry();
    if (entry?.status !== "running") throw new Error(`gateway ${entry?.status}`);
    await get("/api/proxy/gateway/v1/config");
  }).toPass({ timeout: 180000, intervals: [500, 1000] });

  // Two requiresRestart fields filed under two different topics, from the schema.
  const schema = await get("/api/proxy/gateway/v1/config/schema");
  const doc = await get("/api/proxy/gateway/v1/config");
  const usable = schema.fields.filter(
    (f) =>
      f.requiresRestart === true &&
      !f.showWhen &&
      !f.managedBy &&
      !f.sensitive &&
      (f.enumValues?.length || ["integer", "duration"].includes(f.valueType)),
  );
  usable.sort((a, b) => {
    const rank = (f) => (PREFER.includes(f.key) ? PREFER.indexOf(f.key) : PREFER.length);
    return rank(a) - rank(b);
  });
  const chosen = [];
  for (const field of usable) {
    const topic = topicOf(field);
    if (chosen.some((c) => c.topic === topic)) continue;
    chosen.push({ ...field, topic });
    if (chosen.length === 2) break;
  }
  report.chosen = chosen.map((f) => ({ key: f.key, label: f.label, category: f.category, topic: f.topic }));
  report.twoFieldsInTwoSections = chosen.length === 2;
  if (chosen.length !== 2) throw new Error("fewer than two requiresRestart gateway fields in different topics");

  // Originals, and a harmless other value for each.
  const originals = {};
  const changed = {};
  for (const f of chosen) {
    originals[f.key] = doc[f.key] ?? f.default;
    if (f.enumValues?.length) {
      const others = f.enumValues.filter((v) => v !== originals[f.key]);
      changed[f.key] = others.includes("WARNING") ? "WARNING" : others[0];
    } else {
      const up = Number(originals[f.key]) + 1;
      changed[f.key] = f.maximum != null && up > f.maximum ? Number(originals[f.key]) - 1 : up;
    }
  }
  report.originals = originals;
  report.changedTo = changed;
  // Unset originals are put back as the value they resolved to.
  report.originalsWereUnset = chosen.filter((f) => doc[f.key] == null).map((f) => f.key);
  await save();

  // Settings files each field where the topic map says; the cards carry data-topic.
  await page.goto(url + "/config");
  for (const f of chosen) {
    await expect(
      page.locator(`[data-testid="settings-card"][data-topic="${f.topic}"]`),
    ).toBeVisible({ timeout: 60000 });
  }

  await pass("change", chosen, changed, true);
  await pass("restore", chosen, originals, false);
  await save();
} catch (error) {
  report.failure = String(error?.stack || error);
  if (page) await page.screenshot({ path: join(output, "failure.png"), fullPage: true }).catch(() => {});
  await save();
  process.exitCode = 1;
} finally {
  await browser.close();
}
