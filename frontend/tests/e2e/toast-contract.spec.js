// @ts-check
import { test, expect } from "@playwright/test";
import {
  PROPERTIES_PAGE_FIVE,
  SAMPLE_PRICE_HISTORY,
  SAMPLE_PROPERTY,
  installCommonMocks,
  mockPriceHistoryByIds,
  mockPropertiesByIds,
  mockPropertiesExport,
  mockPropertiesList,
  mockPropertyDetail,
} from "./helpers/apiMocks.js";

/**
 * DESIGN.md toast contract (UX-DR3, v0.13-s2.6): bottom-anchored, at most two
 * stacked, never covering the filter bar. Before that story the container was
 * top-anchored and grew without a ceiling, so a burst of API errors walked a
 * column of toasts down over the Filtros bar.
 *
 * Shared bottom strip (v0.14-s1.11, closes v0.13-fu13): the toast stack and the
 * compare bar are both bottom-anchored. While the compare bar is on screen the
 * stack starts above it, at every width; otherwise it rests on the 16px bottom
 * inset. The rule is CSS (`:root:has(.compare-bar)` in index.css) and the bar's
 * height is a token, so these cases measure real boxes: the gap pins the
 * offset, and the bar's content must fit inside the bar, which pins the token
 * against the content it was measured from.
 *
 * The clock is frozen (`page.clock.install()`) so the 4 s auto-dismiss cannot
 * race the geometry assertions, and so the drain check advances time on purpose
 * instead of waiting on wall clock.
 */

const COMPARE_LIMIT_TOAST = "Você pode comparar até 4 imóveis";
const EXPORT_FAILURE_TOAST = "Falha na exportação: Export backend error";
const TOAST_DURATION_MS = 4000;

/** `--toast-stack-bottom` with no compare bar, and the stack's right offset. */
const STACK_INSET_PX = 16;
/** The space the rule leaves between the compare bar and the stack. */
const BAR_GAP_PX = 8;
/** Sub-pixel layout rounding allowed on either side of an exact distance. */
const TOLERANCE_PX = 1;

/** @typedef {{x:number,y:number,width:number,height:number}} Box */

/** @param {Box} a @param {Box} b */
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
  return /** @type {Box} */ (box);
}

/** @param {import("@playwright/test").Page} page */
function viewportOf(page) {
  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();
  return /** @type {{width:number,height:number}} */ (viewport);
}

/**
 * The stack's box, asserted laid out and inside the viewport horizontally.
 * @param {import("@playwright/test").Page} page
 */
async function stackBox(page) {
  const stack = await boxOf(page.getByTestId("toast-container"));
  // A zero-area box would make every geometry check vacuously true.
  expect(stack.height, "toast stack must be laid out to be measurable").toBeGreaterThan(0);
  expect(stack.x, "toast stack must not leave the viewport on the left").toBeGreaterThanOrEqual(0);
  return stack;
}

/**
 * No compare bar on screen: the stack rests on the bottom inset, right-aligned.
 * Bounded on both sides because `boundingBox()` still reports a box for a
 * container pushed off-screen, where a negative gap would pass a one-sided bound.
 * @param {import("@playwright/test").Page} page
 */
async function expectStackOnTheBottomInset(page) {
  await expect(page.getByTestId("compare-bar")).toHaveCount(0);
  const { width, height } = viewportOf(page);
  const stack = await stackBox(page);
  const bottomInset = height - (stack.y + stack.height);
  const rightInset = width - (stack.x + stack.width);
  expect(Math.abs(bottomInset - STACK_INSET_PX), `bottom inset was ${bottomInset}px`).toBeLessThanOrEqual(TOLERANCE_PX);
  expect(Math.abs(rightInset - STACK_INSET_PX), `right inset was ${rightInset}px`).toBeLessThanOrEqual(TOLERANCE_PX);
}

/**
 * Compare bar on screen: the stack's lower edge sits above the bar's top edge,
 * no toast touches the bar, and the bar itself is inside the viewport.
 * @param {import("@playwright/test").Page} page
 */
