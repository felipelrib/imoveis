// @ts-check
import { test, expect } from "@playwright/test";

// ---------------------------------------------------------------------------
// Critical user flows: Dashboard, Property modal, Scraper control
// ---------------------------------------------------------------------------

test.describe("Dashboard page", () => {
  test("loads and shows system status", async ({ page }) => {
    await page.route("**/api/system/status", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          redis: true,
          database: true,
          ai_worker_count: 1,
          scraper_worker_count: 2,
        }),
      })
    );

    await page.goto("/");
    await expect(page.locator("text=System Status")).toBeVisible();
    await expect(page.locator("text=Redis")).toBeVisible();
  });

  test("shows empty state when no properties", async ({ page }) => {
    await page.route("**/api/system/status", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ redis: true, database: true }),
      })
    );

    await page.route("**/api/properties**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], page: 1, page_size: 24, total: 0 }),
      })
    );

    await page.goto("/properties");
    // Should render something meaningful, not a blank page
    await expect(page.locator("body")).not.toBeEmpty();
  });

  test("displays property cards when data available", async ({ page }) => {
    await page.route("**/api/properties**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              id: "1",
              title: "2BR Apartment Savassi",
              price: 3500,
              area_m2: 75,
              bedrooms: 2,
              bathrooms: 1,
              platform: "olx",
              combined_score: 0.72,
            },
          ],
          page: 1,
          page_size: 24,
          total: 1,
        }),
      })
    );

    await page.goto("/properties");
    await expect(page.locator("text=2BR Apartment Savassi")).toBeVisible();
  });
});

test.describe("Scraper control", () => {
  test("shows platform list for triggering scrapes", async ({ page }) => {
    await page.route("**/api/platforms", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          olx: { name: "OLX Brasil", enabled: true },
          quintoandar: { name: "QuintoAndar", enabled: true },
        }),
      })
    );

    await page.goto("/scraper");
    await expect(page.locator("text=OLX")).toBeVisible();
    await expect(page.locator("text=QuintoAndar")).toBeVisible();
  });
});
