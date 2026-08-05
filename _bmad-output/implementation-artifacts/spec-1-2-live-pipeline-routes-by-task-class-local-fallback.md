---
title: 'Live pipeline routes by task class with local fallback'
type: 'feature'
created: '2026-08-05'
baseline_revision: 'e0ce58cc667405f4d1cf04d4b27998aa85b8d804'
final_revision: 'squash-merged to main by finish-feature.sh (see main git log)'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/CLAUDE.md'
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** The live Celery `ai`-queue pipeline builds one client from the scalar `cfg.ai.backend` and passes it uniformly to every task class (`tasks.ai_enrich` L821, `tasks.embed_property` L969). Story 1.1's per-task-class `enrichment_routing` map exists and is validated but is consumed nowhere — incremental enrichment cannot route per task class, and there is no single authority that decides cloud-vs-local (degrading to local when cloud is unavailable).

**Approach:** Introduce ONE routing resolver in `src/adapters/ai/client.py` that maps a task class → concrete backend from `cfg.ai.enrichment_routing`, degrading cloud entries to the operator's validated-local scalar. Wire the live path to it via a per-task-class dispatching `RoutingAIClient` (visual/sentiment/deal_verdict) and `create_ai_client(task_class=…)` (embedding), so incremental work resolves per task class and never touches cloud. The resolver also carries a `for_backfill` mode (cloud honored only when a key is present, else degrade) — delivered and unit-tested here as the single authority story 1.3's runner will consume.

## Boundaries & Constraints

**Always:** Live/incremental enrichment resolves each task class's backend from `enrichment_routing` and only ever executes on a **local** backend — any cloud (`gemini`/`gemma`) routing entry degrades to `cfg.ai.backend` (validated non-cloud by story 1.1) on the live path (AD-13, AD-4). No model call happens inline from an API request thread (unchanged — work stays on the `ai` queue under the GPU semaphore). The resolver is the single source of truth for backend selection; degradation is silent (a warning log, never a failure) and never marks a property failed (NFR-4). AI scores stay floats in `[0.0, 1.0]`. `core` gains no `adapters`/`api` import.

**Block If:** The intent is fully resolved; nothing requires human input. (No operator-only external actions exist for this story.)

**Never:** Do NOT restructure the backfill runner or its execution model — `src/core/backfill_runner.py` and `scripts/dev/backfill_gemma.py` are story 1.3's exclusive domain (1.2 ∥ 1.3 are parallel; touching them creates a merge conflict). Do NOT make the backfill execute local work inline (AD-4: a local backfill mode routes through the `ai` queue + semaphore — that wiring is story 1.3). Do NOT change AI prompts, result schemas, or the cloud client classes / `_gemini_client_for` (backfill still needs them). Do NOT remove the scalar cloud branch in `create_ai_client()` (defensive, still used by `task_class=None` callers). Do NOT touch coverage (`system.py`, story 1.4) or the primary docker stack.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Live local-default | routing `visual: ollama`, scalar `ollama`, `for_backfill=False` | resolves `ollama` | No error |
| Live local-explicit | routing `sentiment: lmstudio`, scalar `ollama` | resolves `lmstudio` (map wins for local values) | No error |
| Live cloud degrade | routing `visual: gemma`, scalar `ollama`, `for_backfill=False` | resolves `ollama` (degrade to scalar-local); warning logged | No error, never cloud |
| Backfill cloud-eligible | routing `deal_verdict: gemma`, `for_backfill=True`, `GEMINI_API_KEY` set | resolves `gemma` (cloud honored) | No error |
| Backfill cloud unavailable | routing `deal_verdict: gemma`, `for_backfill=True`, no key | resolves scalar-local (`ollama`); warning logged | No error, never failure (NFR-4) |
| RoutingAIClient dispatch | routing `visual: ollama`, `sentiment: lmstudio` | `analyze_visuals`→Ollama client, `analyze_text`→LMStudio client; distinct backends → distinct clients, shared backend → one client | No error |
| RoutingAIClient never cloud | any routing with cloud entries, live | every underlying client is local | No error |

</intent-contract>

## Code Map

