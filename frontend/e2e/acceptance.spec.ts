/**
 * UI acceptance tests (project brief, section 18). They drive the real UI against the real
 * backend; values shown on screen are cross-checked against the API where it applies.
 */
import { expect, test, type Page } from "@playwright/test";

test.describe.configure({ mode: "serial" });

let page: Page;

async function waitIdle(p: Page) {
  await p.waitForFunction(() => !document.querySelector("header .animate-spin"), null, { timeout: 120_000 });
}

async function currentStep(p: Page): Promise<number> {
  return Number(await p.getByLabel("Timeline step").inputValue());
}

/** Sets the timeline slider like a user drag (native setter so React's onChange fires). */
async function setStep(p: Page, v: number) {
  await p.getByLabel("Timeline step").evaluate((el, value) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setter.call(el, String(value));
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, v);
  await expect.poll(() => currentStep(p)).toBe(v);
}

/** Switches the main view through the top navigation. */
async function view(p: Page, name: string) {
  await p.getByRole("navigation", { name: "Views" }).getByRole("button", { name, exact: true }).click();
}

async function simId(p: Page): Promise<string> {
  return p.evaluate(() => localStorage.getItem("gridwatch:last-sim") ?? "");
}

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
  await page.goto("/");
  await page.waitForSelector(".react-flow__node", { timeout: 120_000 });
  await waitIdle(page);
});

test.afterAll(async () => page.close());

test("1. initial state shows the labelled simulated network and its baseline", async () => {
  await expect(page.getByText("Simulated data, illustrative network")).toBeVisible();
  for (const f of ["F1", "F2", "F3", "F4"]) await expect(page.getByTestId(`feeder-tag-${f}`)).toBeVisible();
  await expect(page.getByText("Interconnected grid", { exact: true })).toBeVisible();
  await expect(page.getByText(/AC power flow \(pandapower\) solved in/)).toBeVisible();
  await expect(page.getByText("Feeders at this step")).toBeVisible();
});

test("2. timeline: play, pause, step, reset", async () => {
  await page.getByRole("button", { name: "Step forward one hour" }).click();
  await expect.poll(() => currentStep(page)).toBe(1);
  await page.getByRole("button", { name: "Play" }).click();
  await expect.poll(() => currentStep(page), { timeout: 60_000 }).toBeGreaterThan(4);
  await page.getByRole("button", { name: "Pause" }).click();
  const paused = await currentStep(page);
  await page.waitForTimeout(1500);
  expect(await currentStep(page)).toBe(paused);
  await page.getByRole("button", { name: "Step back one hour" }).click();
  await expect.poll(() => currentStep(page)).toBe(paused - 1);
  await page.getByRole("button", { name: "Reset to the first step" }).click();
  await expect.poll(() => currentStep(page)).toBe(0);
  await expect(page.getByText(/Step 0 of 335/)).toBeVisible();
});

test("3. selecting a feeder shows its measurements and highlights it", async () => {
  await page.getByTestId("feeder-tag-F2").click();
  await expect(page.getByRole("heading", { name: /Feeder F2/ })).toBeVisible();
  await expect(page.getByText("Feeder-head meter, last 24 h")).toBeVisible();
  await expect(page.getByTestId("feeder-tag-F2")).toHaveAttribute("data-selected", "true");
  await expect(page.getByTestId("feeder-tag-F1")).toHaveAttribute("data-dim", "true");
});

test("4. energy balance on screen matches the backend calculation", async () => {
  // Move to step 100 so the window is a full 24 h.
  await setStep(page, 100);
  await view(page, "Energy balance");
  await page.getByRole("button", { name: "Last 24 h" }).click();
  const formula = page.locator("text=/^U = [-−0-9.,]+ kWh \\(/").first();
  await expect(formula).toBeVisible();
  const id = await simId(page);
  const api = await page.request.get(`/api/simulations/${id}/energy-balance?kind=feeder&id=F2&t=100&start=77&end=101`);
  const b = await api.json();
  const shown = (await formula.textContent()) ?? "";
  const value = Number(shown.replace(/^U = /, "").split(" kWh")[0].replace(/,/g, "").replace("−", "-"));
  expect(value).toBeCloseTo(b.unexplained_kwh, 1);
  await expect(page.getByText("Unexplained energy imbalance is an investigation signal, not proof of electricity theft.")).toBeVisible();
});

