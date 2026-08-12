// @ts-check
/**
 * BIN-125 — prefer API primary_listing for decisioning price over local groupListings.
 */
import { test, expect } from "@playwright/test";
import {
  bestListingForType,
  decisioningPrice,
  groupListings,
  isPrimaryListingRow,
} from "../../src/utils/primaryListing.js";
import {
  installCommonMocks,
  mockPropertiesList,
  mockPropertyDetail,
  PROPERTIES_PAGE,
  SAMPLE_PROPERTY,
} from "./helpers/apiMocks.js";

/** Stale top-level price must lose to primary_listing on card + modal. */
const STALE_PRICE_PROPERTY = {
  ...SAMPLE_PROPERTY,
  id: "stale-price-uuid-1",
  public_id: 125,
  title: "Primary Listing Prefer Flat",
  price: 9999,
  primary_listing: {
    platform: "olx",
    platform_listing_id: "125-rent",
    listing_type: "rent",
    price: 3500,
    currency: "BRL",
    url: "https://www.olx.com.br/imovel/aluguel/apartamentos/mg/detalhes/125-rent",
  },
  listings: [
    {
      platform: "olx",
      platform_listing_id: "125-rent",
      listing_type: "rent",
      price: 3500,
      currency: "BRL",
      url: "https://www.olx.com.br/imovel/aluguel/apartamentos/mg/detalhes/125-rent",
    },
    {
      platform: "quintoandar",
      platform_listing_id: "125-sale",
      listing_type: "sale",
      price: 890000,
      currency: "BRL",
      url: "https://www.quintoandar.com.br/imovel/125-sale",
    },
  ],
};

test.describe("primaryListing helpers (BIN-125)", () => {
  test("decisioningPrice prefers primary_listing over top-level price", () => {
    expect(decisioningPrice({ price: 9999, primary_listing: { price: 3500 } })).toBe(3500);
    expect(decisioningPrice({ price: 4000 })).toBe(4000);
    expect(decisioningPrice({})).toBeNull();
  });

  test("bestListingForType uses primary when type matches", () => {
    const property = {
      primary_listing: { listing_type: "rent", platform: "olx", price: 3500 },
    };
    const grouped = groupListings([
      { listing_type: "rent", platform: "quintoandar", price: 3400 },
      { listing_type: "rent", platform: "olx", price: 3500 },
      { listing_type: "sale", platform: "olx", price: 500000 },
    ]);
    expect(bestListingForType(property, "rent", grouped)).toEqual(property.primary_listing);
    expect(bestListingForType(property, "sale", grouped)?.price).toBe(500000);
    expect(isPrimaryListingRow(property.primary_listing, property)).toBe(true);
    expect(isPrimaryListingRow(grouped.sale[0], property)).toBe(false);
  });
});

test.describe("Grid/modal prefer primary_listing (BIN-125)", () => {
  test.beforeEach(async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, {
      ...PROPERTIES_PAGE,
      properties: [STALE_PRICE_PROPERTY],
      total: 1,
    });
    await mockPropertyDetail(page, STALE_PRICE_PROPERTY);
    await page.goto("/properties");
    await expect(page.getByText("Primary Listing Prefer Flat")).toBeVisible();
  });

  test("card and modal show primary price, not stale top-level price", async ({ page }) => {
    const card = page.locator(".property-card").filter({ hasText: "Primary Listing Prefer Flat" });
    await expect(card.getByTestId("card-price-rows")).toContainText("R$ 3.500");
    await expect(card.getByTestId("card-price-rows")).not.toContainText("9.999");

    await card.click();
    const modal = page.locator(".modal");
    await expect(modal).toBeVisible();
    await expect(modal.locator(".modal-header")).toContainText("R$ 3.500");
    await expect(modal.locator(".modal-header")).not.toContainText("9.999");
    await expect(page.getByTestId("listings-by-platform")).toBeVisible();
    await expect(page.getByTestId("listings-by-platform")).toContainText("R$ 3.500");
  });
});
