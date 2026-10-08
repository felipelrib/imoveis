// @ts-check
/**
 * v0.14-s1.8 — the detail surface is a right-side panel (UX-DR4): percentile
 * sentence (UX-DR8), itemized stored cost (FR-31), and a page behind it that
 * keeps its scroll, filters, list and map.
 */
import { readFileSync } from "node:fs";
import { test, expect } from "@playwright/test";
import {
  installCommonMocks,
  mockPropertiesList,
  mockPropertyDetail,
  PROPERTIES_PAGE,
  PROPERTIES_PAGE_FIVE,
  SAMPLE_PROPERTY,
} from "./helpers/apiMocks.js";

const CATALOG = JSON.parse(
  readFileSync(new URL("../../src/i18n/locales/pt-BR.json", import.meta.url), "utf-8"),
);
const LABELS = {
  combinedScoreRent: CATALOG.attr.combinedScoreRent,
  statisticalScoreRent: CATALOG.attr.statisticalScoreRent,
  zScoreRent: CATALOG.attr.zScoreRent,
  pricePerM2Rent: CATALOG.attr.pricePerM2Rent,
  neighbourhoodAvgPerM2Rent: CATALOG.attr.neighbourhoodAvgPerM2Rent,
  cancel: CATALOG.common.cancel,
};

const RENT_URL = "https://www.olx.com.br/imovel/aluguel/apartamentos/mg/detalhes/700";
const SALE_URL = "https://www.quintoandar.com.br/imovel/701";

/** A stored cost object; overrides replace single fields. */
function cost(overrides = {}) {
  return {
    rent_monthly: 3000,
    rent_state: "known",
    condo_fee_monthly: 495,
    condo_fee_state: "known",
    iptu_monthly: 165,
    iptu_state: "known",
    iptu_periodicity_source: "monthly",
    fees_bundled: false,
    total_monthly_cost: 3660,
    total_state: "complete",
    cost_complete: true,
    ...overrides,
  };
}

const SALE_COST = {
  rent_monthly: null,
  rent_state: "not-applicable",
  condo_fee_monthly: 800,
  condo_fee_state: "known",
  iptu_monthly: 250,
  iptu_state: "known",
  iptu_periodicity_source: "monthly",
  fees_bundled: false,
  total_monthly_cost: null,
  total_state: "not-applicable",
  cost_complete: false,
};

function rentListing(overrides = {}) {
  return {
    id: "listing-rent-1",
    platform: "olx",
    platform_listing_id: "700",
    listing_type: "rent",
    price: 3000,
    currency: "BRL",
    url: RENT_URL,
    cost: cost(),
    ...overrides,
  };
}

function saleListing(overrides = {}) {
  return {
    id: "listing-sale-1",
    platform: "quintoandar",
    platform_listing_id: "701",
    listing_type: "sale",
    price: 890000,
    currency: "BRL",
    url: SALE_URL,
    cost: SALE_COST,
    ...overrides,
  };
}

/** A Property with one rent Listing unless `listings` says otherwise. */
function property(overrides = {}) {
  const listings = overrides.listings ?? [rentListing()];
  return {
    ...SAMPLE_PROPERTY,
    id: "panel-uuid-1",
    public_id: 700,
    title: "Painel Flat",
    price: listings[0]?.price ?? SAMPLE_PROPERTY.price,
    primary_listing: listings[0] ?? null,
    price_per_m2_percentile_rent: null,
    price_per_m2_percentile_sale: null,
    ...overrides,
    listings,
  };
}

/** Open the panel for one Property from the grid. */
async function openPanel(page, prop) {
  await installCommonMocks(page);
  await mockPropertiesList(page, { ...PROPERTIES_PAGE, properties: [prop], total: 1 });
  await mockPropertyDetail(page, prop);
  await page.goto("/properties");
  await page.locator(".property-card").filter({ hasText: prop.title }).click();
  const panel = page.getByTestId("detail-panel");
  await expect(panel.getByTestId("detail-header")).toBeVisible();
  return panel;
}

function listRequests(page) {
  /** @type {string[]} */
  const urls = [];
  page.on("request", (request) => {
    if (/\/api\/properties\?/.test(request.url())) urls.push(request.url());
  });
  return urls;
}

