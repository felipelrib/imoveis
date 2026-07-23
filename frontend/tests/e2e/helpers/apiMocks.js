// @ts-check
/** Shared Playwright API mocks shaped like the real FastAPI responses. */

/** @typedef {import('@playwright/test').Page} Page */

export const SAMPLE_PROPERTY = {
  id: "1",
  title: "2BR Apartment Savassi",
  address: "Rua Pernambuco, 500, Savassi",
  price: 3500,
  area_m2: 75,
  bedrooms: 2,
  bathrooms: 1,
  parking: 1,
  platform: "olx",
  platform_id: "123456789",
  combined_score: 0.72,
  stat_score: 0.68,
  ai_score: 0.75,
  price_per_m2: 46.67,
  neighborhood_name: "Savassi",
  deal_summary: null,
  image_urls: [],
  primary_listing: {
    platform: "olx",
    platform_listing_id: "123456789",
    listing_type: "rent",
    price: 3500,
    currency: "BRL",
    url: "https://www.olx.com.br/imovel/aluguel/apartamentos/mg/detalhes/123456789",
  },
  listings: [
    {
      platform: "olx",
      listing_type: "rent",
      price: 3500,
      url: "https://www.olx.com.br/imovel/aluguel/apartamentos/mg/detalhes/123456789",
    },
  ],
};

/** Sample price-history points (≥2) for compare charts. */
export const SAMPLE_PRICE_HISTORY = [
  {
    id: "ph-1",
    price: 3600,
    start_ts: "2026-01-01T00:00:00Z",
    end_ts: "2026-02-01T00:00:00Z",
    listing_type: "rent",
    platform: "olx",
  },
  {
    id: "ph-2",
    price: 3500,
    start_ts: "2026-02-01T00:00:00Z",
    end_ts: null,
    listing_type: "rent",
    platform: "olx",
  },
];

export const EMPTY_PROPERTIES = {
  properties: [],
  page: 1,
  page_size: 24,
  total: 0,
};

export const PROPERTIES_PAGE = {
  properties: [SAMPLE_PROPERTY],
  page: 1,
  page_size: 24,
  total: 1,
};

/** Five distinct properties for multi-select / compare limit e2e. */
export const PROPERTIES_PAGE_FIVE = {
  properties: [
    { ...SAMPLE_PROPERTY, id: "1", title: "2BR Apartment Savassi" },
    {
      ...SAMPLE_PROPERTY,
      id: "2",
      title: "3BR House Lourdes",
      address: "Rua da Bahia, 100, Lourdes",
      price: 4200,
      bedrooms: 3,
      price_per_m2: 56,
      neighborhood_name: "Lourdes",
      combined_score: 0.65,
      primary_listing: {
        platform: "quintoandar",
        platform_listing_id: "2",
        listing_type: "rent",
        price: 4200,
        currency: "BRL",
        url: "https://example.com/2",
      },
      listings: [
        {
          platform: "quintoandar",
          listing_type: "rent",
          price: 4200,
          url: "https://example.com/2",
        },
      ],
    },
    {
      ...SAMPLE_PROPERTY,
      id: "3",
      title: "Studio Funcionarios",
      address: "Av. Afonso Pena, 200, Funcionarios",
      price: 2100,
      bedrooms: 1,
      area_m2: 40,
      price_per_m2: 52.5,
      neighborhood_name: "Funcionarios",
      primary_listing: {
        platform: "olx",
        platform_listing_id: "3",
        listing_type: "rent",
        price: 2100,
        currency: "BRL",
        url: "https://example.com/3",
      },
      listings: [
        {
          platform: "olx",
          listing_type: "rent",
          price: 2100,
          url: "https://example.com/3",
        },
      ],
    },
    {
      ...SAMPLE_PROPERTY,
      id: "4",
      title: "Penthouse Santo Antonio",
      address: "Rua Curitiba, 50, Santo Antonio",
      price: 8900,
      bedrooms: 4,
      area_m2: 180,
      price_per_m2: 4944,
      neighborhood_name: "Santo Antonio",
      primary_listing: {
        platform: "olx",
        platform_listing_id: "4",
        listing_type: "sale",
        price: 890000,
        currency: "BRL",
        url: "https://example.com/4",
      },
      listings: [
        {
          platform: "olx",
          listing_type: "sale",
          price: 890000,
          url: "https://example.com/4",
        },
      ],
    },
    {
      ...SAMPLE_PROPERTY,
      id: "5",
      title: "Loft Centro",
      address: "Rua Rio de Janeiro, 10, Centro",
      price: 2800,
      bedrooms: 1,
      area_m2: 55,
      price_per_m2: 50.91,
      neighborhood_name: "Centro",
      primary_listing: {
        platform: "quintoandar",
        platform_listing_id: "5",
        listing_type: "rent",
        price: 2800,
        currency: "BRL",
        url: "https://example.com/5",
      },
      listings: [
        {
          platform: "quintoandar",
          listing_type: "rent",
          price: 2800,
          url: "https://example.com/5",
        },
      ],
    },
  ],
  page: 1,
  page_size: 24,
  total: 5,
};

export const SYSTEM_STATUS = {
  database: { status: "ok", detail: "Connected" },
  redis: { status: "ok" },
  ollama: { status: "ok", models: ["llava"] },
  workers: { status: "ok" },
  ai_workers_paused: false,
  stats: { total_properties: 1, enriched_properties: 0 },
};

export const PLATFORMS = [
  { name: "olx", enabled: true },
  { name: "quintoandar", enabled: true },
];

/**
 * Install baseline routes used by most pages (status + empty secondary APIs).
 * @param {Page} page
 * @param {object} [opts]
 */
