/** Website screenshots: the real console and Workbench, a real CPU-model reply. */
import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const require = createRequire(new URL("../../ui/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");

/** The fictional handbook: four pages, each a fact a question can find. */
const HANDBOOK = [
  ["Welcome to Maple Street Community Garden", [
    "The garden opened in spring and is run entirely by its members. Every member has one plot, and every plot is 4 by 8 feet.",
    "Plots are numbered 1 to 24, with the herb bed shared by everyone beside the gate. A new member is shown to their plot at the first workday after they join, and the plot stays theirs for the whole season as long as it is tended.",
    "Membership costs 25 dollars a season, paid to the treasurer at the first workday. The fee buys seed starts, compost, repairs to the raised beds and the insurance on the shed. Nobody is turned away for not being able to pay; ask the treasurer.",
    "The garden sits on land lent by the neighbourhood association. In return we keep the front border tidy, host one open afternoon each summer and share a basket of vegetables with the food pantry every Friday in season.",
    "New members are paired with a neighbour on the next plot for their first season. Your neighbour can show you where the taps are, which beds drain slowly and when the first shade falls across the east side.",
  ]],
  ["Workdays and watering", [
    "The volunteer workday is the first Saturday of each month at 9 am. Bring gloves; the shed has spare tools. Workdays run for about two hours and end with tea and whatever someone has baked.",
    "Plots are watered on Tuesday, Thursday and Saturday at 7 am by the volunteer listed in the watering schedule. If you cannot take your turn, swap with a neighbour and tell the committee so the schedule stays right.",
    "Rain barrels are refilled by the Thursday crew. Please do not use the hose on a plot that has just been watered, and never leave a tap running unattended. In a dry spell the committee may ask everyone to water by hand only.",
    "Seedlings in the cold frames by the fence are watered by the crew on duty. Please leave the lids as you found them: they are propped open on warm days and closed on cold nights.",
    "A short walk around the garden at the end of every workday, with a list in hand, helps us catch broken stakes, slugs and thirsty beds before they become problems.",
  ]],
  ["Compost and the shed", [
    "The compost bins behind the shed are turned every Monday evening. Kitchen scraps go in the green bin and dry leaves in the brown bin. Turn your own scraps in with a fork before you leave.",
    "No meat, dairy or cooked food in either bin. Cut large stems into short lengths so they break down quickly, and keep diseased plants out of the bins and in the bag by the gate instead.",
    "The tool shed is unlocked during workdays and by the key holder on other days. Wipe tools and hang them back in their places; the outline on the wall shows where each one lives.",
    "Wheelbarrows are shared. If one is broken, tie a red ribbon on it and tell the committee. Please do not borrow tools from the shed for use at home without asking first.",
    "Finished compost is ready in autumn and spring. Help yourself to one bucket per plot, and put the empty bucket back by the bins for the next person.",
  ]],
  ["Garden rules", [
    "No pesticides or weed killers anywhere in the garden. Hand-pick pests, use netting, and ask the committee for advice before you buy anything. The bees and the neighbours will thank you.",
    "Keep paths clear, and label anything you plant that spreads. If frost is forecast below 40 degrees Fahrenheit, cover tomatoes before you leave. Old sheets and buckets are kept in the shed for this.",
    "Questions go to the committee at the first workday of the month. For anything urgent, such as a broken tap or a stranger with a van, leave a message on the garden's phone line and a committee member will call you back.",
    "Children are welcome when they are with an adult. Please keep dogs on a lead and out of the beds, and take any rubbish home with you.",
    "A plot left untended for six weeks in season may be offered to the waiting list after the committee has tried to reach its member twice. Tell us if you will be away and we will find you cover.",
  ]],
];

function handbookHtml() {
  const pages = HANDBOOK.map(
    ([title, lines], index) => `<section style="page-break-after:${index === HANDBOOK.length - 1 ? "auto" : "always"}">
<h1>${title}</h1>${lines.map((l) => `<p>${l}</p>`).join("")}
<div class="foot">Maple Street Community Garden handbook, page ${index + 1}</div></section>`,
  ).join("");
  return `<!doctype html><html><head><meta charset="utf-8"><style>
body{font-family:Georgia,serif;font-size:12pt;line-height:1.45;color:#222}
section{height:9.4in;position:relative}
h1{font-size:20pt;color:#2d5a27;margin:0 0 .4in}
p{margin:0 0 .25in}
.foot{position:absolute;bottom:0;font-size:10pt;color:#666}
</style></head><body>${pages}</body></html>`;
}

if (process.argv[2] === "--make-data") {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage();
  await page.setContent(handbookHtml());
  await page.pdf({ path: join(process.argv[3], "maple-street-garden-handbook.pdf"), format: "Letter", margin: { top: "0.6in", bottom: "0.6in", left: "0.9in", right: "0.9in" } });
  await browser.close();
  process.exit(0);
}


// ---------------------------------------------------------------------------
// The run: leak check, scrub, and the shots.
// ---------------------------------------------------------------------------

const [session, output, ...flags] = process.argv.slice(2);
const only = (flags.find((f) => f.startsWith("--only=")) ?? "").slice(7).split(",").filter(Boolean);
const cfg = JSON.parse(await readFile(session, "utf8"));
const { url } = cfg;
const wanted = (id) => only.length === 0 || only.some((o) => id.startsWith(o));

const escapeRe = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** What must not be on a captured page: the briefed patterns, plus this OS's host and user name. */
const bannedPatterns = [
  ...cfg.banned.map((p) => new RegExp(p, "i")),
  ...[cfg.hostName, cfg.userName].filter((n) => n && n.length > 2).map((n) => new RegExp(escapeRe(n), "i")),
];

class LeakError extends Error {}

/** Reads the page's text and every field's value; throws, naming the shot and the string, on a match. */
async function leakCheck(page, shot) {
  const text = await page.evaluate(() =>
    [
      document.body.innerText,
      ...[...document.querySelectorAll("input,textarea,select")].map((e) => e.value ?? ""),
      ...[...document.querySelectorAll("[title],[aria-label],[placeholder],img[alt]")].flatMap((e) => [
        e.getAttribute("title") ?? "",
        e.getAttribute("aria-label") ?? "",
        e.getAttribute("placeholder") ?? "",
        e.getAttribute("alt") ?? "",
      ]),
    ].join("\n"),
  );
  for (const re of bannedPatterns) {
    const found = re.exec(text);
    if (found) {
      const at = Math.max(0, found.index - 30);
      throw new LeakError(`leak check failed for ${shot}: "${found[0]}" (pattern ${re}) in "${text.slice(at, at + 90).replace(/\s+/g, " ")}"`);
    }
  }
}

/** The OS host and user name, and a LAN address, replaced in the page's text before capture. */
async function scrub(page) {
  await page.evaluate(
    ({ host, user }) => {
      const esc = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const rules = [
        [new RegExp(esc(host), "gi"), "desk-pc"],
        ...(user && user.length > 2 ? [[new RegExp(esc(user), "gi"), "owner"]] : []),
        [/\b192\.168\.\d{1,3}\.\d{1,3}\b/g, "10.0.0.12"],
      ];
      const fix = (t) => rules.reduce((out, [re, to]) => out.replace(re, to), t);
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (n.parentElement && /^(SCRIPT|STYLE)$/.test(n.parentElement.tagName)) continue;
        const next = fix(n.nodeValue ?? "");
        if (next !== n.nodeValue) n.nodeValue = next;
      }
      for (const el of document.querySelectorAll("input,textarea")) {
        if (typeof el.value === "string" && fix(el.value) !== el.value) el.value = fix(el.value);
      }
      for (const el of document.querySelectorAll("[title],[aria-label],[placeholder]")) {
        for (const a of ["title", "aria-label", "placeholder"]) {
          const v = el.getAttribute(a);
          if (v && fix(v) !== v) el.setAttribute(a, fix(v));
        }
      }
    },
    { host: cfg.hostName, user: cfg.userName },
  );
}

