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

test.describe("Property detail fallback link (BIN-158)", () => {
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

    // The panel is open but the wrong-platform fallback is suppressed.
    await expect(page.getByRole("button", { name: "Fechar painel" })).toBeVisible();
    await expect(page.getByTestId("detail-fallback-link")).toHaveCount(0);
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

    const link = page.getByTestId("detail-fallback-link");
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute(
      "href",
      "https://www.quintoandar.com.br/imovel/895549038",
    );
  });

  test("a listing link on a look-alike host is not rendered as a link", async ({ page }) => {
    // `evilolx.com.br` ends with `olx.com.br` but is not that host or a subdomain of it.
    const lookAlike = {
      ...SAMPLE_PROPERTY,
      id: "look-alike-1",
      public_id: 93,
      title: "Look-Alike Host Flat",
      listings: [
        {
          platform: "olx",
          platform_listing_id: "111",
          listing_type: "rent",
          price: 3500,
          currency: "BRL",
          url: "https://evilolx.com.br/imovel/111",
        },
        {
          platform: "zapimoveis",
          platform_listing_id: "222",
          listing_type: "rent",
          price: 3600,
          currency: "BRL",
          url: "https://www.zapimoveis.com.br/imovel/222",
        },
      ],
    };
    await installCommonMocks(page);
    await mockPropertiesList(page, { ...PROPERTIES_PAGE, properties: [lookAlike], total: 1 });
    await mockPropertyDetail(page, lookAlike);
    await page.goto("/properties");
    await page.locator("text=Look-Alike Host Flat").first().click();

    const platforms = page.getByTestId("listings-by-platform");
    await expect(platforms.getByTestId("platform-row")).toHaveCount(2);
    await expect(platforms.getByRole("link")).toHaveCount(1);
    await expect(platforms.getByRole("link")).toHaveAttribute(
      "href",
      "https://www.zapimoveis.com.br/imovel/222",
    );
    await expect(platforms.getByText("Link indisponível")).toHaveCount(1);
    await expect(page.locator('a[href*="evilolx"]')).toHaveCount(0);
  });
});
