# bundled-condo-iptu — Flag bundled condo/IPTU across platforms without inventing splits

> Feature branch: `feat/bin-114` · Linear: `BIN-114` · Status: implemented

## Problem

Condo fee and IPTU are sometimes bundled vs separate across platforms. QuintoAndar may
expose a single `condoIptu` (or derive fees from `totalCost - rentPrice`), while OLX
publishes separate Condomínio / IPTU labels. Showing a bundled amount under a plain
"Condo" column with an empty IPTU cell made cross-platform comparison misleading.

## Approach

- **Flag, do not invent splits** — when the platform only gives a bundle, store the
  amount in `condo_fee`, leave `iptu` null, and set `fees_bundled: true` in listing
  `raw_json`. Never fabricate separate condo vs IPTU values.
- **Explicit `false` for separate fees** — QuintoAndar separate `condoFee`+`iptu` and
  all OLX listings stamp `fees_bundled: false` so projection/UI do not treat absence
  as ambiguous.
- **UI clarification** — Property modal shows a "Bundled fees" badge, labels the condo
  cell as Condo+IPTU, and keeps IPTU as an em-dash with a tooltip explaining the
  platform did not publish a split.
- Declined: first-class DB column, inventing `other_taxes`, CompareView fee rows
  (modal listings table is the cross-platform fee surface).

### Per-platform semantics

| Platform | Separate fields | Bundled source | Storage | `fees_bundled` |
|---|---|---|---|---|
| QuintoAndar | `condoFee` + `iptu` | `condoIptu` or `totalCost - rentPrice` | amount in `condo_fee`, `iptu=null` | `true` / `false` |
| OLX | Condomínio + IPTU props | n/a (never bundled) | both columns when present | always `false` |

## Changes

Files touched:

```
 src/adapters/scrapers/quintoandar.py              | Always write fees_bundled bool in raw_json + props_json
 src/adapters/scrapers/olx.py                      | Stamp raw_json.fees_bundled=false on listings
 src/tests/unit/test_scoring_and_fees.py           | Assert explicit false for separate/unknown fees
 src/tests/unit/test_olx.py                        | OLX separate condo+IPTU → fees_bundled false
 src/tests/unit/test_scraper_cassettes.py          | Cassette expectations for false/true
 frontend/src/components/PropertyModal.jsx         | Condo+IPTU cell + IPTU em-dash tooltip when bundled
 frontend/src/i18n/locales/{en,pt-BR}.json         | condoPlusIptu + iptuBundledTitle keys
 frontend/tests/e2e/property-modal-listings.spec.js| Playwright regression for bundled fixture
 docs/features/16-per-platform-listings.md         | Note scraper-alignment follow-up addressed
 docs/features/91-bundled-condo-iptu.md            | NEW — this feature doc
```

## New Dependencies

None.

## How to Test

1. Open a QuintoAndar rent listing known to use bundled fees (or mock `fees_bundled: true`).
2. Property modal → Listings by Platform: badge "Bundled fees", condo cell shows amount +
   "Condo+IPTU", IPTU column shows "—".
3. Open an OLX listing with separate Condomínio/IPTU: no badge; both columns populated.
4. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Historical rows scraped before this change may still omit `fees_bundled` in `raw_json`
  (projection yields null). Re-scrape or a one-off backfill would stamp `false`/`true`
  consistently; UI treats only truthy as bundled.
- Related: BIN-66 (UI table layout), feature 48 (declined `other_taxes`), feature 16
  (original follow-up).
