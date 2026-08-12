// @ts-check
import { test, expect } from "@playwright/test";
import {
  PROPERTIES_PAGE,
  installCommonMocks,
} from "./helpers/apiMocks.js";

test.describe("Max price rent/sale filter (BIN-77/BIN-79)", () => {
  test("max price is text (no steppers) and sends price_type=sale", async ({ page }) => {
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

    await page.getByRole("button", { name: /Filtros avançados/i }).click();

    const maxPrice = page.getByTestId("max-price-input");
    await expect(maxPrice).toBeVisible();
    // type=text cannot render native number steppers (BIN-79).
    await expect(maxPrice).toHaveAttribute("type", "text");
    await expect(maxPrice).toHaveAttribute("inputMode", "numeric");

    await page.getByTestId("price-type-filter").selectOption("sale");
    await maxPrice.fill("500000");

    await expect
      .poll(() =>
        listUrls.some((u) => {
          const decoded = decodeURIComponent(u.replace(/\+/g, " "));
          return (
            decoded.includes("max_price=500000") &&
            decoded.includes("price_type=sale")
          );
        }),
      )
      .toBeTruthy();
  });

  test("transaction Sale Only syncs price type to sale", async ({ page }) => {
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

    await page.locator("label", { hasText: "Transação" }).locator("..").locator("select").selectOption("sale");
    await page.getByRole("button", { name: /Filtros avançados/i }).click();
    await expect(page.getByTestId("price-type-filter")).toHaveValue("sale");

    await page.getByTestId("max-price-input").fill("900000");

    await expect
      .poll(() =>
        listUrls.some((u) => {
          const decoded = decodeURIComponent(u.replace(/\+/g, " "));
          return (
            decoded.includes("listing_type=sale") &&
            decoded.includes("max_price=900000") &&
            decoded.includes("price_type=sale")
          );
        }),
      )
      .toBeTruthy();
  });
});
