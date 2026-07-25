// @ts-check
import { test, expect } from "@playwright/test";
import {
  PROPERTIES_PAGE,
  installCommonMocks,
} from "./helpers/apiMocks.js";

test.describe("Property type filter + platform labels (BIN-75)", () => {
  test("type select sends canonical property_type query param", async ({ page }) => {
    await installCommonMocks(page);

    /** @type {string[]} */
    const listUrls = [];
    await page.route("**/api/properties?**", async (route) => {
      listUrls.push(route.request().url());
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(PROPERTIES_PAGE),
      });
    });

    await page.goto("/properties");
    await expect(page.getByText("2BR Apartment Savassi")).toBeVisible();

    await page.getByTestId("property-type-filter").selectOption("apartment");

    await expect
      .poll(() =>
        listUrls.some((u) => {
          const decoded = decodeURIComponent(u.replace(/\+/g, " "));
          return decoded.includes("property_type=apartment");
        }),
      )
      .toBeTruthy();
  });

  test("property card shows display platform label, not raw slug", async ({ page }) => {
    await installCommonMocks(page);
    await page.route("**/api/properties?**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(PROPERTIES_PAGE),
      });
    });

    await page.goto("/properties");
    const card = page.locator(".property-card").first();
    await expect(card.getByText("OLX", { exact: true })).toBeVisible();
    await expect(card.getByText("olx", { exact: true })).toHaveCount(0);
  });

  test("scraper control platform select shows display labels", async ({ page }) => {
    await installCommonMocks(page);
    await page.goto("/scraper");
    const select = page.getByTestId("scraper-platform-select");
    await expect(select.locator("option[value='olx']")).toHaveText(/OLX/);
    await expect(select.locator("option[value='quintoandar']")).toHaveText(/QuintoAndar/);
  });
});
