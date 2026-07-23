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
    await expect(page.getByTestId("credential-status")).toHaveText("missing");

    await page.getByTestId("credential-input").fill(VALID_KEY);
    await page.getByTestId("credential-save").click();

    await expect(page.getByTestId("credential-status")).toHaveText("set");
    await expect(page.getByText("API credential saved for this session")).toBeVisible();
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

    await expect(page.getByText("Invalid or missing API credential")).toBeVisible();
    await expect(page.getByTestId("credential-status")).toHaveText("missing");
    // Page remains usable (dashboard still rendered)
    await expect(page.locator("text=Service Status")).toBeVisible();
  });

  test("clear removes the session credential", async ({ page }) => {
    await installCommonMocks(page);
    await mockAdminHealth(page, { validKey: VALID_KEY });

    await page.goto("/");
    await page.getByTestId("credential-input").fill(VALID_KEY);
    await page.getByTestId("credential-save").click();
    await expect(page.getByTestId("credential-status")).toHaveText("set");

    await page.getByTestId("credential-clear").click();
    await expect(page.getByTestId("credential-status")).toHaveText("missing");
    await expect(page.getByText("API credential cleared")).toBeVisible();
  });
});
