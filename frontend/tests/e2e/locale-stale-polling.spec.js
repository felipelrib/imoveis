// @ts-check
/**
 * BIN-154 — Dashboard/ScraperControl polling loops must read the *current*
 * locale/t after a mid-session language switch, not the values captured when
 * the mount-only `useEffect(() => {...}, [])` polling loop first subscribed.
 *
 * Locks:
 *  - frontend/src/pages/ScraperControl.jsx "Poll pipeline status" effect
 *    (scrape-run activity log lines) — fixed via tRef/localeRef, mirroring
 *    the ref pattern MapView.jsx already uses for its map-popup content.
 *  - frontend/src/pages/Dashboard.jsx pipeline history/tip poll (chart
 *    x-axis timestamps) — already re-subscribes via a `[locale]` effect dep.
 *
 * Both specs fail (stale English wording/formatting for post-switch poll
 * ticks) if either page reverts to closing over locale/t from mount.
 */
import { test, expect } from "@playwright/test";
import {
  installCommonMocks,
  mockAdminLocale,
  mockPlatforms,
} from "./helpers/apiMocks.js";

const VALID_KEY = "e2e-test-api-key";

test.describe("Locale-aware polling loops (BIN-154)", () => {
  test("scraper activity log uses new-locale wording for scrape runs logged after a mid-session locale switch", async ({
    page,
  }) => {
    /** @type {Array<object>} */
    let recentRuns = [];

    // setLocale() only posts the switch when a credential is present.
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page, { locale: false });
    await mockAdminLocale(page, { initial: "en" });
    await mockPlatforms(page);

    // Overrides installCommonMocks' static pipeline route so recent_scrape_runs
    // can change between poll ticks (poll interval is 3s).
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
          recent_scrape_runs: recentRuns,
        }),
      }),
    );

    await page.goto("/scraper");

    // First poll tick (still 'en'): a scrape run logs with English wording.
    recentRuns = [
      {
        run_id: "run-en-1",
        platform: "olx",
        processed: 5,
        skipped: 1,
        errors: 0,
        status: "ok",
        timestamp: Date.now() / 1000,
      },
    ];
    await expect(
      page.getByText("OLX scrape finished — 5 processed, 1 skipped, 0 failed"),
    ).toBeVisible({ timeout: 6000 });

    // Switch locale mid-session via the sidebar switcher (present on every page).
    await page.getByTestId("locale-select").selectOption("pt-BR");
    await expect(page.locator("html")).toHaveAttribute("lang", "pt-BR");

    // Second poll tick, after the switch: a *new* (unseen) run must log with
    // pt-BR wording — proving the poller re-read t/locale instead of the
    // values closed over when the mount-only effect first subscribed.
    recentRuns = [
      {
        run_id: "run-pt-1",
        platform: "olx",
        processed: 7,
        skipped: 2,
        errors: 0,
        status: "ok",
        timestamp: Date.now() / 1000,
      },
    ];
    await expect(
      page.getByText(
        "Scraping de OLX concluído — 7 processados, 2 pulados, 0 falharam",
      ),
    ).toBeVisible({ timeout: 6000 });

    // Must not have fallen back to stale English wording for the post-switch run.
    await expect(page.getByText(/7 processed/)).toHaveCount(0);
  });

  test("dashboard throughput chart renders new-locale timestamps for poll ticks after a mid-session locale switch", async ({
    page,
  }) => {
    // setLocale() only posts the switch when a credential is present.
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page, { locale: false });
    await mockAdminLocale(page, { initial: "en" });

    // Seed one persisted history point so the chart (needs >=2 points) appears
    // as soon as the first live poll tick appends a second point.
    await page.route("**/api/system/pipeline/history**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          points: [
            {
              ts: new Date().toISOString(),
              throughput_per_min: 1,
              scraper_queue: 0,
              ai_queue: 0,
            },
          ],
        }),
      }),
    );

    await page.goto("/");
    await expect(page.getByText(/AI Throughput/i)).toBeVisible();

    // formatTime('en') renders a 12-hour clock with an AM/PM marker; formatTime
    // ('pt-BR') renders 24-hour with none — a reliable locale signal that
    // doesn't depend on the exact wall-clock value of the poll tick. Recharts
    // v3 portals tick labels into their own z-index layer (not nested under
    // `.recharts-xAxis`), but keeps the axis-specific `recharts-xAxis-tick-labels`
    // class, which conveniently also keeps this scoped away from the queue-depth
    // BarChart's plain-number YAxis ticks (`recharts-yAxis-tick-labels`).
    const ticks = page.locator(
      ".recharts-xAxis-tick-labels .recharts-cartesian-axis-tick-label",
    );
    await expect(ticks.last()).toBeVisible({ timeout: 12000 });
    await expect
      .poll(async () => (await ticks.last().textContent()) || "", {
        timeout: 12000,
      })
      .toMatch(/AM|PM/i);

    // Switch locale mid-session.
    await page.getByTestId("locale-select").selectOption("pt-BR");
    await expect(page.locator("html")).toHaveAttribute("lang", "pt-BR");

    // Wait for the next live poll tick (8s interval) to append a new,
    // pt-BR-formatted (24h, no AM/PM) point. The stale-closure bug kept
    // formatting new ticks in English indefinitely after the switch.
    await expect
      .poll(async () => (await ticks.last().textContent()) || "", {
        timeout: 12000,
      })
      .not.toMatch(/AM|PM/i);
  });
});
