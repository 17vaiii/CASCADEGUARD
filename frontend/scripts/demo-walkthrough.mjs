// Walks through the guided faculty demo in a real browser and saves a screenshot per stage.
// Usage: node scripts/demo-walkthrough.mjs <out-dir> [url]
import { chromium } from "@playwright/test";

const [out = "screenshots", url = "http://localhost:5173/"] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });

await page.goto(url);
await page.waitForSelector(".react-flow__node", { timeout: 90000 });
await page.getByRole("button", { name: "Start demo" }).click();
const dialog = page.getByRole("dialog", { name: "Guided demonstration" });
await dialog.waitFor();

async function waitIdle() {
  // The top bar shows a spinner label while a backend task runs.
  await page.waitForFunction(() => !document.querySelector("header .animate-spin"), null, { timeout: 120000 });
  await page.waitForTimeout(1500);
}

for (let stage = 1; stage <= 7; stage++) {
  await waitIdle();
  if (stage === 3) {
    // Stage 3 plays the timeline; wait until playback stops at the analysis step.
    await page.waitForFunction(() => {
      const b = [...document.querySelectorAll("[role=dialog] button")].find((x) => x.textContent?.includes("Run detection"));
      return b && !b.hasAttribute("disabled");
    }, null, { timeout: 180000 });
    await page.waitForTimeout(1500);
  }
  const title = await dialog.locator("h2").textContent();
  await page.screenshot({ path: `${out}/demo-${stage}.png` });
  console.log(`stage ${stage}: ${title}`);
  if (stage < 7) await dialog.getByRole("button").last().click();
}
console.log(errors.length ? errors.slice(0, 20).join("\n") : "no browser errors");
await browser.close();
