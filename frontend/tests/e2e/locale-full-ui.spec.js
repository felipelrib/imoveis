// @ts-check
import { test, expect } from "@playwright/test";
import {
  installCommonMocks,
  mockAdminLocale,
  mockPropertiesList,
  mockPropertyDetail,
  SAMPLE_PROPERTY,
  PROPERTIES_PAGE,
} from "./helpers/apiMocks.js";

const VALID_KEY = "e2e-test-api-key";

test.describe("Full UI string catalog (BIN-99)", () => {
  test("pt-BR chrome on Dashboard, Properties, and property modal", async ({
    page,
  }) => {
    /** @type {string[]} */
    const posted = [];
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page, { locale: false });
    await mockAdminLocale(page, { initial: "pt-BR", posted });
    await mockPropertiesList(page, PROPERTIES_PAGE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Painel" })).toBeVisible();
    await expect(page.getByText("Total de imóveis", { exact: true })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "pt-BR");

    await page.getByRole("link", { name: "Imóveis" }).click();
    await expect(page.getByRole("heading", { name: "Imóveis" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Filtros avançados/i })
    ).toBeVisible();

    await page.locator("text=2BR Apartment Savassi").click();
    await expect(page.locator(".modal")).toBeVisible();
    await expect(page.getByTestId("neighbourhood-quality-section")).toContainText(
      "Qualidade do bairro"
    );
    await expect(
      page.getByRole("button", { name: "Fechar modal" })
    ).toBeVisible();
  });
});