test.describe("Detail panel: percentile sentence (UX-DR8)", () => {
  test("single-type Property: short sentence and header badge, same N as the card", async ({ page }) => {
    const prop = property({ price_per_m2_percentile_rent: 0.2001 });
    const panel = await openPanel(page, prop);

    await expect(panel.getByTestId("detail-percentile-sentence-rent")).toHaveText(
      "Está entre os 21% mais baratos do bairro.",
    );
    await expect(panel.getByTestId("detail-percentile-badge")).toHaveText("entre os 21% mais baratos");
    await expect(page.getByTestId("card-percentile-badge-rent")).toHaveText("entre os 21% mais baratos");
    await expect(panel.getByTestId("detail-percentile-sentence-sale")).toHaveCount(0);
  });

  test("dual-type Property: each sentence names its cohort", async ({ page }) => {
    const prop = property({
      listings: [rentListing(), saleListing()],
      price_per_m2_percentile_rent: 0.25,
      price_per_m2_percentile_sale: 0.4,
    });
    const panel = await openPanel(page, prop);

    await expect(panel.getByTestId("detail-percentile-sentence-rent")).toHaveText(
      "Está entre os 25% mais baratos dos aluguéis do bairro.",
    );
    await expect(panel.getByTestId("detail-percentile-sentence-sale")).toHaveText(
      "Está entre os 40% mais baratos das vendas do bairro.",
    );
    // The header price is the rent Listing's; so is its badge.
    await expect(panel.getByTestId("detail-percentile-badge")).toHaveText("entre os 25% mais baratos");
  });

  test("dual-type Property with one cohort suppressed: one sentence, still naming the cohort", async ({ page }) => {
    const prop = property({
      listings: [rentListing(), saleListing()],
      price_per_m2_percentile_rent: 0.25,
      price_per_m2_percentile_sale: null,
    });
    const panel = await openPanel(page, prop);

    await expect(panel.getByTestId("detail-percentile-sentence-rent")).toHaveText(
      "Está entre os 25% mais baratos dos aluguéis do bairro.",
    );
    await expect(panel.getByTestId("detail-percentile-sentence-sale")).toHaveCount(0);
  });

  test("dual-type Property whose header price is the sale price: the badge is the sale cohort's", async ({ page }) => {
    const sale = saleListing();
    const prop = property({
      listings: [rentListing(), sale],
      primary_listing: sale,
      price: sale.price,
      price_per_m2_percentile_rent: 0.25,
      price_per_m2_percentile_sale: 0.4,
    });
    const panel = await openPanel(page, prop);

    await expect(panel.getByTestId("detail-header")).toContainText("R$ 890.000");
    await expect(panel.getByTestId("detail-percentile-badge")).toHaveText("entre os 40% mais baratos");
    await expect(panel.getByTestId("detail-percentile-sentence-rent")).toContainText("25%");
  });

  for (const [name, value] of [["suppressed", null], ["above the cutoff", 0.51]]) {
    test(`${name} percentile: no sentence and no badge element`, async ({ page }) => {
      const prop = property({ price_per_m2_percentile_rent: value });
      const panel = await openPanel(page, prop);

      await expect(panel.getByTestId("detail-section-verdict")).toBeVisible();
      await expect(panel.locator('[data-testid^="detail-percentile-sentence"]')).toHaveCount(0);
      await expect(panel.getByTestId("detail-percentile-badge")).toHaveCount(0);
      await expect(panel.locator(".percentile-badge")).toHaveCount(0);
      await expect(panel).not.toContainText("mais baratos");
    });
  }

  test("the legacy rank fields are not shown and nothing says percentil", async ({ page }) => {
    const prop = property({
      price_per_m2_percentile_rent: 0.25,
      percentile_rank: 0.5,
      percentile_rank_rent: 0.5,
      combined_score_rent: 0.7,
      stat_score_rent: 0.6,
      z_score_rent: -0.4,
      price_per_m2_rent: 46.67,
      neighborhood_mean_rent: 52.2,
      description: "Apartamento reformado, sol da manhã.",
    });
    const panel = await openPanel(page, prop);

    const facts = panel.getByTestId("detail-section-facts");
    await expect(facts).toBeVisible();
    await expect(panel).not.toContainText(/percentil/i);
    await expect(panel).not.toContainText("50.0");

    // What the retired overlay showed beside them is still stated.
    const fact = (label) => facts.locator(".detail-kv").filter({ hasText: label }).locator(".detail-kv-val");
    await expect(fact("Endereço")).toHaveText(SAMPLE_PROPERTY.address);
    await expect(fact(LABELS.combinedScoreRent)).toHaveText("70");
    await expect(fact(LABELS.statisticalScoreRent)).toHaveText("60");
    await expect(fact(LABELS.zScoreRent)).toHaveText("-0.400");
    await expect(fact(LABELS.pricePerM2Rent)).toHaveText("R$ 47/m²");
    await expect(fact(LABELS.neighbourhoodAvgPerM2Rent)).toHaveText("R$ 52/m²");

    const scores = panel.getByTestId("detail-scores").locator(".detail-kv-val");
    await expect(scores).toHaveText(["72", "68", "75"]);
    // Numbers only: the meter bars of the old overlay are not carried over.
    await expect(panel.locator("progress, [role=progressbar], [role=meter]")).toHaveCount(0);

    await expect(panel.getByTestId("detail-section-description")).toContainText(
      "Apartamento reformado, sol da manhã.",
    );
  });
});

