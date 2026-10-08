// @ts-check
import { test, expect } from "@playwright/test";
import { PROPERTIES_PAGE, installCommonMocks } from "./helpers/apiMocks.js";

const VALID_KEY = "e2e-test-api-key";

/**
 * A saved search as `GET /saved-searches` returns it (v0.14-s1.9 fields).
 * @param {Record<string, unknown>} overrides
 */
function savedSearch(overrides = {}) {
  return {
    id: "ss-1",
    name: "Savassi 2q",
    filters: {
      listing_type: "rent",
      max_price: 4000,
      price_type: "rent",
      min_bedrooms: 2,
      neighborhood: "Savassi",
    },
    created_at: "2026-10-01T12:00:00",
    notify_new_matches: false,
    min_price_drop: null,
    notify_enabled_at: null,
    new_match_alerts_supported: true,
    last_new_match_alert_on: null,
    price_drop_enabled_at: null,
    last_price_drop_alert_on: null,
    ...overrides,
  };
}

/**
 * Mock `/saved-searches` over an in-test store: GET lists it, PATCH writes it
 * (or answers `patchStatus` without writing). The store outlives a reload.
 *
 * @param {import('@playwright/test').Page} page
 * @param {Record<string, unknown>[]} store
 * @param {{ patches?: Record<string, unknown>[], patchStatus?: number, hold?: Promise<void> }} [opts]
 */
async function mockSavedSearches(page, store, opts = {}) {
  await page.route("**/api/saved-searches**", async (route) => {
    const req = route.request();
    const method = req.method();
    if (method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: store, total: store.length, page: 1, page_size: 50 }),
      });
      return;
    }
    if (method === "PATCH") {
      const id = new URL(req.url()).pathname.split("/").pop();
      const body = req.postDataJSON();
      opts.patches?.push({ id, ...body });
      if (opts.hold) await opts.hold;
      if (opts.patchStatus && opts.patchStatus >= 400) {
        await route.fulfill({
          status: opts.patchStatus,
          contentType: "application/json",
          body: JSON.stringify({ detail: "boom" }),
        });
        return;
      }
      const item = store.find((entry) => entry.id === id);
      Object.assign(item, body);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(item),
      });
      return;
    }
    await route.fallback();
  });
}

/** @param {import('@playwright/test').Page} page */
async function openPainel(page) {
  await page.addInitScript((key) => {
    sessionStorage.setItem("api_key", key);
  }, VALID_KEY);
  await installCommonMocks(page);
  await page.route("**/api/properties?**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(PROPERTIES_PAGE),
    });
  });
}

