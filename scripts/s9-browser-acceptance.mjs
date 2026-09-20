/** S9: actual wheel + CPU model. No browser API interception or canned replies. */
import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import assert from "node:assert/strict";

const require = createRequire(new URL("../../ui/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const [session, output] = process.argv.slice(2);
const { url, token } = JSON.parse(await readFile(session, "utf8"));
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 430, height: 932 } });
const errors = [];
const checks = [];
page.on("pageerror", error => errors.push(String(error)));
await page.addInitScript(value => sessionStorage.setItem("eugene-session-token", value), token);
async function fits(locator, label) {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  assert(box.x >= -1 && box.x + box.width <= page.viewportSize().width + 1, `${label}: ${JSON.stringify(box)}`);
}
async function noOverflow(label) {
  const excess = await page.evaluate(() => [...document.querySelectorAll("main, #main-content, header, nav")]
    .filter(el => el.getBoundingClientRect().width && el.scrollWidth > el.clientWidth + 1)
    .map(el => ({ tag: el.tagName, class: el.className, width: el.clientWidth, scroll: el.scrollWidth })));
  assert.deepEqual(excess, [], `${label} overflow`);
}
try {
  await page.goto(url);
  const composer = page.getByTestId("home-composer");
  await expect(composer).toBeEnabled({ timeout: 30000 });
  await fits(composer, "Home composer");
  await composer.fill("Reply with only the word hello. /no_think");
  const completion = page.waitForResponse(r => r.url().includes("chat/completions") && r.request().method() === "POST");
  await composer.press("Enter");
  const response = await completion;
  assert.equal(response.status(), 200);
  const wire = await response.text();
  await writeFile(join(output, "completion.sse"), wire);
  assert(/hello/i.test(wire) && wire.includes("[DONE]"), "real streamed reply completes");
  await expect(page.getByTestId("home-turn-info")).toContainText("s9-phone-model", { timeout: 120000 });
  await noOverflow("Home 430");
  await page.screenshot({ path: join(output, "home-430.png") });
  checks.push("430px Home -> Try it -> real streamed CPU-model reply");

  await page.getByTestId("home-continue").click();
  await expect(page.getByTestId("composer")).toBeEnabled();
  await expect(page.locator("main")).toContainText(/hello/i);
  for (const width of [430, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await fits(page.getByTestId("composer"), "Playground composer");
    await fits(page.getByRole("button", { name: "Send", exact: true }), "Send");
    await noOverflow(`Playground ${width}`);
  }
  await page.getByTestId("toggle-diagnostic").click();
  const pathPanel = page.getByRole("region", { name: "Path to the gateway", exact: true });
  const toolsPanel = page.getByRole("region", { name: "Tools", exact: true });
  const pathBox = await pathPanel.boundingBox();
  const toolsBox = await toolsPanel.boundingBox();
  assert(toolsBox.y >= pathBox.y + pathBox.height, "Phone diagnostic panels stack");
  await page.getByRole("radio", { name: "Direct to the gateway" }).click();
  await fits(page.getByTestId("base-url"), "Direct gateway URL");
  await fits(page.getByTestId("composer"), "Composer with diagnostics");
  await page.screenshot({ path: join(output, "playground-390.png") });
  checks.push("Shared conversation and Playground controls fit at 430/390px");

  await page.goto(`${url}/library/?sel=library`);
  const model = page.locator("main aside button").filter({ hasText: "Qwen3-0.6B" });
  await expect(model).toBeVisible({ timeout: 30000 });
  await model.click();
  await page.getByRole("heading", { name: /Qwen3-0.6B/ }).scrollIntoViewIfNeeded();
  await fits(page.getByRole("heading", { name: /Qwen3-0.6B/ }), "Model details");
  await noOverflow("Library 390");
  await page.getByRole("button", { name: "new profile", exact: true }).click();
  await page.getByPlaceholder("long context").scrollIntoViewIfNeeded();
  await fits(page.getByPlaceholder("long context"), "Profile name");
  await noOverflow("Library profile editor 390");
  await page.screenshot({ path: join(output, "library-390.png") });
  await page.setViewportSize({ width: 1440, height: 1000 });
  const listBox = await page.locator("main aside").boundingBox();
  const detailBox = await page.getByRole("heading", { name: /Qwen3-0.6B/ }).boundingBox();
  assert(detailBox.x >= listBox.x + listBox.width, "Desktop Library keeps two columns");
  await page.setViewportSize({ width: 390, height: 844 });
  checks.push("Library selection and details stack and remain reachable at 390px");

  await page.goto(`${url}/config/?sel=install`);
  await page.getByLabel("Font size", { exact: true }).selectOption("xlarge");
  for (const path of ["/", "/playground/", "/library/?sel=library"]) {
    await page.goto(url + path);
    await expect(page.locator("main")).toBeVisible();
    await noOverflow(`${path} 390 at extra-large font`);
  }
  await page.goto(`${url}/config/?sel=agent`);
  const hint = page.getByText("securityMode", { exact: true });
  await expect(hint).toBeVisible();
  assert.equal(await hint.evaluate(el => getComputedStyle(el).fontSize), "12.5px");
  await noOverflow("Config 390 at extra-large font");
  checks.push("Font preference scales 10px hints to 12.5px; Config stacks");

  for (const theme of ["plexus", "modern", "editorial"]) {
    await page.evaluate(value => document.documentElement.dataset.theme = value, theme);
    await page.getByTestId("layer-map-toggle").focus();
    await page.keyboard.press("Tab");
    const outline = await page.evaluate(() => {
      const style = getComputedStyle(document.activeElement);
      return { width: style.outlineWidth, style: style.outlineStyle, color: style.outlineColor };
    });
    assert.equal(outline.width, "2px");
    assert.equal(outline.style, "solid");
    assert.notEqual(outline.color, "rgba(0, 0, 0, 0)");
  }
  checks.push("Tab focus has a visible ring in all three themes");

  // The surviving decorative spinner class has no current consumer. Exercise
  // its shipped CSS, including its pseudo-element, without adding product UI.
  await page.evaluate(() => document.body.classList.add("is-thinking-rail"));
  await page.emulateMedia({ reducedMotion: "no-preference" });
  assert.equal(await page.evaluate(() => getComputedStyle(document.body, "::after").animationName), "modern-spin");
  await page.emulateMedia({ reducedMotion: "reduce" });
  assert.equal(await page.evaluate(() => getComputedStyle(document.body, "::after").animationName), "none");
  checks.push("Live reduced-motion preference stops decorative animation");
  assert.deepEqual(errors, []);
  await writeFile(join(output, "results.json"), JSON.stringify({ checks, errors }, null, 2));
  console.log(checks.join("\n"));
} catch (error) {
  await page.screenshot({ path: join(output, "failure.png"), fullPage: true });
  throw error;
} finally {
  await browser.close();
}
