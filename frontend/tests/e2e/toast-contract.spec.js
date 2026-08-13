// @ts-check
import { test, expect } from "@playwright/test";
import {
  PROPERTIES_PAGE_FIVE,
  SAMPLE_PROPERTY,
  installCommonMocks,
  mockPropertiesExport,
  mockPropertiesList,
  mockPropertyDetail,
} from "./helpers/apiMocks.js";

/**
 * DESIGN.md toast contract (UX-DR3, v0.13-s2.6): bottom-anchored, at most two
 * stacked, never covering the filter bar. Before this story the container was
 * top-anchored and grew without a ceiling, so a burst of API errors walked a
 * column of toasts down over the Filtros bar.
 *
 * The clock is frozen (`page.clock.install()`) so the 4 s auto-dismiss cannot
 * race the geometry assertions, and so the drain check advances time on purpose
 * instead of waiting on wall clock.
 */

const COMPARE_LIMIT_TOAST = "Você pode comparar até 4 imóveis";
const EXPORT_FAILURE_TOAST = "Falha na exportação: Export backend error";
const TOAST_DURATION_MS = 4000;

/** @param {{x:number,y:number,width:number,height:number}} a @param {{x:number,y:number,width:number,height:number}} b */
function intersects(a, b) {
  return (
    a.x < b.x + b.width &&
    b.x < a.x + a.width &&
    a.y < b.y + b.height &&
    b.y < a.y + a.height
  );
}

/** Bounding box of a locator, asserted non-null so the geometry checks are real. */
async function boxOf(locator) {
  const box = await locator.boundingBox();
  expect(box, "expected an on-screen bounding box").not.toBeNull();
  return /** @type {{x:number,y:number,width:number,height:number}} */ (box);
}

test.describe("Toast contract — anchoring and stack depth", () => {
  test.beforeEach(async ({ page }) => {
    // Must precede navigation: freezes the page's timers for the whole test.
    await page.clock.install();
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE_FIVE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    await mockPropertiesExport(page, {
      status: 500,
      body: { detail: "Export backend error" },
    });
    await page.goto("/properties");
    await expect(page.locator("text=2BR Apartment Savassi")).toBeVisible();
  });

  test("a third toast evicts the oldest, leaving two bottom-anchored and clear of both bars", async ({
    page,
  }) => {
    await page.getByTestId("compare-mode-toggle").click();
    await expect(page.getByTestId("compare-mode-toggle")).toHaveAttribute("aria-pressed", "true");

    for (const id of ["1", "2", "3", "4"]) {
      await page.getByTestId(`compare-select-${id}`).check();
    }
    await expect(page.getByTestId("compare-count")).toHaveText("4 selecionados");
    await expect(page.getByTestId("compare-bar")).toBeVisible();

    // Toasts 1 and 2: each blocked 5th selection raises the compare-limit warning.
    await page.getByTestId("compare-select-5").click();
    await page.getByTestId("compare-select-5").click();
    await expect(page.getByTestId("toast")).toHaveCount(2);

    // Toast 3, deliberately a DIFFERENT message: a failing CSV export. Three
    // copies of one string could not tell "keep the newest two" apart from
    // "keep the oldest two" — this one can.
    await page.getByTestId("export-csv").click();

    // Newest wins: the export failure is present and only one warning survives.
    await expect(page.getByTestId("toast")).toHaveCount(2);
    // `toContainText`, not `toHaveText`: each toast also renders a type icon.
    // Exact-copy pinning is the compare-count assertions' job, not this one's.
    await expect(page.getByTestId("toast").nth(0)).toContainText(COMPARE_LIMIT_TOAST);
    await expect(page.getByTestId("toast").nth(1)).toContainText(EXPORT_FAILURE_TOAST);

    const viewport = page.viewportSize();
    expect(viewport).not.toBeNull();
    const { height: viewportHeight } = /** @type {{width:number,height:number}} */ (viewport);

    const container = await boxOf(page.getByTestId("toast-container"));
    // A zero-area box would make every geometry check below vacuously true.
    expect(container.height, "toast stack must be laid out to be measurable").toBeGreaterThan(0);

    // Bottom-anchored: the stack sits in the bottom half of the viewport AND its
    // lower edge rests against the bottom inset — a `top:`-anchored container
    // that happened to sit low would fail the second check. The inset is bounded
    // on both sides because `boundingBox()` still reports a box for a container
    // pushed off-screen, where a negative gap would satisfy a one-sided bound.
    expect(container.y).toBeGreaterThan(viewportHeight / 2);
    const bottomInset = viewportHeight - (container.y + container.height);
    expect(bottomInset, "toast stack must rest on the bottom inset, on-screen").toBeGreaterThanOrEqual(0);
    expect(bottomInset).toBeLessThanOrEqual(20);

    // …and it covers neither the filter bar nor the compare bar.
    const filterBar = await boxOf(page.locator(".toolbar"));
    const compareBar = await boxOf(page.getByTestId("compare-bar"));
    expect(intersects(container, filterBar), "toast stack overlaps the filter bar").toBe(false);
    expect(intersects(container, compareBar), "toast stack overlaps the compare bar").toBe(false);

    // Auto-dismiss still drains the stack once time actually moves.
    await page.clock.runFor(TOAST_DURATION_MS + 100);
    await expect(page.getByTestId("toast")).toHaveCount(0);
  });
});
