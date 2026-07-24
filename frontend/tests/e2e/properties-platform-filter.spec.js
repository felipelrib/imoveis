// @ts-check
import { test, expect } from "@playwright/test";
import {
  PROPERTIES_PAGE,
  installCommonMocks,
} from "./helpers/apiMocks.js";

test.describe("Platform source filter (BIN-74)", () => {
  test("source select sends platform query param", async ({ page }) => {
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
    await expect(page.getByTestId("property-location")).toContainText(
      "Savassi, Belo Horizonte",
    );

    await page.getByTestId("platform-filter").selectOption("olx");

    await expect
      .poll(() =>
        listUrls.some((u) => {
          const decoded = decodeURIComponent(u.replace(/\+/g, " "));
          return decoded.includes("platform=olx");
        }),
      )
      .toBeTruthy();
  });
});
