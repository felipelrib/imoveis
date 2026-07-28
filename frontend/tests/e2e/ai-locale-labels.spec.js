// @ts-check
import { test, expect } from "@playwright/test";
import {
  installCommonMocks,
  mockAdminLocale,
  mockPropertiesList,
  mockPropertyDetail,
  PROPERTIES_PAGE,
  SAMPLE_PROPERTY,
} from "./helpers/apiMocks.js";

const VALID_KEY = "e2e-test-api-key";

const AI_PROPERTY = {
  ...SAMPLE_PROPERTY,
  id: "ai-locale-uuid-1",
  public_id: 101,
  title: "AI Locale Flat",
  deal_summary: "Slightly undervalued — good condition",
  ai_analysis: {
    visual: {
      category: "good",
      reasoning: "Well-kept interiors",
      features_detected: ["balcony"],
      issues_detected: [],
      condition_score: 0.8,
    },
    sentiment: {
      category: "highly_desirable",
      reasoning: "Great location claims",
      green_flags: ["near metro"],
      red_flags: [],
      sentiment_score: 0.9,
    },
  },
  stat_analysis: {
    category: "slightly_undervalued",
    reasoning: "",
  },
  neighbourhood_quality: {
    ...SAMPLE_PROPERTY.neighbourhood_quality,
    risk_flags: ["flood_zone", "industrial_adjacent"],
  },
};

test.describe("AI tags & score copy locale (BIN-101)", () => {
  test("PT locale localizes closed-vocab AI labels in the modal", async ({
    page,
  }) => {
    /** @type {string[]} */
    const posted = [];
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page);
    await mockAdminLocale(page, { initial: "pt-BR", posted });
    await mockPropertiesList(page, {
      ...PROPERTIES_PAGE,
      properties: [AI_PROPERTY],
      total: 1,
    });
    await mockPropertyDetail(page, AI_PROPERTY);

    await page.goto("/properties");
    await expect(page.locator("text=AI Locale Flat")).toBeVisible();
    await page.locator("text=AI Locale Flat").click();

    await expect(page.getByText("Estatístico: Ligeiramente abaixo do mercado")).toBeVisible();
    await expect(
      page.getByText("Preço um pouco abaixo da média do bairro.")
    ).toBeVisible();
    await expect(page.getByText("Condição visual: Bom")).toBeVisible();
    await expect(
      page.getByText("Claims do anúncio: Muito desejável")
    ).toBeVisible();
    await expect(page.getByText("Zona de inundação")).toBeVisible();
    await expect(page.getByText("Próximo a área industrial")).toBeVisible();
  });

  test("EN locale keeps catalog labels for closed vocab", async ({ page }) => {
    await installCommonMocks(page);
    await mockAdminLocale(page, { initial: "en" });
    await mockPropertiesList(page, {
      ...PROPERTIES_PAGE,
      properties: [AI_PROPERTY],
      total: 1,
    });
    await mockPropertyDetail(page, AI_PROPERTY);

    await page.goto("/properties");
    await page.locator("text=AI Locale Flat").click();

    await expect(
      page.getByText("Statistical: Slightly Undervalued")
    ).toBeVisible();
    await expect(
      page.getByText("Priced slightly below the neighborhood average.")
    ).toBeVisible();
    await expect(page.getByText("Visual Condition: Good")).toBeVisible();
    await expect(
      page.getByText("Ad claims (listing): Highly Desirable")
    ).toBeVisible();
    await expect(page.getByText("Flood zone")).toBeVisible();
    await expect(page.getByText("Industrial adjacent")).toBeVisible();
  });
});
