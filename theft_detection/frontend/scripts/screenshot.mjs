// Captures screenshots of the running app (dev: http://localhost:5173, or pass a URL).
// Usage: node scripts/screenshot.mjs <out-dir> [url] [view-tab-label]
import { chromium } from "@playwright/test";

const [out = "screenshots", url = "http://localhost:5173/", view = "Digital twin"] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const logs = [];
page.on("console", (m) => { if (m.type() === "error") logs.push("console: " + m.text()); });
page.on("pageerror", (e) => logs.push("pageerror: " + e.message));
await page.goto(url);
try {
  await page.waitForSelector(".react-flow__node", { timeout: 60000 });
} catch (e) {
  logs.push("no network nodes rendered: " + String(e.message).split("\n")[0]);
}
await page.waitForTimeout(3000);
if (view !== "Digital twin") {
  await page.getByRole("button", { name: view, exact: true }).click();
  await page.waitForTimeout(3000);
}
await page.screenshot({ path: `${out}/${view.replace(/\s+/g, "-").toLowerCase()}.png` });
if (logs.length) console.log(logs.slice(0, 20).join("\n"));
await browser.close();
