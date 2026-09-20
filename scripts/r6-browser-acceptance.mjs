/** Packaged UI + real disposable agent/llama-bench. Only Library catalogue reads
 * are fixtures. Args: session JSON {url,token}, existing small GGUF, output folder.
 * Serve the installed UI wheel, never next dev or a checkout's out directory.
 */
import { createRequire } from "node:module";
import { readFile, mkdir } from "node:fs/promises";
import { join } from "node:path";
import assert from "node:assert/strict";

const require = createRequire(new URL("../../ui/package.json", import.meta.url));
const { chromium } = require("@playwright/test");
const [sessionFile, modelPath, output] = process.argv.slice(2);
assert(sessionFile && modelPath && output, "session JSON, model path and output directory required");
const { url, token } = JSON.parse(await readFile(sessionFile, "utf8"));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", error => errors.push(String(error)));
  await page.addInitScript(value => sessionStorage.setItem("eugene-session-token", value), token);
  const model = { id: "cpu-browser", name: "Qwen CPU browser acceptance", path: modelPath,
    format: "gguf", status: "present", sizeBytes: 396705472, files: [], contextLength: 256 };
  const profile = { id: "cpu-profile", name: "CPU acceptance", engine: "llama_cpp", default: true,
    flags: { contextSize: 256, gpuLayers: 0, threads: 2 }, env: { CUDA_VISIBLE_DEVICES: "-1" } };
  await page.route("**/api/proxy/library/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let body = {};
    if (path.endsWith("/profiles")) body = { profiles: [profile] };
    else if (path.endsWith("/models")) body = { models: [model] };
    else if (path.endsWith("/downloads")) body = { downloads: [] };
    else if (path.endsWith("/scan")) body = { state: "idle" };
    else return route.fulfill({ status: 503, json: { detail: "Catalogue fixture: fit is not measured here" } });
    await route.fulfill({ json: body });
  });
  await page.route("**/api/proxy/control/**", route => route.fulfill({ status: 503, json: { detail: "Standalone acceptance agent" } }));
  await page.goto(`${url}/library/?model=cpu-browser`);
  await page.getByRole("button", { name: "Benchmark", exact: true }).click();
  await page.getByLabel("Generated tokens per sample").fill("16");
  await page.getByLabel("Repetitions", { exact: true }).fill("2");
  const submitted = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/v1/benchmarks"));
  await page.getByRole("button", { name: "Start benchmark", exact: true }).click();
  const started = await (await submitted).json();
  assert.equal(started.request.tokens, 16);
  assert.equal(started.request.repetitions, 2);
  const table = page.locator("section[aria-label='Benchmark CPU acceptance'] article").first()
    .getByRole("table", { name: "Measured decode speed" });
  await table.waitFor({ timeout: 60000 });
  assert.equal(await table.locator("tbody tr").count(), 3);
  let job;
  for (let i = 0; i < 100; i++) {
    const result = await page.request.get(`${url}/v1/benchmarks`, { headers: { Authorization: `Bearer ${token}` } });
    job = (await result.json()).benchmarks.find(j => j.id === started.id);
    if (job.state !== "running") break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.equal(job.state, "completed");
  assert.deepEqual(job.depths, [0, 120, 240]);
  await table.scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(output, "benchmark-desktop.png"), fullPage: true });
  await page.reload();
  await page.getByRole("button", { name: "Benchmark", exact: true }).click();
  await page.getByRole("table", { name: "Measured decode speed" }).first().waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("table", { name: "Measured decode speed" }).first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(output, "benchmark-phone.png"), fullPage: true });
  assert.deepEqual(errors, []);
  console.log("PASS wheel-served browser start, real results, reload history and two viewport renders");
  console.log(JSON.stringify({ engineVersion: job.engineVersion, depths: job.depths, points: job.points }));
} finally {
  await browser.close();
}
