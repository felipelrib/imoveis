// @ts-check
/** Shared Playwright API mocks shaped like the real FastAPI responses. */

/** @typedef {import('@playwright/test').Page} Page */

export const SAMPLE_PROPERTY = {
  id: "1",
  public_id: 1,
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
  city: "Belo Horizonte",
  deal_summary: null,
  image_urls: [],
  neighbourhood_quality: {
    amenity_score: 0.8,
    transit_score: 0.7,
    access_score: 0.75,
    safety_score: 0.65,
    neighbourhood_score: 0.725,
    risk_flags: ["flood"],
    quality_meta: { source: "curated" },
    quality_notes: null,
  },
  ai_green_flags: ["near metro"],
  ai_red_flags: ["noisy avenue"],
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
    {
      ...SAMPLE_PROPERTY,
      id: "1",
      public_id: 1,
      title: "2BR Apartment Savassi",
      lat: -19.92,
      lon: -43.94,
    },
    {
      ...SAMPLE_PROPERTY,
      id: "2",
      public_id: 2,
      title: "3BR House Lourdes",
      address: "Rua da Bahia, 100, Lourdes",
      price: 4200,
      bedrooms: 3,
      price_per_m2: 56,
      neighborhood_name: "Lourdes",
      combined_score: 0.65,
      lat: -19.925,
      lon: -43.935,
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
      public_id: 3,
      title: "Studio Funcionarios",
      address: "Av. Afonso Pena, 200, Funcionarios",
      price: 2100,
      bedrooms: 1,
      area_m2: 40,
      price_per_m2: 52.5,
      neighborhood_name: "Funcionarios",
      lat: -19.915,
      lon: -43.945,
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
      public_id: 4,
      title: "Penthouse Santo Antonio",
      address: "Rua Curitiba, 50, Santo Antonio",
      price: 8900,
      bedrooms: 4,
      area_m2: 180,
      price_per_m2: 4944,
      neighborhood_name: "Santo Antonio",
      lat: -19.93,
      lon: -43.95,
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
      public_id: 5,
      title: "Loft Centro",
      address: "Rua Rio de Janeiro, 10, Centro",
      price: 2800,
      bedrooms: 1,
      area_m2: 55,
      price_per_m2: 50.91,
      neighborhood_name: "Centro",
      lat: -19.91,
      lon: -43.93,
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

/** `GET /admin/backfill/status` with no run in flight (v0.13-s1.5 wire shape). */
export const BACKFILL_STATUS_IDLE = {
  state: "idle",
  active: false,
  runner_present: false,
  heartbeat_active: false,
  migration_active: false,
  pending_requests: [],
  start_requested_at: null,
  lease: null,
  budget: {
    limit: 14400,
    consumed: 0,
    remaining: 14400,
    seconds_until_reset: 86400,
  },
  checkpoint: {
    last_property_id: null,
    last_run_date: null,
    processed_total: 0,
  },
  quarantined: null,
  pacing: {
    requests_per_property: 3,
    rpm_limit: 60,
    concurrency: 4,
    tpm_limit: 100000,
  },
};

/** A live run: the lease is held (`active`), the runner is beating, 61% of today's quota spent. */
export const BACKFILL_STATUS_RUNNING = {
  ...BACKFILL_STATUS_IDLE,
  state: "running",
  active: true,
  runner_present: true,
  heartbeat_active: true,
  lease: {
    owner: "gemma-runner@wsl-felipe",
    acquired_at: "2026-08-09T12:00:00Z",
    last_seen: "2026-08-11T09:00:00Z",
    seconds_since_last_seen: 4.2,
  },
  budget: {
    limit: 14400,
    consumed: 8784,
    remaining: 5616,
    seconds_until_reset: 43200,
  },
};

/** `GET /admin/enrichment/coverage` with no live run — throughput/ETA honestly null. */
export const ENRICHMENT_COVERAGE = {
  signals: [
    { task_class: "visual", enriched: 1234, total: 2000, fraction: 0.617 },
    { task_class: "sentiment", enriched: 1800, total: 2000, fraction: 0.9 },
    { task_class: "deal_verdict", enriched: 1200, total: 2000, fraction: 0.6 },
    { task_class: "valuation", enriched: 1900, total: 2000, fraction: 0.95 },
    { task_class: "embedding", enriched: 1950, total: 2000, fraction: 0.975 },
  ],
  minimum_fraction: 0.6,
  total_properties: 2000,
  backfill: {
    active: false,
    remaining: 766,
    throughput_per_day: null,
    eta_days: null,
    projected_completion_date: null,
  },
};

/** Same coverage under a live run: throughput/ETA/date are available. */
export const ENRICHMENT_COVERAGE_RUNNING = {
  ...ENRICHMENT_COVERAGE,
  backfill: {
    active: true,
    remaining: 766,
    throughput_per_day: 4600.0,
    eta_days: 3.2,
    projected_completion_date: "2026-08-14",
  },
};

/**
 * Mock the backfill control plane (`/admin/backfill/{status,start,pause,resume}`).
 * @param {Page} page
 * @param {object} [opts]
 * @param {object} [opts.status] — body for GET /status
 * @param {number} [opts.statusCode] — HTTP status for GET /status (500 to simulate a Redis-side failure)
 * @param {object} [opts.statusAfterStart] — body GET /status returns once a start has been attempted
 *   (the server-real sequence behind a 409: the lease was taken while the card held a stale idle read)
 * @param {number} [opts.startStatus] — HTTP status for POST /start (409 to simulate a held lease)
 * @param {string} [opts.startDetail] — `detail` returned with a non-2xx start
 * @param {object} [opts.startBody] — body merged into a 2xx POST /start response
 *   (`runner_present: false` / `already_requested: true` are honest 202 outcomes)
 * @param {{method: string, url: string}[]} [opts.calls] — every intercepted request
 */
export async function mockAdminBackfill(page, opts = {}) {
  let status = opts.status ?? BACKFILL_STATUS_IDLE;
  const statusCode = opts.statusCode ?? 200;
  const startStatus = opts.startStatus ?? 202;
  const startDetail =
    opts.startDetail ??
    "A backfill run already holds the lease (gemma-runner@wsl-felipe, held for 2 days).";
  const calls = opts.calls;

  await page.route("**/api/admin/backfill/**", (route) => {
    const request = route.request();
    const url = request.url();
    if (calls) calls.push({ method: request.method(), url });

    const json = (code, body) =>
      route.fulfill({
        status: code,
        contentType: "application/json",
        body: JSON.stringify(body),
      });

    if (url.includes("/backfill/status")) {
      if (statusCode >= 400) return json(statusCode, { detail: "Internal server error" });
      return json(200, status);
    }
    if (url.includes("/backfill/start")) {
      if (opts.statusAfterStart) status = opts.statusAfterStart;
      if (startStatus >= 400) return json(startStatus, { detail: startDetail });
      return json(startStatus, {
        requested: true,
        already_requested: false,
        requested_at: "2026-08-11T09:00:00Z",
        runner_present: status.runner_present,
        discarded_requests: [],
        ...(opts.startBody ?? {}),
      });
    }
    if (url.includes("/backfill/pause")) {
      return json(200, { action: "pause", cleared_stop: false, cleared_start: false, status: null });
    }
    if (url.includes("/backfill/resume")) {
      return json(200, { action: "resume", cleared_stop: true, cleared_start: false, status: null });
    }
    return json(404, { detail: "not mocked" });
  });
}

/**
 * Mock `GET /admin/enrichment/coverage` (must not swallow /enrichment/missing|rerun).
 * @param {Page} page
 * @param {object} [body]
 * @param {object} [opts]
 * @param {number} [opts.statusCode] — HTTP status to answer with (500 to simulate a DB failure)
 * @param {{method: string, url: string}[]} [opts.calls] — every intercepted request
 */
export async function mockAdminCoverage(page, body = ENRICHMENT_COVERAGE, opts = {}) {
  const statusCode = opts.statusCode ?? 200;
  const calls = opts.calls;

  await page.route("**/api/admin/enrichment/coverage**", (route) => {
    const request = route.request();
    if (calls) calls.push({ method: request.method(), url: request.url() });
    return route.fulfill({
      status: statusCode,
      contentType: "application/json",
      body: JSON.stringify(
        statusCode >= 400 ? { detail: "Internal server error" } : body
      ),
    });
  });
}

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
        proxy: opts.pipelineProxy ?? {
          proxy_enabled: false,
          proxy_mode: "direct",
          rotation_strategy: "round_robin",
          pool_size: 0,
          proxy_host: null,
          health: "direct",
        },
      }),
    })
  );

  await page.route("**/api/system/pipeline/history**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ points: [] }),
    })
  );

  await page.route("**/api/**/schedule**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ schedules: [] }),
    })
  );

  await page.route("**/api/system/ollama/ensure", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "already_running", models: [] }),
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
      body: JSON.stringify([
        { name: "Savassi", count: 1, city: "Belo Horizonte" },
        { name: "Pinheiros", count: 2, city: "São Paulo" },
        { name: "Cambuí", count: 1, city: "Campinas" },
      ]),
    })
  );

  await page.route("**/api/properties/cities", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        { name: "Belo Horizonte", count: 10 },
        { name: "São Paulo", count: 5 },
        { name: "Campinas", count: 3 },
      ]),
    })
  );

  // Backfill control plane + coverage default to "nothing running" so suites that
  // seed an API key do not 404-spam the Operações card / Painel health strip.
  // The whole `backfill` bag is forwarded — picking out `status` silently dropped
  // a caller's request recorder and its 409/500 simulation.
  if (opts.backfill !== false) {
    await mockAdminBackfill(page, opts.backfill ?? {});
  }
  if (opts.coverage !== false) {
    await mockAdminCoverage(page, opts.coverage ?? ENRICHMENT_COVERAGE);
  }

  // Default locale mock so suites that seed API keys do not hit the real admin API.
  if (opts.locale !== false) {
    await mockAdminLocale(page, {
      initial: opts.locale?.initial ?? "en",
      defaultLocale: opts.locale?.defaultLocale ?? "en",
      supported: opts.locale?.supported,
      posted: opts.locale?.posted,
    });
  }
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
  const pathKeys = [property.id, property.public_id]
    .filter((k) => k != null && k !== "")
    .map(String);
  for (const key of pathKeys) {
    await page.route(`**/api/properties/${key}`, (route) => {
      if (route.request().url().includes("price-history") || route.request().url().includes("by-ids")) {
        return route.fallback();
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(property),
      });
    });
    await page.route(`**/api/properties/${key}/price-history**`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      })
    );
  }
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
    const byId = new Map();
    for (const p of properties) {
      byId.set(String(p.id), p);
      if (p.public_id != null) byId.set(String(p.public_id), p);
    }
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

