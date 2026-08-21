import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for dashboard E2E tests.
 *
 * Tests live in ./e2e and assume a running dashboard at
 * http://localhost:3000 (frontend) + http://localhost:4440 (GraphQL API).
 * Start the dashboard with `speed dashboard start` before running
 * `npx playwright test`.
 *
 * These tests intentionally do NOT start the dashboard themselves
 * because the backend needs to run inside the repo's venv with
 * SPEED_ACTOR env vars set, which is easier to manage by hand.
 */

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