test.describe("Detail panel: monthly cost (FR-31)", () => {
  test("complete cost: four rows with the stored figures", async ({ page }) => {
    const panel = await openPanel(page, property());
    const section = panel.getByTestId("detail-section-cost");

    const rows = section.locator('[data-testid^="cost-row-"]:not([data-testid="cost-row-value"]):not([data-testid="cost-row-note"])');
    await expect(rows).toHaveCount(4);
    await expect(section.getByTestId("cost-row-rent")).toHaveText(/Aluguel\s*R\$ 3\.000/);
    await expect(section.getByTestId("cost-row-condo")).toHaveText(/Condomínio\s*R\$ 495/);
    await expect(section.getByTestId("cost-row-iptu")).toHaveText(/IPTU\s*R\$ 165/);
    await expect(section.getByTestId("cost-row-total")).toHaveText(/Total mensal\s*R\$ 3\.660/);
    await expect(section.getByTestId("cost-row-note")).toHaveCount(0);
    // One rent Listing: there was no choice, so nothing is marked as deciding.
    await expect(section.getByTestId("cost-deciding")).toHaveCount(0);
  });

  test("unknown component: said in words, and the total shows no number", async ({ page }) => {
    const prop = property({
      listings: [rentListing({
        cost: cost({
          iptu_monthly: null,
          iptu_state: "unknown",
          iptu_periodicity_source: "unknown",
          total_monthly_cost: null,
          total_state: "incomplete",
          cost_complete: false,
        }),
      })],
    });
    const panel = await openPanel(page, prop);
    const section = panel.getByTestId("detail-section-cost");

    await expect(section.getByTestId("cost-row-iptu").getByTestId("cost-row-value")).toHaveText("não informado");
    const total = section.getByTestId("cost-row-total");
    await expect(total.getByTestId("cost-row-value")).toHaveText("incompleto");
    await expect(total.getByTestId("cost-row-note")).toHaveText("há valor não informado");
    await expect(total).not.toContainText(/\d/);
    await expect(section.getByTestId("cost-row-condo").getByTestId("cost-row-value")).toHaveText("R$ 495");
  });

  test("bundled fees: one labelled row, no IPTU row, stored total", async ({ page }) => {
    const prop = property({
      listings: [rentListing({
        price: 929,
        cost: cost({
          rent_monthly: 750,
          condo_fee_monthly: 179,
          condo_fee_state: "bundled",
          iptu_monthly: null,
          iptu_state: "bundled",
          iptu_periodicity_source: "unknown",
          fees_bundled: true,
          total_monthly_cost: 929,
          total_state: "bundled",
        }),
      })],
    });
    const panel = await openPanel(page, prop);
    const section = panel.getByTestId("detail-section-cost");

    const bundled = section.getByTestId("cost-row-condoIptuBundled");
    await expect(bundled).toContainText("Condomínio + IPTU");
    await expect(bundled.getByTestId("cost-row-value")).toHaveText("R$ 179");
    await expect(bundled.getByTestId("cost-row-note")).toHaveText("valor único publicado pela plataforma");
    await expect(section.getByTestId("cost-row-iptu")).toHaveCount(0);
    await expect(section.getByTestId("cost-row-condo")).toHaveCount(0);
    await expect(section.getByTestId("cost-row-total").getByTestId("cost-row-value")).toHaveText("R$ 929");
  });

  test("annual IPTU: the row says it was converted", async ({ page }) => {
    const prop = property({
      listings: [rentListing({ cost: cost({ iptu_periodicity_source: "annual" }) })],
    });
    const panel = await openPanel(page, prop);
    const iptu = panel.getByTestId("detail-section-cost").getByTestId("cost-row-iptu");

    await expect(iptu.getByTestId("cost-row-value")).toHaveText("R$ 165");
    await expect(iptu.getByTestId("cost-row-note")).toHaveText("convertido do valor anual");
  });

  test("sale Listing: condo and IPTU only, no rent row and no total row", async ({ page }) => {
    const prop = property({ listings: [saleListing()] });
    const panel = await openPanel(page, prop);
    const section = panel.getByTestId("detail-section-cost");

    await expect(section.getByTestId("cost-row-condo").getByTestId("cost-row-value")).toHaveText("R$ 800");
    await expect(section.getByTestId("cost-row-iptu").getByTestId("cost-row-value")).toHaveText("R$ 250");
    await expect(section.getByTestId("cost-row-rent")).toHaveCount(0);
    await expect(section.getByTestId("cost-row-total")).toHaveCount(0);
  });

  test("Listing without a cost object: no cost block, and no section when none has one", async ({ page }) => {
    // An older payload: only the legacy fee fields, which the panel must not read.
    const prop = property({
      listings: [rentListing({ cost: undefined, base_price: 3000, condo_fee: 495, iptu: 165 })],
    });
    const panel = await openPanel(page, prop);

    await expect(panel.getByTestId("listings-by-platform")).toBeVisible();
    await expect(panel.getByTestId("detail-section-cost")).toHaveCount(0);
    await expect(panel).not.toContainText("R$ 495");
    await expect(panel).not.toContainText("R$ 165");
  });

  test("two rent Listings: the deciding one is marked", async ({ page }) => {
    const prop = property({
      listings: [
        rentListing({ id: "listing-a", platform: "olx", price: 3000 }),
        rentListing({
          id: "listing-b",
          platform: "quintoandar",
          platform_listing_id: "702",
          url: "https://www.quintoandar.com.br/imovel/702",
          price: 3100,
          cost: cost({ rent_monthly: 3100, condo_fee_monthly: 300, iptu_monthly: 100, total_monthly_cost: 3500 }),
        }),
      ],
      deciding_listing_id: "listing-b",
      deciding_rule: "lowest-complete-total",
      total_monthly_cost: 3500,
    });
    const panel = await openPanel(page, prop);
    const blocks = panel.getByTestId("cost-listing-rent");

    await expect(blocks).toHaveCount(2);
    await expect(panel.getByTestId("cost-deciding")).toHaveCount(1);
    const deciding = blocks.filter({ has: page.getByTestId("cost-deciding") });
    await expect(deciding).toHaveAttribute("data-platform", "quintoandar");
    await expect(deciding.getByTestId("cost-deciding")).toHaveText("menor custo total");
    await expect(deciding.getByTestId("cost-row-total").getByTestId("cost-row-value")).toHaveText("R$ 3.500");
  });

  test("two rent Listings decided by headline price: nothing is called the lowest total", async ({ page }) => {
    const incomplete = cost({
      iptu_monthly: null,
      iptu_state: "unknown",
      total_monthly_cost: null,
      total_state: "incomplete",
      cost_complete: false,
    });
    const prop = property({
      listings: [
        rentListing({ id: "listing-a", cost: incomplete }),
        rentListing({
          id: "listing-b",
          platform: "quintoandar",
          platform_listing_id: "702",
          url: "https://www.quintoandar.com.br/imovel/702",
          price: 3100,
          cost: incomplete,
        }),
      ],
      deciding_listing_id: "listing-a",
      deciding_rule: "lowest-headline-price",
      total_monthly_cost: null,
    });
    const panel = await openPanel(page, prop);

    await expect(panel.getByTestId("cost-listing-rent")).toHaveCount(2);
    await expect(panel.getByTestId("cost-deciding")).toHaveCount(0);
    await expect(panel).not.toContainText("menor custo total");
  });

  test("one stated total beside an incomplete one: nothing is called the lowest total", async ({ page }) => {
    // The rule of the server picks the only Listing that has a total; the total
    // of the other one is unknown, so it was not compared and could cost less.
    const prop = property({
      listings: [
        rentListing({ id: "listing-a" }),
        rentListing({
          id: "listing-b",
          platform: "quintoandar",
          platform_listing_id: "702",
          url: "https://www.quintoandar.com.br/imovel/702",
          price: 2900,
          cost: cost({
            rent_monthly: 2900,
            iptu_monthly: null,
            iptu_state: "unknown",
            total_monthly_cost: null,
            total_state: "incomplete",
            cost_complete: false,
          }),
        }),
      ],
      deciding_listing_id: "listing-a",
      deciding_rule: "lowest-complete-total",
      total_monthly_cost: 3660,
    });
    const panel = await openPanel(page, prop);
    const blocks = panel.getByTestId("cost-listing-rent");

    await expect(blocks).toHaveCount(2);
    await expect(blocks.locator('[data-testid="cost-row-total"][data-state="known"]')).toHaveCount(1);
    await expect(blocks.locator('[data-testid="cost-row-total"][data-state="incomplete"]')).toHaveCount(1);
    await expect(panel.getByTestId("cost-deciding")).toHaveCount(0);
    await expect(panel).not.toContainText("menor custo total");
  });

  test("a Listing published without a price: its platform row shows a dash, never R$ 0", async ({ page }) => {
    const prop = property({
      listings: [
        rentListing({ id: "listing-a" }),
        rentListing({
          id: "listing-b",
          platform: "quintoandar",
          platform_listing_id: "702",
          url: "https://www.quintoandar.com.br/imovel/702",
          price: 0,
          cost: undefined,
        }),
      ],
    });
    const panel = await openPanel(page, prop);
    const rows = panel.getByTestId("platform-row");

    await expect(rows).toHaveCount(2);
    const unpriced = rows.filter({ hasText: "QuintoAndar" });
    await expect(unpriced.locator(".detail-platform-price")).toHaveText("—");
    await expect(panel.getByTestId("listings-by-platform")).not.toContainText("R$ 0");
  });

  test("one rent Listing that is the deciding one: no mark, there was no choice", async ({ page }) => {
    const prop = property({
      listings: [rentListing({ id: "listing-a" })],
      deciding_listing_id: "listing-a",
      deciding_rule: "lowest-complete-total",
      total_monthly_cost: 3660,
    });
    const panel = await openPanel(page, prop);

    await expect(panel.getByTestId("cost-listing-rent")).toHaveCount(1);
    await expect(panel.getByTestId("cost-row-total").getByTestId("cost-row-value")).toHaveText("R$ 3.660");
    await expect(panel.getByTestId("cost-deciding")).toHaveCount(0);
  });
});

