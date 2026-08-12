// @ts-check
import { test, expect } from "@playwright/test";
import { installCommonMocks, mockAdminHealth } from "./helpers/apiMocks.js";

const VALID_KEY = "e2e-test-api-key";

test.describe("Frontend credential gate", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      sessionStorage.clear();
    });
  });

  test("shows missing status and accepts a valid paste-once key", async ({ page }) => {
    /** @type {string[]} */
    const capturedKeys = [];
    await installCommonMocks(page);
    await mockAdminHealth(page, { validKey: VALID_KEY, capturedKeys });

    await page.goto("/");
    await expect(page.getByTestId("credential-gate")).toBeVisible();
    await expect(page.getByTestId("credential-status")).toHaveText("ausente");

    await page.getByTestId("credential-input").fill(VALID_KEY);
    await page.getByTestId("credential-save").click();

    await expect(page.getByTestId("credential-status")).toHaveText("definida");
    await expect(page.getByText("Credencial de API salva nesta sessão")).toBeVisible();
    await expect
      .poll(() => capturedKeys.some((k) => k === VALID_KEY))
      .toBeTruthy();
  });

  test("invalid credential shows a non-blocking error toast", async ({ page }) => {
    await installCommonMocks(page);
    await mockAdminHealth(page, { validKey: VALID_KEY });

    await page.goto("/");
    await expect(page.getByTestId("credential-gate")).toBeVisible();

    await page.getByTestId("credential-input").fill("wrong-key");
    await page.getByTestId("credential-save").click();

    await expect(page.getByText("Credencial de API inválida ou ausente")).toBeVisible();
    await expect(page.getByTestId("credential-status")).toHaveText("ausente");
    // Page remains usable (dashboard still rendered)
    await expect(page.locator("text=Status dos serviços")).toBeVisible();
  });

  test("error toast is announced and keyboard-dismissible (BIN-157)", async ({ page }) => {
    await installCommonMocks(page);
    await mockAdminHealth(page, { validKey: VALID_KEY });

    await page.goto("/");
    await page.getByTestId("credential-input").fill("wrong-key");
    await page.getByTestId("credential-save").click();

    const toast = page.getByText("Credencial de API inválida ou ausente");
    await expect(toast).toBeVisible();

    const toastContainer = page.locator('[role="status"]', { hasText: "Credencial de API inválida ou ausente" });
    await expect(toastContainer).toHaveAttribute("aria-live", "polite");

    await toastContainer.focus();
    await page.keyboard.press("Escape");
    await expect(toast).toHaveCount(0);
  });

  test("clear removes the session credential", async ({ page }) => {
    await installCommonMocks(page);
    await mockAdminHealth(page, { validKey: VALID_KEY });

    await page.goto("/");
    await page.getByTestId("credential-input").fill(VALID_KEY);
    await page.getByTestId("credential-save").click();
    await expect(page.getByTestId("credential-status")).toHaveText("definida");

    await page.getByTestId("credential-clear").click();
    await expect(page.getByTestId("credential-status")).toHaveText("ausente");
    await expect(page.getByText("Credencial de API removida")).toBeVisible();
  });
});
