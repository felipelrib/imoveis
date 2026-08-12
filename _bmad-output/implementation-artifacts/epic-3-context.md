# Epic 3 Context: Enrichment Hardening & Operability

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Make the cloud backfill Epic 1 productized actually runnable from the surface built for it, and make the corpus it writes trustworthy. Today the admin Start button only records a request that nothing consumes unless a hand-started dev script happens to be alive; a systemic AI-client failure (revoked key, retired model id, transport outage) writes a fabricated `0.5` score that permanently retires the row from the candidate set; the daily budget counts properties while the provider counts requests, so the never-exceed guarantee can undercount by an order of magnitude exactly when the account is throttled; and a displaced runner's draining rows can rewind its successor's checkpoint and double-count progress. This epic is not new scope — it completes FR-28's stated outcome and closes the corpus-integrity gaps Epic 1's review passes found and correctly fenced out of their own stories' intent contracts (ledger items DW-27, DW-17, DW-18, DW-11). It gates Epic 2: percentile work computes over this corpus, so fabricated scores must stop accruing first.

## Stories

- Story 3.1: Backfill runner hosting — a committed home for the consumer
- Story 3.2: Non-quota AI failures must not fabricate a score
- Story 3.3: The daily budget must count requests, not properties
- Story 3.4: Checkpoint advance semantics under lease loss

## Requirements & Constraints

- **FR-28 (completing the stated outcome):** the backfill runner must be an operator-facing operation, not a request queued into the void — start/pause/resume works without a manual host-side step, and reported runner presence must reflect reality. Interruption at any point (crash, quota exhaustion, operator stop, host reboot) resumes without re-enriching completed rows.
- **FR-27 / FR-29 (hardening the delivered surface):** quota exhaustion and provider errors back off or degrade to local — never an outage, never a fabricated result. Coverage/progress figures stay honest under failure and handover.
- **Never-exceed budget:** the configured daily budget must be about the provider's real request-per-day count. Reservation stays atomic; rollback preserved. Quota sizing basis is unchanged: free-tier Gemma ≈ 30 RPM / 14,400 RPD best case, ~3 requests/property ⇒ ≈4,600 properties/day ⇒ a whole-DB pass is inherently multi-day (~6-day planning basis). Never plan single-day whole-DB cloud runs.
- **NFR-1 local-first, bounded cloud assist:** cloud assist may accelerate backfill, never gate core function; the local path is never removed. Hosting work must not move the runner off-box, and nothing may route scraping or enrichment through a datacenter ASN (residential-egress invariant).
- **NFR-3 security:** cloud API keys via env only, never committed; admin routes stay API-key gated; forbidden literals stay out of the repo.
- **NFR-4 resilience:** circuit breakers and checkpoints keep the system operable under partial failure; a systemic failure should stop the run, not silently poison rows.
- **NFR-6 observability:** an active backfill and its pacing stay operator-visible; supervisor restarts recover without operator action.
- **NFR-2 config discipline:** all settings via `AppConfig` / `configs/app_config.yaml` (+ env) — no scattered env reads. When a config key's *meaning* changes, its documented meaning in the YAML changes with it.
- **Primary-stack inviolability:** no compose action against the primary project may be introduced in any gate or script; `validate.sh` / `finish-feature.sh` must remain primary-safe (runnable during a live backfill).
- **Validation gates:** AI client/prompt changes run `validate-ai.sh`; API schema changes update/run the contract suite; DB schema changes run `alembic check`. Every fix ships a regression test that fails before it.

## Technical Decisions

- **AD-13 (cloud assist, bounded):** exactly one Redis pacer namespace owns the daily quota — no second consumer ever. At most one runner instance holds the backfill lease; CLI and admin share it, and budget consumption is atomic under that lease. A supervised runner must not create a second pacer, a second lease holder, or a double-start on restart.
- **AD-4 / AD-10 (second driver, never second writer):** the backfill runner drives the single ordered enrichment pipeline authority; it does no GPU work and therefore bypasses the `ai` queue and GPU semaphore by construction. Any future local-backend mode would have to go through that queue + semaphore.
- **AD-1 (hexagonal boundary):** `core` must not import `adapters` or `api`. The runner core is the main file this epic edits — add no new leaks.
- **AD-6 (admin surface):** admin/backfill endpoints stay auth-gated at the API edge and audited.
- **Failure signalling:** distinguish a systemic client failure from a legitimate result by a **typed marker on the fallback result** plus a consecutive-fallback circuit breaker in the run loop — never by string-matching the analysis text. The local-backend template-fallback behaviour and the already-shipped quota back-off path must be preserved unchanged.
- **Budget accounting:** reconcile the reservation against the client's real request/retry counters after each row, via a settle operation built on the existing atomic Lua reserve. Existing budget state written under the old semantics must migrate or roll without granting a run a second day's spend. Continuous-mode back-off, window-roll, and stall-detector branches must be re-verified against the new quantity.
- **Checkpoint semantics:** checkpoint advance is currently an unconditional write to a key shared by every runner, while in-flight rows always drain by design. The fix is either a monotonic compare-and-set on the id ordering or a lease-gated advance — whichever is chosen, record the trade-off, because the same call also records genuinely completed work that must not be lost. The drain must still complete (no cancelled mid-enrichment), and the checkpoint rule must express the *same* handover policy as the existing state-publish guard, not a second divergent one.
- **Hosting choice is an ADR:** the runner's committed home (systemd unit, dedicated compose service, or promotion to a supported entrypoint) is an architecture decision recorded with its rationale, plus an operator-visible install/upgrade step in the feature doc.
- **Testing tiers:** the runner core and budget/checkpoint logic are pure-domain surfaces — TDD with branch coverage (below/at threshold, recovery, interleaving with quota back-off; under/at/over cap, heavy-retry rows, rows failing before sending; real handover with owner losing the lease mid-drain). Existing Lua-contention guarantees must still hold, re-derived against the new quantities.

## UX & Interaction Patterns

No new UI surfaces. Two contract rules from the shipped Operações surface still bind: reported runner presence and pacing must be honest (absent rather than fabricated when no run is active — no fake ETA or throughput), and the operator-facing states/labels already shipped for the backfill card keep their pt-BR wording and wire enum values unchanged.

## Cross-Story Dependencies

- **Epic 3 gates Epic 2.** Stories 3.2, 3.3 and 3.4 govern what the enrichment pipeline writes; Epic 2's cohort percentile work computes over that corpus, so it must not start while fabricated scores are still accruing.
- **Within the epic:** 3.1 is independent of 3.2–3.4 (hosting vs runner internals) but must not run concurrently with them. 3.4 depends on 3.3 — both edit the same runner core file. 3.2 and 3.3 can run in parallel with each other once 3.1 has landed.
- **Upstream:** all four build on Epic 1 (closed) — the canonical task-class enum, the runner control core with its lease/pause/resume semantics, the admin control API, and the Operações card.
