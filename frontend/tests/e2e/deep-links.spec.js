// @ts-check
import { test, expect } from "@playwright/test";
import {
  PROPERTIES_PAGE,
  PROPERTIES_PAGE_FIVE,
  SAMPLE_PRICE_HISTORY,
  SAMPLE_PROPERTY,
  installCommonMocks,
  mockPropertiesByIds,
  mockPropertiesList,
  mockPropertyDetail,
  mockPriceHistoryByIds,
} from "./helpers/apiMocks.js";

test.describe("Shareable deep links (BIN-82)", () => {
  test("opening a property card updates the URL to /properties/:id", async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    await page.goto("/properties");
    await expect(page.locator("text=2BR Apartment Savassi")).toBeVisible();

    await page.locator("text=2BR Apartment Savassi").click();
    await expect(page).toHaveURL(/\/properties\/1$/);
    await expect(page.getByRole("button", { name: "Close modal" })).toBeVisible();
  });

  test("loading /properties/:id opens the property modal", async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    await page.goto("/properties/1");

    await expect(page.getByRole("button", { name: "Close modal" })).toBeVisible();
    await expect(page).toHaveURL(/\/properties\/1$/);

    await page.getByRole("button", { name: "Close modal" }).click();
    await expect(page).toHaveURL(/\/properties$/);
    await expect(page.getByRole("button", { name: "Close modal" })).toHaveCount(0);
  });

  test("favourites has its own URL and restores the favourites view", async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE);
    await page.route("**/api/favourites**", (route) => {
      const url = route.request().url();
      if (url.includes("/check/")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ is_favourited: true }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [SAMPLE_PROPERTY],
          total: 1,
        }),
      });
    });

    await page.goto("/properties");
    await page.getByTestId("favourites-nav").click();
    await expect(page).toHaveURL(/\/favourites$/);
    await expect(page.getByRole("heading", { name: /Favourites/ })).toBeVisible();
    await expect(page.locator("text=2BR Apartment Savassi")).toBeVisible();

    await page.goto("/favourites");
    await expect(page.getByRole("heading", { name: /Favourites/ })).toBeVisible();
    await expect(page.locator("text=2BR Apartment Savassi")).toBeVisible();

    await page.getByTestId("favourites-back").click();
    await expect(page).toHaveURL(/\/properties$/);
  });

  test("compare URL encodes ids and deep-link opens the compare view", async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE_FIVE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    await mockPropertiesByIds(page, PROPERTIES_PAGE_FIVE.properties);
    await mockPriceHistoryByIds(page, {
      "1": SAMPLE_PRICE_HISTORY,
      "2": SAMPLE_PRICE_HISTORY,
    });

    await page.goto("/properties");
    await page.getByTestId("compare-mode-toggle").click();
    await expect(page.getByTestId("compare-mode-toggle")).toHaveAttribute("aria-pressed", "true");
    await page.getByTestId("compare-select-1").click();
    await page.getByTestId("compare-select-2").click();
    await page.getByTestId("compare-open").click();

    await expect(page).toHaveURL(/\/compare\/1,2$/);
    await expect(page.getByTestId("compare-view")).toBeVisible();

    await page.getByTestId("compare-exit").click();
    await expect(page).toHaveURL(/\/properties$/);
    await expect(page.getByTestId("compare-bar")).toBeVisible();

    await page.goto("/compare/1,2");
    await expect(page.getByTestId("compare-view")).toBeVisible();
    await expect(page.getByTestId("compare-col-1")).toContainText("2BR Apartment Savassi");
    await expect(page.getByTestId("compare-col-2")).toContainText("3BR House Lourdes");
  });
});
