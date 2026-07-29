// @ts-check
/**
 * BIN-116 — locale-aware money/date formatters (shipped with BIN-99; regression locks).
 * Currency amounts stay BRL; only digit grouping / date order follow UI locale.
 */
import { test, expect } from "@playwright/test";
import {
  formatCurrency,
  formatCurrencyBRL,
  formatDate,
  formatNumber,
  formatPricePerM2,
} from "../../src/i18n/format.js";
import {
  installCommonMocks,
  mockAdminLocale,
  mockPropertiesList,
  PROPERTIES_PAGE,
} from "./helpers/apiMocks.js";

const VALID_KEY = "e2e-test-api-key";

test.describe("format.js helpers (BIN-116)", () => {
  test("digit grouping and date order follow locale; BRL code unchanged", () => {
    expect(formatCurrency(3500, "en")).toBe("R$ 3,500");
    expect(formatCurrency(3500, "pt-BR")).toBe("R$ 3.500");

    expect(formatNumber(3500, "en")).toBe("3,500");
    expect(formatNumber(3500, "pt-BR")).toBe("3.500");

    expect(formatPricePerM2(8500.4, "en")).toBe("R$ 8,500/m²");
    expect(formatPricePerM2(8500.4, "pt-BR")).toBe("R$ 8.500/m²");

    expect(formatCurrencyBRL(3500, "en")).toMatch(/^R\$\s*3,500/);
    expect(formatCurrencyBRL(3500, "pt-BR")).toMatch(/^R\$\s*3\.500/);

    const midDay = "2024-06-15T15:00:00";
    expect(formatDate(midDay, "en")).toBe("06/15");
    expect(formatDate(midDay, "pt-BR")).toBe("15/06");
  });

  test("null/invalid values stay safe sentinels", () => {
    expect(formatCurrency(null, "en")).toBe("—");
    expect(formatNumber(undefined, "pt-BR")).toBe("—");
    expect(formatDate(null, "en")).toBe("?");
  });
});

test.describe("Properties price display locale (BIN-116)", () => {
  test("en card shows comma grouping", async ({ page }) => {
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE);

    await page.goto("/properties");
    await expect(page.getByText("2BR Apartment Savassi")).toBeVisible();
    await expect(page.getByText("R$ 3,500")).toBeVisible();
  });

  test("pt-BR card shows period grouping", async ({ page }) => {
    /** @type {string[]} */
    const posted = [];
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page, { locale: false });
    await mockAdminLocale(page, { initial: "pt-BR", posted });
    await mockPropertiesList(page, PROPERTIES_PAGE);

    await page.goto("/properties");
    await expect(page.locator("html")).toHaveAttribute("lang", "pt-BR");
    await expect(page.getByText("2BR Apartment Savassi")).toBeVisible();
    await expect(page.getByText("R$ 3.500")).toBeVisible();
  });
});
