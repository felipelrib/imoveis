// @ts-check
import { test, expect } from "@playwright/test";
import { SAMPLE_PROPERTY, installCommonMocks } from "./helpers/apiMocks.js";

// v0.14-fu1 — the map's viewport fetch must stay inside the page size the API
// accepts. It asked for 200 while GET /properties allows 100, so on the real
// API every map fetch was a 422 and no point was drawn; the other specs never
// saw it because their mocks answer any page size.

const API_MAX_PAGE_SIZE = 100; // src/api/properties.py, PropertyListFilters.page_size

test.describe("Map viewport fetch (v0.14-fu1)", () => {
  test("asks for no more rows than the API accepts", async ({ page }) => {
    // WebGL init under full-suite load (same bump as compare-map-select).
    test.setTimeout(60_000);
    await installCommonMocks(page);
    /** @type {{ url: URL, status: number }[]} */
    const seen = [];
    await page.route("**/api/properties?**", async (route) => {
      const url = new URL(route.request().url());
      const pageSize = Number(url.searchParams.get("page_size") ?? "24");
      // Mirror the API's validation instead of answering anything.
      const status = pageSize >= 1 && pageSize <= API_MAX_PAGE_SIZE ? 200 : 422;
      seen.push({ url, status });
      const property = { ...SAMPLE_PROPERTY, id: "1", public_id: 1, title: "Apto no mapa", lat: -19.93, lon: -43.94 };
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status === 200
            ? { properties: [property], page: 1, page_size: pageSize, pages: 1, total: 1 }
            : { detail: [{ type: "less_than_equal", loc: ["query", "page_size"] }] },
        ),
      });
    });

    await page.goto("/properties");
    await page.getByRole("button", { name: /Mapa/ }).click();
    await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("map-view")).toHaveAttribute("data-map-ready", "true", {
      timeout: 30000,
    });

    // The map fetches for its viewport when a move ends: pan it.
    const canvas = page.locator(".maplibregl-canvas");
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
      .poll(() => seen.some((r) => r.url.searchParams.has("bbox")), { timeout: 15000 })
      .toBeTruthy();
    const mapFetches = seen.filter((r) => r.url.searchParams.has("bbox"));
    for (const r of mapFetches) {
      expect(Number(r.url.searchParams.get("page_size"))).toBeLessThanOrEqual(API_MAX_PAGE_SIZE);
      expect(r.status).toBe(200);
    }
  });
});