test.describe("Saved-search alert management (v0.14-s1.10)", () => {
  test("switch on and a 240 threshold are written at once and survive a reload", async ({
    page,
  }) => {
    const store = [savedSearch()];
    /** @type {Record<string, unknown>[]} */
    const patches = [];
    await openPainel(page);
    await mockSavedSearches(page, store, { patches });

    await page.goto("/properties");
    const row = page.getByTestId("saved-search-row-ss-1");
    await expect(row).toBeVisible();
    // Name, then what the search filters on.
    await expect(row.getByRole("button", { name: "Savassi 2q", exact: true })).toBeVisible();
    await expect(row).toContainText("Rent · up to R$ 4,000/month · 2+ beds · Savassi");

    const toggle = page.getByTestId("saved-search-notify-ss-1");
    const threshold = page.getByTestId("saved-search-drop-ss-1");
    const state = page.getByTestId("saved-search-alert-state-ss-1");
    // Nothing is on by default.
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await expect(threshold).toHaveValue("");
    await expect(state).toHaveText("Alerts off");

    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await expect.poll(() => patches.length).toBe(1);
    expect(patches[0]).toEqual({ id: "ss-1", notify_new_matches: true });
    await expect(state).toHaveText("Alerts on new homes");

    await threshold.fill("240");
    await threshold.press("Enter");
    await expect.poll(() => patches.length).toBe(2);
    expect(patches[1]).toEqual({ id: "ss-1", min_price_drop: 240 });
    await expect(state).toHaveText("Alerts on new homes and drops of R$ 240 or more");

    await page.reload();
    await expect(page.getByTestId("saved-search-notify-ss-1")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await expect(page.getByTestId("saved-search-drop-ss-1")).toHaveValue("240");
    await expect(page.getByTestId("saved-search-alert-state-ss-1")).toHaveText(
      "Alerts on new homes and drops of R$ 240 or more",
    );
    // The reload wrote nothing.
    expect(patches).toHaveLength(2);
    expect(store[0]).toMatchObject({ notify_new_matches: true, min_price_drop: 240 });
  });

  test("the threshold field sends a value only: invalid text stays, empty clears", async ({
    page,
  }) => {
    const store = [savedSearch({ notify_new_matches: true, min_price_drop: 100 })];
    /** @type {Record<string, unknown>[]} */
    const patches = [];
    await openPainel(page);
    await mockSavedSearches(page, store, { patches });

    await page.goto("/properties");
    const threshold = page.getByTestId("saved-search-drop-ss-1");
    const state = page.getByTestId("saved-search-alert-state-ss-1");
    await expect(threshold).toHaveValue("100");
    await expect(state).toHaveText("Alerts on new homes and drops of R$ 100 or more");

    // Not an amount: marked invalid, nothing sent.
    await threshold.fill("-5");
    await threshold.press("Enter");
    await expect(threshold).toHaveAttribute("aria-invalid", "true");
    await threshold.fill("cem");
    await threshold.blur();
    await expect(threshold).toHaveAttribute("aria-invalid", "true");
    expect(patches).toHaveLength(0);

    // Escape puts the stored value back.
    await threshold.focus();
    await threshold.press("Escape");
    await expect(threshold).toHaveValue("100");
    await expect(threshold).not.toHaveAttribute("aria-invalid", "true");

    // The stored value typed again is not a change.
    await threshold.fill("R$ 100");
    await threshold.blur();
    await expect(threshold).toHaveValue("100");
    expect(patches).toHaveLength(0);

    // A grouped amount with centavos, written on blur.
    await threshold.fill("1.500,50");
    await threshold.blur();
    await expect.poll(() => patches.length).toBe(1);
    expect(patches[0]).toEqual({ id: "ss-1", min_price_drop: 1500.5 });
    await expect(threshold).toHaveValue("1,500.50");

    // The field reads back what it shows (comma grouping in `en`): no change.
    await threshold.fill("1,500.50");
    await threshold.blur();
    await expect(threshold).toHaveValue("1,500.50");
    await expect(threshold).not.toHaveAttribute("aria-invalid", "true");
    expect(patches).toHaveLength(1);

    // A dot followed by three digits is thousands (pt-BR), never 1.5.
    await threshold.fill("1.500");
    await threshold.press("Enter");
    await expect.poll(() => patches.length).toBe(2);
    expect(patches[1]).toEqual({ id: "ss-1", min_price_drop: 1500 });
    await expect(threshold).toHaveValue("1,500");

    // A decimal comma with no grouping (pt-BR centavos).
    await threshold.fill("1500,5");
    await threshold.press("Enter");
    await expect.poll(() => patches.length).toBe(3);
    expect(patches[2]).toEqual({ id: "ss-1", min_price_drop: 1500.5 });
    await expect(threshold).toHaveValue("1,500.50");

    // A comma-grouped amount is thousands, not a decimal.
    await threshold.fill("1,600");
    await threshold.press("Enter");
    await expect.poll(() => patches.length).toBe(4);
    expect(patches[3]).toEqual({ id: "ss-1", min_price_drop: 1600 });
    await expect(threshold).toHaveValue("1,600");

    // Zero is a threshold: any drop.
    await threshold.fill("0");
    await threshold.press("Enter");
    await expect.poll(() => patches.length).toBe(5);
    expect(patches[4]).toEqual({ id: "ss-1", min_price_drop: 0 });
    await expect(state).toHaveText("Alerts on new homes and any price drop");

    // Empty is no threshold: null is sent, not left out.
    await threshold.fill("");
    await threshold.press("Enter");
    await expect.poll(() => patches.length).toBe(6);
    expect(patches[5]).toEqual({ id: "ss-1", min_price_drop: null });
    await expect(state).toHaveText("Alerts on new homes");
    await expect(threshold).toHaveValue("");
    await expect(threshold).toHaveAttribute("placeholder", "no alert");
  });

  test("a failed write puts the old value back and says so in a toast", async ({ page }) => {
    const store = [savedSearch()];
    /** @type {Record<string, unknown>[]} */
    const patches = [];
    /** @type {() => void} */
    let release = () => {};
    const hold = new Promise((resolve) => {
      release = () => resolve(undefined);
    });
    await openPainel(page);
    await mockSavedSearches(page, store, { patches, patchStatus: 500, hold });

    await page.goto("/properties");
    const toggle = page.getByTestId("saved-search-notify-ss-1");
    await expect(toggle).toHaveAttribute("aria-checked", "false");

    // Optimistic while the request is in flight; a second click is ignored.
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await expect.poll(() => patches.length).toBe(1);

    release();
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await expect(page.getByTestId("saved-search-alert-state-ss-1")).toHaveText("Alerts off");
    const toast = page.getByTestId("toast").filter({
      hasText: "Could not update the alerts of this search",
    });
    await expect(toast).toBeVisible();
    // Non-blocking: the row is still usable under the toast.
    expect(patches).toHaveLength(1);

    // The threshold reverts the same way.
    const threshold = page.getByTestId("saved-search-drop-ss-1");
    await threshold.fill("240");
    await threshold.press("Enter");
    await expect.poll(() => patches.length).toBe(2);
    await expect(threshold).toHaveValue("");
    expect(store[0]).toMatchObject({ notify_new_matches: false, min_price_drop: null });

    // Nothing was stored, so a reload shows the same.
    await page.reload();
    await expect(page.getByTestId("saved-search-notify-ss-1")).toHaveAttribute(
      "aria-checked",
      "false",
    );
    await expect(page.getByTestId("saved-search-drop-ss-1")).toHaveValue("");
  });

  test("two writes in flight: the answer that lands last does not undo the other field", async ({
    page,
  }) => {
    const store = [savedSearch()];
    /** @type {Record<string, unknown>[]} */
    const patches = [];
    /** @type {() => void} */
    let releaseSwitch = () => {};
    const switchHeld = new Promise((resolve) => {
      releaseSwitch = () => resolve(undefined);
    });
    await openPainel(page);
    await page.route("**/api/saved-searches**", async (route) => {
      const req = route.request();
      if (req.method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ items: store, total: store.length, page: 1, page_size: 50 }),
        });
        return;
      }
      if (req.method() !== "PATCH") {
        await route.fallback();
        return;
      }
      const body = req.postDataJSON();
      patches.push(body);
      if ("notify_new_matches" in body) {
        // The server read the row for this answer before the threshold was
        // written: its body still carries no minimum. It lands last.
        const stale = { ...store[0], notify_new_matches: true, min_price_drop: null };
        store[0].notify_new_matches = true;
        await switchHeld;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(stale),
        });
        return;
      }
      Object.assign(store[0], body, { price_drop_enabled_at: "2026-10-08T15:00:00" });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(store[0]),
      });
    });

    await page.goto("/properties");
    const toggle = page.getByTestId("saved-search-notify-ss-1");
    const threshold = page.getByTestId("saved-search-drop-ss-1");
    const state = page.getByTestId("saved-search-alert-state-ss-1");

    await toggle.click();
    await expect.poll(() => patches.length).toBe(1);
    await threshold.fill("240");
    await threshold.press("Enter");
    await expect.poll(() => patches.length).toBe(2);
    expect(patches).toEqual([{ notify_new_matches: true }, { min_price_drop: 240 }]);
    // The threshold answered; the switch is still in flight (optimistic).
    await expect(threshold).toHaveValue("240");
    await expect(toggle).toHaveAttribute("aria-checked", "true");

    releaseSwitch();
    await expect(state).toHaveText("Alerts on new homes and drops of R$ 240 or more");
    await expect(threshold).toHaveValue("240");
    await expect(toggle).toHaveAttribute("aria-checked", "true");

    // And it is what the store holds: a reload shows the same.
    await page.reload();
    await expect(page.getByTestId("saved-search-drop-ss-1")).toHaveValue("240");
    await expect(page.getByTestId("saved-search-notify-ss-1")).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  test("the summary line says what each stored search filters by", async ({ page }) => {
    const store = [
      savedSearch({
        id: "ss-sale",
        name: "Compra",
        // No stored price type: the cap follows the listing type, as the list does.
        filters: {
          listing_type: "sale",
          property_type: "apartment",
          max_price: 500000,
          min_bedrooms: 1,
          min_parking: 1,
          city: "Belo Horizonte",
          max_price_per_m2_percentile: 0.25,
          platform: "olx",
          is_furnished: true,
          accepts_pets: true,
          min_score: 0.7,
        },
      }),
      // Neither a listing type nor a price type: the cap is a rent cap.
      savedSearch({ id: "ss-cap", name: "Teto", filters: { max_price: 3000 } }),
      savedSearch({ id: "ss-empty", name: "Tudo", filters: {} }),
    ];
    await openPainel(page);
    await mockSavedSearches(page, store);

    await page.goto("/properties");
    const sale = page.getByTestId("saved-search-row-ss-sale").locator(".saved-search-summary");
    await expect(sale).toHaveText(
      "Sale · Apartment · up to R$ 500,000 · 1+ bed · 1+ parking space · Belo Horizonte · " +
        "among the 25% cheapest · OLX · Furnished · Pet Friendly · score 0.7+",
    );
    await expect(
      page.getByTestId("saved-search-row-ss-cap").locator(".saved-search-summary"),
    ).toHaveText("up to R$ 3,000/month");
    await expect(
      page.getByTestId("saved-search-row-ss-empty").locator(".saved-search-summary"),
    ).toHaveText("No filters");
  });

  test("a search that cannot produce alerts says so instead of offering the controls", async ({
    page,
  }) => {
    const store = [
      savedSearch({
        id: "ss-q",
        name: "Com varanda",
        filters: { q: "varanda gourmet" },
        new_match_alerts_supported: false,
      }),
      savedSearch({
        id: "ss-legacy",
        name: "Antiga",
        filters: { listingType: "rent" },
        new_match_alerts_supported: false,
      }),
      // Unsupported but still on: the switch stays so it can be switched off.
      savedSearch({
        id: "ss-on",
        name: "Texto ligado",
        filters: { q: "quintal" },
        new_match_alerts_supported: false,
        notify_new_matches: true,
        min_price_drop: 100,
      }),
    ];
    /** @type {Record<string, unknown>[]} */
    const patches = [];
    await openPainel(page);
    await mockSavedSearches(page, store, { patches });

    await page.goto("/properties");
    await expect(page.getByTestId("saved-search-alerts-muted-ss-q")).toHaveText(
      "A text search does not produce email alerts.",
    );
    await expect(page.getByTestId("saved-search-row-ss-q")).toContainText("“varanda gourmet”");
    await expect(page.getByTestId("saved-search-notify-ss-q")).toHaveCount(0);
    await expect(page.getByTestId("saved-search-drop-ss-q")).toHaveCount(0);
    await expect(page.getByTestId("saved-search-alert-state-ss-q")).toHaveCount(0);

    await expect(page.getByTestId("saved-search-alerts-muted-ss-legacy")).toHaveText(
      "This search does not produce email alerts.",
    );
    await expect(page.getByTestId("saved-search-notify-ss-legacy")).toHaveCount(0);

    await expect(page.getByTestId("saved-search-alerts-muted-ss-on")).toHaveText(
      "A text search does not produce email alerts.",
    );
    await expect(page.getByTestId("saved-search-drop-ss-on")).toHaveCount(0);
    const toggle = page.getByTestId("saved-search-notify-ss-on");
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await toggle.click();
    await expect.poll(() => patches.length).toBe(1);
    expect(patches[0]).toEqual({ id: "ss-on", notify_new_matches: false });
    // Off now: the row is as muted as the others.
    await expect(page.getByTestId("saved-search-notify-ss-on")).toHaveCount(0);
    await expect(page.getByTestId("saved-search-alerts-muted-ss-on")).toBeVisible();
  });

  test("the row reads in pt-BR and applying a search does not touch its alerts", async ({
    page,
  }) => {
    const store = [savedSearch({ notify_new_matches: true, min_price_drop: 1500 })];
    /** @type {Record<string, unknown>[]} */
    const patches = [];
    await page.addInitScript((key) => {
      sessionStorage.setItem("api_key", key);
    }, VALID_KEY);
    await installCommonMocks(page, { locale: { initial: "pt-BR", defaultLocale: "pt-BR" } });
    await page.route("**/api/properties?**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(PROPERTIES_PAGE),
      });
    });
    await mockSavedSearches(page, store, { patches });

    await page.goto("/properties");
    const row = page.getByTestId("saved-search-row-ss-1");
    await expect(row).toContainText("Aluguel · até R$ 4.000/mês · 2+ quartos · Savassi");
    await expect(row).toContainText("Avisos por e-mail");
    await expect(row).toContainText("Queda mínima");
    await expect(page.getByTestId("saved-search-drop-ss-1")).toHaveValue("1.500");
    await expect(page.getByTestId("saved-search-alert-state-ss-1")).toHaveText(
      "Avisa imóveis novos e quedas a partir de R$ 1.500",
    );
    await expect(page.getByRole("switch", { name: "Avisos por e-mail" })).toHaveAttribute(
      "aria-checked",
      "true",
    );

    // The name applies the search; the save dialog offers no alert option.
    await row.getByRole("button", { name: "Savassi 2q", exact: true }).click();
    await page.getByRole("button", { name: /Filtros avançados/i }).click();
    await expect(page.getByTestId("max-price-input")).toHaveValue("4000");
    await page.getByRole("button", { name: /Salvar filtros atuais/i }).click();
    const dialog = page.getByTestId("save-search-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("switch")).toHaveCount(0);
    await expect(dialog.getByRole("checkbox")).toHaveCount(0);
    expect(patches).toHaveLength(0);
  });
});
