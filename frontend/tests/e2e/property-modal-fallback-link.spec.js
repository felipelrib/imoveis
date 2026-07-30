// @ts-check
import { test, expect } from "@playwright/test";
import {
  installCommonMocks,
  mockPropertiesList,
  mockPropertyDetail,
  PROPERTIES_PAGE,
  SAMPLE_PROPERTY,
} from "./helpers/apiMocks.js";

/**
 * BIN-158 — the "View Original" fallback link (rendered when a property has no
 * populated `listings`) must not hardcode a QuintoAndar URL for every platform.
 * An OLX property must not get a quintoandar.com.br link; a QuintoAndar property
 * still gets its id-based detail link.
 */

const OLX_NO_LISTINGS = {
  ...SAMPLE_PROPERTY,
  id: "olx-no-listings-1",
  public_id: 91,
  title: "OLX No-Listings Flat",
  platform: "olx",
  platform_id: "123456789",
  listings: [],
};

const QA_NO_LISTINGS = {
  ...SAMPLE_PROPERTY,
  id: "qa-no-listings-1",
  public_id: 92,
  title: "QuintoAndar No-Listings Flat",
  platform: "quintoandar",
  platform_id: "895549038",
  listings: [],
};

test.describe("Property modal fallback link (BIN-158)", () => {
  test("OLX property with no listings gets no QuintoAndar fallback link", async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, {
      ...PROPERTIES_PAGE,
      properties: [OLX_NO_LISTINGS],
      total: 1,
    });
    await mockPropertyDetail(page, OLX_NO_LISTINGS);
    await page.goto("/properties");
    await page.locator("text=OLX No-Listings Flat").first().click();

    // Modal is open but the wrong-platform fallback is suppressed.
    await expect(page.getByRole("button", { name: "Close modal" })).toBeVisible();
    await expect(page.getByTestId("modal-fallback-link")).toHaveCount(0);
    await expect(page.locator('a[href*="quintoandar.com.br"]')).toHaveCount(0);
  });

  test("QuintoAndar property with no listings gets its id-based fallback link", async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, {
      ...PROPERTIES_PAGE,
      properties: [QA_NO_LISTINGS],
      total: 1,
    });
    await mockPropertyDetail(page, QA_NO_LISTINGS);
    await page.goto("/properties");
    await page.locator("text=QuintoAndar No-Listings Flat").first().click();

    const link = page.getByTestId("modal-fallback-link");
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute(
      "href",
      "https://www.quintoandar.com.br/imovel/895549038",
    );
  });
});
