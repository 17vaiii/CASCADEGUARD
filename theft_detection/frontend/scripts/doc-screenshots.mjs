// Regenerates the README / docs screenshots from the running app.
// Usage: node scripts/doc-screenshots.mjs [out-dir=../docs/screenshots] [url=http://127.0.0.1:8000/]
import { chromium } from "@playwright/test";

const [out = "../docs/screenshots", url = "http://127.0.0.1:8000/"] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const idle = () => page.waitForFunction(() => !document.querySelector("header .animate-spin"), null, { timeout: 180000 });
const nav = (name) => page.getByRole("navigation", { name: "Views" }).getByRole("button", { name, exact: true }).click();
const shot = async (name) => { await page.mouse.move(2, 880); await page.waitForTimeout(2500); await page.screenshot({ path: `${out}/${name}.png` }); console.log("saved", name); };

await page.goto(url);
await page.waitForSelector(".react-flow__node", { timeout: 120000 });
await idle();

// Run the guided demo up to the detection stage, then close the guide for clean captures.
await page.getByRole("button", { name: "Start demo" }).click();
const dialog = page.getByRole("dialog", { name: "Guided demonstration" });
for (let stage = 1; stage <= 3; stage++) {
  await idle();
  if (stage === 3) {
    await page.waitForFunction(() => {
      const b = [...document.querySelectorAll("[role=dialog] button")].find((x) => x.textContent?.includes("Run detection"));
      return b && !b.hasAttribute("disabled");
    }, null, { timeout: 180000 });
    await shot("demo-observe");
  }
  await dialog.getByRole("button").last().click();
}
await idle();
await page.getByRole("button", { name: "Exit demo" }).click();
await page.getByTestId("feeder-tag-F2").click();
await shot("digital-twin");

await nav("Energy balance");
await page.getByRole("button", { name: "Last 72 h" }).click();
await shot("energy-balance");

await nav("Digital twin");
await page.locator("button", { hasText: /^C-F2-/ }).first().click();
await nav("Investigate");
await shot("investigate");
await page.getByRole("button", { name: "Compare methods at this step" }).click();
await idle();
await shot("compare-methods");

await nav("Model evaluation");
await shot("model-evaluation");
await nav("Sources and limits");
await shot("sources");
await browser.close();
