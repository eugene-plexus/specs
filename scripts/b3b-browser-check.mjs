// 2b.3b in the system Chrome: Workbench's own page against a real job site,
// driven by b3b-browser-check.py, which owns every process. Playwright comes
// from the ui checkout. Prints JSON: checks, and any problems the page reported.
// Each step after the setup reports its own failure and the run goes on, so a
// sabotage that breaks one step still reports the others.
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
const require = createRequire(cfg.playwright + "/");
const { chromium } = require(cfg.playwright);
const out = { checks: [], problems: [] };

function check(number, claim, passed, detail = "") {
  out.checks.push([
    number,
    claim,
    Boolean(passed),
    typeof detail === "string" ? detail : JSON.stringify(detail),
  ]);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** The site's own audit lines for tool calls, oldest first (one account here). */
function calls() {
  if (!existsSync(cfg.audit)) return [];
  return readFileSync(cfg.audit, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line))
    .filter((e) => e.method === "tools/call");
}

const onDisk = (name) => existsSync(join(cfg.folder, name));
const seen = async () => (await (await fetch(`${cfg.fixture}/stats`)).json()).seen;
const machine = async (action) =>
  (await fetch(`${cfg.fixture}/machine/${action}`, { method: "POST" })).json();

const chrome = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].find((p) => existsSync(p));
const browser = await chromium.launch({ executablePath: chrome, headless: true });

let asked = 0;
let page = null;
const lastAnswer = () => page.locator('[data-testid="answer"]').last();

/** Sends `text`, remembering how many answers there were, so the waits below
 * look at the new one; and counts approval prompts from here on. */
async function send(text) {
  await page.evaluate(() => {
    window.__seen.approve = 0;
  });
  asked = await page.locator('[data-testid="answer"]').count();
  await page.fill('[data-testid="composer"]', text);
  await page.keyboard.press("Enter");
  await page.waitForFunction(
    (before) => document.querySelectorAll('[data-testid="answer"]').length > before,
    asked,
    { timeout: 20000 },
  );
}

/** Until the newest answer ends ("ended") or shows an approval prompt
 * ("asks"); "timeout" if neither. With `prompts` false, only its end. */
async function settle(timeout = 60000, prompts = true) {
  try {
    const handle = await page.waitForFunction(
      ([before, prompts]) => {
        const all = document.querySelectorAll('[data-testid="answer"]');
        const last = all[all.length - 1];
        if (all.length <= before) return false;
        if (last.getAttribute("data-status") !== "running") return "ended";
        const asks = [...last.querySelectorAll("button")].some(
          (b) => b.textContent.trim() === "Approve call",
        );
        return prompts && asks ? "asks" : false;
      },
      [asked, prompts],
      { timeout },
    );
    return await handle.jsonValue();
  } catch {
    return "timeout";
  }
}

/** What the newest answer shows: its status, its words, and each call's line. */
async function shown() {
  const answer = lastAnswer();
  return {
    status: await answer.getAttribute("data-status"),
    // The end: the model's last words and the answer's status follow its calls.
    text: ((await answer.textContent()) ?? "").slice(-300),
    calls: await answer.locator('section[aria-label="Tool calls"] article p[role="status"]').allTextContents(),
    approvals: await page.evaluate(() => window.__seen.approve),
  };
}

/** One step: its own pass or failure, then whatever it left running is stopped. */
async function step(number, claim, work) {
  try {
    const [passed, detail] = await work();
    check(number, claim, passed, detail);
  } catch (error) {
    check(number, claim, false, `the step broke: ${String(error?.message ?? error).slice(0, 600)}`);
  }
  try {
    const stop = page.locator('[data-testid="stop"]');
    if (await stop.count()) {
      await stop.click();
      await settle(20000, false);
    }
  } catch {
    // The next step reports what this left behind.
  }
}

async function sites() {
  await page.goto(cfg.workbench + "/");
  await page.getByRole("button", { name: "Job sites (your machines)" }).click();
  return page.locator(`[data-testid="workspaces-${cfg.site}"]`);
}

/** The workspace's box, once the page lists one; reloads until it does. */
async function workspaceBox(seconds = 40) {
  const deadline = Date.now() + seconds * 1000;
  for (;;) {
    const section = await sites();
    await section.waitFor({ timeout: 20000 });
    const box = section.locator('[data-testid^="workspace-"]');
    if (await box.count()) return box.first();
    if (Date.now() > deadline) throw new Error("the page never listed ada's workspace");
    await sleep(1000);
  }
}

