// @ts-check
import { test, expect } from "@playwright/test";
import {
  SAMPLE_PROPERTY,
  installCommonMocks,
  mockPropertiesExport,
} from "./helpers/apiMocks.js";

// v0.14-s1.7 — cohort price/m² percentile badge on the card price line and the
// `Preço no bairro` filter (UX-DR8 copy, UX-DR9 visual). The API is mocked;
// what the filter selects on real rows is the backend integration suite.

const VALID_KEY = "e2e-test-api-key";
const PARAM = "max_price_per_m2_percentile";
// 2 chip lines of 30px + one 6px row gap (index.css `.filter-chip-strip`).
const STRIP_MAX_HEIGHT = 66;

/**
 * @param {string} id
 * @param {string} title
 * @param {Record<string, unknown>} [extra]
 */
function rentProperty(id, title, extra = {}) {
  return { ...SAMPLE_PROPERTY, id, public_id: Number(id), title, ...extra };
}

/** @param {Record<string, unknown>[]} properties */
function pageOf(properties) {
  return { properties, page: 1, page_size: 24, pages: 1, total: properties.length };
}

const DUAL_LISTINGS = [
  { platform: "olx", listing_type: "rent", price: 3500, url: "https://example.test/rent" },
  { platform: "zap", listing_type: "sale", price: 650000, url: "https://example.test/sale" },
];

/**
 * Serve one list payload and record every list URL.
 * @param {import('@playwright/test').Page} page
 * @param {object} payload
 */
async function mockList(page, payload) {
  /** @type {URL[]} */
  const urls = [];
  await page.route("**/api/properties?**", async (route) => {
    urls.push(new URL(route.request().url()));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });
  return urls;
}

/**
 * @param {import('@playwright/test').Page} page
 * @param {string} title
 */
function cardOf(page, title) {
  return page.locator(".property-card").filter({ hasText: title });
}

/** @param {string} css e.g. `rgba(116, 189, 130, 0.12)` */
function rgba(css) {
  const parts = (css.match(/[\d.]+/g) || []).map(Number);
  return { rgb: parts.slice(0, 3), alpha: parts.length > 3 ? parts[3] : 1 };
}

