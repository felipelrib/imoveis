// @ts-check
import { test, expect } from "@playwright/test";
import {
  PROPERTIES_PAGE_FIVE,
  SAMPLE_PROPERTY,
  installCommonMocks,
  mockPropertiesList,
  mockPropertyDetail,
} from "./helpers/apiMocks.js";

test.describe("Properties multi-select for comparison", () => {
  test.beforeEach(async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE_FIVE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    await page.goto("/properties");
    await expect(page.locator("text=2BR Apartment Savassi")).toBeVisible();
  });

  test("enables Compare at 2 selections and keeps bar visible at 1", async ({ page }) => {
    await expect(page.getByTestId("compare-bar")).toHaveCount(0);

    await page.getByTestId("compare-select-1").check();
    await expect(page.getByTestId("compare-bar")).toBeVisible();
    await expect(page.getByTestId("compare-count")).toHaveText("1 selected");
    await expect(page.getByTestId("compare-open")).toBeDisabled();

    await page.getByTestId("compare-select-2").check();
    await expect(page.getByTestId("compare-count")).toHaveText("2 selected");
    await expect(page.getByTestId("compare-open")).toBeEnabled();
  });

  test("blocks a 5th selection with a warning toast", async ({ page }) => {
    for (const id of ["1", "2", "3", "4"]) {
      await page.getByTestId(`compare-select-${id}`).check();
    }
    await expect(page.getByTestId("compare-count")).toHaveText("4 selected");
    await expect(page.getByTestId("compare-open")).toBeEnabled();

    await page.getByTestId("compare-select-5").check();
    await expect(page.getByText("You can compare up to 4 properties")).toBeVisible();
    await expect(page.getByTestId("compare-count")).toHaveText("4 selected");
    await expect(page.getByTestId("compare-select-5")).not.toBeChecked();
  });

  test("Clear returns to normal browse", async ({ page }) => {
    await page.getByTestId("compare-select-1").check();
    await page.getByTestId("compare-select-2").check();
    await expect(page.getByTestId("compare-bar")).toBeVisible();

    await page.getByTestId("compare-clear").click();
    await expect(page.getByTestId("compare-bar")).toHaveCount(0);
    await expect(page.getByTestId("compare-select-1")).not.toBeChecked();
    await expect(page.getByTestId("compare-select-2")).not.toBeChecked();
  });

  test("checkbox click does not open the property modal", async ({ page }) => {
    await page.getByTestId("compare-select-1").check();
    await expect(page.locator(".modal")).toHaveCount(0);
    await expect(page.getByTestId("compare-bar")).toBeVisible();
  });
});