const browser = await chromium.launch({ channel: "chrome", headless: true });
const manifest = [];
const failures = [];

async function open(width, height, base = url, token = cfg.token) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 2 });
  if (token) await page.addInitScript((v) => sessionStorage.setItem("eugene-session-token", v), token);
  page.on("pageerror", (e) => console.log("pageerror", e.message.slice(0, 200)));
  return page;
}

/** Scrubs, runs the leak check, then writes the PNG (of `locator` when given) and records it. */
async function shoot(page, id, { route, alt, locator, around, pad = 16, viewport }) {
  await scrub(page);
  await leakCheck(page, id);
  const file = `${id}.png`;
  const path = join(output, file);
  if (around) {
    // One picture of the region that holds these elements, with a margin.
    const boxes = [];
    for (const l of around) boxes.push(await l.boundingBox());
    const [scrollX, scrollY] = await page.evaluate(() => [window.scrollX, window.scrollY]);
    const x = Math.max(0, Math.min(...boxes.map((b) => b.x)) + scrollX - pad);
    const y = Math.max(0, Math.min(...boxes.map((b) => b.y)) + scrollY - pad);
    const x2 = Math.max(...boxes.map((b) => b.x + b.width)) + scrollX + pad;
    const y2 = Math.max(...boxes.map((b) => b.y + b.height)) + scrollY + pad;
    await page.screenshot({ path, fullPage: true, clip: { x, y, width: x2 - x, height: y2 - y } });
  } else if (locator) await locator.screenshot({ path });
  else await page.screenshot({ path });
  const size = page.viewportSize();
  manifest.push({ id, file, route, viewport: viewport ?? `${size.width}x${size.height}`, alt });
  console.log("shot", file);
}