- `src/adapters/ai/client.py` -- add `resolve_enrichment_backend(task_class, cfg, *, for_backfill=False) -> str` (routing lookup + cloud→local-scalar degrade), `cloud_available(cfg) -> bool` (`bool(cfg.ai.gemini_api_key)`), a `_build_local_client(backend, cfg)` helper (extract the ollama/lmstudio construction currently inline in `create_ai_client`), a `RoutingAIClient(LocalAIClient)` that dispatches `analyze_visuals`/`analyze_text`/`summarize_deal`/`embed` to per-task-class local clients (built once per distinct backend) and composes their `session_context()`s via `AsyncExitStack`, and `create_enrichment_client(cfg=None, task_classes=…) -> RoutingAIClient`. Extend `create_ai_client(task_class=None)`: when `task_class` is given, resolve a **local** backend and build it (never the cloud branch); `task_class=None` keeps today's scalar behavior (incl. the defensive cloud branch) verbatim.
- `src/adapters/queue/tasks.py` -- `ai_enrich`: replace `create_ai_client()` (L821) with `create_enrichment_client(cfg, task_classes=<stage-appropriate set>)`; add a tiny stage→task-classes map (`STAGES_ALL`→visual+sentiment+deal_verdict, `STAGES_VISUAL_SENTIMENT`→visual+sentiment, `STAGES_VERDICT_ONLY`→deal_verdict). `embed_property`: `create_ai_client()` (L969) → `create_ai_client(task_class=EnrichmentTaskClass.EMBEDDING)`. `run_enrichment`/`_write_deal_verdict`/`analyze_visual_and_sentiment` signatures unchanged (they receive the dispatching client).
- `src/core/enrichment.py` -- (read-only) source of `EnrichmentTaskClass`, `is_cloud_backend`. No change.
- `src/tests/unit/test_ai_routing.py` -- NEW. TDD for the resolver (all matrix branches), `cloud_available`, `create_ai_client(task_class=…)` returns a local client even for a cloud routing entry, and `RoutingAIClient` dispatch/dedup/never-cloud (mocked clients).
- `src/tests/unit/test_ai_enrich_stages.py` -- update the three `tasks_mod.create_ai_client` patch sites to `tasks_mod.create_enrichment_client`; keep the stage-branching assertions.

## Tasks & Acceptance

**Execution:**
- [x] `src/adapters/ai/client.py` -- add resolver + `cloud_available` + `_build_local_client` + `RoutingAIClient` + `create_enrichment_client`; extend `create_ai_client(task_class=…)` for local per-class resolution (scalar path unchanged) -- single routing authority, live path never cloud (AD-13/AD-4).
- [x] `src/tests/unit/test_ai_routing.py` -- TDD the I/O matrix: resolver local-default/local-explicit/cloud-degrade (live) and cloud-eligible/cloud-unavailable (backfill); `create_ai_client(task_class=…)` local-only; `RoutingAIClient` per-class dispatch, backend dedup, and never-cloud.
- [x] `src/adapters/queue/tasks.py` -- wire `ai_enrich` to `create_enrichment_client` (stage-scoped task classes) and `embed_property` to `create_ai_client(task_class=EMBEDDING)` -- live routing per task class.
- [x] `src/tests/unit/test_ai_enrich_stages.py` -- repoint the `create_ai_client` patches to `create_enrichment_client`; assert the stage set still drives VLM/download/verdict branching.
- [x] `docs/features/v0.13-s1.2-live-pipeline-routes-by-task-class-local-fallback.md` -- NEW feature doc (harness-required by `finish-feature.sh`; template-conformant).

**Acceptance Criteria:**
- Given the routing map, when the live `ai`-queue pipeline enriches a property, then each task class's backend is resolved from the map and only local backends ever execute on the live path (cloud entries degrade to the local scalar); no model call runs inline from an API request thread (unchanged).
- Given a cloud-eligible task class with cloud unavailable (no `GEMINI_API_KEY`), when the resolver runs in `for_backfill` mode, then it resolves to the local scalar backend (degrade, warning logged) without raising — the tested contract story 1.3's runner consumes.
- Given the AI client surface changed, when the story completes, then `bash scripts/agent/validate-ai.sh` passes, contract tests still hold (scores remain floats in `[0,1]`), and routing resolution has unit coverage for local-default, cloud-eligible, and degraded branches.

## Review Triage Log

