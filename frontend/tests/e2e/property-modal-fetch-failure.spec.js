// @ts-check
import { test, expect } from "@playwright/test";
import {
  installCommonMocks,
  mockPropertiesList,
  mockPropertyDetail,
  PROPERTIES_PAGE,
  SAMPLE_PROPERTY,
} from "./helpers/apiMocks.js";

/**
 * BIN-153: a failed GET /properties/{id} used to leave `property` null while
 * `loading` still flipped to false, so the non-loading render branch
 * dereferenced `p.platform` etc. without optional chaining and threw —
 * caught by the app-wide ErrorBoundary, blanking the entire Properties page
 * (grid, filters, sidebar), not just the modal.
 */
async function mockFailedPropertyDetail(page, status) {
  // Seed benign responses for the sibling requests the modal also fires
  // (watchlist/favourite checks, price history) so only the detail fetch fails.
  await mockPropertyDetail(page, SAMPLE_PROPERTY);
  // Re-register the detail route last so it wins over the success stub above
  // (Playwright resolves overlapping page.route handlers last-registered-first).
  await page.route(`**/api/properties/${SAMPLE_PROPERTY.id}`, (route) => {
    const url = route.request().url();
    if (url.includes("price-history") || url.includes("by-ids")) {
      return route.fallback();
    }
    return route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify({ detail: "boom" }),
    });
  });
}

test.describe("Property modal fetch failure (BIN-153)", () => {
  test.beforeEach(async ({ page }) => {
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE);
  });

  test("shows an error state instead of crashing on 404", async ({ page }) => {
    await mockFailedPropertyDetail(page, 404);

    await page.goto("/properties");
    await expect(page.locator(`text=${SAMPLE_PROPERTY.title}`)).toBeVisible();
    await page.locator(`text=${SAMPLE_PROPERTY.title}`).click();

    await expect(page.getByTestId("property-modal-error")).toBeVisible();
    await expect(page.getByText("Couldn't load this property")).toBeVisible();

    // The rest of the page must stay intact — no top-level ErrorBoundary blank-out.
    await page.getByLabel("Close modal").click();
    await expect(page.locator(`text=${SAMPLE_PROPERTY.title}`)).toBeVisible();
  });

  test("shows an error state instead of crashing on 500", async ({ page }) => {
    await mockFailedPropertyDetail(page, 500);

    await page.goto("/properties");
    await page.locator(`text=${SAMPLE_PROPERTY.title}`).click();

    await expect(page.getByTestId("property-modal-error")).toBeVisible();
    await expect(page.getByText("Couldn't load this property")).toBeVisible();
    await expect(page.locator(`text=${SAMPLE_PROPERTY.title}`)).toBeVisible();
  });
});
