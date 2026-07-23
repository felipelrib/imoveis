// @ts-check
import { test, expect } from "@playwright/test";
import {
  EMPTY_PROPERTIES,
  PROPERTIES_PAGE,
  SAMPLE_PROPERTY,
  installCommonMocks,
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
    await expect(page.locator("text=Scraper enqueued").or(page.locator("text=task-e2e-1")).or(page.locator("text=Enqueuing"))).toBeVisible({
      timeout: 10000,
    });
  });
});
