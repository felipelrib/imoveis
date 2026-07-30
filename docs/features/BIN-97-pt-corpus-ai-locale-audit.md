# PT listing corpus vs AI / stats / embeddings — locale audit (BIN-97)

> Feature branch: `feat/bin-97-pt-corpus-ai-audit` · Linear: `BIN-97` · Status: implemented

## Problem

Scraped listing text is Portuguese while product AI/UI is English. Operators needed a
**measured** answer on whether that mix hurts semantic search (`q=`), AI enrichment, or
statistical scoring — so stories 8.5 / 8.6 (BIN-101 / BIN-102) fix real gaps instead of
guessing.

## Approach

- No product behaviour change (audit only).
- Probe multilingual `bge-m3` with a fixed PT fixture corpus + paired PT/EN queries
  (`scripts/dev/probe_pt_en_locale_audit.py`).
- Probe sentiment on the same PT ads and score category / flag language.
- Sample the live DB: embedding coverage, description coverage, stored AI meta language,
  and live `<=>` rank anecdotes for PT vs EN queries.
- Lock the English `_stat_analysis` band catalog in a unit test for BIN-101 cataloguing.

## Changes

Files touched:

```
 scripts/dev/probe_pt_en_locale_audit.py              | NEW — Ollama + optional DB locale probe
 src/tests/unit/test_scoring_locale_catalog.py        | NEW — EN band catalog + numeric invariance
 src/tests/unit/test_ai_quality.py                    | Mark live Ollama golden as ``slow``
 scripts/agent/validate.sh                            | Unit gate: ``-m "not slow"``
 .github/workflows/ci.yml / nightly.yml               | Same ``not slow`` exclusion
 _bmad-output/implementation-artifacts/sprint-status.yaml | Epic 8 + 8.1 tracking
 docs/features/BIN-97-pt-corpus-ai-locale-audit.md        | NEW — this findings note
```

## New Dependencies

None.

## How to Test

1. Unit catalog lock:
   ```bash
   bash scripts/agent/validate.sh fast
   ```
2. Live Ollama probe (WSL → Windows host if needed):
   ```bash
   export OLLAMA_HOST=http://$(ip route show default | awk '/default/{print $3}'):11434
   # optional live DB anecdotes:
   set -a && source .env.local && set +a
   export POSTGRES_USER=imoveis POSTGRES_PASSWORD=imoveis_local_dev
   export DATABASE_URL="postgresql://imoveis:imoveis_local_dev@localhost:${POSTGRES_PORT}/realestate"
   .venv/bin/python scripts/dev/probe_pt_en_locale_audit.py --db --out /tmp/bin97-probe.json
   ```

## Findings (2026-07-27 probe)

### Corpus reality (live primary DB)

| Metric | Value |
|---|---|
| Active properties | ~25 371 |
| With embedding | ~3 932 |
| With non-empty `description` | **0** |
| Embedded title language | Mostly PT tokens; ~69% also match ` in ` English QuintoAndar title template |

Embeddings today are **title-only**. Search cards often omit body text; sentiment therefore
often runs on empty descriptions → homogenized / empty green flags in stored meta
(~9.3k empty flag lists; ~3.4k identical `["close to supermarket","near park"]`).

### Semantic search (`bge-m3`)

**Fixture PT title+description corpus** (5 listings, 5 query pairs):

| Lang | Top-1 | MRR |
|---|---|---|
| EN queries | 1.0 | 1.0 |
| PT queries | 1.0 | 1.0 |

PT queries score higher cosine similarity to PT docs (e.g. 0.62–0.79 vs EN 0.51–0.68) but
EN still retrieved the correct doc at rank 1 in every pair — **cross-lingual recall is fine
when descriptions exist**.

**Live title-only anecdotes:**

- `apartamento perto do metrô` / `apartment near metro` share the same #1 title; EN then
  drifts to generic `Apartamento in Centro` rows.
- `casa com quintal` hits a title that literally says *quintal*; `house with backyard`
  does **not** surface that row in top-5 (domain lexicon gap).
- `cobertura luxo` ranks real *Cobertura* titles; `luxury penthouse` ranks *luxo* casas —
  **penthouse ↔ cobertura** is a real EN query miss on a PT title corpus.

