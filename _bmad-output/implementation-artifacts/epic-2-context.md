# Epic 2 Context: Deal-Intelligence Deepening (Theme B cut)

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give users a sharper deal signal than one combined score. Every property card and the detail surface show where a Property's price/m² falls within its **neighbourhood × listing-type** cohort — computed once in the pipeline, stored, filterable, and suppressed entirely when the cohort is too small to mean anything. Saved searches gain **new-match email alerts**: when a genuinely new Property matches a notification-enabled search, the user is told — but only after enrichment makes it decidable, so the click always lands on a real verdict and percentile rather than a pending placeholder. The epic also lands two foundation pieces: repairing corpus rows poisoned with fabricated scores before they can skew percentiles, and correcting shared UI-contract defects (toast anchoring, pt-BR plural agreement) so the new surfaces build on a correct base instead of inheriting and re-pinning defects. The modal→side-panel migration belongs here too: the detail surface becomes the contract's right-side panel. Everything consumes shipped foundations — neighbourhood polygons, dual-type scoring, saved searches, the notifier registry — so there is no new geo work and no new notification channel work.

## Stories

- Story 2.1: Cohort price/m² percentiles computed in the pipeline
- Story 2.2: Percentile badge on cards + percentile filter
- Story 2.3: Saved-search new-match detection on the pipeline
- Story 2.4: Saved-search alert management UI
- Story 2.5: Detail side panel — modal migration + percentile sentence
- Story 2.6: UI contract debt — toast anchoring + pt-BR plural agreement
- Story 2.7: Corpus repair — rows poisoned with fabricated scores before s3.2

## Requirements & Constraints

- **Percentile capability:** a Property's price/m² position within its cohort is a *stored* signal, computed on a single price basis defined in the pipeline stage, keyed by neighbourhood × listing type. Dual rent/sale Properties carry a percentile per listing type. Never re-derived at read time.
- **Suppression over noise:** cohorts below a config-owned minimum size produce a null percentile, and missing area or unassigned neighbourhood is skipped — never defaulted, never a placeholder. Signal noise (percentiles on meaningless cohorts) is the explicit counter-metric.
- **New-match alerts:** only genuinely new Properties fire (a re-scrape or price update on an existing Property does not); each search × property pair notifies at most once; a disabled search never fires; platform circuit-breaks and scrape failures produce no spurious matches.
- **Enrichment gating:** an alert is *held*, never dropped, until the verdict exists and the percentile has been evaluated (a value or a suppressed null both count as evaluated).
- **Delivery posture:** email only for v1, through the shipped notifier registry — no new channel, no Telegram, no second notifier path. Email new-match alerts batch into one daily window per search, and the weekly digest excludes already-alerted Properties (no double delivery).
- **Per-search thresholds:** the minimum-drop threshold lives per saved search beside its notify toggle — there is no global setting — and every alert email states the threshold that fired it.
- **Corpus honesty gate:** percentiles must not be computed over rows carrying known-fabricated scores. Poisoned rows must be returned to the enrichment candidate set; legitimate scores (including honest neutral-sentiment values) must be left untouched.
- **i18n (NFR-7):** pt-BR is the UI default; every new string lands in both `en` and `pt-BR` catalogs; wire/DB enum values stay English. Counts must agree with their nouns in pt-BR (singular/plural split, as the catalog already models elsewhere).
- **Validation gates:** API schema changes update and run the contract suite; DB schema changes pass `alembic check`; merge requires a green `validate.sh all` including the full Playwright suite. Applying corpus surgery to the primary DB goes through the sanctioned guarded operator step, never an unguarded script against a live backfill.

## Technical Decisions