/** Runs one shot; a failure is recorded and the run goes on, except a leak, which ends it. */
async function step(id, run, page) {
  if (!wanted(id)) return;
  try {
    await run();
  } catch (error) {
    if (error instanceof LeakError) throw error;
    failures.push({ id, error: String(error?.message ?? error).split("\n")[0].slice(0, 300) });
    console.log("FAILED", id, String(error?.message ?? error).split("\n")[0].slice(0, 300));
    const shown = typeof page === "function" ? page() : page;
    if (shown) await shown.screenshot({ path: join(output, `failed-${id}.png`) }).catch(() => undefined);
  }
}

/** The proof the leak check can fail: a page with the real host name planted must be refused. */
async function proveLeakCheck() {
  const page = await browser.newPage();
  await page.setContent(`<body><p>Machines</p><p>${cfg.hostName} is online</p></body>`);
  let refused = null;
  try {
    await leakCheck(page, "planted-host-name");
  } catch (error) {
    if (error instanceof LeakError) refused = error.message;
  }
  await page.setContent(`<body><p>Machines</p><p>${cfg.hostName} is online</p></body>`);
  await scrub(page);
  let cleaned = true;
  try {
    await leakCheck(page, "planted-host-name-after-scrub");
  } catch {
    cleaned = false;
  }
  const clean = await browser.newPage();
  await clean.setContent("<body><p>desk-pc is online. A key sk-demo is not one.</p></body>");
  await leakCheck(clean, "demo-name-page");
  await page.close();
  await clean.close();
  if (!refused) throw new Error("the leak check did NOT fail on a planted host name");
  console.log("LEAK-CHECK PROOF: refused a page with the planted host name:", refused);
  console.log("LEAK-CHECK PROOF: the scrub replaces it, then the same page passes:", cleaned);
}

const textOf = async (locator) => ((await locator.innerText()) ?? "").replace(/\s+/g, " ").trim();
const cardOf = (locator) => locator.locator("xpath=ancestor::section[1]");

