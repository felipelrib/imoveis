# Epic 3 Context: Enrichment Hardening & Operability

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Make the cloud backfill Epic 1 productized actually runnable from the surface built for it, and make the corpus it writes trustworthy. The admin Start button originally only recorded a request that nothing consumed unless a hand-started dev script happened to be alive; a systemic AI-client failure (revoked key, retired model id, transport outage) writes a fabricated `0.5` score that permanently retires the row from the candidate set; the daily budget counts properties while the provider counts requests, so the never-exceed guarantee can undercount by an order of magnitude exactly when the account is throttled; and a displaced runner's draining rows can rewind its successor's checkpoint and double-count progress. Hosting the runner (3.1, landed) then exposed a second-order gap: the enablement path the operator is told to use is not the one that works, and the runner's env file is also the test gate's env file. This epic is not new scope — it completes FR-28's stated outcome and closes the corpus-integrity and operability gaps Epic 1's review passes and 3.1's operator handoff found (ledger items DW-27, DW-17, DW-18, DW-11, DW-31, DW-33). It gates Epic 2: percentile work computes over this corpus, so fabricated scores must stop accruing first.

## Stories

- Story 3.1: Backfill runner hosting — a committed home for the consumer *(done)*
- Story 3.2: Non-quota AI failures must not fabricate a score
- Story 3.3: The daily budget must count requests, not properties
- Story 3.4: Checkpoint advance semantics under lease loss
- Story 3.5: Runner env contract — correct enablement surface, honest preflight, no test-gate collision

## Requirements & Constraints

- **FR-28 (completing the stated outcome):** the backfill runner must be an operator-facing operation, not a request queued into the void — start/pause/resume works without a manual host-side step, reported runner presence reflects reality, and the *documented* way to enable cloud backfill must be the way that actually works. Interruption at any point (crash, quota exhaustion, operator stop, host reboot) resumes without re-enriching completed rows.
- **FR-27 / FR-29 (hardening the delivered surface):** quota exhaustion and provider errors back off or degrade to local — never an outage, never a fabricated result. Coverage/progress figures stay honest under failure and handover.
- **Never-exceed budget:** the configured daily budget must be about the provider's real request-per-day count. Reservation stays atomic; rollback preserved. Quota sizing basis is unchanged: free-tier Gemma ≈ 30 RPM / 14,400 RPD best case, ~3 requests/property ⇒ ≈4,600 properties/day ⇒ a whole-DB pass is inherently multi-day (~6-day planning basis). Never plan single-day whole-DB cloud runs.
- **NFR-1 local-first, bounded cloud assist:** cloud assist may accelerate backfill, never gate core function; the local path is never removed. **The shipped `configs/app_config.yaml` must stay all-local, and that invariant is pinned by an existing unit test** — cloud opt-in is a per-host decision, never a committed config edit. Hosting work must not move the runner off-box, and nothing may route scraping or enrichment through a datacenter ASN (residential-egress invariant).
- **NFR-2 config discipline:** all settings via `AppConfig` / `configs/app_config.yaml` (+ env overrides) — no scattered env reads in feature code. When a config key's *meaning* changes, its documented meaning in the YAML changes with it. Any check that reasons about effective configuration must consider **both** inputs (YAML and env override), not one of them.
- **NFR-3 security:** cloud API keys via env only, never committed; admin routes stay API-key gated; forbidden literals stay out of the repo.
- **NFR-4 resilience:** circuit breakers and checkpoints keep the system operable under partial failure; a systemic failure should stop the run, not silently poison rows.
- **NFR-6 observability:** an active backfill and its pacing stay operator-visible; supervisor restarts recover without operator action; operator-facing preflight/diagnostics must be honest in both directions (no false "broken" for a working host, no missing warning for a genuinely unconfigured one).
- **Operator-doc coherence:** every operator-facing surface (setup/deployment docs, env template, installer messages, feature docs) must name the same sanctioned enablement path; a runbook step that reddens the merge gate or dirties the worktree is a defect, not a caveat.
- **Primary-stack inviolability:** no compose action against the primary project may be introduced in any gate or script; `validate.sh` / `finish-feature.sh` must remain primary-safe (runnable during a live backfill).
- **Gate integrity:** the test suite must stay green with a fully-populated operator env file present on the host. Fixes to env bleed are structural (one mechanism), never per-test-module patches, and a gate is never weakened to reach green.
- **Validation gates:** AI client/prompt changes run `validate-ai.sh`; API schema changes update/run the contract suite; DB schema changes run `alembic check`. Every fix ships a regression test that fails before it.

