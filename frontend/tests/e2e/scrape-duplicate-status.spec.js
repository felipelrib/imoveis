// @ts-check
import { test, expect } from "@playwright/test";
import {
  ENRICHMENT_COVERAGE,
  installCommonMocks,
  mockAdminBackfill,
  mockAdminCoverage,
  mockAdminLocale,
  mockPlatforms,
  mockScrapeTrigger,
} from "./helpers/apiMocks.js";

/**
 * Story 1.18: `POST /scrape` is single-flight per platform and scope. A trigger
 * of a scrape that is already queued or running answers 200 with
 * `already_queued` / `already_running` and publishes nothing. Before this spec
 * the page ignored the body and said "enqueued" for all three statuses.
 */

const VALID_KEY = "e2e-test-api-key";

/** @param {import("@playwright/test").Page} page @param {object} response */
async function bootScraperControl(page, response) {
  await page.addInitScript((key) => {
    sessionStorage.setItem("api_key", key);
  }, VALID_KEY);
  await installCommonMocks(page);
  await mockAdminLocale(page, { initial: "pt-BR", defaultLocale: "pt-BR" });
  await mockPlatforms(page);
  await mockAdminBackfill(page, {});
  await mockAdminCoverage(page, ENRICHMENT_COVERAGE);
  await mockScrapeTrigger(page, response);
  await page.goto("/scraper");
}

const CASES = [
  {
    status: "queued",
    toast: "Scraper enfileirado",
    log: "Enfileirado — acompanhe o Pipeline ao vivo",
  },
  {
    status: "already_queued",
    toast: "Este scrape já está na fila",
    log: "Não enfileirado — este scrape já está aguardando na fila.",
  },
  {
    status: "already_running",
    toast: "Este scrape já está em execução",
    log: "Não enfileirado — este scrape já está em execução.",
  },
];

test.describe("Scraper Control — manual trigger tells what POST /scrape did", () => {
  for (const { status, toast, log } of CASES) {
    test(`status ${status} is reported as it is`, async ({ page }) => {
      await bootScraperControl(page, { task_id: "task-abc", platform: "olx", status });

      const run = page.getByRole("button", { name: "Executar scraper" });
      await expect(run).toBeEnabled();
      await run.click();

      const toasts = page.getByTestId("toast");
      await expect(toasts).toHaveCount(1);
      await expect(toasts.first()).toContainText(toast);
      await expect(page.getByText(log)).toBeVisible();
      if (status !== "queued") {
        await expect(page.getByText("Scraper enfileirado")).toHaveCount(0);
        await expect(page.getByText("Enfileirado — acompanhe")).toHaveCount(0);
      }
    });
  }
});
