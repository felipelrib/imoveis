// @ts-check
import { test, expect } from "@playwright/test";
import {
  PROPERTIES_PAGE,
  installCommonMocks,
  mockAdminLocale,
} from "./helpers/apiMocks.js";

const VALID_KEY = "e2e-test-api-key";

test.describe("Locale-aware filters (BIN-100)", () => {
  test("pt-BR filter labels with EN wire query params", async ({ page }) => {
    /** @type {string[]} */
    const posted = [];
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page, { locale: false });
    await mockAdminLocale(page, { initial: "pt-BR", posted });

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
    await expect(page.getByRole("heading", { name: "Imóveis" })).toBeVisible();

    const sortSelect = page.getByTestId("sort-by-filter");
    await expect(sortSelect.locator("option[value='combined_score']")).toHaveText(
      "⭐ Melhor score"
    );

    const listingSelect = page.getByTestId("listing-type-filter");
    await expect(listingSelect.locator("option[value='rent']")).toHaveText(
      "Somente aluguel"
    );
    await expect(listingSelect.locator("option[value='sale']")).toHaveText(
      "Somente venda"
    );

    const typeSelect = page.getByTestId("property-type-filter");
    await expect(typeSelect.locator("option[value='apartment']")).toHaveText(
      "Apartamento"
    );
    await expect(typeSelect.locator("option[value='house']")).toHaveText("Casa");

    await page.getByRole("button", { name: /Filtros avançados/i }).click();
    await expect(page.getByText("Mobiliado", { exact: true })).toBeVisible();
    await expect(page.getByText("Aceita pets", { exact: true })).toBeVisible();

    await listingSelect.selectOption("rent");
    await typeSelect.selectOption("apartment");
    await page.getByTestId("furnished-filter").check();
    await page.getByTestId("pets-filter").check();

    await expect
      .poll(() =>
        listUrls.some((u) => {
          const decoded = decodeURIComponent(u.replace(/\+/g, " "));
          return (
            decoded.includes("listing_type=rent") &&
            decoded.includes("property_type=apartment") &&
            decoded.includes("is_furnished=true") &&
            decoded.includes("accepts_pets=true")
          );
        })
      )
      .toBeTruthy();
  });

  test("saved search stores EN snake_case wire and reopens with PT labels", async ({
    page,
  }) => {
    /** @type {string[]} */
    const posted = [];
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page, { locale: false });
    await mockAdminLocale(page, { initial: "pt-BR", posted });

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
    await expect(page.getByRole("heading", { name: "Imóveis" })).toBeVisible();

    await page.getByTestId("listing-type-filter").selectOption("rent");
    await page.getByTestId("property-type-filter").selectOption("apartment");
    await page.getByRole("button", { name: /Filtros avançados/i }).click();
    await page.getByTestId("furnished-filter").check();

    await page.getByRole("button", { name: /Salvar filtros atuais/i }).click();
    await page.getByPlaceholder(/Dê um nome a esta busca/i).fill("Aluguel Savassi");
    await page.locator(".modal").getByRole("button", { name: /^Salvar$/i }).click();

    await expect
      .poll(() => store.length)
      .toBe(1);
    expect(store[0].filters).toMatchObject({
      listing_type: "rent",
      property_type: "apartment",
      is_furnished: true,
    });
    expect(store[0].filters).not.toHaveProperty("listingType");

    // Clear filters then re-apply saved search
    await page.getByRole("button", { name: /Limpar tudo/i }).click();
    await expect(page.getByTestId("listing-type-filter")).toHaveValue("both");
    await expect(page.getByTestId("property-type-filter")).toHaveValue("");

    await page.getByText("Aluguel Savassi", { exact: true }).click();
    await expect(page.getByTestId("listing-type-filter")).toHaveValue("rent");
    await expect(page.getByTestId("property-type-filter")).toHaveValue("apartment");
    await expect(page.getByTestId("furnished-filter")).toBeChecked();
    await expect(
      page.getByTestId("listing-type-filter").locator("option:checked")
    ).toHaveText("Somente aluguel");
    await expect(
      page.getByTestId("property-type-filter").locator("option:checked")
    ).toHaveText("Apartamento");
  });
});