### AI enrichment (PT ads → EN tags)

On fixture PT descriptions with `qwen2.5vl:7b`:

- Categories: **100%** English enum (`Good` / `Poor` / …).
- Reasoning: **100%** English prose.
- Free-form flags: **~60%** English — model often **copies Portuguese phrases** into
  `green_flags` (e.g. `próximo a restaurantes`, `vista panorâmica`, `3 suítes`).
- Numeric scores look directionally correct (luxury ~0.85, flood/reforma ~0.15).

Stored live meta: sentiment reasoning has **0** rows with PT diacritics; ~706 deal
verdicts contain PT characters (mostly neighbourhood proper nouns like *São*, or stale
PT copy). Stat bands are **100%** English catalog strings.

### Statistical scoring

Numeric path (z-score → sigmoid → blend with AI / neighbourhood weights) is
**locale-invariant**. Only user-facing strings need cataloguing for BIN-101:

| Source | Strings |
|---|---|
| `scoring._stat_analysis` | Highly Undervalued / Slightly Undervalued / Average / Slightly Overvalued / Highly Overvalued + EN reasonings |
| `client.template_deal_verdict` | EN punchlines (`good condition`, `needs renovation`, claim counts, `neighbourhood quality N%`, risk counts) |
| Prompt enums | Visual: Pristine…Poor · Sentiment: Highly Desirable…Poor |
| Risk codes (raw UI) | `flood_zone`, `industrial_adjacent` |
| Frontend chrome | Combined / Statistical / AI Quality / Deal verdict / Amenity / Transit / … |

## Recommendations

### BIN-101 (8.5 — localize AI tags, verdicts & score copy)

1. **Expand `ai.output_language` (or `ui.locale`)** beyond deal-verdict LLM only — apply to
   sentiment/visual prompts (hard-require flag language), template fallback, and
   `_stat_analysis` via a display catalog (keep machine category codes stable if useful).
2. **Do not rely on few-shots alone** for flag language — probe showed PT leakage on
   green_flags even when reasoning is EN.
3. Map risk codes + stat band categories through the same catalog as UI chrome.
4. Re-run `verdict_only` / selective enrichment after prompt locale changes (BIN-95).

### BIN-102 (8.6 — embeddings & semantic search locale)

1. **Keep indexing scraped title+description** with `bge-m3` — no re-embed-for-language
   alone; model already cross-lingual on rich PT bodies.
2. **Priority fix outside pure i18n:** restore listing **descriptions** into the scrape /
   persist path (today 0% coverage). That improves both search and sentiment more than
   query rewrite.
3. After descriptions exist: optional **query normalize** for domain pairs
   (`penthouse`↔`cobertura`, `backyard`↔`quintal`, `doorman`↔`portaria`) when UI locale is
   EN and corpus is PT — cheap win; full bidirectional rewrite not required for fixture
   recall.
4. **Optional:** also embed EN AI tags / neighbourhood name when present — secondary;
   do not replace scraped text.
5. **No-op for re-embed-only** unless descriptions are backfilled or model/dim changes.

### Explicit deferred

- Bilingual scraping / dual-store listing bodies — out of epic scope.
- Changing numeric scoring math for language — not needed.

## Notes / Follow-ups

- Probe script is intentionally offline-safe without `--db`; CI does not call Ollama.
- Stale docs: `docs/features/BIN-12-deal-summary-enrichment.md` refreshed in BIN-126
  (`BIN-126-refresh-deal-summary-feature-doc.md`) to match EN default + locale-aware verdicts
  (SoT: `BIN-101-localize-ai-tags-verdicts.md` / BIN-101). `BIN-18-semantic-search.md` locale/model
  notes updated in BIN-102 (`BIN-102-semantic-search-locale.md`).
- Related: BIN-63 epic · BIN-101 · BIN-102 · BIN-73 (`bge-m3`) · BIN-64/69 English baseline.
- **BIN-102 (8.6) shipped:** query synonym expansion for known PT↔EN housing terms
  (`core.semantic_query`); probe via `--normalize`. No re-embed / no AI-tag index.
- **BUG (Medium)**: live corpus had empty `description` for all active rows — fixed in
  BIN-105 (`docs/features/BIN-105-listing-description-scrape.md`: detail enrich + backfill).
