// @ts-check
import { test, expect } from "@playwright/test";
import {
  installCommonMocks,
  mockPropertiesList,
  mockPropertyDetail,
  PROPERTIES_PAGE,
  SAMPLE_PROPERTY,
} from "./helpers/apiMocks.js";

const FURNISHED_PROPERTY = {
  ...SAMPLE_PROPERTY,
  id: "furnished-uuid-1",
  public_id: 42,
  title: "Furnished Savassi Flat",
  deal_summary: "Slightly undervalued — good condition, no listing claim alerts",
  listings: [
    {
      platform: "olx",
      platform_listing_id: "123456789",
      listing_type: "rent",
      price: 3650,
      base_price: 3000,
      condo_fee: 495,
      iptu: 165,
      currency: "BRL",
      url: "https://www.olx.com.br/imovel/aluguel/apartamentos/mg/detalhes/123456789",
      is_furnished: true,
      accepts_pets: true,
      fees_bundled: false,
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
      platform: "quintoandar",
      platform_listing_id: "895549038",
      listing_type: "rent",
      price: 929,
      base_price: 750,
      condo_fee: 179,
      iptu: null,
      currency: "BRL",
      url: "https://www.quintoandar.com.br/imovel/895549038",
      is_furnished: false,
      accepts_pets: null,
      fees_bundled: true,
    },
  ],
};

test.describe("Property modal listings (BIN-65/66/67)", () => {
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

  test("shows furnished/pets attrs and base price outside fee booleans", async ({ page }) => {
    await page.locator("text=Furnished Savassi Flat").click();
    await expect(page.getByTestId("listings-by-platform")).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Base" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Condomínio" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Mobiliado" })).toHaveCount(0);
    await expect(page.getByTestId("attr-chip-furnished")).toBeVisible();
    await expect(page.getByTestId("attr-chip-pets-ok")).toBeVisible();
    await expect(page.getByText("R$ 3.000")).toBeVisible();
    await expect(page.getByText("Veredito do negócio")).toBeVisible();
  });
});

test.describe("Property modal bundled fees (BIN-114)", () => {
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

  test("flags bundled condo+IPTU and leaves IPTU as em-dash", async ({ page }) => {
    await page.locator("text=Bundled Fees Alvorada Flat").click();
    const listings = page.getByTestId("listings-by-platform");
    await expect(listings).toBeVisible();
    await expect(listings.getByText("Taxas inclusas")).toBeVisible();
    const condoCell = page.getByTestId("fee-condo-bundled");
    await expect(condoCell).toBeVisible();
    await expect(condoCell).toContainText("R$ 179");
    await expect(condoCell).toContainText("Cond.+IPTU");
    const iptuCell = page.getByTestId("fee-iptu-bundled");
    await expect(iptuCell).toBeVisible();
    await expect(iptuCell).toHaveText("—");
    await expect(iptuCell).toHaveAttribute(
      "title",
      "IPTU incluído no valor Cond.+IPTU — a plataforma não publicou valores separados",
    );
  });
});