test.describe("Detail panel: price history", () => {
  const point = (id, price, month, platform = "olx") => ({
    id,
    price,
    start_ts: `2026-0${month}-01T00:00:00Z`,
    end_ts: null,
    listing_type: "rent",
    platform,
  });

  async function openWithHistory(page, history) {
    const prop = property();
    await installCommonMocks(page);
    await mockPropertiesList(page, { ...PROPERTIES_PAGE, properties: [prop], total: 1 });
    await mockPropertyDetail(page, prop);
    await page.route(`**/api/properties/${prop.public_id}/price-history**`, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(history) }),
    );
    await page.goto("/properties");
    await page.locator(".property-card").filter({ hasText: prop.title }).click();
    const panel = page.getByTestId("detail-panel");
    await expect(panel.getByTestId("detail-header")).toBeVisible();
    return panel;
  }

  test("two series with two points each: the chart is drawn, before the platform rows", async ({ page }) => {
    const panel = await openWithHistory(page, [
      point("a1", 3200, 1),
      point("a2", 3000, 2),
      point("b1", 3300, 1, "quintoandar"),
      point("b2", 3100, 2, "quintoandar"),
    ]);
    const section = panel.getByTestId("detail-section-price-history");

    await expect(section).toContainText("Histórico de preço");
    await expect(section.locator("svg.recharts-surface").first()).toBeVisible();
    await expect(section.locator(".recharts-line")).toHaveCount(2);
    // Series differ by stroke pattern, not by colour.
    const strokes = await section.locator(".recharts-line-curve").evaluateAll((paths) =>
      paths.map((path) => [path.getAttribute("stroke"), path.getAttribute("stroke-dasharray")]),
    );
    expect(new Set(strokes.map(([stroke]) => stroke)).size).toBe(1);
    expect(new Set(strokes.map(([, dash]) => dash)).size).toBe(2);
    // The legend swatches carry the same patterns; with one ink for every
    // series a plain swatch could not say which line is which platform.
    const swatches = await section.locator(".recharts-legend-icon").evaluateAll((icons) =>
      icons.map((icon) => {
        const dash = getComputedStyle(icon).strokeDasharray;
        return dash === "none" ? null : dash;
      }),
    );
    expect(swatches).toHaveLength(2);
    expect(swatches.filter((dash) => dash == null)).toHaveLength(1);
    expect(swatches.filter((dash) => dash != null)).toHaveLength(1);

    // DESIGN.md order: the chart comes before the per-platform comparison.
    const chartFirst = await page.evaluate(() => {
      const chart = document.querySelector('[data-testid="detail-section-price-history"]');
      const platforms = document.querySelector('[data-testid="listings-by-platform"]');
      return !!chart && !!platforms
        && !!(chart.compareDocumentPosition(platforms) & Node.DOCUMENT_POSITION_FOLLOWING);
    });
    expect(chartFirst).toBe(true);
  });

  test("a single point: the section says two are needed and draws no chart", async ({ page }) => {
    const panel = await openWithHistory(page, [point("a1", 3000, 1)]);
    const section = panel.getByTestId("detail-section-price-history");

    await expect(section).toContainText("Requer pelo menos dois pontos de dados para exibir o gráfico");
    await expect(section.locator("svg.recharts-surface")).toHaveCount(0);
  });

  test("no history: no section", async ({ page }) => {
    const panel = await openWithHistory(page, []);
    await expect(panel.getByTestId("detail-section-price-history")).toHaveCount(0);
  });
});

