# Fix hardcoded QuintoAndar-only fallback link in PropertyModal

> Feature branch: `feat/bin-158-fix-hardcoded-quintoandar-fallback-link` · Linear: `BIN-158` · Status: implemented

## Problem

When a property has no populated `listings` array, `PropertyModal` renders a "View Original" fallback link built from `p.platform_id`. That template was hardcoded to `https://www.quintoandar.com.br/imovel/${p.platform_id}` regardless of `p.platform`, so an OLX (or the newly-added ZapImóveis, [BIN-127](https://linear.app/felipelrib/issue/BIN-127)) property with a `platform_id` but empty `listings` rendered a link pointing at the **wrong** platform's site.

## Approach

- Added a `platformFallbackUrl(platform, platformId)` helper next to `sanitizeListingUrl`.
- Only platforms whose detail page is reachable from the id alone get a template. QuintoAndar's `https://www.quintoandar.com.br/imovel/{id}` is such a URL, so it's returned (and run back through `sanitizeListingUrl` defensively). OLX and ZapImóveis use slug-based detail URLs that cannot be reconstructed from a numeric id, so the helper returns `null` and the fallback link is simply **not rendered** for them — better a missing link than a wrong-platform one.
- The real per-listing links (from `l.url`) are unaffected; this only governs the no-listings fallback.

## Changes

Files touched:

```
 frontend/src/components/PropertyModal.jsx               | ADD platformFallbackUrl helper; gate fallback link on it (no more hardcoded QA URL)
 frontend/tests/e2e/property-modal-fallback-link.spec.js | NEW — regression: OLX no-listings → no QA link; QuintoAndar → id-based link
```

## New Dependencies

None.

## How to Test

1. Automated regression (fails before the fix, passes after):
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Manual: open an OLX property that has no listing rows — the "🔗 View Original" button is absent (previously it linked to quintoandar.com.br). Open a QuintoAndar property with no listings — the button links to `https://www.quintoandar.com.br/imovel/<id>`.

## Notes / Follow-ups

- If OLX/ZapImóveis id→URL reconstruction becomes possible (e.g. the scraper persists a slug), extend `platformFallbackUrl` with those templates. Until then their fallback is intentionally suppressed.
- Part of epic [BIN-128](https://linear.app/felipelrib/issue/BIN-128) (v0.10 — Technical debt remediation).