test.describe("Percentile badge on the card (v0.14-s1.7)", () => {
  test("pt-BR text, price-drop ink on the two tints, right-aligned on a serif price line", async ({ page }) => {
    await installCommonMocks(page);
    await mockList(
      page,
      pageOf([rentProperty("1", "Apto Savassi barato", { price_per_m2_percentile_rent: 0.25 })]),
    );

    await page.goto("/properties");
    const card = cardOf(page, "Apto Savassi barato");
    await expect(card).toBeVisible();

    const badge = card.getByTestId("card-percentile-badge-rent");
    await expect(badge).toHaveText("entre os 25% mais baratos");
    await expect(card.locator(".percentile-badge")).toHaveCount(1);

    const style = await badge.evaluate((el) => {
      const s = getComputedStyle(el);
      return {
        color: s.color,
        background: s.backgroundColor,
        border: s.borderTopColor,
        borderWidth: s.borderTopWidth,
        borderStyle: s.borderTopStyle,
        radius: s.borderTopLeftRadius,
        whiteSpace: s.whiteSpace,
      };
    });
    // #74bd82, #74bd821f (12%), #74bd8259 (35%).
    expect(rgba(style.color)).toEqual({ rgb: [116, 189, 130], alpha: 1 });
    expect(rgba(style.background).rgb).toEqual([116, 189, 130]);
    expect(rgba(style.background).alpha).toBeCloseTo(0.12, 2);
    expect(rgba(style.border).rgb).toEqual([116, 189, 130]);
    expect(rgba(style.border).alpha).toBeCloseTo(0.35, 2);
    expect(style.borderWidth).toBe("1px");
    expect(style.borderStyle).toBe("solid");
    expect(style.radius).toBe("7px");
    expect(style.whiteSpace).toBe("nowrap");

    // Right-aligned on its own price line, after the price.
    const row = card.getByTestId("card-price-row-rent");
    const price = row.locator(".property-price");
    const [rowBox, badgeBox, priceBox] = await Promise.all([
      row.boundingBox(),
      badge.boundingBox(),
      price.boundingBox(),
    ]);
    if (!rowBox || !badgeBox || !priceBox) throw new Error("price line not laid out");
    expect(Math.abs(rowBox.x + rowBox.width - (badgeBox.x + badgeBox.width))).toBeLessThanOrEqual(1);
    // Inside its price line and never over the price: beside it when the card
    // is wide enough, otherwise wrapped under it (still on the right).
    expect(badgeBox.x).toBeGreaterThanOrEqual(rowBox.x);
    expect(badgeBox.y).toBeGreaterThanOrEqual(rowBox.y - 1);
    expect(badgeBox.y + badgeBox.height).toBeLessThanOrEqual(rowBox.y + rowBox.height + 1);
    const besidePrice = badgeBox.x >= priceBox.x + priceBox.width;
    const underPrice = badgeBox.y >= priceBox.y + priceBox.height - 6;
    expect(besidePrice || underPrice).toBe(true);
    // The badge stays left of the favourite / watchlist icons.
    const iconBox = await card.getByTestId("favourite-toggle-1").boundingBox();
    if (!iconBox) throw new Error("icons not laid out");
    expect(badgeBox.x + badgeBox.width).toBeLessThanOrEqual(iconBox.x);

    const priceStyle = await price.evaluate((el) => {
      const s = getComputedStyle(el);
      return { family: s.fontFamily, numeric: s.fontVariantNumeric };
    });
    expect(priceStyle.family).toMatch(/^Georgia/);
    expect(priceStyle.family).toMatch(/serif$/);
    expect(priceStyle.numeric).toContain("tabular-nums");
  });

  test("N is the smallest whole percent that keeps the sentence true; nothing above 50%", async ({ page }) => {
    await installCommonMocks(page);
    await mockList(
      page,
      pageOf([
        rentProperty("1", "Share 0.05", { price_per_m2_percentile_rent: 0.05 }),
        rentProperty("2", "Share 0.2001", { price_per_m2_percentile_rent: 0.2001 }),
        rentProperty("3", "Share 0.25", { price_per_m2_percentile_rent: 0.25 }),
        rentProperty("4", "Share 0.5", { price_per_m2_percentile_rent: 0.5 }),
        // 0.07 * 100 is 7.000000000000001 in floating point: still 7, not 8.
        rentProperty("5", "Share 0.07", { price_per_m2_percentile_rent: 0.07 }),
        rentProperty("6", "Share 0.001", { price_per_m2_percentile_rent: 0.001 }),
        rentProperty("7", "Share 0.51", { price_per_m2_percentile_rent: 0.51 }),
        rentProperty("8", "Share 1.0", { price_per_m2_percentile_rent: 1.0 }),
      ]),
    );

    await page.goto("/properties");
    await expect(cardOf(page, "Share 0.05")).toBeVisible();

    for (const [title, n] of [
      ["Share 0.05", 5],
      ["Share 0.2001", 21],
      ["Share 0.25", 25],
      ["Share 0.5", 50],
      ["Share 0.07", 7],
      ["Share 0.001", 1],
    ]) {
      await expect(
        cardOf(page, String(title)).getByTestId("card-percentile-badge-rent"),
      ).toHaveText(`entre os ${n}% mais baratos`);
    }
    for (const title of ["Share 0.51", "Share 1.0"]) {
      await expect(cardOf(page, title)).toBeVisible();
      await expect(cardOf(page, title).locator(".percentile-badge")).toHaveCount(0);
    }
  });

  test("a suppressed Property has no badge element and no placeholder", async ({ page }) => {
    await installCommonMocks(page);
    await mockList(
      page,
      pageOf([
        rentProperty("1", "Suppressed null", { price_per_m2_percentile_rent: null }),
        // The field is absent altogether (favourites projection, older API).
        rentProperty("2", "Field absent"),
        // The legacy percentile_rank* is never read for the badge.
        rentProperty("3", "Legacy only", {
          price_per_m2_percentile_rent: null,
          percentile_rank: 0.1,
          percentile_rank_rent: 0.1,
        }),
        // A sale percentile says nothing about a rent price line.
        rentProperty("4", "Other type only", {
          price_per_m2_percentile_rent: null,
          price_per_m2_percentile_sale: 0.1,
        }),
      ]),
    );

    await page.goto("/properties");
    for (const title of ["Suppressed null", "Field absent", "Legacy only", "Other type only"]) {
      const card = cardOf(page, title);
      await expect(card).toBeVisible();
      await expect(card.locator(".percentile-badge")).toHaveCount(0);
      await expect(card.locator('[data-testid^="card-percentile-badge"]')).toHaveCount(0);
      const rowText = (await card.getByTestId("card-price-row-rent").textContent()) || "";
      expect(rowText).not.toMatch(/%|mais baratos|—/);
    }
  });

  test("a dual card carries one badge per price line", async ({ page }) => {
    await installCommonMocks(page);
    await mockList(
      page,
      pageOf([
        rentProperty("1", "Dual both cheap", {
          listings: DUAL_LISTINGS,
          price_per_m2_percentile_rent: 0.2,
          price_per_m2_percentile_sale: 0.4,
        }),
        rentProperty("2", "Dual rent cheap only", {
          listings: DUAL_LISTINGS,
          price_per_m2_percentile_rent: 0.2,
          price_per_m2_percentile_sale: 0.9,
        }),
      ]),
    );

    await page.goto("/properties");
    const both = cardOf(page, "Dual both cheap");
    await expect(both).toBeVisible();
    await expect(
      both.getByTestId("card-price-row-rent").getByTestId("card-percentile-badge-rent"),
    ).toHaveText("entre os 20% mais baratos");
    await expect(
      both.getByTestId("card-price-row-sale").getByTestId("card-percentile-badge-sale"),
    ).toHaveText("entre os 40% mais baratos");
    await expect(both.locator(".percentile-badge")).toHaveCount(2);

    const rentOnly = cardOf(page, "Dual rent cheap only");
    await expect(rentOnly.getByTestId("card-percentile-badge-rent")).toHaveText(
      "entre os 20% mais baratos",
    );
    await expect(rentOnly.getByTestId("card-price-row-sale").locator(".percentile-badge")).toHaveCount(0);
    await expect(rentOnly.locator(".percentile-badge")).toHaveCount(1);

    // Each badge is right-aligned on its own line.
    for (const type of ["rent", "sale"]) {
      const row = both.getByTestId(`card-price-row-${type}`);
      const [rowBox, badgeBox] = await Promise.all([
        row.boundingBox(),
        row.locator(".percentile-badge").boundingBox(),
      ]);
      if (!rowBox || !badgeBox) throw new Error("price line not laid out");
      expect(Math.abs(rowBox.x + rowBox.width - (badgeBox.x + badgeBox.width))).toBeLessThanOrEqual(1);
    }
  });

  test("the en catalog reads `among the N% cheapest`", async ({ page }) => {
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page, { locale: { initial: "en" } });
    await mockList(
      page,
      pageOf([rentProperty("1", "English card", { price_per_m2_percentile_rent: 0.25 })]),
    );

    await page.goto("/properties");
    await expect(
      cardOf(page, "English card").getByTestId("card-percentile-badge-rent"),
    ).toHaveText("among the 25% cheapest");

    await page.getByRole("button", { name: /Advanced Filters/i }).click();
    const select = page.getByTestId("price-percentile-filter");
    await expect(page.locator('label[for="price-percentile-filter"]')).toHaveText("Price in neighbourhood");
    await expect(select.locator("option")).toHaveText([
      "any price",
      "among the 25% cheapest",
      "among the 50% cheapest",
    ]);
  });
});