test.describe("Detail panel: favourite and watch controls (BIN-82)", () => {
  test("both toggles act on the Property UUID, not on the route id", async ({ page }) => {
    // Route id is the public_id (700); the mutations must carry the UUID.
    const prop = property();
    expect(String(prop.public_id)).not.toBe(prop.id);
    await installCommonMocks(page);
    await mockPropertiesList(page, { ...PROPERTIES_PAGE, properties: [prop], total: 1 });
    await mockPropertyDetail(page, prop);

    /** @type {{ method: string, path: string, body: any }[]} */
    const calls = [];
    const record = (emptyList) => (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      const method = request.method();
      if (method === "GET") {
        const body = path.includes("/check/") ? { watched: false, favourited: false } : emptyList;
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      }
      calls.push({ method, path, body: request.postDataJSON() });
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "row-1" }) });
    };
    await page.route("**/api/watchlist**", record([]));
    await page.route("**/api/favourites**", record({ items: [], total: 0 }));
    const lists = listRequests(page);

    await page.goto("/properties");
    await page.locator(".property-card").filter({ hasText: prop.title }).click();
    const panel = page.getByTestId("detail-panel");
    await expect(panel.getByTestId("detail-header")).toBeVisible();

    const watch = panel.getByTestId("detail-watchlist-toggle");
    const cardBell = page.getByTestId(`watchlist-toggle-${prop.id}`);
    await expect(watch).toHaveAccessibleName("Monitorar quedas de preço");
    await expect(cardBell).not.toHaveClass(/active/);
    await panel.getByTestId("detail-drop-pct-input").fill("12");
    await watch.click();
    await expect(watch).toHaveAccessibleName("Remover da lista de monitoramento");
    await expect(panel.getByTestId("detail-drop-pct-input")).toHaveCount(0);
    // The page behind follows: the bell of the card is on.
    await expect(cardBell).toHaveClass(/active/);
    await watch.click();
    await expect(watch).toHaveAccessibleName("Monitorar quedas de preço");
    await expect(cardBell).not.toHaveClass(/active/);

    const favourite = panel.getByTestId("detail-favourite-toggle");
    const cardStar = page.getByTestId(`favourite-toggle-${prop.id}`);
    await expect(favourite).toHaveAccessibleName("Adicionar aos favoritos");
    await expect(cardStar).not.toHaveClass(/active/);
    await favourite.click();
    await expect(favourite).toHaveAccessibleName("Remover dos favoritos");
    // The page behind follows: the card's star is on.
    await expect(cardStar).toHaveClass(/active/);
    await favourite.click();
    await expect(favourite).toHaveAccessibleName("Adicionar aos favoritos");
    await expect(cardStar).not.toHaveClass(/active/);

    expect(calls).toEqual([
      { method: "POST", path: "/api/watchlist", body: { property_id: prop.id, min_drop_pct: 12 } },
      { method: "DELETE", path: `/api/watchlist/${prop.id}`, body: null },
      { method: "POST", path: "/api/favourites", body: { property_id: prop.id } },
      { method: "DELETE", path: `/api/favourites/${prop.id}`, body: null },
    ]);

    // Outside Favoritos a favourite change reloads nothing when the panel closes.
    await page.waitForLoadState("networkidle");
    const listsBefore = lists.length;
    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
    await page.waitForLoadState("networkidle");
    expect(lists.length).toBe(listsBefore);
  });
});

