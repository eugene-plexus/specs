/** Real pointer/key events and real streamed content; no API fixtures. */
import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import assert from "node:assert/strict";
const require = createRequire(new URL("../../ui/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const [settingsFile] = process.argv.slice(2);
const settings = JSON.parse(await readFile(settingsFile, "utf8"));
const { url, output, download, startedEpochMs } = settings;
const passphrase = "s10-disposable-passphrase";
const message = "Say hello in five words.";
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(30000);
const report = { target: settings.target, download, startedEpochMs, errors: [] };
page.on("pageerror", error => report.errors.push(String(error)));
const save = () => writeFile(join(output, "browser.json"), JSON.stringify(report, null, 2));
await page.addInitScript(() => {
  const read = () => JSON.parse(sessionStorage.getItem("s10-count") || '{"clicks":0,"keys":0,"typed":[]}');
  const update = action => { const count = read(); action(count); sessionStorage.setItem("s10-count", JSON.stringify(count)); };
  document.addEventListener("pointerdown", () => update(c => c.clicks++), true);
  document.addEventListener("keydown", () => update(c => c.keys++), true);
  document.addEventListener("change", event => {
    const field = event.target;
    if ((field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) && field.value &&
        !["checkbox", "radio"].includes(field.type)) {
      // Count the values without persisting a passphrase or client key.
      update(c => { if (!c.typed.some(v => v.value === field.value)) c.typed.push({ value: field.value, type: field.type }); });
    }
  }, true);
});
async function counts() {
  return page.evaluate(() => JSON.parse(sessionStorage.getItem("s10-count") || "{}"));
}
async function tabTo(locator) {
  for (let i = 0; i < 80; i++) {
    if (await locator.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press("Tab");
  }
  throw new Error("Keyboard could not reach the field");
}
try {
  // A WSL listener can become healthy before Windows installs its localhost
  // forwarding rule. Keep that wait in the measured elapsed time.
  await expect(async () => {
    const response = await page.goto(url, { timeout: 5000 });
    assert.equal(response.status(), 200);
  }).toPass({ timeout: 30000, intervals: [500, 1000] });
  await expect(page.getByRole("heading", { name: "Choose a passphrase", exact: true })).toBeVisible({ timeout: 60000 });
  const fields = page.locator('input[type="password"]');
  await expect(fields).toHaveCount(2);
  await tabTo(fields.nth(0));
  await page.keyboard.type(passphrase);
  await tabTo(fields.nth(1));
  await page.keyboard.type(passphrase);
  await page.getByRole("button", { name: /Continue/ }).click();
  await expect(page.getByRole("heading", { name: "Where should models live?", exact: true })).toBeVisible({ timeout: 120000 });
  await expect(page.getByRole("radio", { name: /Make a folder for me/ })).toBeChecked();
  await page.getByRole("button", { name: "Finish", exact: true }).click();
  await expect(page.getByTestId("home")).toBeVisible({ timeout: 120000 });
  const action = download ? page.getByTestId("home-primary") : page.getByTestId("run-button");
  await expect(action).toBeVisible({ timeout: 120000 });
  if (download) await expect(action).toContainText("Download and run");
  report.offeredAction = await action.textContent();
  report.modelCard = await page.getByTestId("home-first-model").textContent();
  await action.click();
  const composer = page.getByTestId("home-composer");
  const install = page.getByTestId("run-install");
  await Promise.race([
    install.waitFor({ state: "visible", timeout: 900000 }),
    composer.waitFor({ state: "visible", timeout: 900000 }),
  ]);
  report.askedAboutEngine = await install.isVisible();
  if (report.askedAboutEngine) await install.click();
  await expect(composer).toBeEnabled({ timeout: 900000 });
  await tabTo(composer);
  await page.keyboard.type(message);
  // Observe text in the live DOM, not the completion footer. The response
  // parser below separately proves that the text came from an assistant delta.
  await page.evaluate(() => {
    const card = document.querySelector('[data-testid="home-try-it"]');
    const observer = new MutationObserver(() => {
      if (card.querySelector(".group.items-start > div:first-child")?.textContent?.trim()) {
        window.__s10FirstToken = Date.now(); observer.disconnect();
      }
    });
    observer.observe(card, { childList: true, subtree: true, characterData: true });
  });
  const request = page.waitForResponse(r => r.url().includes("chat/completions") && r.request().method() === "POST", { timeout: 180000 });
  await page.getByRole("button", { name: "Send", exact: true }).click();
  const response = await request;
  assert.equal(response.status(), 200);
  const wire = await response.text();
  const frames = wire.split("\n").filter(l => l.startsWith("data: ") && !l.includes("[DONE]"))
    .map(l => JSON.parse(l.slice(6)));
  const answer = frames.map(f => f.choices?.[0]?.delta?.content || "").join("");
  assert(answer.trim().length > 0, "assistant sent actual content");
  assert(wire.includes("[DONE]"), "stream completed");
  await expect(page.getByTestId("home-turn-info")).toBeVisible({ timeout: 180000 });
  const firstToken = await page.evaluate(() => window.__s10FirstToken);
  assert(firstToken, "first visible assistant text was observed");
  const count = await counts();
  const configValues = count.typed.filter(v => v.value !== message);
  report.firstReply = {
    clicks: count.clicks, keystrokes: count.keys, typedValues: configValues.length,
    pathsTyped: count.typed.filter(v => /[\\/]/.test(v.value)).length,
    firstVisibleTokenEpochMs: firstToken,
    installToFirstTokenSeconds: (firstToken - startedEpochMs) / 1000,
    installToCompletedReplySeconds: (Date.now() - startedEpochMs) / 1000,
    answer, turn: await page.getByTestId("home-turn-info").textContent(),
  };
  await save();
  assert(count.clicks <= 6, `${count.clicks} clicks exceeds six`);
  assert(count.keys > passphrase.length * 2, "real keystrokes were counted");
  assert.equal(configValues.length, 1);
  assert.equal(configValues[0].type, "password");
  assert.equal(report.firstReply.pathsTyped, 0);
  await page.screenshot({ path: join(output, "first-reply.png") });

  const before = (await counts()).clicks;
  const card = page.getByTestId("home-use-from-apps");
  await card.getByTestId("make-key").click();
  await expect(card.getByTestId("fresh-key")).toBeVisible();
  const address = (await card.getByTestId("base-url").textContent()).trim();
  const modelElement = card.getByTestId("app-model").first();
  const model = await modelElement.evaluate(el => el.tagName === "SELECT" ? el.value : el.textContent.trim());
  const key = (await card.getByTestId("fresh-key").textContent()).trim();
  const connectedClicks = (await counts()).clicks - before;
  assert(connectedClicks <= 3);
  // Credentials are handed to the runner in a separate, disposable file only.
  await writeFile(join(output, "connection.json"), JSON.stringify({ address, model, key }));
  report.connect = { clicks: connectedClicks, address, model, lifetime: /good for a year/i.test(await card.textContent()) ? "a year" : "" };
  assert.equal(report.connect.lifetime, "a year");
  const reach = page.getByTestId("home-reach");
  await expect(reach.getByTestId("reach-switch")).toHaveCount(1);
  report.reach = { switches: 1, headline: await reach.getByTestId("reach-headline").textContent(), exercised: false };
  // Do not pretend counting a switch proves phone connectivity. The existing
  // reach acceptance and the moderated phone task provide that separate evidence.
  report.sessionToken = undefined;
  assert.deepEqual(report.errors, [], "no uncaught browser errors");
  await save();
  console.log(JSON.stringify(report.firstReply));
} catch (error) {
  report.failure = String(error);
  await save();
  await page.screenshot({ path: join(output, "failure.png"), fullPage: true });
  throw error;
} finally {
  await browser.close();
}