async function expectStackAboveTheCompareBar(page) {
  const { width, height } = viewportOf(page);
  const bar = await boxOf(page.getByTestId("compare-bar"));
  const stack = await stackBox(page);

  expect(bar.x, "compare bar must not leave the viewport on the left").toBeGreaterThanOrEqual(0);
  expect(bar.x + bar.width, "compare bar must not leave the viewport on the right").toBeLessThanOrEqual(width);
  expect(bar.y + bar.height, "compare bar must be on screen").toBeLessThanOrEqual(height);

  // The bar's height is fixed by a token; content that outgrew it would spill
  // into the gap under the toasts while the gap itself still measured 8px.
  for (const child of ["compare-count", "compare-clear", "compare-open"]) {
    const box = await boxOf(page.getByTestId(child));
    expect(box.x, `${child} leaves the bar on the left`).toBeGreaterThanOrEqual(bar.x);
    expect(box.x + box.width, `${child} leaves the bar on the right`).toBeLessThanOrEqual(bar.x + bar.width);
    expect(box.y, `${child} leaves the bar at the top`).toBeGreaterThanOrEqual(bar.y);
    expect(box.y + box.height, `${child} leaves the bar at the bottom`).toBeLessThanOrEqual(bar.y + bar.height);
  }

  const gap = bar.y - (stack.y + stack.height);
  expect(Math.abs(gap - BAR_GAP_PX), `gap between the stack and the bar was ${gap}px`).toBeLessThanOrEqual(TOLERANCE_PX);
  expect(intersects(stack, bar), "toast stack overlaps the compare bar").toBe(false);

  const toasts = page.getByTestId("toast");
  for (let i = 0; i < (await toasts.count()); i += 1) {
    const toast = await boxOf(toasts.nth(i));
    expect(intersects(toast, bar), `toast ${i} overlaps the compare bar`).toBe(false);
    expect(toast.y, `toast ${i} must be on screen`).toBeGreaterThanOrEqual(0);
  }
}

/**
 * Compare mode with four selected and two compare-limit warnings on screen.
 * @param {import("@playwright/test").Page} page
 */
async function raiseTwoToastsOverTheCompareBar(page) {
  await page.getByTestId("compare-mode-toggle").click();
  await expect(page.getByTestId("compare-mode-toggle")).toHaveAttribute("aria-pressed", "true");

  for (const id of ["1", "2", "3", "4"]) {
    await page.getByTestId(`compare-select-${id}`).check();
  }
  await expect(page.getByTestId("compare-count")).toHaveText("4 selecionados");
  await expect(page.getByTestId("compare-bar")).toBeVisible();

  // Each blocked 5th selection raises the compare-limit warning.
  await page.getByTestId("compare-select-5").click();
  await page.getByTestId("compare-select-5").click();
  await expect(page.getByTestId("toast")).toHaveCount(2);
}

