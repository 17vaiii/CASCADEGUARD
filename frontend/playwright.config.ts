import { defineConfig } from "@playwright/test";

// UI acceptance tests. Start the app first (scripts/run.ps1 serves the built UI on :8000),
// or set BASE_URL=http://localhost:5173 to test the Vite dev server.
export default defineConfig({
  testDir: "e2e",
  timeout: 180_000,
  expect: { timeout: 30_000 },
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://127.0.0.1:8000",
    viewport: { width: 1600, height: 900 },
    trace: "retain-on-failure",
  },
});