### 2026-08-05 — Review pass 1 (patch-level only, no spec/intent loopback)
- intent_gap: 0
- bad_spec: 0
- patch: 7: (high 0, medium 2, low 5)
- defer: 0
- reject: 2: (high 0, medium 0, low 2)
- addressed_findings:
  - `[medium]` `[patch]` Query-side embedding still used the bare scalar (`api/properties.py::_get_embedding_client`) while `tasks.embed_property` now routes via the map — an `enrichment_routing.embedding` differing from the scalar would produce query vectors in a different space than stored vectors and silently corrupt semantic search. Routed the read side through `create_ai_client(task_class=EMBEDDING)`; added a regression test asserting the kwarg.
  - `[medium]` `[patch]` `_build_local_client` silently coerced any non-`lmstudio` string (incl. cloud `gemini`/`gemma`) to Ollama. Added an `is_cloud_backend` guard that raises on a cloud value (protects the story-1.3 backfill seam) while preserving the historical unknown-non-cloud → Ollama default. Tests for both.
  - `[low]` `[patch]` Live-path cloud degrade logged at WARNING → once per task class per property = log flood for an expected steady state. Demoted the live (`for_backfill=False`) degrade to DEBUG; the backfill no-key degrade stays WARNING (operator misconfiguration). Tests updated.
  - `[low]` `[patch]` `cloud_available` treated a whitespace-only key as present. Now `.strip()`s — a whitespace key is absent (would fail auth). Test added.
  - `[low]` `[patch]` `RoutingAIClient` inherited the base `__aenter__/__aexit__`, which manage only its own empty-URL session — an `async with client:` caller would leak the underlying sessions. Overrode both to open/close every underlying client's session; documented that `session_context()` yields `self` (folds the "yields self vs raw session" note). Test added.
  - `[low]` `[patch]` `create_enrichment_client(task_classes=())` provisioned nothing (empty tuple ≠ None). Now `if not task_classes` defaults to the live trio. Test added.
  - `[low]` `[patch]` `RoutingAIClient.close()` aborted remaining teardown if one client's `close()` raised. Made it best-effort (suppress + warn). Test added.
  - Rejected (2): partial/missing routing-map key → `KeyError` in the resolver — story 1.1's validator enforces map **totality** by design (fail-loud at load); a silent `.get() or scalar` fallback here would undermine that invariant. Stage→task-classes `KeyError` if `STAGES` grows — fully defended by the `stages ∈ STAGES` clamp at the top of `ai_enrich`.

## Design Notes

**Degrade target = the scalar.** `resolve_enrichment_backend` degrades a cloud routing value to `cfg.ai.backend` (not a hardcoded `ollama`): the scalar is the operator's chosen local backend, validated non-cloud by story 1.1, so it is the correct live-path fallback. A *local* routing value (e.g. `sentiment: lmstudio`) is honored directly — the map is the source of truth; only cloud values degrade.

```python
def resolve_enrichment_backend(task_class, cfg, *, for_backfill=False) -> str:
    routed = cfg.ai.enrichment_routing[task_class.value]
    if is_cloud_backend(routed):
        if for_backfill and cloud_available(cfg):
            return routed                 # cloud honored only for backfill + key present
        return cfg.ai.backend             # degrade to validated-local scalar (NFR-4)
    return routed
```

**Why `RoutingAIClient` and not one client:** AC-1 requires *each* task class resolved from the map; a single shared client would silently ignore a map that routes visual/sentiment/deal_verdict to different local backends. `RoutingAIClient` builds one underlying local client per *distinct* resolved backend (so the default all-`ollama` config builds exactly one client and behaves identically to today) and dispatches each method to its task class's client. It keeps `run_enrichment`/`analyze_visual_and_sentiment`/`_write_deal_verdict` signatures untouched — they still receive one `client` that happens to dispatch — so the stage tests and the `validate-ai.sh` golden path are unaffected.

**1.2 ↔ 1.3 boundary:** the `for_backfill` resolver branch is delivered and unit-tested here (AC-3 "degraded branches") but is **not** wired into the runner — the backfill's local-execution path must go through the `ai` queue + semaphore (AD-4), which is story 1.3's runner work. Story 1.2 touches neither `backfill_runner.py` nor `backfill_gemma.py`, keeping 1.2 ∥ 1.3 conflict-free.

## Verification

