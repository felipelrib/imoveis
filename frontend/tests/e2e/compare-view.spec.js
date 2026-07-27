// @ts-check
import { test, expect } from "@playwright/test";
import {
  PROPERTIES_PAGE_FIVE,
  SAMPLE_PRICE_HISTORY,
  SAMPLE_PROPERTY,
  installCommonMocks,
  mockPropertiesByIds,
  mockPropertiesList,
  mockPropertyDetail,
  mockPriceHistoryByIds,
} from "./helpers/apiMocks.js";

async function enterCompareMode(page) {
  await page.getByTestId("compare-mode-toggle").click();
  await expect(page.getByTestId("compare-mode-toggle")).toHaveAttribute("aria-pressed", "true");
}

async function selectAndOpenCompare(page, ids) {
  await enterCompareMode(page);
  for (const id of ids) {
    await page.getByTestId(`compare-select-${id}`).click();
  }
  await page.getByTestId("compare-open").click();
}

test.describe("Side-by-side compare view", () => {
  test.beforeEach(async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE_FIVE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    await mockPropertiesByIds(page, PROPERTIES_PAGE_FIVE.properties);
    await mockPriceHistoryByIds(page, {
      "1": SAMPLE_PRICE_HISTORY,
      "2": SAMPLE_PRICE_HISTORY.map((h, i) => ({
        ...h,
        id: `ph-2-${i}`,
        price: h.price + 500,
        platform: "quintoandar",
      })),
    });
    await page.goto("/properties");
    await expect(page.locator("text=2BR Apartment Savassi")).toBeVisible();
  });

  test("opens compare with attribute columns, scores, price/m², and history", async ({ page }) => {
    await selectAndOpenCompare(page, ["1", "2"]);

    await expect(page).toHaveURL(/\/compare\/1,2$/);
    await expect(page.getByTestId("compare-view")).toBeVisible();
    await expect(page.getByTestId("compare-table")).toBeVisible();
    await expect(page.getByTestId("compare-col-1")).toContainText("2BR Apartment Savassi");
    await expect(page.getByTestId("compare-col-2")).toContainText("3BR House Lourdes");

    await expect(page.getByTestId("compare-row-price")).toBeVisible();
    await expect(page.getByTestId("compare-row-price_per_m2")).toContainText("R$");
    await expect(page.getByTestId("compare-row-combined_score")).toBeVisible();
    await expect(page.getByTestId("compare-history-1")).toBeVisible();
    await expect(page.getByTestId("compare-history-2")).toBeVisible();
  });

  test("compare view panel is opaque (does not show grid through it)", async ({ page }) => {
    await selectAndOpenCompare(page, ["1", "2"]);
    await expect(page.getByTestId("compare-view")).toBeVisible();

    const bg = await page.getByTestId("compare-view").evaluate((el) => getComputedStyle(el).backgroundColor);
    const m = String(bg).match(/rgba?\(([^)]+)\)/i);
    let alpha = 1;
    if (m) {
      const parts = m[1].split(",").map((s) => s.trim());
      alpha = parts.length === 4 ? Number.parseFloat(parts[3]) : 1;
    }
    expect(alpha).toBeGreaterThanOrEqual(0.95);
  });

  test("Back to grid keeps selection; Clear & exit clears it and leaves compare mode", async ({ page }) => {
    await selectAndOpenCompare(page, ["1", "2"]);
    await expect(page.getByTestId("compare-view")).toBeVisible();
    await expect(page).toHaveURL(/\/compare\/1,2$/);

    await page.getByTestId("compare-exit").click();
    await expect(page.getByTestId("compare-view")).toHaveCount(0);
    await expect(page).toHaveURL(/\/properties$/);
    await expect(page.getByTestId("compare-bar")).toBeVisible();
    await expect(page.getByTestId("compare-count")).toHaveText("2 selected");

    await page.getByTestId("compare-open").click();
    await expect(page.getByTestId("compare-view")).toBeVisible();
    await page.getByTestId("compare-exit-clear").click();
    await expect(page.getByTestId("compare-view")).toHaveCount(0);
    await expect(page.getByTestId("compare-bar")).toHaveCount(0);
    await expect(page.getByTestId("compare-select-1")).toHaveCount(0);
    await expect(page.getByTestId("compare-mode-toggle")).toHaveAttribute("aria-pressed", "false");
  });

  test("missing price history degrades to placeholder", async ({ page }) => {
    await mockPriceHistoryByIds(page, { "1": [], "3": [] });
    await selectAndOpenCompare(page, ["1", "3"]);

    await expect(page.getByTestId("compare-view")).toBeVisible();
    await expect(page.getByTestId("compare-history-empty-1")).toHaveText("No price history");
    await expect(page.getByTestId("compare-history-empty-3")).toHaveText("No price history");
  });
});
