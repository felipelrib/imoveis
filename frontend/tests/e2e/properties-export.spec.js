// @ts-check
import { test, expect } from "@playwright/test";
import {
  PROPERTIES_PAGE,
  installCommonMocks,
  mockPropertiesExport,
  mockPropertiesList,
} from "./helpers/apiMocks.js";

test.describe("Properties export (BIN-51)", () => {
  test("exports CSV and JSON with active filters", async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE);

    /** @type {string[]} */
    const exportUrls = [];
    await mockPropertiesExport(page, { capturedUrls: exportUrls });

    await page.goto("/properties");
    await expect(page.getByText("2BR Apartment Savassi")).toBeVisible();

    await page.getByRole("button", { name: /Advanced Filters/i }).click();
    await page
      .locator("label", { hasText: "Max price R$" })
      .locator("..")
      .locator("input")
      .fill("5000");
    await expect(
      page.locator("label", { hasText: "Max price R$" }).locator("..").locator("input")
    ).toHaveValue("5000");

    const csvDownloadPromise = page.waitForEvent("download");
    await page.getByTestId("export-csv").click();
    const csvDownload = await csvDownloadPromise;
    expect(csvDownload.suggestedFilename()).toBe("properties-export.csv");

    await expect
      .poll(() =>
        exportUrls.some(
          (u) => u.includes("format=csv") && u.includes("max_price=5000")
        )
      )
      .toBeTruthy();

    const jsonDownloadPromise = page.waitForEvent("download");
    await page.getByTestId("export-json").click();
    const jsonDownload = await jsonDownloadPromise;
    expect(jsonDownload.suggestedFilename()).toBe("properties-export.json");

    await expect
      .poll(() =>
        exportUrls.some(
          (u) => u.includes("format=json") && u.includes("max_price=5000")
        )
      )
      .toBeTruthy();
  });

  test("export errors toast without blocking the page", async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE);
    await mockPropertiesExport(page, {
      status: 500,
      body: { detail: "Export backend error" },
    });

    await page.goto("/properties");
    await expect(page.getByText("2BR Apartment Savassi")).toBeVisible();

    await page.getByTestId("export-csv").click();

    await expect(page.getByText(/Export failed: Export backend error/i)).toBeVisible();
    await expect(page.getByText("2BR Apartment Savassi")).toBeVisible();
    await expect(page.getByTestId("export-csv")).toBeEnabled();
  });
});
