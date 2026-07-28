// @ts-check
import { test, expect } from "@playwright/test";
import {
  EMPTY_PROPERTIES,
  PROPERTIES_PAGE,
  SAMPLE_PROPERTY,
  installCommonMocks,
  mockAdminHealth,
  mockPlatforms,
  mockPropertiesList,
  mockPropertyDetail,
  mockScrapeTrigger,
} from "./helpers/apiMocks.js";

test.describe("Dashboard page", () => {
  test("loads and shows service status", async ({ page }) => {
    await installCommonMocks(page);
    await page.goto("/");
    await expect(page.locator("text=Service Status")).toBeVisible();
    await expect(page.locator("text=Redis").first()).toBeVisible();
    await expect(page.locator("text=PostgreSQL")).toBeVisible();
  });

  test("shows em dash for property counts when database is unhealthy (BIN-60)", async ({
    page,
  }) => {
    await installCommonMocks(page, {
      status: {
        database: { status: "error", detail: "connection refused" },
        redis: { status: "ok" },
        ollama: { status: "ok", models: ["llava"] },
        workers: { status: "ok" },
        ai_workers_paused: false,
        stats: { total_properties: null, enriched_properties: null },
      },
    });
    await page.goto("/");
    const totalCard = page.locator(".stat-card").filter({ hasText: "Total Properties" });
    await expect(totalCard.locator(".stat-value")).toHaveText("—");
    await expect(totalCard.locator(".stat-sub")).toHaveText("database unavailable");
    // Must not flash a false empty database.
    await expect(totalCard.locator(".stat-value")).not.toHaveText("0");
  });

  test("queues enrich-missing from Quick Actions", async ({ page }) => {
    await installCommonMocks(page);
    let enrichCalled = false;
    await page.route("**/api/admin/enrichment/missing", async (route) => {
      enrichCalled = route.request().method() === "POST";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ queued_enrichments: 3, skipped_no_images: 1 }),
      });
    });
    await page.goto("/");
    await page.getByTestId("enrich-missing").click();
    await expect(page.getByTestId("enrich-missing-result")).toContainText(
      "Queued 3 for enrichment"
    );
    await expect.poll(() => enrichCalled).toBeTruthy();
  });

  test("dry-run enrichment re-run posts body and shows would_queue (BIN-95)", async ({
    page,
  }) => {
    await installCommonMocks(page);
    /** @type {object | null} */
    let posted = null;
    await page.route("**/api/admin/enrichment/rerun", async (route) => {
      if (route.request().method() === "POST") {
        posted = route.request().postDataJSON();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            mode: "force",
            stages: "all",
            dry_run: true,
            queued: 0,
            would_queue: 7,
            skipped_no_images: 0,
            skipped_too_few_photos: 0,
            skipped_missing_prior_enrichment: 0,
            filters: {},
          }),
        });
        return;
      }
      await route.fallback();
    });
    await page.goto("/");
    await expect(page.getByTestId("enrichment-rerun-panel")).toBeVisible();
    await page.getByTestId("enrichment-rerun-mode").selectOption("force");
    await page.getByTestId("enrichment-rerun-dry-run").click();
    await expect(page.getByTestId("enrichment-rerun-result")).toContainText(
      "Would queue 7"
    );
    await expect.poll(() => posted?.mode).toBe("force");
    await expect.poll(() => posted?.dry_run).toBe(true);
  });

  test("force enrichment re-run sends mode=force (BIN-95)", async ({ page }) => {
    await installCommonMocks(page);
    /** @type {object | null} */
    let posted = null;
    await page.route("**/api/admin/enrichment/rerun", async (route) => {
      if (route.request().method() === "POST") {
        posted = route.request().postDataJSON();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            mode: "force",
            stages: "verdict_only",
            dry_run: false,
            queued: 2,
            would_queue: 2,
            skipped_no_images: 0,
            skipped_too_few_photos: 0,
            skipped_missing_prior_enrichment: 1,
            filters: {},
          }),
        });
        return;
      }
      await route.fallback();
    });
    await page.goto("/");
    await page.getByTestId("enrichment-rerun-mode").selectOption("force");
    await page.getByTestId("enrichment-rerun-stages").selectOption("verdict_only");
    await page.getByTestId("enrichment-rerun-run").click();
    await expect(page.getByTestId("enrichment-rerun-result")).toContainText("Queued 2");
    await expect.poll(() => posted?.mode).toBe("force");
    await expect.poll(() => posted?.stages).toBe("verdict_only");
    await expect.poll(() => posted?.dry_run).toBe(false);
  });

  test("loads pipeline history into charts on mount (BIN-61)", async ({ page }) => {
    await installCommonMocks(page);
    const ts = new Date().toISOString();
    await page.route("**/api/system/pipeline/history**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          points: [
            {
              ts,
              total_properties: 10,
              enriched_properties: 1,
              scraper_queue: 2,
              ai_queue: 3,
              throughput_per_min: 1.5,
            },
            {
              ts,
              total_properties: 11,
              enriched_properties: 2,
              scraper_queue: 1,
              ai_queue: 4,
              throughput_per_min: 2.0,
            },
          ],
        }),
      })
    );
    await page.goto("/");
    await expect(page.getByText(/AI Throughput/i)).toBeVisible();
    await expect(page.locator(".recharts-responsive-container").first()).toBeVisible();
  });
});

