// @ts-check
import { test, expect } from "@playwright/test";
import {
  PROPERTIES_PAGE,
  installCommonMocks,
} from "./helpers/apiMocks.js";

test.describe("City and neighborhood searchable multi-select (BIN-70)", () => {
  test("city and neighborhood dropdowns open on click, search, and filter requests", async ({
    page,
  }) => {
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

    await page.getByRole("button", { name: /Advanced Filters/i }).click();

    // Dropdown closed until trigger clicked
    await expect(page.getByTestId("neighborhood-filter-dropdown")).toHaveCount(0);
    await page.getByTestId("neighborhood-filter-trigger").click();
    await expect(page.getByTestId("neighborhood-filter-dropdown")).toBeVisible();
    await expect(
      page.getByTestId("neighborhood-filter-dropdown").getByText("Belo Horizonte"),
    ).toBeVisible();
    await expect(
      page.getByTestId("neighborhood-filter-dropdown").getByText("São Paulo"),
    ).toBeVisible();

    await page.getByTestId("neighborhood-filter-search").fill("Pinheiros");
    await expect(page.getByRole("option", { name: /Pinheiros/i })).toBeVisible();
    await expect(page.getByRole("option", { name: /Savassi/i })).toHaveCount(0);
    await page.getByRole("option", { name: /Pinheiros/i }).click();

    await page.getByTestId("city-filter-trigger").click();
    await expect(page.getByTestId("city-filter-dropdown")).toBeVisible();
    await page
      .getByTestId("city-filter-dropdown")
      .getByRole("option", { name: /São Paulo/i })
      .click();

    await expect
      .poll(() =>
        listUrls.some((u) => {
          const decoded = decodeURIComponent(u.replace(/\+/g, " "));
          return (
            decoded.includes("neighborhood_name=") &&
            decoded.includes("Pinheiros") &&
            decoded.includes("city_name=") &&
            decoded.includes("São Paulo")
          );
        })
      )
      .toBeTruthy();
  });
});
