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
    await expect(page.locator(".modal")).toContainText("3.500");
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