test.describe("Detail panel: geometry and what stays put (UX-DR4)", () => {
  test("grid: panel on the right edge, scrim between the nav sidebar and the panel", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const panel = await openPanel(page, property());

    await expect(page).toHaveURL(/\/properties\/700$/);
    // No centered overlay of any kind.
    await expect(page.locator(".dialog-overlay")).toHaveCount(0);
    await expect(page.locator('[role="dialog"]')).toHaveCount(0);

    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    const panelBox = await panel.boundingBox();
    const scrimBox = await page.getByTestId("detail-scrim").boundingBox();
    if (!panelBox || !scrimBox) throw new Error("panel or scrim has no box");

    expect(Math.abs(panelBox.x + panelBox.width - clientWidth)).toBeLessThanOrEqual(1);
    expect(Math.round(panelBox.width)).toBe(640);
    expect(panelBox.x).toBeGreaterThan(clientWidth / 2);
    expect(Math.round(panelBox.y)).toBe(0);
    expect(Math.round(panelBox.height)).toBe(900);

    // Partial scrim: from the nav sidebar's right edge to the panel's left edge.
    expect(Math.round(scrimBox.x)).toBe(240);
    expect(Math.abs(scrimBox.x + scrimBox.width - panelBox.x)).toBeLessThanOrEqual(1);

    const under = await page.evaluate((cardX) => {
      const hit = (x, y) => document.elementFromPoint(x, y);
      return {
        nav: !!hit(100, 300)?.closest(".sidebar"),
        grid: hit(cardX, 450)?.getAttribute("data-testid"),
      };
    }, 300);
    expect(under.nav).toBe(true);
    expect(under.grid).toBe("detail-scrim");
  });

  test("clicking the scrim closes the panel", async ({ page }) => {
    await openPanel(page, property());
    await page.getByTestId("detail-scrim").click({ position: { x: 20, y: 20 } });
    await expect(page).toHaveURL(/\/properties$/);
    await expect(page.getByTestId("detail-panel")).toHaveCount(0);
  });

  test("narrow window: the panel takes the full width", async ({ page }) => {
    await page.setViewportSize({ width: 700, height: 800 });
    const panel = await openPanel(page, property());
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    const box = await panel.boundingBox();
    if (!box) throw new Error("panel has no box");
    expect(Math.round(box.x)).toBe(0);
    expect(Math.abs(box.width - clientWidth)).toBeLessThanOrEqual(1);
  });

  test("769 to 900px: the panel starts at the nav sidebar's edge and no scrim is drawn", async ({ page }) => {
    await page.setViewportSize({ width: 850, height: 800 });
    const panel = await openPanel(page, property());
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    const box = await panel.boundingBox();
    if (!box) throw new Error("panel has no box");

    expect(Math.round(box.x)).toBe(240);
    expect(Math.abs(box.x + box.width - clientWidth)).toBeLessThanOrEqual(1);
    await expect(page.locator(".sidebar")).toBeVisible();
    await expect(page.getByTestId("detail-scrim")).toBeHidden();
    expect(await page.getByTestId("detail-scrim").boundingBox()).toBeNull();
  });

  test("open then Esc: scroll, filter and list untouched, focus back on the card", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 500 });
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE_FIVE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    const requests = listRequests(page);

    await page.goto("/properties");
    await expect(page.locator(".property-card")).toHaveCount(5);
    await page.getByTestId("listing-type-filter").selectOption("rent");
    await expect.poll(() => requests.some((url) => url.includes("listing_type=rent"))).toBe(true);
    await page.waitForLoadState("networkidle");

    await page.evaluate(() => window.scrollTo({ top: 180, behavior: "instant" }));
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(180);

    // Open with the keyboard so the pointer does not scroll the card into view.
    const card = page.locator('.property-card[data-property-id="1"]');
    await card.evaluate((el) => el.focus({ preventScroll: true }));
    const before = { scrollY: await page.evaluate(() => window.scrollY), requests: requests.length };
    await page.keyboard.press("Enter");

    const panel = page.getByTestId("detail-panel");
    await expect(panel.getByTestId("detail-header")).toBeVisible();
    await expect(page).toHaveURL(/\/properties\/1$/);
    expect(await page.evaluate(() => document.activeElement?.getAttribute("data-testid"))).toBe("detail-panel");
    expect(await page.evaluate(() => window.scrollY)).toBe(before.scrollY);

    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
    await expect(page).toHaveURL(/\/properties$/);

    expect(await page.evaluate(() => window.scrollY)).toBe(before.scrollY);
    await expect(page.getByTestId("listing-type-filter")).toHaveValue("rent");
    expect(await page.evaluate(() => document.activeElement?.getAttribute("data-property-id"))).toBe("1");
    await page.waitForLoadState("networkidle");
    expect(requests.length).toBe(before.requests);
  });

  test("Favoritos: opening and closing a favourite keeps the view and the list", async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    /** @type {string[]} */
    const favouriteLists = [];
    await page.route("**/api/favourites**", (route) => {
      const url = route.request().url();
      if (url.includes("/check/")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ favourited: true }),
        });
      }
      if (url.includes("page_size=24")) favouriteLists.push(url);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [{ ...SAMPLE_PROPERTY, id: "fav-1", property_id: SAMPLE_PROPERTY.id }],
          total: 1,
        }),
      });
    });
    const propertyLists = listRequests(page);

    await page.goto("/favourites");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("★ Favoritos");
    await expect(page.locator(".property-card")).toHaveCount(1);
    await page.waitForLoadState("networkidle");
    const before = { favourites: favouriteLists.length, properties: propertyLists.length };

    await page.locator(".property-card").click();
    await expect(page.getByTestId("detail-panel").getByTestId("detail-header")).toBeVisible();
    await expect(page).toHaveURL(/\/properties\/1$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("★ Favoritos");
    await expect(page.getByTestId("results-count")).toHaveText("1 favorito");
    await expect(page.getByTestId("detail-favourite-toggle")).toHaveAccessibleName("Remover dos favoritos");

    await page.keyboard.press("Escape");
    await expect(page).toHaveURL(/\/favourites$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("★ Favoritos");
    await expect(page.locator(".property-card")).toHaveCount(1);
    await page.waitForLoadState("networkidle");
    expect(favouriteLists.length).toBe(before.favourites);
    expect(propertyLists.length).toBe(before.properties);
  });

  test("Favoritos: a favourite removed in the panel leaves the list when the panel closes", async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    let favourited = true;
    /** @type {string[]} */
    const favouriteLists = [];
    /** @type {string[]} */
    const removals = [];
    await page.route("**/api/favourites**", (route) => {
      const request = route.request();
      const url = request.url();
      const json = (body) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      if (request.method() === "DELETE") {
        favourited = false;
        removals.push(new URL(url).pathname);
        return json({});
      }
      if (url.includes("/check/")) return json({ favourited });
      if (url.includes("page_size=24")) favouriteLists.push(url);
      return json({
        items: favourited ? [{ ...SAMPLE_PROPERTY, id: "fav-1", property_id: SAMPLE_PROPERTY.id }] : [],
        total: favourited ? 1 : 0,
      });
    });

    await page.goto("/favourites");
    await expect(page.locator(".property-card")).toHaveCount(1);
    await expect(page.getByTestId("favourites-nav")).toContainText("1");
    await page.waitForLoadState("networkidle");
    const listsBefore = favouriteLists.length;

    await page.locator(".property-card").click();
    const toggle = page.getByTestId("detail-favourite-toggle");
    await expect(toggle).toHaveAccessibleName("Remover dos favoritos");
    await toggle.click();
    await expect(toggle).toHaveAccessibleName("Adicionar aos favoritos");
    expect(removals).toEqual([`/api/favourites/${SAMPLE_PROPERTY.id}`]);

    // While the panel is open the list behind it does not move...
    await page.waitForLoadState("networkidle");
    expect(favouriteLists.length).toBe(listsBefore);
    await expect(page.locator(".property-card")).toHaveCount(1);
    // ...but the favourite count in the sidebar already follows.
    await expect(page.getByTestId("favourites-nav")).not.toContainText("1");

    await page.keyboard.press("Escape");
    await expect(page).toHaveURL(/\/favourites$/);
    await expect(page.getByTestId("results-count")).toHaveText("0 favoritos");
    await expect(page.locator(".property-card")).toHaveCount(0);
    expect(favouriteLists.length).toBe(listsBefore + 1);
  });
});