/**
 * Mock GET /admin/schedule and capture X-API-Key headers (BIN-59).
 * @param {Page} page
 * @param {object} [opts]
 * @param {string[]} [opts.capturedKeys]
 * @param {object} [opts.body]
 */
export async function mockAdminSchedule(page, opts = {}) {
  const capturedKeys = opts.capturedKeys;
  const body = opts.body ?? {
    schedules: [
      {
        platform: "olx",
        interval_minutes: 60,
        last_run: null,
        next_run: null,
        estimated: false,
      },
    ],
  };

  await page.route("**/api/admin/schedule**", (route) => {
    const key = route.request().headers()["x-api-key"] || "";
    if (capturedKeys) capturedKeys.push(key);
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

/**
 * Mock GET/POST /admin/locale with in-memory preference (BIN-98).
 * @param {Page} page
 * @param {object} [opts]
 * @param {string} [opts.initial]
 * @param {string} [opts.defaultLocale]
 * @param {string[]} [opts.supported]
 * @param {string[]} [opts.posted]
 */
export async function mockAdminLocale(page, opts = {}) {
  let active = opts.initial ?? "en";
  const defaultLocale = opts.defaultLocale ?? "en";
  const supported = opts.supported ?? ["en", "pt-BR"];
  const posted = opts.posted;

  await page.route("**/api/admin/locale**", async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          locale: active,
          default: defaultLocale,
          supported,
        }),
      });
    }
    if (method === "POST") {
      const body = route.request().postDataJSON() || {};
      const next = body.locale;
      if (!supported.includes(next)) {
        return route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({ detail: `Unsupported locale '${next}'` }),
        });
      }
      active = next;
      if (posted) posted.push(next);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          locale: active,
          default: defaultLocale,
          supported,
        }),
      });
    }
    return route.fulfill({ status: 405, body: "" });
  });
}