test.describe("Toast contract — anchoring, stack depth and the shared bottom strip", () => {
  test.beforeEach(async ({ page }) => {
    // Must precede navigation: freezes the page's timers for the whole test.
    await page.clock.install();
    await installCommonMocks(page);
    await mockPropertiesList(page, PROPERTIES_PAGE_FIVE);
    await mockPropertyDetail(page, SAMPLE_PROPERTY);
    await mockPropertiesByIds(page, PROPERTIES_PAGE_FIVE.properties);
    await mockPriceHistoryByIds(page, { "1": SAMPLE_PRICE_HISTORY, "2": SAMPLE_PRICE_HISTORY });
    await mockPropertiesExport(page, {
      status: 500,
      body: { detail: "Export backend error" },
    });
    await page.goto("/properties");
    await expect(page.locator("text=2BR Apartment Savassi")).toBeVisible();
  });

  test("a third toast evicts the oldest, leaving two above the compare bar and clear of the filter bar", async ({
    page,
  }) => {
    await raiseTwoToastsOverTheCompareBar(page);

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

    // Bottom-anchored: with the compare bar on screen the stack starts right
    // above it — a `top:`-anchored container that happened to sit low would
    // miss the exact gap — and it stays in the bottom half of the viewport.
    const { height } = viewportOf(page);
    const container = await stackBox(page);
    expect(container.y).toBeGreaterThan(height / 2);
    await expectStackAboveTheCompareBar(page);

    // …and it does not cover the filter bar.
    const filterBar = await boxOf(page.locator(".toolbar"));
    expect(intersects(container, filterBar), "toast stack overlaps the filter bar").toBe(false);

    // Auto-dismiss still drains the stack once time actually moves.
    await page.clock.runFor(TOAST_DURATION_MS + 100);
    await expect(page.getByTestId("toast")).toHaveCount(0);
  });

  // 1280 is the suite default; 900 and 640 are the widths where the centred bar
  // and the right-anchored stack used to meet (v0.13-fu13).
  for (const viewport of [
    { width: 1280, height: 720 },
    { width: 900, height: 720 },
    { width: 640, height: 720 },
  ]) {
    test.describe(`at ${viewport.width}×${viewport.height}`, () => {
      test.use({ viewport });

      test("without a compare bar the stack rests on the bottom inset, right-aligned", async ({ page }) => {
        await page.getByTestId("export-csv").click();
        await expect(page.getByTestId("toast")).toHaveCount(1);
        await expect(page.getByTestId("toast")).toContainText(EXPORT_FAILURE_TOAST);
        await expectStackOnTheBottomInset(page);
      });

      test("the stack sits above the compare bar and both bar buttons take their clicks", async ({ page }) => {
        await raiseTwoToastsOverTheCompareBar(page);
        await expectStackAboveTheCompareBar(page);

        // A real click: Playwright refuses it when another element — a toast —
        // would receive the event instead. The toasts are still up (frozen clock).
        await page.getByTestId("compare-open").click();
        await expect(page.getByTestId("compare-view")).toBeVisible();
        await expect(page.getByTestId("toast")).toHaveCount(2);
        // Compare view open: the bar is unmounted, so the stack is back down.
        await expectStackOnTheBottomInset(page);

        await page.getByTestId("compare-exit").click();
        await expect(page.getByTestId("compare-view")).toHaveCount(0);
        await expect(page.getByTestId("compare-bar")).toBeVisible();
        await expect(page.getByTestId("toast")).toHaveCount(2);
        await expectStackAboveTheCompareBar(page);

        await page.getByTestId("compare-clear").click();
        await expect(page.getByTestId("compare-bar")).toHaveCount(0);
        await expect(page.getByTestId("toast")).toHaveCount(2);
        await expectStackOnTheBottomInset(page);
      });
    });
  }

  // 900: the panel takes the whole content width. 1000: it is a side panel
  // over a scrim, in the band below 1100px the follow-up named.
  for (const width of [900, 1000]) {
    test.describe(`at ${width}×720 with the detail panel open`, () => {
      test.use({ viewport: { width, height: 720 } });

      test("the rule holds over the panel and the bar stays clickable", async ({ page }) => {
        await raiseTwoToastsOverTheCompareBar(page);

        // The panel runs under the bar at both widths.
        await page.locator("text=2BR Apartment Savassi").first().click();
        const panel = page.getByTestId("detail-panel");
        await expect(panel).toBeVisible();
        await expect(page.getByTestId("compare-bar")).toBeVisible();
        await expect(page.getByTestId("toast")).toHaveCount(2);

        const panelBox = await boxOf(panel);
        const bar = await boxOf(page.getByTestId("compare-bar"));
        expect(intersects(panelBox, bar), "the panel is expected to run under the compare bar").toBe(true);
        await expectStackAboveTheCompareBar(page);

        await page.getByTestId("compare-clear").click();
        await expect(page.getByTestId("compare-bar")).toHaveCount(0);
        await expect(panel).toBeVisible();
        await expect(page.getByTestId("toast")).toHaveCount(2);
        await expectStackOnTheBottomInset(page);
      });
    });
  }

  test.describe("at 900×720 with the save-search dialog open", () => {
    test.use({ viewport: { width: 900, height: 720 } });

    test("the stack stays above the bar and clear of the dialog, which keeps its clicks", async ({ page }) => {
      await raiseTwoToastsOverTheCompareBar(page);

      await page.getByRole("button", { name: /Salvar filtros atuais/i }).click();
      const dialog = page.getByTestId("save-search-dialog");
      await expect(dialog).toBeVisible();
      await expect(page.getByTestId("toast")).toHaveCount(2);

      // The dialog's overlay dims the bar but does not unmount it, so the rule
      // still positions the stack; the centred dialog is not under a toast.
      await expectStackAboveTheCompareBar(page);
      const stack = await stackBox(page);
      expect(intersects(stack, await boxOf(dialog)), "toast stack overlaps the save-search dialog").toBe(false);

      await dialog.getByRole("button", { name: "Cancelar", exact: true }).click();
      await expect(dialog).toHaveCount(0);
      await expect(page.getByTestId("toast")).toHaveCount(2);
      await expectStackAboveTheCompareBar(page);
    });
  });

  test("a Dashboard toast rests on the bottom inset", async ({ page }) => {
    await page.route("**/api/admin/enrichment/missing", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ queued_enrichments: 1, skipped_no_images: 0 }),
      }),
    );
    await page.goto("/");
    await page.getByTestId("enrich-missing").click();
    await expect(page.getByTestId("toast")).toHaveCount(1);
    await expectStackOnTheBottomInset(page);
  });
});