async function rulesShown(box) {
  return {
    read: await box.getByLabel("Read and search").inputValue(),
    change: await box.getByLabel("Change files").inputValue(),
  };
}

async function backToChat(url) {
  await page.goto(url);
  await page.waitForSelector('[data-testid="composer"]');
}

try {
  const context = await browser.newContext();
  await context.addInitScript(() => {
    window.__seen = { approve: 0 };
    const scan = () => {
      for (const b of document.querySelectorAll("button")) {
        if (b.textContent.trim() === "Approve call" && !b.__counted) {
          b.__counted = true;
          window.__seen.approve += 1;
        }
      }
    };
    new MutationObserver(scan).observe(document, { subtree: true, childList: true, characterData: true });
  });
  page = await context.newPage();
  page.on("pageerror", (e) => out.problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (/Content Security Policy|Refused/i.test(m.text())) out.problems.push(`console: ${m.text()}`);
  });
  page.on("response", (r) => {
    if (r.status() >= 500) out.problems.push(`${r.status()} ${new URL(r.url()).pathname}`);
  });

  // ---- the setup: if any of it fails, nothing after it can run -------------

  // W0. ada signs in on Eugene's own page.
  await page.goto(cfg.workbench + "/");
  await page.click('[data-testid="sign-in"]');
  await page.waitForSelector('input[name="password"]');
  await page.fill('input[name="name"]', "ada");
  await page.fill('input[name="password"]', cfg.password);
  await Promise.all([
    page.waitForURL((u) => u.toString().startsWith(cfg.workbench), { timeout: 20000 }),
    page.click("button[type=submit]"),
  ]);
  await page.waitForSelector('[data-testid="me"]', { timeout: 20000 });
  const me = (await page.textContent('[data-testid="me"]')) ?? "";
  check("W0", "ada signs in with Eugene and comes back to Workbench signed in", /ada/.test(me), me);

  // W0b. Her workspace, added from Workbench, waits for her key; approved at
  // the machine, it is hers with read "allow" and change "ask" (J68, J69).
  const section = await sites();
  await section.waitFor({ timeout: 20000 });
  const form = section.getByRole("form", { name: "Add a workspace on desk" });
  await form.getByLabel("Name").fill("Notes");
  await form.getByLabel("Path on desk").fill(cfg.folder);
  await form.getByRole("button", { name: "Add workspace" }).click();
  const notice = page.locator('[data-testid="job-site-held"]');
  await notice.waitFor({ timeout: 20000 });
  const heldSaid = (await notice.textContent()) ?? "";
  const listedBefore = await section.locator('[data-testid^="workspace-"]').count();
  const approved = await machine("approve");
  let box = await workspaceBox();
  const defaults = await rulesShown(box);
  check("W0b", "a workspace added in Workbench waits for ada's key, and once approved at the machine it is listed with read Without asking and change Ask me each time",
    /key/i.test(heldSaid) && listedBefore === 0 && approved.done === 1 &&
      defaults.read === "allow" && defaults.change === "ask",
    { heldSaid, listedBefore, approved, defaults });
  await page.screenshot({ path: `${cfg.shots}/1-workspace.png`, fullPage: true });

  // A chat with the workspace selected.
  await page.goto(cfg.workbench + "/");
  await page.click('[data-testid="new-chat"]');
  await page.waitForURL(/\/chats\//);
  const chatUrl = page.url();
  await page.getByRole("button", { name: "This chat's settings" }).click();
  const settings = page.locator('[data-testid="chat-settings"]');
  await settings.getByLabel(/desk · Notes · Read and write text/).check();
  const folderWords = (await settings.locator("fieldset", { hasText: "Folders for this chat" }).textContent()) ?? "";
  await settings.getByRole("button", { name: "Save", exact: true }).click();
  await settings.getByText("Saved.").waitFor({ timeout: 10000 });

  // ---- the steps ------------------------------------------------------------

  // W1. "allow": the read runs with no prompt, and the site applied allow.
  await step("W1", "a read the rules allow runs with no prompt: Finished, the answer done, and the site's line says allow, not asked", async () => {
    const before = calls().length;
    await send("W1: read the plan");
    const end = await settle();
    const view = await shown();
    const lines = calls().slice(before);
    return [end === "ended" && view.status === "done" && /W1-DONE/.test(view.text) &&
      view.approvals === 0 && view.calls.length === 1 && view.calls[0] === "Finished" &&
      lines.length === 1 && lines[0].tool === "read_text" && lines[0].rule === "allow" &&
      !("asked" in lines[0]) && lines[0].decision === "allowed" && lines[0].outcome === "done",
    { end, view, lines }];
  });

  // W1b. The chat's own words agree with the rules: not every operation waits.
  check("W1b", "the chat's folder list does not say every file operation waits for approval, when the rules let reads run",
    !/Each file operation waits for approval/.test(folderWords) && /your rules there/.test(folderWords),
    folderWords.slice(0, 300));

  // W2a. "ask": the write waits for ada, runs once she approves, and the site
  // is told she was asked (J72).
  await step("W2a", "a write the rules ask about prompts, nothing runs while it waits, and once approved it runs and the site's line says ask, asked", async () => {
    const before = calls().length;
    await send("W2a: write approved.txt");
    const first = await settle();
    const progress = (await page.locator('[data-testid="progress"]').textContent().catch(() => "")) ?? "";
    const waiting = { first, file: onDisk("approved.txt"), lines: calls().length - before, progress };
    if (first !== "asks") return [false, { waiting, view: await shown() }];
    await page.screenshot({ path: `${cfg.shots}/2-ask.png`, fullPage: true });
    await lastAnswer().getByRole("button", { name: "Approve call" }).click();
    const end = await settle(60000, false);
    const view = await shown();
    const lines = calls().slice(before);
    const written = onDisk("approved.txt") ? readFileSync(join(cfg.folder, "approved.txt"), "utf8") : null;
    return [!waiting.file && waiting.lines === 0 && /Review the tool calls/.test(waiting.progress) &&
      end === "ended" && view.status === "done" && view.calls[0] === "Finished" &&
      written === "written by W2a\n" && lines.length === 1 && lines[0].rule === "ask" &&
      lines[0].asked === true && lines[0].outcome === "done",
    { waiting, end, view, lines, written }];
  });

  // W2b. Declined: never runs, and never reaches the site.
  await step("W2b", "a write that is declined does not run, and nothing reaches the site", async () => {
    const before = calls().length;
    await send("W2b: write declined.txt");
    const first = await settle();
    if (first !== "asks") return [false, { first, view: await shown(), file: onDisk("declined.txt") }];
    await lastAnswer().getByRole("button", { name: "Decline" }).click();
    const end = await settle(60000, false);
    const view = await shown();
    return [end === "ended" && view.calls[0] === "Declined" && !onDisk("declined.txt") &&
      calls().length === before, { end, view, lines: calls().slice(before) }];
  });

  // W2c. Stop while a call waits for approval: the answer stops and the call never runs.
  await step("W2c", "Stop while a call waits for approval ends the answer, says so, and the call never runs", async () => {
    const before = calls().length;
    await send("W2c: write stopped.txt");
    const first = await settle();
    if (first !== "asks") return [false, { first, view: await shown(), file: onDisk("stopped.txt") }];
    await page.click('[data-testid="stop"]');
    const end = await settle(20000, false);
    const view = await shown();
    const said = (await lastAnswer().locator('[data-testid="answer-status"]').textContent().catch(() => "")) ?? "";
    await sleep(3000);
    return [end === "ended" && view.status === "stopped" && /Stopped/.test(said) &&
      view.calls[0] !== "Finished" && !onDisk("stopped.txt") && calls().length === before,
    { end, view, said, lines: calls().slice(before) }];
  });

  // W3. "deny": set in Workbench's rules editor, at once (a tightening, J51);
  // the next answer is offered no write tool, and one the model remembers is refused.
  await step("W3", "with change set to Never in the editor, the model is offered no write tool, and a write tool it remembers is refused before anything reaches the site", async () => {
    box = await workspaceBox();
    await box.getByLabel("Change files").selectOption("deny");
    await box.getByRole("button", { name: "Save rules" }).click();
    let inEffect = null;
    for (let i = 0; i < 40; i += 1) {
      await sleep(1000);
      box = await workspaceBox();
      inEffect = await rulesShown(box);
      if (inEffect.change === "deny") break;
    }
    await backToChat(chatUrl);
    const before = calls().length;
    const offeredBefore = (await seen()).length;
    await send("W3: write denied.txt");
    const end = await settle();
    const view = await shown();
    const offered = (await seen()).slice(offeredBefore).filter((s) => s.step === "W3");
    return [inEffect?.change === "deny" && offered.length >= 1 &&
      !offered[0].offered.some((t) => t === "write_text" || t === "edit_text") &&
      offered[0].offered.includes("read_text") && end === "ended" && view.status === "failed" &&
      /not offered/.test(view.text) && !onDisk("denied.txt") && calls().length === before,
    { inEffect, offered: offered[0]?.offered, end, view, lines: calls().slice(before) }];
  });

  // W3b. Giving access back is held for ada's key (J68): the editor does not
  // show it as in effect, before a reload or after one.
  await step("W3b", "a change back to Ask me each time waits for ada's key, and the editor keeps showing the rule in effect (Never)", async () => {
    box = await workspaceBox();
    await box.getByLabel("Change files").selectOption("ask");
    await box.getByRole("button", { name: "Save rules" }).click();
    await page.locator('[data-testid="job-site-held"]').waitFor({ timeout: 20000 }).catch(() => {});
    const heldWords = (await page.locator('[data-testid="job-site-held"], [role="alert"]').allTextContents()).join(" | ");
    await sleep(1500);
    const beforeReload = await rulesShown(box);
    box = await workspaceBox();
    const afterReload = await rulesShown(box);
    const turnedDown = await machine("reject");
    return [/key/i.test(heldWords) && beforeReload.change === "deny" && afterReload.change === "deny" &&
      turnedDown.done === 1, { heldWords, beforeReload, afterReload, turnedDown }];
  });

  // W4. 40 calls the rules allow, searching and reading, with no prompt (J71).
  await step("W4", "a 40-call search-and-read answer finishes with no prompt: 40 calls Finished, 40 allowed at the site, and the model got every result", async () => {
    await backToChat(chatUrl);
    const before = calls().length;
    await send("W4: search the docs and read them");
    const end = await settle(180000);
    const view = await shown();
    const lines = calls().slice(before);
    const last = (await seen()).filter((s) => s.step === "W4").at(-1);
    await page.screenshot({ path: `${cfg.shots}/3-forty.png`, fullPage: true });
    return [end === "ended" && view.status === "done" && /W4-DONE/.test(view.text) &&
      view.approvals === 0 && view.calls.length === 40 && view.calls.every((c) => c === "Finished") &&
      lines.length === 40 && lines.every((l) => l.rule === "allow" && l.outcome === "done") &&
      lines.filter((l) => l.tool === "glob").length === 1 &&
      lines.filter((l) => l.tool === "grep").length === 1 && last?.results === 40,
    { end, status: view.status, text: view.text.slice(-120), approvals: view.approvals,
      shown: view.calls.length, notFinished: view.calls.filter((c) => c !== "Finished"),
      atSite: lines.length, last }];
  });

  // W5. Stop ends an answer that would go on reading: no call after it.
  await step("W5", "Stop ends a reading answer that would go on: stopped, said so, and no call reaches the site or the model after it", async () => {
    await backToChat(chatUrl);
    const before = calls().length;
    await send("W5: keep reading");
    await page.waitForFunction(
      () => {
        const all = document.querySelectorAll('[data-testid="answer"]');
        const last = all[all.length - 1];
        return [...last.querySelectorAll('section[aria-label="Tool calls"] p[role="status"]')]
          .filter((p) => p.textContent === "Finished").length >= 5;
      },
      null,
      { timeout: 60000 },
    );
    await page.click('[data-testid="stop"]');
    const end = await settle(20000, false);
    const view = await shown();
    const atStop = { site: calls().length - before, model: (await seen()).filter((s) => s.step === "W5").length };
    await sleep(4000);
    const later = { site: calls().length - before, model: (await seen()).filter((s) => s.step === "W5").length };
    const said = (await lastAnswer().locator('[data-testid="answer-status"]').textContent().catch(() => "")) ?? "";
    await page.screenshot({ path: `${cfg.shots}/4-stopped.png`, fullPage: true });
    return [end === "ended" && view.status === "stopped" && /Stopped/.test(said) && atStop.site >= 5 &&
      later.site === atStop.site && later.model === atStop.model,
    { end, status: view.status, said, atStop, later }];
  });
} catch (error) {
  out.problems.push(`driver: ${error.stack || error}`);
} finally {
  await browser.close();
}
process.stdout.write(JSON.stringify(out));
