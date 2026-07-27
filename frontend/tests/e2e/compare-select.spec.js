// @ts-check
import { test, expect } from "@playwright/test";
import {
  PROPERTIES_PAGE_FIVE,
  SAMPLE_PROPERTY,
  installCommonMocks,
  mockPropertiesList,
  mockPropertyDetail,
} from "./helpers/apiMocks.js";

/** Parse CSS color alpha; rgb(...) → 1, rgba(..., a) → a */
function cssAlpha(color) {
  const m = String(color).match(/rgba?\(([^)]+)\)/i);
  if (!m) return 1;
  const parts = m[1].split(",").map((s) => s.trim());
  return parts.length === 4 ? Number.parseFloat(parts[3]) : 1;
}

async function enterCompareMode(page) {
  await page.getByTestId("compare-mode-toggle").click();
  await expect(page.getByTestId("compare-mode-toggle")).toHaveAttribute("aria-pressed", "true");
}

test.describe("Properties multi-select for comparison", () => {
  test.beforeEach(async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE_FIVE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    await page.goto("/properties");
    await expect(page.locator("text=2BR Apartment Savassi")).toBeVisible();
  });

  test("hides compare checkboxes until Compare mode is activated", async ({ page }) => {
    await expect(page.getByTestId("compare-select-1")).toHaveCount(0);
    await enterCompareMode(page);
    await expect(page.getByTestId("compare-select-1")).toBeVisible();
  });

  test("enables Compare at 2 selections and keeps bar visible at 1", async ({ page }) => {
    await enterCompareMode(page);
    await expect(page.getByTestId("compare-bar")).toHaveCount(0);

    await page.getByTestId("compare-select-1").check();
    await expect(page.getByTestId("compare-bar")).toBeVisible();
    await expect(page.getByTestId("compare-count")).toHaveText("1 selected");
    await expect(page.getByTestId("compare-open")).toBeDisabled();

    await page.getByTestId("compare-select-2").check();
    await expect(page.getByTestId("compare-count")).toHaveText("2 selected");
    await expect(page.getByTestId("compare-open")).toBeEnabled();
  });

  test("compare selection bar stays opaque over the grid", async ({ page }) => {
    await enterCompareMode(page);
    await page.getByTestId("compare-select-1").check();
    await page.getByTestId("compare-select-2").check();
    await expect(page.getByTestId("compare-bar")).toBeVisible();

    const bg = await page.getByTestId("compare-bar").evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(cssAlpha(bg)).toBeGreaterThanOrEqual(0.95);
  });

  test("saved searches sidebar stays opaque", async ({ page }) => {
    const bg = await page.locator(".saved-searches-sidebar").evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(cssAlpha(bg)).toBeGreaterThanOrEqual(0.95);
  });

  test("blocks a 5th selection with a warning toast", async ({ page }) => {
    await enterCompareMode(page);
    for (const id of ["1", "2", "3", "4"]) {
      await page.getByTestId(`compare-select-${id}`).check();
    }
    await expect(page.getByTestId("compare-count")).toHaveText("4 selected");
    await expect(page.getByTestId("compare-open")).toBeEnabled();

    await page.getByTestId("compare-select-5").click();
    await expect(page.getByText("You can compare up to 4 properties")).toBeVisible();
    await expect(page.getByTestId("compare-count")).toHaveText("4 selected");
    await expect(page.getByTestId("compare-select-5")).not.toBeChecked();
  });

  test("Clear returns to selection-empty compare mode; Exit hides checkboxes", async ({ page }) => {
    await enterCompareMode(page);
    await page.getByTestId("compare-select-1").check();
    await page.getByTestId("compare-select-2").check();
    await expect(page.getByTestId("compare-bar")).toBeVisible();

    await page.getByTestId("compare-clear").click();
    await expect(page.getByTestId("compare-bar")).toHaveCount(0);
    await expect(page.getByTestId("compare-select-1")).not.toBeChecked();
    await expect(page.getByTestId("compare-select-2")).not.toBeChecked();
    await expect(page.getByTestId("compare-select-1")).toBeVisible();

    await page.getByTestId("compare-mode-toggle").click();
    await expect(page.getByTestId("compare-mode-toggle")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("compare-select-1")).toHaveCount(0);
  });

  test("checkbox click does not open the property modal", async ({ page }) => {
    await enterCompareMode(page);
    await page.getByTestId("compare-select-1").check();
    await expect(page.locator(".modal")).toHaveCount(0);
    await expect(page.getByTestId("compare-bar")).toBeVisible();
  });

  test("watchlist uses lucide Bell distinct from favourites Star", async ({ page }) => {
    const fav = page.getByTestId("favourite-toggle-1");
    const watch = page.getByTestId("watchlist-toggle-1");
    await expect(fav.locator("svg")).toBeVisible();
    await expect(watch.locator("svg")).toBeVisible();
    await expect(fav).toHaveAttribute("aria-label", /Favourites/i);
    await expect(watch).toHaveAttribute("aria-label", /price drops|Watchlist/i);
  });
});