test.describe("Detail panel over the map view", () => {
  // WebGL start-up under full-suite load, as in compare-map-select.spec.js.
  test.describe.configure({ timeout: 60_000 });

  const SECOND_PROPERTY = PROPERTIES_PAGE_FIVE.properties[1];

  async function openMapView(page) {
    await page.getByRole("button", { name: /Map/i }).click();
    await expect(page.getByTestId("map-view")).toBeVisible({ timeout: 15000 });
    await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("map-view")).toHaveAttribute("data-map-ready", "true", {
      timeout: 30000,
    });
  }

  /**
   * Open a Property through the router, as selecting a point does
   * (`onSelectProperty` -> navigate). The points themselves cannot be clicked
   * here: under the Vite dev server the MapLibre worker script is a 404, so
   * the GeoJSON point layer never draws (the compare specs use HTML markers).
   */
  async function routeTo(page, path) {
    await page.evaluate((target) => {
      window.history.pushState(null, "", target);
      window.dispatchEvent(new PopStateEvent("popstate"));
    }, path);
  }

  /** Grid with five Properties; detail mocks for the first two (1 favourited, 2 not). */
  async function setup(page) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE_FIVE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    await mockPropertyDetail(page, SECOND_PROPERTY);
    await page.route("**/api/favourites/check/*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ favourited: route.request().url().endsWith("/check/1") }),
      }),
    );
    await page.goto("/properties");
    await expect(page.locator(".property-card")).toHaveCount(5);
  }

  const sameMapNode = (page) => page.evaluate(() => {
    const node = document.querySelector('[data-testid="map-view"]');
    const w = /** @type {any} */ (window);
    return node === w.__mapNode && node?.querySelector("canvas") === w.__mapCanvas;
  });

  test("the map keeps its node, has no scrim and stays visible left of the panel", async ({ page }) => {
    await setup(page);
    const requests = listRequests(page);

    await openMapView(page);
    const map = page.getByTestId("map-view");
    await map.evaluate((el) => {
      /** @type {any} */ (window).__mapNode = el;
      /** @type {any} */ (window).__mapCanvas = el.querySelector("canvas");
    });
    const mapBox = await map.boundingBox();
    if (!mapBox) throw new Error("map has no box");

    await routeTo(page, "/properties/1");
    const panel = page.getByTestId("detail-panel");
    await expect(panel.getByTestId("detail-header")).toContainText("2BR Apartment Savassi");
    await expect(page).toHaveURL(/\/properties\/1$/);
    await expect(panel.getByTestId("detail-favourite-toggle")).toHaveAccessibleName("Remover dos favoritos");

    // Same DOM node and same canvas: the map was not remounted.
    expect(await sameMapNode(page)).toBe(true);

    // No scrim over the map; the panel covers only its right part.
    await expect(page.getByTestId("detail-scrim")).toHaveCount(0);
    const panelBox = await panel.boundingBox();
    if (!panelBox) throw new Error("panel has no box");
    expect(mapBox.x).toBeLessThan(panelBox.x - 100);
    const leftHit = await page.evaluate(
      ([x, y]) => !!document.elementFromPoint(x, y)?.closest('[data-testid="map-view"]'),
      [mapBox.x + 40, mapBox.y + mapBox.height / 2],
    );
    expect(leftHit).toBe(true);

    // Selecting another point swaps the content; the panel itself stays (one level).
    await panel.evaluate((el) => { /** @type {any} */ (window).__panelNode = el; });
    await routeTo(page, "/properties/2");
    await expect(panel.getByTestId("detail-header")).toContainText("3BR House Lourdes");
    await expect(panel.getByTestId("detail-header")).not.toContainText("2BR Apartment Savassi");
    await expect(panel.getByTestId("detail-favourite-toggle")).toHaveAccessibleName("Adicionar aos favoritos");
    await expect(page.getByTestId("detail-panel")).toHaveCount(1);
    expect(await page.evaluate(() => (
      document.querySelector('[data-testid="detail-panel"]') === /** @type {any} */ (window).__panelNode
    ))).toBe(true);
    expect(await sameMapNode(page)).toBe(true);

    // A data refresh behind the panel: the filter changes, the list is refetched,
    // and the panel, its Property and the map stay as they are.
    const before = requests.length;
    await page.getByTestId("listing-type-filter").selectOption("rent");
    await expect.poll(() => requests.slice(before).some((url) => url.includes("listing_type=rent"))).toBe(true);
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveURL(/\/properties\/2$/);
    await expect(panel.getByTestId("detail-header")).toContainText("3BR House Lourdes");
    await expect(page.getByTestId("listing-type-filter")).toHaveValue("rent");
    expect(await sameMapNode(page)).toBe(true);
    expect(await page.evaluate(() => (
      document.querySelector('[data-testid="detail-panel"]') === /** @type {any} */ (window).__panelNode
    ))).toBe(true);

    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
    await expect(page.getByTestId("listing-type-filter")).toHaveValue("rent");
    expect(await sameMapNode(page)).toBe(true);
  });

  test("Esc that closes a dropdown of the page does not also close the panel", async ({ page }) => {
    await setup(page);
    await page.getByRole("button", { name: /Filtros avançados/i }).click();
    await openMapView(page);
    await routeTo(page, "/properties/1");
    const panel = page.getByTestId("detail-panel");
    await expect(panel.getByTestId("detail-header")).toBeVisible();

    // Keyboard, because the control may sit under the panel at this width.
    await page.getByTestId("city-filter-trigger").focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("city-filter-dropdown")).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(page.getByTestId("city-filter-dropdown")).toHaveCount(0);
    await expect(panel.getByTestId("detail-header")).toBeVisible();
    await expect(page).toHaveURL(/\/properties\/1$/);

    // Focus is back on the trigger of the dropdown and nothing is open: the next
    // Esc is free, so it closes the panel. Focus is on a page control, and
    // closing the panel leaves it there.
    expect(await page.evaluate(() => document.activeElement?.getAttribute("data-testid"))).toBe(
      "city-filter-trigger",
    );
    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
    await expect(page).toHaveURL(/\/properties$/);
    expect(await page.evaluate(() => document.activeElement?.getAttribute("data-testid"))).toBe(
      "city-filter-trigger",
    );
  });

  test("Esc while the save-search dialog is open does not close the panel behind it", async ({ page }) => {
    await setup(page);
    await openMapView(page);
    await routeTo(page, "/properties/1");
    const panel = page.getByTestId("detail-panel");
    await expect(panel.getByTestId("detail-header")).toBeVisible();

    await page.getByRole("button", { name: /Salvar filtros atuais/ }).click();
    const dialog = page.getByTestId("save-search-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("input")).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(panel.getByTestId("detail-header")).toBeVisible();
    await expect(page).toHaveURL(/\/properties\/1$/);
    await expect(dialog).toBeVisible();

    // With the dialog dismissed the key belongs to the panel again.
    await dialog.getByRole("button", { name: LABELS.cancel }).click();
    await expect(dialog).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
  });
});
