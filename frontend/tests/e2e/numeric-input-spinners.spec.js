// @ts-check
import { test, expect } from "@playwright/test";
import {
  installCommonMocks,
  mockPropertiesList,
  mockPropertyDetail,
  mockPlatforms,
  mockAdminSchedule,
  PROPERTIES_PAGE,
  SAMPLE_PROPERTY,
} from "./helpers/apiMocks.js";

/**
 * BIN-155 — remaining numeric inputs must use the BIN-79 pattern
 * (type="text" + inputMode="numeric") so native spinner arrows never render.
 * CSS alone does not hide the steppers, so this asserts the input type.
 */

const VALID_KEY = "test-admin-key";

test.describe("Numeric-input spinners hidden (BIN-155)", () => {
  test("watchlist drop-alert % input has no native spinner", async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, {
      ...PROPERTIES_PAGE,
      properties: [SAMPLE_PROPERTY],
      total: 1,
    });
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    await page.goto("/properties");
    await page.locator(`text=${SAMPLE_PROPERTY.title}`).first().click();

    const dropPct = page.getByTestId("modal-drop-pct-input");
    await expect(dropPct).toBeVisible();
    await expect(dropPct).toHaveAttribute("type", "text");
    await expect(dropPct).toHaveAttribute("inputMode", "numeric");

    // Non-digit keystrokes are stripped, preserving numeric-only content.
    await dropPct.fill("");
    await dropPct.type("1a2");
    await expect(dropPct).toHaveValue("12");
  });

  test("schedule-interval edit input has no native spinner", async ({ page }) => {
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page);
    await mockPlatforms(page);
    await mockAdminSchedule(page); // one olx schedule row

    await page.goto("/scraper");
    await page.getByRole("button", { name: "Edit" }).first().click();

    const interval = page.getByTestId("schedule-interval-input");
    await expect(interval).toBeVisible();
    await expect(interval).toHaveAttribute("type", "text");
    await expect(interval).toHaveAttribute("inputMode", "numeric");

    await interval.fill("");
    await interval.type("3x0");
    await expect(interval).toHaveValue("30");
  });
});