- **Cohort stats live in the pipeline stage (AD-10)** and are consumed read-only through the single canonical projection (AD-12) — one API-owned DTO, no parallel flattener, no read-time re-derivation in views. The percentile is a float and nullable end to end.
- **Minimum cohort size is `AppConfig`-owned (AD-2)** — no hardcoded threshold anywhere.
- **Filtering is server-side** on the stored value; the frontend round-trips it through the existing filter state. Cohorts are per listing type, so switching tipo re-evaluates against that type's cohort — cross-type leakage is a known past defect class and must not reappear.
- **Matching is read-only (AD-3):** saved-search matching must not become a second writer of Property/Listing fields; the dedupe/persist path stays the sole write authority. Matcher logic belongs in `core`-tier code with no new `core` → `adapters` imports (AD-1).
- **Notifications go through Celery + the single notifier preference registry (AD-9)**, with subscription identity on the single principal model (AD-11, nullable owner).
- **Frontend talks only to the FastAPI surface (AD-8)** — never directly to Redis, DB, or model backends.
- **Forensic predicates are one-off artifacts:** the fabrication-detection predicate used for corpus repair must live only in the repair artifact — never in feature code, never in a recurring path — and the delivery mechanism (migration vs admin action vs script) is recorded with its rationale.
- **Testing tiers:** percentile math is pure domain — TDD with boundary coverage (cohort exactly at min size, single-listing cohorts, ties); matcher branches (match/no-match/threshold/disabled) get the same treatment; the Celery task wrapper gets one happy-path and one error-path test only. Brownfield projection/SQL and corpus-repair predicates get a **characterization test locking current behaviour before the change**. Playwright e2e covers badge display + filter, toggle + threshold persistence, and panel open → `Esc`-close → scroll preserved.

## UX & Interaction Patterns

- **Percentile microcopy is a hard contract.** Badge: `entre os 25% mais baratos` — the word *barato* appears on the badge itself. Sentence (detail surface): `entre os 25% mais baratos do bairro`; on dual-type Properties the sentence names the cohort type (`…dos aluguéis do bairro` / `…das vendas do bairro`). Statistician notation (`P25`, "percentil", `≤`) is banned, and every phrasing must make lower-price-is-better explicit.
- **Badge visual:** compact chip, `price-drop` ink on `price-drop-tint-12` background with a `price-drop-tint-35` border, small radius, right-aligned on the serif price line, rendering the primary listing on dual-type Properties. When suppressed it is **absent entirely** — never a placeholder.
- **Percentile filter:** a `Preço no bairro` select in the Filtros panel (`entre os 25% mais baratos` / `entre os 50% mais baratos` / `qualquer preço` default); the active value renders as **one chip** and must compose under the filter bar's hard two-line ceiling.
- **Detail surface is a right-side panel, not a modal.** It slides over a **partial** scrim — the grid dims, the map rail stays visible — one level deep, `Esc` closes, and no centered modal survives (no dead modal code, and existing modal e2e specs are migrated rather than deleted).
- **Persistence contract (one rule, three surfaces):** map viewport, grid scroll position, and filter state survive data refreshes and panel open/close; the map viewport also survives filter edits.
- **Toasts are bottom-anchored, max two stacked**, non-blocking, never covering the filter bar. API errors and conflicts surface as toasts, never as blocking states.
- **Honest absence, no meters:** progress bars are banned everywhere; null renders as absent; no fake percentile, no placeholder sentence.
- **Saved-search rows (Buscas salvas):** `surface-card` rows with hairline separators, search name in body type and filter summary in meta type, per-search notify toggle plus inline threshold value (accent when interactive), alert state visible at a glance.
- **Meia-noite tokens, dark-only:** serif reserved for price and neighbourhood name, tabular numerals for all numbers, radii scale with no pills, 4-based spacing.

## Cross-Story Dependencies

- **Upstream (Epic 3, closed) gates this epic.** Epic 3 stopped fabricated scores from accruing; **2.7** repairs the rows already poisoned before that landed. **2.1 must not start until 2.7 has landed** — percentiles must compute over honest values. Repaired-but-not-yet-re-enriched rows are honest nulls, which 2.1's suppression rules already handle.
- **2.6 is the UX foundation piece** and gates every Epic 2 UI story (2.2, 2.4, 2.5): starting them first would pin further e2e assertions on top of the wrong pt-BR strings and the wrong toast anchor.
- **2.1 is the data foundation:** 2.2 and 2.3 both consume it. 2.5 consumes 2.2's projection (2.2 stays grid-only, so no story depends on a later one). 2.4 consumes 2.3's subscription capability.
- **Wave order:** (2.6 ∥ 2.7 ∥ the scheduled DW-32 ledger fix) → 2.1 → (2.2 ∥ 2.3) → (2.4 ∥ 2.5).
- **Gates:** 2.1←2.7 and 2.1←Epic 3 (3.2+3.3+3.4); 2.2←2.1+2.6; 2.3←2.1; 2.4←2.3+2.6; 2.5←2.2+2.6.
- **Do not parallelize:** any Epic 2 UI story ahead of 2.6. 2.6 and 2.7 *are* file-disjoint and safely run in parallel with each other.
- **Out of scope here:** the in-app Alertas panel and desktop push are v0.14 surfaces; total-cost-of-occupancy normalization (FR-31) is deferred to the debt ledger.
