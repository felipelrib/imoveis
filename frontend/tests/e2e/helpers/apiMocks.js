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
  image_urls: [],
  listings: [
    {
      platform: "olx",
      listing_type: "rent",
      price: 3500,
      url: "https://www.olx.com.br/imovel/aluguel/apartamentos/mg/detalhes/123456789",
    },
  ],
};

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
