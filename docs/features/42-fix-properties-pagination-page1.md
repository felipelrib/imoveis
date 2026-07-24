# Properties page-1 pagination — reload listings when returning to page 1

> Feature branch: `fix/properties-pagination-page1` · Linear: `BIN-57` · Status: implemented

## Problem

After navigating to page 2+ on the Properties listing, returning to page 1 (via «, ‹, or the numbered page button) left the grid showing the previous page’s results. The page-change effect skipped `load` when `page === 1`, assuming only the filter effect would fetch page 1.

## Approach

- Always call `load(page)` when `page` changes in “all” view mode, including page 1.
- Keep the filter effect resetting to page 1 and fetching on filter changes.
- Add a Playwright regression that mocks distinct page-1 / page-2 payloads and asserts page 1 → 2 → 1 refetches and re-renders page-1 listings.
- Encode “bug fix ⇒ regression spec” in the local feature-pipeline / code-review harness (gitignored `.cursor/`).

## Changes

Files touched:

```
 frontend/src/pages/Properties.jsx                      | FIX — load on every page change including page 1
 frontend/tests/e2e/properties-pagination.spec.js       | NEW — BIN-57 pagination regression (page 1↔2)
 docs/features/42-fix-properties-pagination-page1.md   | NEW — feature notes
```

## New Dependencies

None.

## How to Test

1. Open `/properties` with enough listings for multiple pages.
2. Go to page 2, confirm listings change.
3. Click page 1 (or «) — page-1 listings must reload (not stay on page-2 cards).
4. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```
   Or Playwright only: `cd frontend && npx playwright test tests/e2e/properties-pagination.spec.js`

## Notes / Follow-ups

- Filter changes while on page 2+ can briefly double-fetch page 1 (filter effect + page effect after `setPage(1)`); harmless.
- Linear: https://linear.app/felipelrib/issue/BIN-57/properties-listing-page-1-pagination-broken-after-visiting-other-pages
