// @ts-check
import { test, expect } from "@playwright/test";
import {
  SAMPLE_PROPERTY,
  installCommonMocks,
  mockPropertiesList,
  mockPropertyDetail,
} from "./helpers/apiMocks.js";

// v0.14-fu2 (DW-53) — the property points are a GeoJSON source, which MapLibre
// tiles in its web worker. After the maplibre-gl 6 upgrade the worker script
// was requested from a URL nothing serves (404), so the basemap drew and no
// point ever did. `data-map-ready` cannot see that: it only says the style
// loaded. This spec asserts what a person sees: a point that is really
// rendered (MapLibre hit-tests rendered features for the layer's hover and
// click handlers) and a worker script that loaded.

// MapView's initial centre (Belo Horizonte), so the point sits at the middle
// of the canvas without the test having to reach into the map instance.
const MAP_CENTER = { lat: -19.92, lon: -43.94 };
const PROPERTY = { ...SAMPLE_PROPERTY, ...MAP_CENTER };

const WORKER_SCRIPT = /maplibre-gl-worker/;

test.describe("Map property points (v0.14-fu2)", () => {
  test("a property point is rendered, its worker script loads, and clicking it opens the detail panel", async ({ page }) => {
    // WebGL init under full-suite load (same bump as compare-map-select).
    test.setTimeout(60_000);

    /** @type {{ url: string, status: number, contentType: string }[]} */
    const workerResponses = [];
    /** @type {string[]} */
    const workerFailures = [];
    page.on("response", (response) => {
      if (WORKER_SCRIPT.test(response.url())) {
        workerResponses.push({
          url: response.url(),
          status: response.status(),
          contentType: response.headers()["content-type"] ?? "",
        });
      }
    });
    page.on("requestfailed", (request) => {
      if (WORKER_SCRIPT.test(request.url())) workerFailures.push(request.url());
    });

    await installCommonMocks(page);
    await mockPropertiesList(page, {
      properties: [PROPERTY],
      page: 1,
      page_size: 24,
      pages: 1,
      total: 1,
    });
    await mockPropertyDetail(page, PROPERTY);

    await page.goto("/properties");
    await expect(page.getByText(PROPERTY.title)).toBeVisible();
    await page.getByRole("button", { name: /Mapa/ }).click();
    const canvas = page.locator(".maplibregl-canvas");
    await expect(canvas).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("map-view")).toHaveAttribute("data-map-ready", "true", {
      timeout: 30000,
    });

    await canvas.scrollIntoViewIfNeeded();
    const box = await canvas.boundingBox();
    if (!box) throw new Error("map canvas not laid out");
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;

    // Rendered, not merely added: MapView sets the pointer cursor from a
    // `mouseenter` on the `unclustered-point` layer, which MapLibre fires only
    // when a rendered feature of that layer is under the mouse. The mouse is
    // nudged on every poll because the worker delivers the tile asynchronously.
    let nudge = 0;
    await expect
      .poll(
        async () => {
          nudge = nudge === 0 ? 1 : 0;
          await page.mouse.move(cx + nudge, cy);
          return canvas.evaluate((el) => /** @type {HTMLElement} */ (el).style.cursor);
        },
        { timeout: 20000, message: "no rendered property point under the map centre" },
      )
      .toBe("pointer");

    // The worker script was fetched and every fetch of it returned a script.
    expect(workerFailures).toEqual([]);
    expect(workerResponses.length).toBeGreaterThan(0);
    for (const r of workerResponses) {
      expect(r.status, `worker script ${r.url}`).toBe(200);
      // A static host with an SPA fallback answers a missing worker file with
      // index.html and status 200 (seen on `vite preview` of the unfixed build).
      expect(r.contentType, `worker script ${r.url}`).toMatch(/javascript/);
    }

    // Clicking the point opens its popup; the popup's button opens the panel
    // (the third way into the detail panel, left untested by v0.14-s1.8).
    await page.mouse.click(cx, cy);
    const popup = page.locator(".maplibregl-popup");
    await expect(popup).toContainText(PROPERTY.title);
    await popup.locator(".map-view-btn").click();
    await expect(page.getByTestId("detail-panel")).toBeVisible();
    await expect(page.getByTestId("detail-panel")).toContainText(PROPERTY.title);
  });
});
