// @ts-check
import { defineConfig } from "@playwright/test";

const e2ePort = Number(process.env.PLAYWRIGHT_PORT || 5177);

export default defineConfig({
  testDir: "./tests/e2e",
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${e2ePort}`,
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
  webServer: {
    command: `npm run dev -- --port ${e2ePort}`,
    port: e2ePort,
    // Avoid attaching to an unrelated Vite on :5173 (common in parallel worktrees).
    reuseExistingServer: false,
  },
});