export async function installCommonMocks(page, opts = {}) {
  const status = opts.status ?? SYSTEM_STATUS;

  await page.route("**/api/system/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(status),
    })
  );

  await page.route("**/api/system/pipeline", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        queues: { scrapers: 0, ai: 0 },
        scrapers_status: {},
        ai_metrics: {
          throughput_per_min: 0,
          avg_duration_sec: 0,
          total_recorded: 0,
        },
      }),
    })
  );

  await page.route("**/api/**/schedule**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ schedules: [] }),
    })
  );

  await page.route("**/api/alerts**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    })
  );

  await page.route("**/api/watchlist**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    })
  );

  await page.route("**/api/favourites**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0 }),
    })
  );

  await page.route("**/api/saved-searches**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [] }),
    })
  );

  await page.route("**/api/properties/neighborhoods", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{ name: "Savassi", count: 1 }]),
    })
  );
}

/**
 * Mock GET /properties/export (BIN-51). Register before list mocks when capturing URLs.
 * @param {Page} page
 * @param {object} [opts]
 * @param {number} [opts.status]
 * @param {'csv'|'json'|null} [opts.format] — if set, only fulfill matching format
 * @param {string|object} [opts.body]
 * @param {string[]} [opts.capturedUrls]
 * @param {Record<string, string>} [opts.headers]
 */
export async function mockPropertiesExport(page, opts = {}) {
  const status = opts.status ?? 200;
  const capturedUrls = opts.capturedUrls;
  const formatFilter = opts.format ?? null;

  await page.route("**/api/properties/export**", async (route) => {
    const url = route.request().url();
    if (capturedUrls) capturedUrls.push(url);

    const reqFormat = new URL(url).searchParams.get("format");
    if (formatFilter && reqFormat !== formatFilter) {
      return route.fallback();
    }

    if (status >= 400) {
      const errBody =
        typeof opts.body === "object" && opts.body !== null
          ? opts.body
          : { detail: typeof opts.body === "string" ? opts.body : "Export failed" };
      return route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(errBody),
      });
    }

    if (reqFormat === "csv") {
      const csv =
        typeof opts.body === "string"
          ? opts.body
          : "id,title\n1,2BR Apartment Savassi\n";
      return route.fulfill({
        status: 200,
        contentType: "text/csv; charset=utf-8",
        headers: {
          "Content-Disposition": 'attachment; filename="properties-export.csv"',
          "X-Export-Total": "1",
          "X-Export-Truncated": "false",
          ...(opts.headers || {}),
        },
        body: csv,
      });
    }

    const jsonBody =
      typeof opts.body === "object" && opts.body !== null
        ? opts.body
        : {
            properties: [SAMPLE_PROPERTY],
            total: 1,
            truncated: false,
          };
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(jsonBody),
    });
  });
}

/**
 * @param {Page} page
 * @param {object} body
 */
export async function mockPropertiesList(page, body = PROPERTIES_PAGE) {
  await page.route("**/api/properties?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    })
  );
  // Also match /api/properties without query (rare)
  await page.route("**/api/properties", (route) => {
    if (route.request().url().includes("/properties/")) {
      return route.fallback();
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

/**
 * @param {Page} page
 * @param {object} property
 */
export async function mockPropertyDetail(page, property = SAMPLE_PROPERTY) {
  await page.route(`**/api/properties/${property.id}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(property),
    })
  );
  await page.route(`**/api/properties/${property.id}/price-history`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    })
  );
  await page.route(`**/api/watchlist/check/${property.id}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ watched: false }),
    })
  );
  await page.route(`**/api/favourites/check/${property.id}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ favourited: false }),
    })
  );
}

/**
 * Mock GET /properties/by-ids for compare view.
 * @param {Page} page
 * @param {object[]} properties
 */
export async function mockPropertiesByIds(page, properties) {
  await page.route("**/api/properties/by-ids**", (route) => {
    const url = new URL(route.request().url());
    const requested = (url.searchParams.get("ids") || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const byId = new Map(properties.map((p) => [String(p.id), p]));
    const ordered = requested.map((id) => byId.get(id)).filter(Boolean);
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ properties: ordered }),
    });
  });
}

/**
 * Mock price-history for one or more property ids.
 * @param {Page} page
 * @param {Record<string, object[]>} historyById
 */
export async function mockPriceHistoryByIds(page, historyById = {}) {
  await page.route("**/api/properties/*/price-history**", (route) => {
    const match = route.request().url().match(/\/properties\/([^/]+)\/price-history/);
    const id = match ? match[1] : null;
    const body = (id && historyById[id]) || [];
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

/**
 * @param {Page} page
 */
export async function mockPlatforms(page) {
  await page.route("**/api/platforms", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(PLATFORMS),
    })
  );
}

/**
 * @param {Page} page
 * @param {object} [response]
 */
export async function mockScrapeTrigger(page, response = { task_id: "task-abc" }) {
  await page.route("**/api/scrape", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(response),
    })
  );
}

/**
 * Mock GET /admin/health — accepts only the given X-API-Key (BIN-46 credential gate).
 * @param {Page} page
 * @param {object} [opts]
 * @param {string} [opts.validKey]
 * @param {string[]} [opts.capturedKeys] — push each request's X-API-Key when provided
 */
export async function mockAdminHealth(page, opts = {}) {
  const validKey = opts.validKey ?? "e2e-test-api-key";
  const capturedKeys = opts.capturedKeys;

  await page.route("**/api/admin/health", (route) => {
    const key = route.request().headers()["x-api-key"] || "";
    if (capturedKeys) capturedKeys.push(key);
    if (key && key === validKey) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "ok" }),
      });
    }
    return route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Could not validate API Key" }),
    });
  });
}
