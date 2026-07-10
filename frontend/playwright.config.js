// @ts-check
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
  webServer: process.env.CI
    ? undefined
    : {
        command: "npm run dev -- --port 5173",
        port: 5173,
        reuseExistingServer: true,
      },
});