**Commands:**
- `bash scripts/agent/validate.sh fast` -- expected: lint + unit green (new `test_ai_routing.py` + updated `test_ai_enrich_stages.py` pass).
- `bash scripts/agent/validate-ai.sh` -- expected: AI-quality golden pass (or CI-safe skip if Ollama unreachable). Merge-blocking AI-client-change gate. From WSL set `OLLAMA_HOST=http://$(ip route show default | awk '/default/{print $3}'):11434` if Ollama binds on Windows.
- `bash scripts/agent/validate.sh all` -- expected: full gate green incl. `src/tests/contract/` (no schema change; scores stay floats in `[0,1]`). Run by `finish-feature.sh`.

## Auto Run Result

Status: **done** (1 review pass, patch-level only — no intent-gap/bad-spec loopback).

**Implemented change:** The live Celery `ai`-queue enrichment pipeline now resolves its backend **per task class** through story 1.1's `enrichment_routing` map. A single routing authority `resolve_enrichment_backend(task_class, cfg, *, for_backfill=False)` maps a task class → concrete backend; on the live path any cloud (`gemini`/`gemma`) routing entry degrades to the operator's validated-local scalar (`cfg.ai.backend`), so incremental enrichment never executes cloud (AD-13/AD-4). A `RoutingAIClient` dispatches `analyze_visuals`/`analyze_text`/`summarize_deal`/`embed` to the local client resolved for VISUAL/SENTIMENT/DEAL_VERDICT/EMBEDDING (one client per distinct backend), keeping `run_enrichment`/`_write_deal_verdict`/`analyze_visual_and_sentiment` signatures untouched. `ai_enrich` builds it stage-scoped; `embed_property` and the semantic-search query path use `create_ai_client(task_class=EMBEDDING)`. The `for_backfill` resolver branch (cloud honored only with a key, else degrade) is delivered + unit-tested as the single authority story 1.3's runner will consume; the runner itself is untouched (1.2 ∥ 1.3).

**Files changed:**
- `src/adapters/ai/client.py` — `resolve_enrichment_backend`, `cloud_available`, `_build_local_client` (with cloud guard), `RoutingAIClient`, `create_enrichment_client`; `create_ai_client(task_class=…)` local per-class resolution (scalar path unchanged).
- `src/adapters/queue/tasks.py` — `ai_enrich` → `create_enrichment_client` (stage→task-class map); `embed_property` → `create_ai_client(task_class=EMBEDDING)`.
- `src/api/properties.py` — `_get_embedding_client` routes the query embedding through the EMBEDDING task class (read/write symmetry — review patch).
- `src/tests/unit/test_ai_routing.py` — NEW (resolver matrix, `cloud_available`, local-only factory, `RoutingAIClient` dispatch/dedup/never-cloud/lifecycle).
- `src/tests/unit/test_ai_enrich_stages.py`, `src/tests/unit/test_properties_embedding_client_cache.py` — updated patch targets + read-side routing regression test.
- `docs/features/v0.13-s1.2-live-pipeline-routes-by-task-class-local-fallback.md` — NEW feature doc.

**Review findings breakdown:** 7 patches applied (2 medium: query-embedding read/write symmetry, `_build_local_client` cloud guard; 5 low: log-flood demotion, whitespace-key `cloud_available`, `RoutingAIClient` `async with` lifecycle, empty-`task_classes` default, best-effort `close`). 0 intent-gap, 0 bad-spec, 0 deferred, 2 rejected (map-totality enforced upstream by design; stage-map defended by the `STAGES` clamp).

**Follow-up review recommended:** true — the review pass introduced changes to `src/api/properties.py` (a read-side API path no adversarial hunter saw in the original diff) with embedding-space data-consistency implications, plus a client-lifecycle contract change; an independent look at the review delta is warranted despite each fix being localized and test-covered.

**Verification:** `bash scripts/agent/validate.sh fast` → green (1442 passed, 1 skipped; lint clean after committing the isort fixer edit). `bash scripts/agent/validate-ai.sh` → green (Ollama reachable; 2 golden tests pass). `bash scripts/agent/validate.sh all` runs at merge via `finish-feature.sh`.

**Residual risks:** Changing the *effective* embedding backend (scalar or `enrichment_routing.embedding`) invalidates previously-stored vectors regardless of this change — a pre-existing operational reality (re-embed after such a config change), not a regression. The `for_backfill` resolver branch is dead until story 1.3 wires it into the runner (intentional, per the 1.2 ∥ 1.3 boundary).