try {
  await proveLeakCheck();

  // 1-3. Home.
  const desk = await open(1440, 900);
  await step("01-home-reply-desktop", async () => {
    await desk.goto(url);
    const composer = desk.getByTestId("home-composer");
    await expect(composer).toBeEnabled({ timeout: 60000 });
    const choice = await desk
      .getByTestId("home-model")
      .evaluate((s) => [...s.options].find((o) => /qwen3-0\.6b/.test(o.textContent))?.value);
    await desk.getByTestId("home-model").selectOption(choice);
    await composer.fill("Suggest three names for a friendly home robot.");
    await composer.press("Enter");
    await expect(desk.getByTestId("home-turn-info")).toContainText("qwen3-0.6b", { timeout: 180000 });
    await desk.waitForTimeout(800);
    const card = cardOf(composer);
    const said = await textOf(card);
    await shoot(desk, "01-home-reply-desktop", {
      route: "/",
      locator: card,
      alt: `The Try it card on Eugene's Home page. The message "Suggest three names for a friendly home robot." has been sent to the model qwen3-0.6b, and its reply is shown with a line beneath it naming the model. Text on the card: ${said.slice(0, 260)}`,
    });
  }, desk);

  await step("03-home-use-from-apps-codex", async () => {
    await desk.goto(url);
    const apps = desk.getByTestId("home-use-from-apps");
    await expect(apps).toBeVisible({ timeout: 60000 });
    await desk.setViewportSize({ width: 1440, height: 2600 });
    await desk.waitForTimeout(500);
    await apps.getByRole("button", { name: "Codex", exact: true }).click();
    await expect(desk.getByTestId("recipe").first()).toBeVisible({ timeout: 20000 });
    await desk.waitForTimeout(500);
    const snippet = await textOf(desk.getByTestId("recipe-snippet").first());
    await shoot(desk, "03-home-use-from-apps-codex", {
      route: "/",
      around: [apps],
      alt: `The Use it from your apps card on Eugene's Home page, with the Codex recipe open. The card shows the gateway address, the model to use, a key made for the install named laptop (only the end of the key is shown, never the key itself), and Codex's connection settings: ${snippet.slice(0, 200)}`,
    });
    await desk.setViewportSize({ width: 1440, height: 900 });
  }, desk);

  const phone = await open(390, 844);
  await step("02-home-reply-phone", async () => {
    await phone.goto(url);
    const composer = phone.getByTestId("home-composer");
    await expect(composer).toBeEnabled({ timeout: 60000 });
    const choice = await phone
      .getByTestId("home-model")
      .evaluate((s) => [...s.options].find((o) => /qwen3-0\.6b/.test(o.textContent))?.value);
    await phone.getByTestId("home-model").selectOption(choice);
    await composer.fill("Give me one name for a cat, in one short sentence.");
    await composer.press("Enter");
    await expect(phone.getByTestId("home-turn-info")).toContainText("qwen3-0.6b", { timeout: 180000 });
    await phone.waitForTimeout(800);
    const card = cardOf(composer);
    await card.scrollIntoViewIfNeeded();
    const said = await textOf(card);
    await shoot(phone, "02-home-reply-phone", {
      route: "/",
      locator: card,
      alt: `Eugene's Home page on a phone-width screen (390 pixels wide), the Try it card. The model qwen3-0.6b has replied to "Give me one name for a cat, in one short sentence."; the card shows its model picker, message box, Send button and the reply: ${said.slice(0, 260)}`,
    });
  }, phone);

  // 4. Discover.
  await step("04-discover-works-here-now", async () => {
    await desk.goto(`${url}/discover/`);
    await expect(desk.getByTestId("starter-set")).toBeVisible({ timeout: 60000 });
    await desk.locator("select", { hasText: "Works here now" }).first().selectOption({ label: "Works here now" });
    await desk.waitForTimeout(4000);
    await desk.getByText("Qwen3.8-27B-GGUF", { exact: true }).first().click();
    await expect(desk.getByText("All versions")).toBeVisible({ timeout: 60000 });
    await desk.getByText("Will work on this machine now").first().click();
    await desk.waitForTimeout(800);
    const popover = await desk.evaluate(() => {
      const t = document.body.innerText;
      return t.split("\n").filter((l) => /^(llama\.cpp|vLLM|MLX|Strata|Kev)[^:]*:/.test(l)).join(" | ");
    });
    await shoot(desk, "04-discover-works-here-now", {
      route: "/discover/",
      alt: `Eugene's Discover page filtered to "Works here now". A model's page is open with its suggested version and the list of versions with sizes and fit labels; the "Will work on this machine now" label is open and gives each engine's reason and fit: ${popover.slice(0, 300)}`,
    });
  }, desk);

  // 5. A Library model page, and its Delete confirmation.
  await step("05-library-runs-as", async () => {
    await desk.goto(`${url}/library/`);
    await desk.getByText("nomic-embed-text-v1.5.Q8_0", { exact: true }).first().click();
    const runsAs = desk.getByTestId("run-runs-as");
    await expect(runsAs).toBeVisible({ timeout: 30000 });
    await runsAs.scrollIntoViewIfNeeded();
    await desk.waitForTimeout(1000);
    await shoot(desk, "05-library-runs-as", {
      route: "/library/",
      alt: "Eugene's Library page with the model nomic-embed-text-v1.5.Q8_0 selected. Beside the Run button its page says Runs as: search model (found in the file), with a link to change how it runs.",
    });
  }, desk);
  await step("05b-library-delete-confirmation", async () => {
    await desk.getByRole("button", { name: /^Delete/ }).first().click();
    const confirm = desk.getByText(/from the Library and from disk\?/).first();
    await expect(confirm).toBeVisible({ timeout: 20000 });
    await confirm.scrollIntoViewIfNeeded();
    await desk.getByRole("button", { name: /^Cancel/ }).first().scrollIntoViewIfNeeded();
    await desk.waitForTimeout(500);
    await shoot(desk, "05b-library-delete-confirmation", {
      route: "/library/",
      alt: "The Delete confirmation for the model nomic-embed-text-v1.5.Q8_0 in Eugene's Library, below the model's page. It lists the files that will be deleted from the disk and offers Cancel and a confirming button.",
    });
    await desk.getByRole("button", { name: /^Cancel/ }).first().click();
  }, desk);

  // 6. Settings -> Where to find models.
  await step("06-settings-where-to-find-models", async () => {
    await desk.goto(`${url}/config/`);
    const heading = desk.getByText("Where to find models", { exact: true }).first();
    await expect(heading).toBeVisible({ timeout: 60000 });
    const group = heading.locator("xpath=ancestor::*[.//button[normalize-space()='add a hub']][1]");
    await group.scrollIntoViewIfNeeded();
    await shoot(desk, "06-settings-where-to-find-models", {
      route: "/config/",
      around: [heading, group],
      alt: "Eugene's Settings page, the Where to find models setting: an ordered list of sources Discover searches, \"Engines' own lists\" (with llama.cpp's, vLLM's, MLX's, Kev's and Strata's lists) first and the Hugging Face hub second, each with up and down arrows and a remove button, and buttons to add a hub or an engine's list.",
    });
  }, desk);

  // 7. Backends: add a Gemini account (empty).
  await step("07-backends-add-gemini", async () => {
    await desk.goto(`${url}/backends/add/`);
    const which = desk.locator("select").filter({ hasText: "Google Gemini API" }).first();
    await which.selectOption({ label: "Google Gemini API" });
    await desk.waitForTimeout(800);
    const top = desk.getByText("Add an app you already run", { exact: true }).first();
    const last = desk.getByText("Not now", { exact: true }).first();
    await shoot(desk, "07-backends-add-gemini", {
      route: "/backends/add/",
      around: [top, which, last],
      alt: "Eugene's page for adding a backend, with Google Gemini API chosen. The form for the new account is shown with its fields empty, including the API key field, and Add and Not now buttons.",
    });
  }, desk);

  // 8. Routing: Web search order.
  await step("08-routing-web-search-order", async () => {
    await desk.goto(`${url}/routing/`);
    const order = desk.getByTestId("web-search-order");
    await expect(order).toBeVisible({ timeout: 60000 });
    await expect(desk.getByTestId("search-order-row").first()).toBeVisible({ timeout: 30000 });
    await order.scrollIntoViewIfNeeded();
    const rows = await textOf(order);
    await shoot(desk, "08-routing-web-search-order", {
      route: "/routing/",
      locator: order,
      alt: `The Web search order section of Eugene's Routing page. It lists the search accounts in the order Eugene tries them, each with move up and move down buttons: ${rows.slice(0, 300)}`,
    });
  }, desk);

  // 9. Machines.
  await step("09-machines", async () => {
    await desk.goto(`${url}/nodes/`);
    await expect(desk.getByTestId("node-versions").first()).toBeVisible({ timeout: 60000 });
    await desk.waitForTimeout(3000);
    await desk.setViewportSize({ width: 1440, height: 1700 });
    await desk.waitForTimeout(800);
    await desk.getByTestId("nodes-scroll").evaluate((e) => (e.scrollTop = 0));
    const shown = await textOf(desk.getByTestId("nodes-scroll"));
    // The machines listen on this host's own addresses; the picture shows demo addresses.
    await desk.evaluate(() => {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        n.nodeValue = (n.nodeValue ?? "").replace(/127\.0\.0\.1/g, "10.0.0.11");
      }
    });
    const install = desk.getByText("This install", { exact: true }).first().locator("xpath=ancestor::section[1]");
    const versions = desk.getByTestId("node-versions").first();
    await shoot(desk, "09-machines", {
      route: "/nodes/",
      around: [install, versions],
      alt: `Eugene's Machines page listing the two machines in the install, desk-pc and garage-nas, with their address, status, system and what each serves, and a Versions section with each machine's update status: ${shown.slice(0, 300)}`,
    });
    await desk.setViewportSize({ width: 1440, height: 900 });
  }, desk);

  // 10. Metrics.
  await step("10-metrics-request-outcomes", async () => {
    await desk.goto(`${url}/metrics/`);
    const heading = desk.getByText("Request outcomes", { exact: false }).first();
    await expect(heading).toBeVisible({ timeout: 60000 });
    await desk.waitForTimeout(2000);
    const group = heading.locator("xpath=ancestor::*[self::section or self::div][.//text()[contains(.,'served')]][1]");
    await group.scrollIntoViewIfNeeded();
    const said = await textOf(group);
    await shoot(desk, "10-metrics-request-outcomes", {
      route: "/metrics/",
      locator: group,
      alt: `The Request outcomes bar on Eugene's Metrics page for the selected time window: ${said.slice(0, 260)}`,
    });
  }, desk);

  // 11-15. Workbench.
  const WB = cfg.workbench;
  /** A browser signed in to Workbench the way a person does it: on Eugene's page, with the passphrase. */
  async function workbench(width, height) {
    const page = await open(width, height, null, null);
    await page.goto(WB + "/");
    await page.getByTestId("sign-in").click();
    await page.waitForSelector('input[name="password"]');
    if (await page.locator('input[name="name"]').count()) await page.fill('input[name="name"]', "operator");
    await page.fill('input[name="password"]', cfg.passphrase);
    await Promise.all([
      page.waitForURL((u) => u.toString().startsWith(WB), { timeout: 30000 }),
      page.click("button[type=submit]"),
    ]);
    // On a phone the sidebar that holds `me` is folded away, so the element is attached, not visible.
    await page.waitForSelector('[data-testid="me"]', { state: "attached", timeout: 30000 });
    return page;
  }
  const lastAnswer = (page) => page.locator('[data-testid="answer"]').last();
  async function finished(page, timeout = 600000) {
    await page.waitForFunction(
      () => {
        const all = document.querySelectorAll('[data-testid="answer"]');
        const last = all[all.length - 1];
        return all.length > 0 && last.getAttribute("data-status") !== "running";
      },
      undefined,
      { timeout },
    );
  }
  /** Types the question and sends it, and checks it went: the composer empties and the message appears. */
  async function ask(page, text) {
    const before = await page.locator('[data-testid="user-message"]').count();
    for (let attempt = 0; attempt < 3; attempt++) {
      await page.fill('[data-testid="composer"]', text);
      await page.getByTestId("send").click();
      try {
        await expect(page.locator('[data-testid="user-message"]')).toHaveCount(before + 1, { timeout: 15000 });
        return;
      } catch {
        await page.waitForTimeout(2000);
      }
    }
    throw new Error("the question was not sent");
  }
  const answerText = async (page) => textOf(lastAnswer(page));
  let wb = null;
  let phoneWb = null;
  const needWb = async () => (wb ??= await workbench(1440, 900));

  await step("11-workbench-attached-document", async () => {
    const page = await needWb();
    await page.goto(`${WB}/chats/${cfg.chats.plain}`);
    await page.waitForSelector('[data-testid="composer"]');
    await page.setInputFiles('[data-testid="attach-input"]', join(cfg.documents, "maple-street-garden-handbook.pdf"));
    await page.waitForSelector('ul[aria-label="Attached"] li, [data-testid="attached"]', { timeout: 60000 });
    await ask(page, "From the attached handbook: how often are the compost bins turned? Name the file you used.");
    await finished(page);
    await page.waitForTimeout(1000);
    await page.locator(`[data-testid="answer"]`).last().evaluate((e) => e.scrollIntoView({ block: "end" }));
    await page.evaluate(() => document.querySelectorAll("main, [data-testid='chat-scroll']").forEach((e) => (e.scrollTop = e.scrollHeight)));
    await page.waitForTimeout(600);
    const said = await answerText(page);
    await shoot(page, "11-workbench-attached-document", {
      route: `/chats/${cfg.chats.plain}`,
      alt: `A Workbench chat. The message attaches the file maple-street-garden-handbook.pdf and asks how often the compost bins are turned and which file was used. The answer from gemma-4-e4b follows: ${said.slice(0, 280)}`,
    });
  }, () => wb);

  await step("12-workbench-memory", async () => {
    const page = await needWb();
    await page.goto(`${WB}/memory`);
    await page.waitForSelector('[data-testid="memory-page"]', { timeout: 30000 });
    await page.waitForTimeout(1500);
    const said = await textOf(page.getByTestId("memory-page"));
    await page.getByText("Your notes", { exact: true }).first().evaluate((e) => e.scrollIntoView({ block: "start" }));
    await page.waitForTimeout(500);
    await shoot(page, "12-workbench-memory", {
      route: "/memory",
      alt: `Workbench's Memory page, listing three notes it keeps for the owner: ${said.slice(0, 300)}`,
    });
  }, () => wb);

  await step("13-workbench-cited-passage", async () => {
    const page = await needWb();
    await page.goto(`${WB}/chats/${cfg.chats.docs}`);
    await page.waitForSelector('[data-testid="composer"]');
    await ask(page, "When is the volunteer workday at the garden?");
    await finished(page);
    await page.waitForTimeout(1000);
    const toggle = page.getByTestId("passage-toggle").first();
    if (await toggle.count()) await toggle.click().catch(() => undefined);
    await page.waitForTimeout(800);
    await page.locator(`[data-testid="answer"]`).last().evaluate((e) => e.scrollIntoView({ block: "end" }));
    await page.evaluate(() => document.querySelectorAll("main, [data-testid='chat-scroll']").forEach((e) => (e.scrollTop = e.scrollHeight)));
    await page.waitForTimeout(600);
    const said = await answerText(page);
    await shoot(page, "13-workbench-cited-passage", {
      route: `/chats/${cfg.chats.docs}`,
      alt: `A Workbench chat with Documents on. The question is when the volunteer workday is; the answer from gemma-4-e4b is followed by its sources, which name the file maple-street-garden-handbook.pdf and the page the passage came from: ${said.slice(0, 300)}`,
    });
  }, () => wb);

  await step("14-workbench-tool-approval", async () => {
    const page = await needWb();
    await page.goto(`${WB}/chats/${cfg.chats.tool}`);
    await page.waitForSelector('[data-testid="composer"]');
    await ask(page, "Use your tool to list the files in my documents folder.");
    const approve = page.getByRole("button", { name: /^Approve/ }).first();
    await expect(approve).toBeVisible({ timeout: 600000 });
    await page.waitForTimeout(800);
    const said = await answerText(page);
    await shoot(page, "14-workbench-tool-approval", {
      route: `/chats/${cfg.chats.tool}`,
      alt: `A Workbench chat in which the model has asked to call a tool from the Documents folder server. The call is held, with its name and arguments shown and Approve call and Decline buttons, until the person decides: ${said.slice(0, 300)}`,
    });
    await page.getByRole("button", { name: /^Decline/ }).first().click();
  }, () => wb);

  await step("15-workbench-chat-phone", async () => {
    const page = (phoneWb = await workbench(390, 844));
    await page.goto(`${WB}/chats/${cfg.chats.docs}`);
    await page.waitForSelector('[data-testid="answer"]', { timeout: 60000 });
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(800);
    const said = await answerText(page);
    await shoot(page, "15-workbench-chat-phone", {
      route: `/chats/${cfg.chats.docs}`,
      alt: `Workbench at phone width (390 pixels wide), showing the chat about the volunteer workday: the question, the answer and its sources: ${said.slice(0, 260)}`,
    });
    await page.close();
  }, () => phoneWb);

  await desk.close();
  await phone.close();
} finally {
  await writeFile(join(output, "manifest.json"), JSON.stringify({ run: cfg.run, shots: manifest, failures }, null, 2));
  await browser.close();
}
if (failures.length) {
  console.log("FAILURES", JSON.stringify(failures));
  process.exitCode = 1;
}
