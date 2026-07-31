# Empty property descriptions — stop fabricating sentiment on no input

> Feature branch: `fix/bin-243-empty-descriptions` · Linear: `BIN-243` · Status: implemented

## Problem

Every property in the DB had an empty `description` (0 of 26,188 rows had any
text, though 26,186 had images). The sentiment / listing-claim enrichment stage
therefore ran on empty input for **every** property. Local Ollama masked this by
fabricating a confident `good / 0.75`; Gemma honestly returned "no data" (surfaced
during the BIN-242 A/B). Either way, sentiment — and a chunk of the deal verdict —
was meaningless.

## Approach

Investigation (2026-07-31) found the symptom had **three distinct layers**, not the
single "enrich is broken" bug the ticket assumed:

1. **Data staleness (primary cause).** All 26,188 rows were last scraped
   2026-07-24…27, but the description-enrich step (BIN-105) merged 2026-07-28. So
   every existing row predates the feature — descriptions were **never attempted**.
   Persistence itself is correct: `_create_property` writes `candidate.description`,
   and `_update_or_noop` refuses to blank a stored value with an empty re-scrape
   (`_description_effectively_unchanged`). The empty DB is stale data, not a
   persist bug.
2. **QuintoAndar `__NEXT_DATA__` often lacks the description (data reality).** Three
   live QA detail pages (HTTP 200) were probed: the SSR `__NEXT_DATA__` `remarks`
   field is empty and the payload contains no long string. Because
   `extract_quintoandar_description` only parsed `__NEXT_DATA__`, it returned empty.
   > **⚠️ Corrected by [BIN-245] (2026-07-31).** The conclusion below — "QA exposes
   > no seller free-text, treat it as legitimately description-less" — was **wrong**.
   > A wider probe (and an operator screenshot) showed real QA detail pages **do**
   > carry rich seller descriptions, rendered in the **DOM** (`DescriptionsSection`
   > block) and frequently absent from the JSON blob. The bug was that our extractor
   > was `__NEXT_DATA__`-only. BIN-245 adds a DOM fallback + a real captured fixture,
   > and a backfill now populates QA descriptions. QA is **not** excluded from
   > sentiment.

   *(Original, now-superseded reasoning:)* The only description-like text is a
   templated one-liner in the *search* payload (`shortRentDescription`), often
   empty; the existing `extract_quintoandar_description` was written against a 1.2 KB
   synthetic fixture.
3. **OLX unverifiable in dev (89% of rows).** OLX has rich seller ad bodies, but
   every request (search + detail) returns Cloudflare 403 in this environment
   (`proxy: null`). Per repo convention this is environmental, not a parse
   regression — but it means the OLX extractor cannot be oracle-verified or
   backfilled here. Deferred to **BIN-244** (needs the residential proxy pool).

Given that, the shippable, verifiable fix is to **stop asking the model to judge an
empty string**: when a property has no description text, skip the text model and
record an explicit neutral, no-signal `SentimentResult` (`0.5`, `average`, with a
"sentiment skipped" reason) instead of a fabricated positive. This is honest,
deterministic, saves a GPU/API round-trip, and applies uniformly to every
description-less property (OLX and QA alike) until backfill lands.

## Changes

Files touched:

```
 src/adapters/ai/enrich_pipeline.py                         | CHANGED — skip text model on blank description; return neutral_sentiment_no_description()
 src/tests/unit/test_enrich_pipeline_no_description.py       | NEW — asserts blank/None desc skips model + returns neutral; non-empty still calls model
 src/tests/integration/test_listings_e2e.py                 | CHANGED — TestDescriptionPersistence: DB round-trip + blank re-scrape does not wipe stored description
 docs/features/BIN-243-empty-descriptions.md                | NEW — this doc
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh backend
```

Targeted:

```bash
PYTHONPATH=src python -m pytest src/tests/unit/test_enrich_pipeline_no_description.py -q
# DB round-trip (needs DATABASE_URL → realestate_test):
PYTHONPATH=src python -m pytest src/tests/integration/test_listings_e2e.py::TestDescriptionPersistence -q
```

Behavioural check: enrich a property whose `description` is empty — the persisted
`meta.sentiment` reasoning is *"No listing description available; sentiment
skipped."* with `sentiment_score = 0.5`, and no text-model call is made.

## Notes / Follow-ups

- **BIN-244** (follow-up): live-verify the OLX detail extractor against real pages
  and lock a real fixture, then run `scripts/dev/backfill_listing_descriptions.py`
  to populate existing OLX rows. Requires the residential proxy pool (OLX 403s
  here). Then re-run the BIN-242 sentiment A/B on properties that now have real
  descriptions.
- The committed `olx_detail*.html` fixtures are hand-written synthetic stubs,
  never validated against production HTML — BIN-244 should replace the OLX one with
  a real captured page. (**BIN-245** already added a real captured QA fixture,
  `quintoandar_detail_dom.html`.)
- ~~QuintoAndar is intentionally excluded from meaningful sentiment: it is an
  institutional platform with no seller free-text.~~ **Corrected by [BIN-245]:** QA
  *does* expose seller free-text (DOM-rendered); the extractor was JSON-only. QA is
  included in sentiment once descriptions are backfilled.

[BIN-245]: https://linear.app/felipelrib/issue/BIN-245
