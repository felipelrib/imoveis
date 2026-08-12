// @ts-check
import { test, expect } from "@playwright/test";
import {
  installCommonMocks,
  mockAdminLocale,
} from "./helpers/apiMocks.js";

const VALID_KEY = "e2e-test-api-key";

test.describe("Locale foundation (BIN-98)", () => {
  test("language switcher updates chrome and persists across reload", async ({
    page,
  }) => {
    /** @type {string[]} */
    const posted = [];
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page);
    await mockAdminLocale(page, { initial: "en", posted });

    await page.goto("/");
    await expect(page.getByTestId("locale-switcher")).toBeVisible();
    await expect(page.getByTestId("locale-select")).toHaveValue("en");
    await expect(page.getByText("Navigation", { exact: true })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");

    await page.getByTestId("locale-select").selectOption("pt-BR");
    await expect
      .poll(() => posted.includes("pt-BR"))
      .toBeTruthy();
    await expect(page.getByText("Navegação", { exact: true })).toBeVisible();
    await expect(page.getByTestId("locale-select")).toHaveValue("pt-BR");
    await expect(page.locator("html")).toHaveAttribute("lang", "pt-BR");

    await page.reload();
    await expect(page.getByTestId("locale-select")).toHaveValue("pt-BR");
    await expect(page.getByText("Navegação", { exact: true })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "pt-BR");
  });

  test("without API key, switcher warns instead of posting", async ({ page }) => {
    await page.addInitScript(() => {
      sessionStorage.clear();
    });
    await installCommonMocks(page);
    /** @type {string[]} */
    const posted = [];
    await mockAdminLocale(page, { posted });

    await page.goto("/");
    // No credential: the app renders the pt-BR default, so switch to `en` to
    // exercise the same "cannot persist" path.
    await page.getByTestId("locale-select").selectOption("en");
    await expect(
      page.getByText("Defina uma credencial de API para persistir o idioma")
    ).toBeVisible();
    expect(posted).toEqual([]);
  });
});
