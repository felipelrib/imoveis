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
  id: "furnished-1",
  title: "Furnished Savassi Flat",
  deal_summary: "Slightly undervalued — good condition, no location alerts",
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
    await expect(page.getByRole("columnheader", { name: "Condo" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Furnished" })).toHaveCount(0);
    await expect(page.getByTestId("attr-chip-furnished")).toBeVisible();
    await expect(page.getByTestId("attr-chip-pets-ok")).toBeVisible();
    await expect(page.getByText("R$ 3.000")).toBeVisible();
    await expect(page.getByText("Deal verdict")).toBeVisible();
  });
});
