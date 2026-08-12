// @ts-check
import { test, expect } from "@playwright/test";
import {
  installCommonMocks,
  mockPropertiesList,
  mockPropertyDetail,
  PROPERTIES_PAGE,
  SAMPLE_PROPERTY,
} from "./helpers/apiMocks.js";

const QUALITY_PROPERTY = {
  ...SAMPLE_PROPERTY,
  id: "nhood-uuid-1",
  public_id: 94,
  title: "Nhood Quality Flat",
  deal_summary: "Slightly undervalued — good condition, neighbourhood quality 73%, no listing claim alerts",
  ai_analysis: {
    visual: {
      category: "Good",
      reasoning: "Well-kept interiors",
      features_detected: ["balcony"],
      issues_detected: [],
      condition_score: 0.8,
    },
    sentiment: {
      category: "Average",
      reasoning: "Seller emphasises lifestyle amenities",
      green_flags: ["near metro"],
      red_flags: ["noisy avenue"],
      sentiment_score: 0.6,
    },
  },
  stat_analysis: {
    category: "Slightly Undervalued",
    reasoning: "Below neighbourhood median",
  },
};

test.describe("Neighbourhood quality vs ad claims labels (BIN-94)", () => {
  test.beforeEach(async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, {
      ...PROPERTIES_PAGE,
      properties: [QUALITY_PROPERTY],
      total: 1,
    });
    await mockPropertyDetail(page, QUALITY_PROPERTY);
    await page.goto("/properties");
    await expect(page.locator("text=Nhood Quality Flat")).toBeVisible();
  });

  test("card shows nhood score and ad claims framing", async ({ page }) => {
    await expect(page.getByTestId("card-nhood-score")).toBeVisible();
    await expect(page.getByTestId("card-ad-claims")).toContainText("Claims do anúncio");
    await expect(page.getByTestId("card-ad-claims")).toContainText("near metro");
  });

  test("modal separates neighbourhood quality from ad claims", async ({ page }) => {
    await page.locator("text=Nhood Quality Flat").click();
    await expect(page.getByTestId("neighbourhood-quality-section")).toBeVisible();
    await expect(page.getByTestId("neighbourhood-quality-section")).toContainText(
      "Qualidade do bairro"
    );
    await expect(page.getByTestId("neighbourhood-quality-section")).toContainText("Inundação");
    await expect(page.getByTestId("ad-claims-section")).toBeVisible();
    await expect(page.getByTestId("ad-claims-section")).toContainText("Claims do anúncio");
    await expect(page.getByText("Location Sentiment")).toHaveCount(0);
    await expect(page.getByText("Alegações do anúncio (pontos positivos)")).toBeVisible();
    await expect(page.getByText("Alegações do anúncio (pontos de atenção)")).toBeVisible();
  });
});
