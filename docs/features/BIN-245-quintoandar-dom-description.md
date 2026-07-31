# QuintoAndar DOM description extraction — fix JSON-only extractor

> Feature branch: `feat/bin-245-qa-description-dom` · Linear: `BIN-245` · Status: implemented

## Problem

`extract_quintoandar_description` only parsed the detail page's `__NEXT_DATA__`
JSON blob. Many real QuintoAndar listings render the seller description **only in
the server-side DOM** (a `DescriptionsSection` block) and omit it from the JSON,
so the extractor returned empty for them. This produced DB-wide empty QA
descriptions and led [BIN-243](BIN-243-empty-descriptions.md) to the **wrong**
conclusion that "QuintoAndar exposes no seller free-text" and should be excluded
from sentiment.

A live probe (2026-07-31) and an operator screenshot refuted that. Example —
listing `894353786` (Santo Antônio, BH): the page shows *"Imóvel aconchegante
para alugar com 3 quartos, sendo 1 suíte… próximo a Greenwich Schools, Parque
Mosteiro Tom Jobim, Hospital Madre Teresa…"*, but the longest string in its
`__NEXT_DATA__` is 87 chars. The old extractor returned `0` for it; a sibling
listing (`894738628`) happened to also carry the text in JSON, which is why the
bug looked intermittent.

## Approach

- **JSON first, DOM fallback.** Keep the existing `__NEXT_DATA__` path (it's still
  valid and takes precedence). When it yields empty, fall back to the DOM: find the
  first element whose class contains `DescriptionsSection` and extract its text.
- **Match the stable class prefix, not the hashed suffix.** The rendered class is a
  CSS-module name like `DescriptionsSection_descriptionsWrapper__HNAzX`; the
  `__HNAzX` hash is build-specific. We match on the `DescriptionsSection` prefix via
  regex so a QA redeploy doesn't silently break extraction.
- **Reuse BeautifulSoup** (already a dependency, used across scrapers) rather than a
  brittle balanced-`<div>` regex — nested `<a>`/`<span>` links inside the paragraph
  make regex extraction unsafe.
- **Normalize inline-link spacing.** `get_text(" ")` leaves a stray space before
  punctuation where nested neighbourhood/city links sit ("Belo Horizonte ."); a
  small cleanup collapses whitespace and tidies space-before-punctuation.
- **Oracle-first fixture.** Replaced reliance on the synthetic stub with a
  byte-exact captured `DescriptionsSection` block from the real `894353786` page
  (`quintoandar_detail_dom.html`), whose description is DOM-only — exactly the case
  the old extractor missed.

## Changes

Files touched:

```
 src/adapters/scrapers/listing_description.py               | CHANGED — split JSON path into _qa_from_next_data; add _qa_from_dom DOM fallback + _normalize_dom_text; extract_quintoandar_description now JSON-then-DOM
 src/tests/fixtures/scrapers/quintoandar_detail_dom.html   | NEW — byte-exact real capture (listing 894353786), description DOM-only
 src/tests/unit/test_listing_description.py                | CHANGED — DOM-fallback regression on the real fixture + JSON-precedes-DOM test
 docs/features/BIN-243-empty-descriptions.md               | CHANGED — corrected the wrong "QA has no seller free-text" conclusion
 docs/features/BIN-245-quintoandar-dom-description.md       | NEW — this doc
```

## New Dependencies

None (`beautifulsoup4` was already in `requirements.txt`).

## How to Test

```bash
bash scripts/agent/validate.sh backend
```

Targeted:

```bash
PYTHONPATH=src python -m pytest src/tests/unit/test_listing_description.py -q
```

Live/behavioural check (QA is reachable directly, no proxy):

```bash
export DATABASE_URL="postgresql://imoveis:${POSTGRES_PASSWORD:-imoveis_local_dev}@localhost:5433/realestate"
# dry-run: shows QA rows that would gain a description
PYTHONPATH=src python scripts/dev/backfill_listing_descriptions.py --platform quintoandar --limit 5
```

Verified 2026-07-31: extractor returns 428 chars for `894353786` (was 0); a
`--apply --limit 8 --no-embed` run populated real descriptions into the primary DB
(spot-checked in `properties.description`).

## Notes / Follow-ups

- **Operational rollout (not done in this PR):** run the full backfill against all
  ~2,798 QA rows with empty descriptions —
  `scripts/dev/backfill_listing_descriptions.py --apply --platform quintoandar`
  (throttled live fetches; enqueues `embed_property`). Many older QA listings are
  delisted and legitimately return empty (`quintoandar_description_empty`); those
  keep BIN-243's neutral no-signal sentiment.
- After the backfill, re-run the [BIN-242](https://linear.app/felipelrib/issue/BIN-242)
  sentiment A/B on QA properties that now have real descriptions.
- OLX descriptions remain blocked on Cloudflare — separate work in
  [BIN-246](https://linear.app/felipelrib/issue/BIN-246) (headless-browser bypass)
  and [BIN-244](https://linear.app/felipelrib/issue/BIN-244) (OLX verify + backfill).
