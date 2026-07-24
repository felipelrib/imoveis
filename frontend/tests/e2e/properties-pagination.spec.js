// @ts-check
import { test, expect } from "@playwright/test";
import {
  SAMPLE_PROPERTY,
  installCommonMocks,
} from "./helpers/apiMocks.js";

const PAGE_ONE_TITLE = "Page One Listing Savassi";
const PAGE_TWO_TITLE = "Page Two Listing Lourdes";

const PAGE1_BODY = {
  properties: [{ ...SAMPLE_PROPERTY, id: "1", title: PAGE_ONE_TITLE }],
  page: 1,
  page_size: 24,
  total: 48,
  pages: 2,
};

const PAGE2_BODY = {
  properties: [
    {
      ...SAMPLE_PROPERTY,
      id: "25",
      title: PAGE_TWO_TITLE,
      address: "Rua da Bahia, 100, Lourdes",
      neighborhood_name: "Lourdes",
    },
  ],
  page: 2,
  page_size: 24,
  total: 48,
  pages: 2,
};

/**
 * Page-aware /api/properties mock so returning to page 1 is observable.
 * @param {import('@playwright/test').Page} page
 * @param {{ requests?: number[] }} [opts]
 */
async function mockPagedPropertiesList(page, opts = {}) {
  const requests = opts.requests ?? [];
  await page.route("**/api/properties?**", async (route) => {
    const url = new URL(route.request().url());
    const pageNum = Number(url.searchParams.get("page") || "1");
    requests.push(pageNum);
    const body = pageNum <= 1 ? PAGE1_BODY : PAGE2_BODY;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

test.describe("Properties pagination (BIN-57)", () => {
  test("reloads page 1 after visiting another page", async ({ page }) => {
    /** @type {number[]} */
    const pageRequests = [];
    await installCommonMocks(page);
    await mockPagedPropertiesList(page, { requests: pageRequests });

    await page.goto("/properties");
    await expect(page.getByText(PAGE_ONE_TITLE)).toBeVisible();

    await page.locator(".page-btn", { hasText: /^2$/ }).click();
    await expect(page.getByText(PAGE_TWO_TITLE)).toBeVisible();
    await expect(page.getByText(PAGE_ONE_TITLE)).toHaveCount(0);

    await page.locator(".page-btn", { hasText: /^1$/ }).click();
    await expect(page.getByText(PAGE_ONE_TITLE)).toBeVisible();
    await expect(page.getByText(PAGE_TWO_TITLE)).toHaveCount(0);

    await expect
      .poll(() => pageRequests.filter((p) => p === 1).length)
      .toBeGreaterThanOrEqual(2);
  });
});
