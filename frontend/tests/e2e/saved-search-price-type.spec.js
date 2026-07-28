// @ts-check
import { test, expect } from "@playwright/test";
import {
  PROPERTIES_PAGE,
  installCommonMocks,
} from "./helpers/apiMocks.js";

const VALID_KEY = "e2e-test-api-key";

test.describe("Saved-search price_type casing (BIN-109)", () => {
  test("save/reopen maxPrice + priceType=sale as snake_case wire", async ({
    page,
  }) => {
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page);

    /** @type {Record<string, unknown>[]} */
    const store = [];

    await page.route("**/api/properties?**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(PROPERTIES_PAGE),
      });
    });

    await page.route("**/api/saved-searches**", async (route) => {
      const req = route.request();
      const method = req.method();
      if (method === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ items: store, total: store.length }),
        });
        return;
      }
      if (method === "POST") {
        const body = req.postDataJSON();
        const item = {
          id: `ss-${store.length + 1}`,
          name: body.name,
          filters: body.filters,
          created_at: new Date().toISOString(),
        };
        store.push(item);
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(item),
        });
        return;
      }
      await route.fallback();
    });

    await page.goto("/properties");
    await expect(page.getByText("2BR Apartment Savassi")).toBeVisible();

    await page.getByRole("button", { name: /Advanced Filters/i }).click();
    await page.getByTestId("price-type-filter").selectOption("sale");
    await page.getByTestId("max-price-input").fill("500000");

    await page.getByRole("button", { name: /Save Current Filters/i }).click();
    await page.getByPlaceholder(/Name this search/i).fill("Sale budget BH");
    await page.locator(".modal").getByRole("button", { name: /^Save$/i }).click();

    await expect.poll(() => store.length).toBe(1);
    expect(store[0].filters).toMatchObject({
      price_type: "sale",
    });
    expect(String(store[0].filters.max_price)).toBe("500000");
    expect(store[0].filters).not.toHaveProperty("priceType");
    expect(store[0].filters).not.toHaveProperty("maxPrice");

    await page.getByRole("button", { name: /Clear All/i }).click();
    await expect(page.getByTestId("max-price-input")).toHaveValue("");
    await expect(page.getByTestId("price-type-filter")).toHaveValue("rent");

    await page.getByText("Sale budget BH", { exact: true }).click();
    await expect(page.getByTestId("max-price-input")).toHaveValue("500000");
    await expect(page.getByTestId("price-type-filter")).toHaveValue("sale");
  });
});
