# Semantic search locale — PT↔EN query expansion (BIN-102)

> Feature branch: `feat/bin-102-embeddings-semantic-search-locale` · Linear: `BIN-102` · Status: implemented

## Problem

Semantic `q=` embeds the raw user query against a Portuguese title/description
corpus via multilingual `bge-m3`. English housing terms that do not appear in PT
titles (e.g. `penthouse` vs `cobertura`, `backyard` vs `quintal`) under-ranked
on the live title-only corpus (BIN-97 audit), causing silent cross-language
degradation for EN UI users.

## Approach

- Keep indexing scraped `title` + `description` only — no re-embed, no model/dim
  change, no AI-tag index (audit: secondary; empty descriptions are the larger
  non-i18n win and stay deferred).
- Expand `q=` with a small bidirectional PT↔EN housing lexicon before embed
  (`core.semantic_query.normalize_semantic_query`): append missing counterparts;
  never strip the user's words.
- Prefer querying in listing language (PT) when possible; EN queries work via
  expansion for known domain pairs.
- Prove behaviour with unit tests on the lexicon; optional live probe via
  `scripts/dev/probe_pt_en_locale_audit.py --normalize`.

## Changes

Files touched:

```
 src/core/semantic_query.py                         | NEW — PT↔EN housing lexicon expander
 src/api/properties.py                              | Expand q= before embed truncate
 src/tests/unit/test_semantic_query.py              | NEW — expander regression tests
 scripts/dev/probe_pt_en_locale_audit.py            | --normalize compare EN MRR raw vs expanded
 docs/features/BIN-18-semantic-search.md                | Locale notes + bge-m3 / 1024-d correction
 docs/features/BIN-97-pt-corpus-ai-locale-audit.md      | Cross-link 8.6 shipped
 docs/features/BIN-102-semantic-search-locale.md         | NEW — this note
 _bmad-output/implementation-artifacts/sprint-status.yaml | 8-6 → done
```

## New Dependencies

None.

## How to Test

1. Unit lexicon:
   ```bash
   bash scripts/agent/validate.sh fast
   ```
2. Optional live Ollama compare (WSL → Windows host if needed):
   ```bash
   export OLLAMA_HOST=http://$(ip route show default | awk '/default/{print $3}'):11434
   PYTHONPATH=src .venv/bin/python scripts/dev/probe_pt_en_locale_audit.py --normalize
   ```
3. Manual: `GET /properties?q=luxury+penthouse` embeds expanded text including
   `cobertura` (no operator backfill required).

## Notes / Follow-ups

- No forced embedding backfill — index text unchanged.
- Description coverage restored via BIN-105 (`docs/features/BIN-105-listing-description-scrape.md`);
  re-run backfill + embeddings after deploy for full search+sentiment gains.
- Lexicon is intentionally small (audit misses); extend pairs in
  `semantic_query.py` when new EN↔PT gaps appear.
- Related: BIN-63 epic · BIN-97 audit · BIN-73 (`bge-m3`) · `BIN-18-semantic-search.md`.
