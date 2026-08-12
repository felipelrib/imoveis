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
  wholePercent,
} from "../../src/i18n/format.js";
import { etaLine, throughputLine } from "../../src/components/operations/lines.js";
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

/**
 * v0.13-s1.6 — every branch below exists because the naive rendering states
 * something the corpus does not support. They shipped as bug fixes with no test
 * of their own; these are the locks.
 */
test.describe("coverage / backfill number rendering (v0.13-s1.6)", () => {
  test("wholePercent never rounds to a finished or an empty corpus", () => {
    expect(wholePercent(0.617)).toBe(62);
    // Almost-100 must not read as done while rows are still unenriched…
    expect(wholePercent(0.996)).toBe(99);
    // …and only a genuine 1.0 is 100%.
    expect(wholePercent(1)).toBe(100);
    // A signal that has started must not report "nothing measured"…
    expect(wholePercent(0.0001)).toBe(1);
    // …while a true zero stays zero.
    expect(wholePercent(0)).toBe(0);
    // Undefined coverage stays undefined — the caller renders absence.
    expect(wholePercent(null)).toBeNull();
    expect(wholePercent(undefined)).toBeNull();
    expect(wholePercent(NaN)).toBeNull();
    expect(wholePercent(Infinity)).toBeNull();
  });

  test("the rate and ETA lines agree with their own numbers", () => {
    /** @type {(key: string, params?: Record<string, unknown>) => string} */
    const t = (key, params) =>
      params ? `${key}:${JSON.stringify(params)}` : key;

    // A positive rate under half a row a day is said, never rounded to "~0".
    expect(throughputLine(0.4, t, "pt-BR")).toBe("operations.throughputBelowOne");
    expect(throughputLine(1.2, t, "pt-BR")).toBe("operations.throughputOne");
    expect(throughputLine(4600, t, "pt-BR")).toBe(
      'operations.throughputLine:{"n":"4.600"}'
    );
    expect(throughputLine(4600, t, "en")).toBe(
      'operations.throughputLine:{"n":"4,600"}'
    );

    expect(etaLine(0.2, t, "pt-BR")).toBe("operations.etaUnderOneDay");
    // [1.0, 1.5) rounds to 1 — the singular key, not "~1 dias".
    expect(etaLine(1.0, t, "pt-BR")).toBe("operations.etaOneDay");
    expect(etaLine(1.4, t, "pt-BR")).toBe("operations.etaOneDay");
    expect(etaLine(3.2, t, "pt-BR")).toBe('operations.etaLine:{"n":"3"}');
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
