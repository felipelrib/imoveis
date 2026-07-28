# Refresh deal-summary feature doc — retire stale PT-BR-only verdict claims

> Feature branch: `feat/bin-126-refresh-deal-summary-doc` · Linear: `BIN-126` · Status: implemented

## Problem

`docs/features/15-deal-summary-enrichment.md` (and a sibling line in `03-ai-enrichment.md`)
still described deal verdicts as Portuguese-only after the English product baseline
(BIN-64) and AI locale work (BIN-101). Operators reading feature 15 would get the wrong
mental model of current enrich language.

**Source:** `docs/features/78-pt-corpus-ai-locale-audit.md` Notes / Follow-ups.

## Approach

- Rewrite feature 15 Approach / How to Test / Notes to match locale-aware templates and
  `resolve_ai_output_language()` (English default; `pt-BR` when UI locale is Portuguese).
- Point explicitly at [82-localize-ai-tags-verdicts.md](82-localize-ai-tags-verdicts.md) /
  [BIN-101](https://linear.app/felipelrib/issue/BIN-101) as AI locale source of truth.
- Patch the one-line PT-BR claim in feature 03; mark the audit follow-up in feature 78 done.

## Changes

Files touched:

```
 docs/features/15-deal-summary-enrichment.md           | Refresh locale behaviour + SoT links
 docs/features/03-ai-enrichment.md                     | Locale-aware deal verdict wording
 docs/features/78-pt-corpus-ai-locale-audit.md         | Mark stale-doc follow-up resolved
 docs/features/84-refresh-deal-summary-feature-doc.md  | NEW — this note
```

## New Dependencies

None.

## How to Test

1. Open `docs/features/15-deal-summary-enrichment.md` — title/Approach must not claim
   PT-BR-only verdicts; must link to feature 82 / BIN-101.
2. Grep docs for leftover "PT-BR punchline" / "Portuguese deal verdict" in features 03/15:
   ```bash
   rg -n 'Portuguese deal verdict|PT-BR "punchline"|PT-BR string' docs/features/0{3,15}* docs/features/15*
   ```
   Expect no matches on those stale phrases.
3. Docs-only change — no runtime validation required beyond the docs CI check on PR.

## Notes / Follow-ups

- Parent epic: [BIN-104](https://linear.app/felipelrib/issue/BIN-104) (feature follow-up backlog).
- Related: BIN-12 (original deal summary) · BIN-64 · BIN-101 · feature 78 audit.
