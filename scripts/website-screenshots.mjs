/** Website screenshots: the real packaged console, a real CPU-model reply. */
import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const require = createRequire(new URL("../../ui/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const [session, output] = process.argv.slice(2);
const { url, token } = JSON.parse(await readFile(session, "utf8"));
const browser = await chromium.launch({ channel: "chrome", headless: true });
const shots = [];

async function open(width, height) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 2 });
  await page.addInitScript((value) => sessionStorage.setItem("eugene-session-token", value), token);
  return page;
}

async function reply(page, prompt) {
  await page.goto(url);
  const composer = page.getByTestId("home-composer");
  await expect(composer).toBeEnabled({ timeout: 60000 });
  await composer.fill(prompt);
  await composer.press("Enter");
  await expect(page.getByTestId("home-turn-info")).toContainText("qwen3-0.6b", { timeout: 180000 });
  await page.waitForTimeout(800);
}

async function shoot(page, name, locator) {
  const path = join(output, `${name}.png`);
  if (locator) await locator.screenshot({ path });
  else await page.screenshot({ path });
  shots.push(name);
}

try {
  const desk = await open(1440, 900);
  await reply(desk, "Suggest three names for a friendly home robot.");
  await shoot(desk, "home-reply-desk");
  await shoot(desk, "home-try-it", desk.getByTestId("home-composer").locator("xpath=ancestor::section[1]"));
  await desk.getByTestId("home-use-from-apps").scrollIntoViewIfNeeded();
  await shoot(desk, "home-use-from-apps", desk.getByTestId("home-use-from-apps"));

  await desk.goto(`${url}/discover/`);
  await expect(desk.getByTestId("starter-set")).toBeVisible({ timeout: 60000 });
  await desk.waitForTimeout(1500);
  await shoot(desk, "discover-desk");
  const recommended = desk.getByTestId("starter-recommended");
  if (await recommended.isVisible()) await shoot(desk, "discover-recommended", recommended);

  const phone = await open(390, 844);
  await reply(phone, "What is a good name for a cat?");
  await shoot(phone, "home-reply-phone");
} finally {
  await writeFile(join(output, "screenshots.json"), JSON.stringify({ shots }, null, 2));
  await browser.close();
}
