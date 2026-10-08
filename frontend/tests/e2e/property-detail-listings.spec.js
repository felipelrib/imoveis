// @ts-check
import { test, expect } from "@playwright/test";
import {
  installCommonMocks,
  mockPropertiesList,
  mockPropertyDetail,
  PROPERTIES_PAGE,
  SAMPLE_PROPERTY,
} from "./helpers/apiMocks.js";

// Cost comes from the stored `cost` object of each Listing (v0.14-s1.2), never
// from the legacy `base_price` / `condo_fee` / `iptu` fields. The fixtures
// carry no legacy fee field at all, so a panel that read them would show
// nothing where these tests expect a figure.

const FURNISHED_PROPERTY = {
  ...SAMPLE_PROPERTY,
  id: "furnished-uuid-1",
  public_id: 42,
  title: "Furnished Savassi Flat",
  deal_summary: "Slightly undervalued — good condition, no listing claim alerts",
  listings: [
    {
      id: "listing-furnished-1",
      platform: "olx",
      platform_listing_id: "123456789",
      listing_type: "rent",
      price: 3660,
      currency: "BRL",
      url: "https://www.olx.com.br/imovel/aluguel/apartamentos/mg/detalhes/123456789",
      is_furnished: true,
      accepts_pets: true,
      cost: {
        rent_monthly: 3000,
        rent_state: "known",
        condo_fee_monthly: 495,
        condo_fee_state: "known",
        iptu_monthly: 165,
        iptu_state: "known",
        iptu_periodicity_source: "monthly",
        fees_bundled: false,
        total_monthly_cost: 3660,
        total_state: "complete",
        cost_complete: true,
      },
    },
  ],
};

const BUNDLED_FEES_PROPERTY = {
  ...SAMPLE_PROPERTY,
  id: "bundled-fees-uuid-1",
  public_id: 43,
  title: "Bundled Fees Alvorada Flat",
  deal_summary: "Fair value — condition unknown",
  listings: [
    {
      id: "listing-bundled-1",
      platform: "quintoandar",
      platform_listing_id: "895549038",
      listing_type: "rent",
      price: 929,
      currency: "BRL",
      url: "https://www.quintoandar.com.br/imovel/895549038",
      is_furnished: false,
      accepts_pets: null,
      cost: {
        rent_monthly: 750,
        rent_state: "known",
        condo_fee_monthly: 179,
        condo_fee_state: "bundled",
        iptu_monthly: null,
        iptu_state: "bundled",
        iptu_periodicity_source: "unknown",
        fees_bundled: true,
        total_monthly_cost: 929,
        total_state: "bundled",
        cost_complete: true,
      },
    },
  ],
};

test.describe("Property detail listings (BIN-65/66/67)", () => {
  test.beforeEach(async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, {
      ...PROPERTIES_PAGE,
      properties: [FURNISHED_PROPERTY],
      total: 1,
    });
    await mockPropertyDetail(page, FURNISHED_PROPERTY);
    await page.goto("/properties");
    await expect(page.locator("text=Furnished Savassi Flat")).toBeVisible();
  });

  test("shows furnished/pets attrs, the platform row and the itemized cost", async ({ page }) => {
    await page.locator("text=Furnished Savassi Flat").click();

    const platforms = page.getByTestId("listings-by-platform");
    await expect(platforms).toBeVisible();
    await expect(platforms).toContainText("OLX");
    await expect(platforms).toContainText("R$ 3.660");
    await expect(platforms.getByRole("link", { name: "Abrir na plataforma" })).toHaveAttribute(
      "href",
      "https://www.olx.com.br/imovel/aluguel/apartamentos/mg/detalhes/123456789",
    );
    await expect(page.getByTestId("attr-chip-furnished")).toBeVisible();
    await expect(page.getByTestId("attr-chip-pets-ok")).toBeVisible();

    // The legacy Base / Condo / IPTU table is gone; cost is its own section.
    await expect(page.getByRole("columnheader")).toHaveCount(0);
    const cost = page.getByTestId("detail-section-cost");
    await expect(cost.getByTestId("cost-row-rent")).toContainText("R$ 3.000");
    await expect(cost.getByTestId("cost-row-condo")).toContainText("R$ 495");
    await expect(cost.getByTestId("cost-row-iptu")).toContainText("R$ 165");
    await expect(cost.getByTestId("cost-row-total")).toContainText("R$ 3.660");

    await expect(page.getByText("Veredito do negócio")).toBeVisible();
  });
});

test.describe("Property detail bundled fees (BIN-114)", () => {
  test.beforeEach(async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, {
      ...PROPERTIES_PAGE,
      properties: [BUNDLED_FEES_PROPERTY],
      total: 1,
    });
    await mockPropertyDetail(page, BUNDLED_FEES_PROPERTY);
    await page.goto("/properties");
    await expect(page.locator("text=Bundled Fees Alvorada Flat")).toBeVisible();
  });

  test("shows the combined condo + IPTU figure as one labelled row", async ({ page }) => {
    await page.locator("text=Bundled Fees Alvorada Flat").click();
    const cost = page.getByTestId("detail-section-cost");
    await expect(cost).toBeVisible();

    const bundled = cost.getByTestId("cost-row-condoIptuBundled");
    await expect(bundled).toContainText("Condomínio + IPTU");
    await expect(bundled.getByTestId("cost-row-value")).toHaveText("R$ 179");
    await expect(bundled.getByTestId("cost-row-note")).toHaveText(
      "valor único publicado pela plataforma",
    );

    // One row for the combined figure: no separate condo or IPTU row.
    await expect(cost.getByTestId("cost-row-condo")).toHaveCount(0);
    await expect(cost.getByTestId("cost-row-iptu")).toHaveCount(0);
    await expect(cost.getByTestId("cost-row-rent").getByTestId("cost-row-value")).toHaveText("R$ 750");
    await expect(cost.getByTestId("cost-row-total").getByTestId("cost-row-value")).toHaveText("R$ 929");
  });
});