test.describe("Properties critical path", () => {
  test("shows empty state when no properties", async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, EMPTY_PROPERTIES);
    await page.goto("/properties");
    await expect(page.locator("text=No properties found")).toBeVisible();
  });

  test("displays property cards when data available", async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE);
    await page.goto("/properties");
    await expect(page.locator("text=2BR Apartment Savassi")).toBeVisible();
  });

  test("applies bedroom filter and reloads list", async ({ page }) => {
    await installCommonMocks(page);
    /** @type {string[]} */
    const requested = [];
    await page.route("**/api/properties?**", async (route) => {
      requested.push(route.request().url());
      const url = new URL(route.request().url());
      const minBed = url.searchParams.get("min_bedrooms");
      const body =
        minBed === "2"
          ? PROPERTIES_PAGE
          : { ...PROPERTIES_PAGE, properties: [], total: 0 };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    });

    await page.goto("/properties");
    await page.getByRole("button", { name: /Advanced Filters/i }).click();
    await page.locator("label", { hasText: "Beds" }).locator("..").locator("select").selectOption("2");

    await expect
      .poll(() => requested.some((u) => u.includes("min_bedrooms=2")))
      .toBeTruthy();
  });

  test("opens property modal with detail", async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    await page.goto("/properties");
    await page.locator("text=2BR Apartment Savassi").click();
    await expect(page.locator(".modal")).toBeVisible();
    await expect(page.locator(".modal")).toContainText("2BR Apartment Savassi");
    await expect(page.locator(".modal")).toContainText("3,500");
  });
});

test.describe("Scraper control critical path", () => {
  test("shows platforms and triggers scrape", async ({ page }) => {
    await installCommonMocks(page);
    await mockPlatforms(page);
    await mockScrapeTrigger(page, { task_id: "task-e2e-1" });

    await page.goto("/scraper");
    await expect(page.locator("select.form-select").first()).toBeVisible();
    await expect(page.locator("option[value='olx']")).toHaveCount(1);
    await expect(page.locator("option[value='quintoandar']")).toHaveCount(1);

    await page.getByRole("button", { name: /Run Scraper/i }).click();
    await expect(page.getByText(/Scraper enqueued|Task enqueued|Enqueuing/i).first()).toBeVisible({
      timeout: 10000,
    });
  });

  test("skips schedule poll without credential and attaches key when set", async ({ page }) => {
    /** @type {string[]} */
    const scheduleKeys = [];
    /** @type {string[]} */
    const scheduleUrls = [];

    await installCommonMocks(page);
    await mockPlatforms(page);
    await mockAdminHealth(page, { validKey: "e2e-test-api-key" });

    await page.route("**/api/admin/schedule**", async (route) => {
      scheduleUrls.push(route.request().url());
      const key = route.request().headers()["x-api-key"] || "";
      scheduleKeys.push(key);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          schedules: [
            {
              platform: "olx",
              interval_minutes: 60,
              last_run: null,
              next_run: null,
              estimated: false,
            },
          ],
        }),
      });
    });

    // Clear credential once (do not use addInitScript — it re-runs on every nav).
    await page.goto("/");
    await page.evaluate(() => sessionStorage.clear());

    await page.goto("/scraper");
    await expect(page.getByText("Paste API credential to load schedules.")).toBeVisible();
    await expect.poll(() => scheduleUrls.length, { timeout: 2000 }).toBe(0);

    await page.getByTestId("credential-input").fill("e2e-test-api-key");
    await page.getByTestId("credential-save").click();
    await expect(page.getByTestId("credential-status")).toHaveText("set");

    // Remount scraper so the schedule effect runs with the stored key.
    await page.goto("/scraper");
    await expect.poll(() => scheduleKeys.some((k) => k === "e2e-test-api-key")).toBeTruthy();
    await expect(page.getByText(/Interval:/i).first()).toBeVisible();
  });
});