## Technical Decisions

- **AD-13 (cloud assist, bounded):** exactly one Redis pacer namespace owns the daily quota — no second consumer ever. At most one runner instance holds the backfill lease; CLI and admin share it, and budget consumption is atomic under that lease. A supervised runner must not create a second pacer, a second lease holder, or a double-start on restart. Enabling cloud for backfill task classes must not make the live/incremental Celery path cloud-routed.
- **AD-4 / AD-10 (second driver, never second writer):** the backfill runner drives the single ordered enrichment pipeline authority; it does no GPU work and therefore bypasses the `ai` queue and GPU semaphore by construction. Any future local-backend mode would have to go through that queue + semaphore.
- **AD-1 (hexagonal boundary):** `core` must not import `adapters` or `api`. The runner core is the main file this epic edits — add no new leaks.
- **AD-6 (admin surface):** admin/backfill endpoints stay auth-gated at the API edge and audited.
- **Enablement surface:** per-host cloud routing is expressed as an env override consumed by the same config loader that reads the YAML (the installed supervisor already reads the host env file). Overrides set individual routing leaves over the YAML-loaded map so the map stays total for the startup validator, and nothing enters git.
- **Env-file scoping:** the host runner's env contract and the validation harness's sourced env are currently the same file. The resolution is one deliberate structural choice — a separate `EnvironmentFile` for the unit, a narrowed set of keys sourced by the validation script, or suite-wide stripping of the app's env-override prefix — recorded with its rationale, with any existing per-module guard folded into the winning mechanism rather than left as a divergent copy.
- **Failure signalling:** distinguish a systemic client failure from a legitimate result by a **typed marker on the fallback result** plus a consecutive-fallback circuit breaker in the run loop — never by string-matching the analysis text. The local-backend template-fallback behaviour and the already-shipped quota back-off path must be preserved unchanged.
- **Budget accounting:** reconcile the reservation against the client's real request/retry counters after each row, via a settle operation built on the existing atomic Lua reserve. Existing budget state written under the old semantics must migrate or roll without granting a run a second day's spend. Continuous-mode back-off, window-roll, and stall-detector branches must be re-verified against the new quantity.
- **Checkpoint semantics:** checkpoint advance is currently an unconditional write to a key shared by every runner, while in-flight rows always drain by design. The fix is either a monotonic compare-and-set on the id ordering or a lease-gated advance — whichever is chosen, record the trade-off, because the same call also records genuinely completed work that must not be lost. The drain must still complete (no cancelled mid-enrichment), and the checkpoint rule must express the *same* handover policy as the existing state-publish guard, not a second divergent one.
- **Hosting choice is an ADR:** the runner's committed home is an architecture decision recorded with its rationale, plus an operator-visible install/upgrade step in the feature doc.
- **Testing tiers:** the runner core and budget/checkpoint logic are pure-domain surfaces — TDD with branch coverage (below/at threshold, recovery, interleaving with quota back-off; under/at/over cap, heavy-retry rows, rows failing before sending; real handover with owner losing the lease mid-drain). Shell/installer and env-contract work is characterized by tests over rendered/resolved output rather than live hosts. Existing Lua-contention guarantees must still hold, re-derived against the new quantities.

## UX & Interaction Patterns

No new UI surfaces. Two contract rules from the shipped Operações surface still bind: reported runner presence and pacing must be honest (absent rather than fabricated when no run is active — no fake ETA or throughput), and the operator-facing states/labels already shipped for the backfill card keep their pt-BR wording and wire enum values unchanged. The same honesty rule extends to CLI/installer operator output.

## Cross-Story Dependencies

- **Epic 3 gates Epic 2.** Stories 3.2, 3.3 and 3.4 govern what the enrichment pipeline writes; Epic 2's cohort percentile work computes over that corpus, so it must not start while fabricated scores are still accruing. Story 3.5 touches no enrichment-write path and carries no Epic 2 gate.
- **Within the epic:** 3.1 (landed) was the serial first wave. 3.2 and 3.3 run in parallel; 3.4 depends on 3.3 — both edit the same runner core file. 3.5 has **no gate**: it shares no files with 3.2–3.4 and runs parallel to all of them, but it is corrective work on 3.1's delivery, so it depends on 3.1 being in place.
- **Upstream:** all stories build on Epic 1 (closed) — the canonical task-class enum and its startup validator, the runner control core with its lease/pause/resume semantics, the admin control API, and the Operações card.
