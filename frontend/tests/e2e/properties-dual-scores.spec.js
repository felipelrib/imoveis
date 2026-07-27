// @ts-check
import { test, expect } from "@playwright/test";
import {
  installCommonMocks,
  SAMPLE_PROPERTY,
} from "./helpers/apiMocks.js";

const DUAL_SCORE_PROPERTY = {
  ...SAMPLE_PROPERTY,
  id: "dual-1",
  public_id: 99,
  title: "Dual-listed Loft Centro",
  combined_score: 0.75,
  combined_score_rent: 0.82,
  combined_score_sale: 0.48,
  stat_score: 0.78,
  stat_score_rent: 0.85,
  stat_score_sale: 0.42,
  available_for_rent: true,
  available_for_sale: true,
  props_json: { available_for_rent: true, available_for_sale: true },
  listings: [
    {
      platform: "olx",
      listing_type: "rent",
      price: 3500,
      url: "https://example.test/rent",
    },
    {
      platform: "zap",
      listing_type: "sale",
      price: 650000,
      url: "https://example.test/sale",
    },
  ],
};

const DUAL_PAGE = {
  total: 1,
  page: 1,
  page_size: 24,
  pages: 1,
  properties: [DUAL_SCORE_PROPERTY],
};

test.describe("Dual listing-type scores (BIN-83)", () => {
  test("Transaction Both shows rent and sale score badges", async ({ page }) => {
    await installCommonMocks(page);
    await page.route("**/api/properties?**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(DUAL_PAGE),
      });
    });

    await page.goto("/properties");
    const card = page.locator(".property-card").filter({ hasText: "Dual-listed Loft Centro" });
    await expect(card).toBeVisible();
    await expect(card.getByText("Score Rent")).toBeVisible();
    await expect(card.getByText("Score Sale")).toBeVisible();
    await expect(card.getByText("82")).toBeVisible();
    await expect(card.getByText("48")).toBeVisible();
  });

  test("Transaction Sale shows sale score only", async ({ page }) => {
    await installCommonMocks(page);
    await page.route("**/api/properties?**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(DUAL_PAGE),
      });
    });

    await page.goto("/properties");
    const card = page.locator(".property-card").filter({ hasText: "Dual-listed Loft Centro" });
    await expect(card).toBeVisible();

    await page
      .locator("label", { hasText: "Transaction" })
      .locator("..")
      .locator("select")
      .selectOption("sale");

    await expect(card.getByText("Score Rent")).not.toBeVisible();
    await expect(card.getByText("Score Sale")).not.toBeVisible();
    await expect(card.getByText("Score", { exact: true })).toBeVisible();
    await expect(card.getByText("48")).toBeVisible();
  });
});
