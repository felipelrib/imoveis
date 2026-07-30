// @ts-check
import { test, expect } from "@playwright/test";
import {
  PROPERTIES_PAGE_FIVE,
  SAMPLE_PROPERTY,
  installCommonMocks,
  mockPropertiesList,
  mockPropertyDetail,
} from "./helpers/apiMocks.js";

async function enterCompareMode(page) {
  await page.getByTestId("compare-mode-toggle").click();
  await expect(page.getByTestId("compare-mode-toggle")).toHaveAttribute("aria-pressed", "true");
}

async function openMapView(page) {
  await page.getByRole("button", { name: /Map/i }).click();
  await expect(page.getByTestId("map-view")).toBeVisible({ timeout: 15000 });
  await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15000 });
}

/** Wait until MapLibre compare hit targets exist (map may still be settling after bbox
 * fetch). Timeouts are generous because under full-suite Playwright load (many chromium
 * workers competing for CPU/WebGL), MapLibre's render pass can lag well past what it
 * takes standalone — this is pre-existing environmental flakiness, not a product
 * regression (see docs/harness-troubleshooting.md#validation-validatesh). */
async function waitForMapCompareHits(page) {
  await expect(page.getByTestId("map-compare-select-1")).toBeVisible({ timeout: 45000 });
  await expect(page.getByTestId("map-compare-select-5")).toBeVisible({ timeout: 20000 });
}

test.describe("Map-view multi-select for comparison", () => {
  // Default Playwright test timeout (30s) is tight for waitForMapCompareHits'
  // generous 45s assertion budget under full-suite CPU contention (see comment
  // there) — raise the per-test ceiling so the assertion timeout isn't cut off
  // by the outer test timeout first.
  test.describe.configure({ timeout: 90_000 });

  test.beforeEach(async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE_FIVE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    await page.goto("/properties");
    await expect(page.locator("text=2BR Apartment Savassi")).toBeVisible();
  });

  test("hides map compare hit targets until Compare mode is activated", async ({ page }) => {
    await openMapView(page);
    await expect(page.getByTestId("map-compare-select-1")).toHaveCount(0);

    await enterCompareMode(page);
    await waitForMapCompareHits(page);
  });

  test("enables Compare at 2 map selections", async ({ page }) => {
    await openMapView(page);
    await enterCompareMode(page);
    await waitForMapCompareHits(page);
    await expect(page.getByTestId("compare-bar")).toHaveCount(0);

    await page.getByTestId("map-compare-select-1").click();
    await expect(page.getByTestId("compare-bar")).toBeVisible();
    await expect(page.getByTestId("compare-count")).toHaveText("1 selected");
    await expect(page.getByTestId("compare-open")).toBeDisabled();
    await expect(page.getByTestId("map-compare-select-1")).toHaveAttribute("aria-pressed", "true");

    await page.getByTestId("map-compare-select-2").click();
    await expect(page.getByTestId("compare-count")).toHaveText("2 selected");
    await expect(page.getByTestId("compare-open")).toBeEnabled();
  });

  test("blocks a 5th map selection with a warning toast", async ({ page }) => {
    await openMapView(page);
    await enterCompareMode(page);
    await waitForMapCompareHits(page);

    for (const id of ["1", "2", "3", "4"]) {
      await page.getByTestId(`map-compare-select-${id}`).click();
    }
    await expect(page.getByTestId("compare-count")).toHaveText("4 selected");
    await expect(page.getByTestId("compare-open")).toBeEnabled();

    await page.getByTestId("map-compare-select-5").click();
    await expect(page.getByText("You can compare up to 4 properties")).toBeVisible();
    await expect(page.getByTestId("compare-count")).toHaveText("4 selected");
    await expect(page.getByTestId("map-compare-select-5")).toHaveAttribute("aria-pressed", "false");
  });

  test("Clear empties map selection; Exit removes hit targets", async ({ page }) => {
    await openMapView(page);
    await enterCompareMode(page);
    await waitForMapCompareHits(page);

    await page.getByTestId("map-compare-select-1").click();
    await page.getByTestId("map-compare-select-2").click();
    await expect(page.getByTestId("compare-bar")).toBeVisible();

    await page.getByTestId("compare-clear").click();
    await expect(page.getByTestId("compare-bar")).toHaveCount(0);
    await expect(page.getByTestId("map-compare-select-1")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("map-compare-select-2")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("map-compare-select-1")).toBeVisible();

    await page.getByTestId("compare-mode-toggle").click();
    await expect(page.getByTestId("compare-mode-toggle")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("map-compare-select-1")).toHaveCount(0);
  });

  test("map compare select does not open the property modal", async ({ page }) => {
    await openMapView(page);
    await enterCompareMode(page);
    await waitForMapCompareHits(page);

    await page.getByTestId("map-compare-select-1").click();
    await expect(page.locator(".modal")).toHaveCount(0);
    await expect(page.getByTestId("compare-bar")).toBeVisible();
  });
});