test.describe("`Preço no bairro` filter (v0.14-s1.7)", () => {
  test("request, chip with the panel closed, type switch, chip removal", async ({ page }) => {
    await installCommonMocks(page);
    const urls = await mockList(
      page,
      pageOf([rentProperty("1", "Apto filtrado", { price_per_m2_percentile_rent: 0.2 })]),
    );

    await page.goto("/properties");
    await expect(cardOf(page, "Apto filtrado")).toBeVisible();
    // Default: no parameter, no chip strip.
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.every((u) => !u.searchParams.has(PARAM))).toBe(true);
    await expect(page.getByTestId("filter-chip-strip")).toHaveCount(0);

    await page.getByRole("button", { name: /Filtros avançados/i }).click();
    const select = page.getByTestId("price-percentile-filter");
    await expect(page.locator('label[for="price-percentile-filter"]')).toHaveText("Preço no bairro");
    await expect(select).toHaveValue("");
    await expect(select.locator("option")).toHaveText([
      "qualquer preço",
      "entre os 25% mais baratos",
      "entre os 50% mais baratos",
    ]);

    await select.selectOption({ label: "entre os 25% mais baratos" });
    await expect.poll(() => urls.at(-1)?.searchParams.get(PARAM)).toBe("0.25");
    // No listing type selected: the server reads either column.
    expect(urls.at(-1)?.searchParams.has("listing_type")).toBe(false);

    // Close the panel: the chip stays.
    await page.getByRole("button", { name: /Ocultar avançados/i }).click();
    await expect(select).toHaveCount(0);
    const strip = page.getByTestId("filter-chip-strip");
    const chip = page.getByTestId("filter-chip-price-percentile");
    await expect(chip).toBeVisible();
    await expect(chip.locator(".filter-chip-label")).toHaveText("entre os 25% mais baratos");
    await expect(strip.locator(".filter-chip")).toHaveCount(1);

    const stripBox = await strip.boundingBox();
    if (!stripBox) throw new Error("chip strip not laid out");
    expect(stripBox.height).toBeLessThanOrEqual(STRIP_MAX_HEIGHT);
    const stripStyle = await strip.evaluate((el) => {
      const s = getComputedStyle(el);
      return { maxHeight: s.maxHeight, overflow: s.overflowY };
    });
    expect(stripStyle.maxHeight).toBe(`${STRIP_MAX_HEIGHT}px`);
    expect(stripStyle.overflow).toBe("hidden");

    const chipStyle = await chip.evaluate((el) => {
      const s = getComputedStyle(el);
      return { color: s.color, border: s.borderTopColor, radius: s.borderTopLeftRadius };
    });
    // filter-chip active: accent (#4da3ff) border and text, 9px radius.
    expect(chipStyle.color).toBe("rgb(77, 163, 255)");
    expect(chipStyle.border).toBe("rgb(77, 163, 255)");
    expect(chipStyle.radius).toBe("9px");

    // Transaction → sale: same value, re-evaluated for that listing type.
    await page
      .locator("label", { hasText: "Transação" })
      .locator("..")
      .locator("select")
      .selectOption("sale");
    await expect
      .poll(() => {
        const last = urls.at(-1);
        return `${last?.searchParams.get("listing_type")}|${last?.searchParams.get(PARAM)}`;
      })
      .toBe("sale|0.25");
    await expect(chip.locator(".filter-chip-label")).toHaveText("entre os 25% mais baratos");

    // × removes the filter: the next request has no parameter.
    const before = urls.length;
    await page.getByRole("button", { name: "Remover filtro: Preço no bairro" }).click();
    await expect(strip).toHaveCount(0);
    await expect.poll(() => urls.length).toBeGreaterThan(before);
    expect(urls.at(-1)?.searchParams.has(PARAM)).toBe(false);
    expect(urls.at(-1)?.searchParams.get("listing_type")).toBe("sale");

    await page.getByRole("button", { name: /Filtros avançados/i }).click();
    await expect(page.getByTestId("price-percentile-filter")).toHaveValue("");
  });

  test("the 50% option, `Limpar tudo` and the export carry the value", async ({ page }) => {
    await installCommonMocks(page);
    const urls = await mockList(page, pageOf([rentProperty("1", "Apto exportado")]));
    /** @type {string[]} */
    const exportUrls = [];
    await mockPropertiesExport(page, { capturedUrls: exportUrls });

    await page.goto("/properties");
    await expect(cardOf(page, "Apto exportado")).toBeVisible();

    await page.getByRole("button", { name: /Filtros avançados/i }).click();
    const select = page.getByTestId("price-percentile-filter");
    await select.selectOption("0.5");
    await expect.poll(() => urls.at(-1)?.searchParams.get(PARAM)).toBe("0.5");
    await expect(page.getByTestId("filter-chip-price-percentile").locator(".filter-chip-label")).toHaveText(
      "entre os 50% mais baratos",
    );

    const download = page.waitForEvent("download");
    await page.getByTestId("export-json").click();
    await download;
    await expect
      .poll(() => exportUrls.some((u) => new URL(u).searchParams.get(PARAM) === "0.5"))
      .toBeTruthy();

    const before = urls.length;
    await page.getByRole("button", { name: /Limpar tudo/i }).click();
    await expect(select).toHaveValue("");
    await expect(page.getByTestId("filter-chip-strip")).toHaveCount(0);
    await expect.poll(() => urls.length).toBeGreaterThan(before);
    expect(urls.at(-1)?.searchParams.has(PARAM)).toBe(false);
  });

  test("a saved search keeps the value under its wire key and restores the chip", async ({ page }) => {
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page, { locale: { initial: "pt-BR", defaultLocale: "pt-BR" } });
    const urls = await mockList(page, pageOf([rentProperty("1", "Apto salvo")]));

    /** @type {{ id: string, name: string, filters: Record<string, unknown>, created_at: string }[]} */
    const store = [];
    await page.route("**/api/saved-searches**", async (route) => {
      const req = route.request();
      if (req.method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ items: store, total: store.length }),
        });
        return;
      }
      if (req.method() === "POST") {
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
    await expect(cardOf(page, "Apto salvo")).toBeVisible();

    await page.getByRole("button", { name: /Filtros avançados/i }).click();
    const select = page.getByTestId("price-percentile-filter");
    await select.selectOption("0.25");
    await expect(page.getByTestId("filter-chip-price-percentile")).toBeVisible();

    await page.getByRole("button", { name: /Salvar filtros atuais/i }).click();
    await page.locator(".modal input").fill("Quarto mais barato");
    await page.locator(".modal .btn-primary").click();

    await expect.poll(() => store.length).toBe(1);
    expect(Number(store[0].filters[PARAM])).toBe(0.25);
    expect(store[0].filters).not.toHaveProperty("maxPricePerM2Percentile");

    await page.getByRole("button", { name: /Limpar tudo/i }).click();
    await expect(select).toHaveValue("");
    await expect(page.getByTestId("filter-chip-strip")).toHaveCount(0);

    await page.getByText("Quarto mais barato", { exact: true }).click();
    await expect(select).toHaveValue("0.25");
    await expect(page.getByTestId("filter-chip-price-percentile").locator(".filter-chip-label")).toHaveText(
      "entre os 25% mais baratos",
    );
    await expect.poll(() => urls.at(-1)?.searchParams.get(PARAM)).toBe("0.25");
  });

  test("the empty-state `Limpar filtros` clears the percentile filter", async ({ page }) => {
    await installCommonMocks(page);
    /** @type {URL[]} */
    const urls = [];
    await page.route("**/api/properties?**", async (route) => {
      const url = new URL(route.request().url());
      urls.push(url);
      // Nothing is that cheap: the filtered list is empty.
      const payload = url.searchParams.has(PARAM)
        ? pageOf([])
        : pageOf([rentProperty("1", "Apto sem filtro")]);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(payload),
      });
    });

    await page.goto("/properties");
    await expect(cardOf(page, "Apto sem filtro")).toBeVisible();
    await page.getByRole("button", { name: /Filtros avançados/i }).click();
    await page.getByTestId("price-percentile-filter").selectOption("0.25");
    await expect(page.getByTestId("filter-chip-price-percentile")).toBeVisible();
    await expect(page.locator(".property-card")).toHaveCount(0);

    await page.getByRole("button", { name: /Limpar filtros/i }).click();
    await expect(page.getByTestId("filter-chip-strip")).toHaveCount(0);
    await expect(cardOf(page, "Apto sem filtro")).toBeVisible();
    expect(urls.at(-1)?.searchParams.has(PARAM)).toBe(false);
    await expect(page.getByTestId("price-percentile-filter")).toHaveValue("");
  });

  test("a saved search with another cap is shown as it is applied; an unusable one is dropped", async ({ page }) => {
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page, { locale: { initial: "pt-BR", defaultLocale: "pt-BR" } });
    const urls = await mockList(page, pageOf([rentProperty("1", "Apto salvo")]));
    const store = [
      { id: "ss-1", name: "Trinta e meio", filters: { [PARAM]: 0.305 }, created_at: "2026-10-08T00:00:00Z" },
      { id: "ss-2", name: "Valor ruim", filters: { [PARAM]: 25 }, created_at: "2026-10-08T00:00:00Z" },
    ];
    await page.route("**/api/saved-searches**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: store, total: store.length }),
      }),
    );

    await page.goto("/properties");
    await expect(cardOf(page, "Apto salvo")).toBeVisible();
    await page.getByRole("button", { name: /Filtros avançados/i }).click();
    const select = page.getByTestId("price-percentile-filter");

    await page.getByText("Trinta e meio", { exact: true }).click();
    await expect(select).toHaveValue("0.305");
    await expect(select.locator("option")).toHaveText([
      "qualquer preço",
      "entre os 25% mais baratos",
      "entre os 30.5% mais baratos",
      "entre os 50% mais baratos",
    ]);
    await expect(page.getByTestId("filter-chip-price-percentile").locator(".filter-chip-label")).toHaveText(
      "entre os 30.5% mais baratos",
    );
    await expect.poll(() => urls.at(-1)?.searchParams.get(PARAM)).toBe("0.305");

    // 25 is not a share in (0, 1]: no filter, no chip, no parameter.
    const before = urls.length;
    await page.getByText("Valor ruim", { exact: true }).click();
    await expect(select).toHaveValue("");
    await expect(page.getByTestId("filter-chip-strip")).toHaveCount(0);
    await expect.poll(() => urls.length).toBeGreaterThan(before);
    expect(urls.at(-1)?.searchParams.has(PARAM)).toBe(false);
  });

  test("Favoritos ignores the filters, so it shows no chip", async ({ page }) => {
    await installCommonMocks(page);
    await mockList(page, pageOf([rentProperty("1", "Apto favorito")]));

    await page.goto("/properties");
    await expect(cardOf(page, "Apto favorito")).toBeVisible();
    await page.getByRole("button", { name: /Filtros avançados/i }).click();
    await page.getByTestId("price-percentile-filter").selectOption("0.25");
    await expect(page.getByTestId("filter-chip-price-percentile")).toBeVisible();

    await page.getByTestId("favourites-nav").click();
    await expect(page.getByTestId("favourites-back")).toBeVisible();
    await expect(page.getByTestId("filter-chip-strip")).toHaveCount(0);

    await page.getByTestId("favourites-back").click();
    await expect(page.getByTestId("filter-chip-price-percentile")).toBeVisible();
  });

  test("the map fetch carries the value", async ({ page }) => {
    // WebGL init under full-suite load (same bump as compare-map-select).
    test.setTimeout(60_000);
    await installCommonMocks(page);
    const urls = await mockList(
      page,
      pageOf([rentProperty("1", "Apto no mapa", { lat: -19.93, lon: -43.94 })]),
    );

    await page.goto("/properties");
    await expect(cardOf(page, "Apto no mapa")).toBeVisible();
    await page.getByRole("button", { name: /Filtros avançados/i }).click();
    await page.getByTestId("price-percentile-filter").selectOption("0.25");
    await expect(page.getByTestId("filter-chip-price-percentile")).toBeVisible();

    await page.getByRole("button", { name: /Mapa/ }).click();
    const canvas = page.locator(".maplibregl-canvas");
    await expect(canvas).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("map-view")).toHaveAttribute("data-map-ready", "true", {
      timeout: 30000,
    });

    // The map refetches for its viewport when a move ends: pan it.
    await canvas.scrollIntoViewIfNeeded();
    const box = await canvas.boundingBox();
    if (!box) throw new Error("map canvas not laid out");
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    await page.mouse.move(cx + 90, cy + 40, { steps: 8 });
    await page.mouse.up();

    await expect
      .poll(
        () => urls.some((u) => u.searchParams.has("bbox") && u.searchParams.get(PARAM) === "0.25"),
        { timeout: 15000 },
      )
      .toBeTruthy();
  });
});