test("5. injecting a scenario changes the underlying data", async () => {
  await view(page, "Digital twin");
  const open = page.getByRole("button", { name: "Open Scenario Lab" });
  if (await open.isVisible()) await open.click();
  await page.getByLabel("Scenario", { exact: true }).selectOption("C");
  await page.getByLabel("Feeder", { exact: true }).selectOption("F3");
  await page.getByRole("button", { name: "Inject scenario" }).click();
  await waitIdle(page);
  await expect(page.getByText("Simulated unmetered load", { exact: true })).toBeVisible();
  await setStep(page, 200);
  await page.getByRole("button", { name: "What changed vs normal?" }).click();
  await waitIdle(page);
  // The DT with the load changes most; same-feeder DTs may show a small voltage-coupling difference.
  await expect(page.getByText(/^DT meter F3-DT\d$/).first()).toBeVisible();
  await expect(page.getByText(/^Feeder meter F3$/)).toBeVisible();
});

test("6-7. detection runs and alerts carry explanations grounded in measurements", async () => {
  await page.getByRole("button", { name: "Run detection at this step" }).click();
  await waitIdle(page);
  await expect(page.getByText(/alerts at step 200 in \d+ ms/)).toBeVisible();
  const first = page.locator("button", { hasText: /^(Feeder|DT) F3/ }).first();
  await expect(first).toBeVisible();
  await first.click();
  await view(page, "Investigate");
  await expect(page.getByText(/unexplained [0-9.,]+ kWh \([0-9]+% of input, [0-9.]+ sigma\)/).first()).toBeVisible();
  await expect(page.getByText(/not proof of electricity theft/).first()).toBeVisible();
});

test("8. selecting an alert highlights the corresponding element on the network", async () => {
  await view(page, "Digital twin");
  const alert = page.locator("button", { hasText: /^DT F3-DT\d/ }).first();
  const dt = ((await alert.locator("span").first().textContent()) ?? "").replace("DT ", "").trim();
  await alert.click();
  await expect(page.getByTestId(`dt-${dt}`)).toHaveAttribute("data-selected", "true");
  await expect(page.getByTestId(`dt-${dt}`)).toHaveAttribute("data-status", "alert");
  await expect(page.getByTestId("feeder-tag-F1")).toHaveAttribute("data-dim", "true");
});

test("9. methods are compared using actual evaluation results", async () => {
  await view(page, "Investigate");
  await page.getByRole("button", { name: "Compare methods at this step" }).click();
  await expect(page.getByText("Random Forest (consumer + grid features)").first()).toBeVisible();
  await view(page, "Model evaluation");
  await expect(page.getByText("Model evaluation on the synthetic benchmark")).toBeVisible();
  const res = await (await page.request.get("/api/experiments/results")).json();
  expect(res.available).toBe(true);
  const f1 = res.main.consumer.find((r: { method: string }) => r.method === "rf_combined").f1 as number;
  await expect(page.getByText(f1.toFixed(3)).first()).toBeVisible();
});

test("10. same configuration and seed reproduce data and results", async () => {
  await view(page, "Digital twin");
  const open = page.getByRole("button", { name: "Open Scenario Lab" });
  if (await open.isVisible()) await open.click();
  await page.getByRole("button", { name: "Verify reproducibility" }).click();
  await waitIdle(page);
  await expect(page.getByText("Regenerated from the seed: identical data")).toBeVisible();
});

test("11. reset returns the scenario to its baseline state", async () => {
  await page.getByRole("button", { name: "Normal operation", exact: true }).click();
  await waitIdle(page);
  await expect(page.getByText("no event injected")).toBeVisible();
  const id = await simId(page);
  const sim = await (await page.request.get(`/api/simulations/${id}`)).json();
  expect(sim.config.scenario).toBe("A");
  expect(sim.events).toHaveLength(0);
});

test("12. the dashboard separates verified facts, assumptions, synthetic data and results", async () => {
  await view(page, "Sources and limits");
  for (const h of ["Publicly sourced facts", "Not verified, and therefore not claimed", "Modelling assumptions", "Synthetic elements", "Responsible use"]) {
    await expect(page.getByRole("heading", { name: h })).toBeVisible();
  }
});

test("demo: the guided demonstration runs through all seven stages", async () => {
  await page.getByRole("button", { name: "Start demo" }).click();
  const dialog = page.getByRole("dialog", { name: "Guided demonstration" });
  for (let stage = 1; stage <= 7; stage++) {
    await waitIdle(page);
    if (stage === 3) await expect(dialog.getByRole("button", { name: /Run detection/ })).toBeEnabled({ timeout: 150_000 });
    await expect(dialog.getByText(`${stage} / 7`)).toBeVisible();
    if (stage < 7) await dialog.getByRole("button").last().click();
  }
  await expect(dialog.getByText(/identical data fingerprint/)).toBeVisible({ timeout: 60_000 });
});
