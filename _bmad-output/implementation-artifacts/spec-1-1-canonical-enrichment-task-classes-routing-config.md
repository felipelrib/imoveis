---
title: 'Canonical enrichment task classes + per-task-class routing config'
type: 'feature'
created: '2026-08-05'
status: 'done'
baseline_revision: 'ec689fe60040a96bc8b2ca695f6d0d6f252e608e'
final_revision: 'squash-merged to main by finish-feature.sh (see main git log)'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/CLAUDE.md'
warnings: []
---

<intent-contract>

## Intent

**Problem:** Enrichment has no shared vocabulary of signal types (they live as scattered meta keys `"visual"`/`"sentiment"`/`"deal_verdict"`, columns, and `STAGES_*` constants), and backend selection is a single unconstrained scalar `ai.backend` that would silently make unmetered cloud calls on the live path if set to `gemini`/`gemma`. Routing, backfill scope, and coverage each risk inventing their own words.

**Approach:** Introduce ONE canonical enum of enrichment task classes/signal types in `src/core/` (framework-free), and give `AppConfig` a per-task-class → backend routing map that supersedes the scalar `ai.backend` as the source of truth, with a single startup validator that fails fast on unknown backend, unknown task class, or a cloud backend on the live path (the legacy scalar).

## Boundaries & Constraints

**Always:** The enum lives in `src/core/` with no `adapters`/`api` imports (AD-1). Validation runs at config load and raises `ConfigError` naming the offending key (fail-fast, never mid-pipeline). Cloud backends (`gemini`/`gemma`) are permitted as routing-map values (backfill-eligibility, AD-13) but forbidden as the live-path scalar `ai.backend`. Default shipped config routes every task class to a local backend and validates clean (NFR-1). Config tests clear `get_config()`'s `lru_cache`.

**Block If:** The intent is fully resolved; nothing here requires human input. (No operator-only external actions exist for this story.)

**Never:** Do NOT wire live routing (`create_ai_client`/`enrich_pipeline.py`/`client.py` — that is story 1.2), backfill scope (`enrichment_rerun.py` `STAGES_*` — story 1.3), or coverage (`src/api/system.py` — story 1.4). Do NOT change AI prompts or clients. Do NOT remove the local path or the single Redis pacer. Do NOT add a `core → adapters/api` import. Do NOT touch the primary docker stack.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Default config | `ai.backend: ollama`, routing all-local | Loads; every `EnrichmentTaskClass` maps to a local backend | No error |
| Cloud eligible for backfill | routing `sentiment: gemma` | Loads clean (cloud allowed as routing value) | No error |
| Unknown backend in map | routing `visual: frobnicate` | Config load fails | `ConfigError` naming `ai.enrichment_routing.visual` + bad value |
| Unknown task class in map | routing `frobnicate: ollama` | Config load fails | `ConfigError` naming the unknown key |
| Legacy cloud scalar | `ai.backend: gemini` (or `gemma`) | Config load fails | `ConfigError` naming `ai.backend`, stating cloud is backfill-only |
| Unknown scalar backend | `ai.backend: frob` | Config load fails | `ConfigError` naming `ai.backend` |
| Local scalar | `ai.backend: lmstudio` | Loads clean | No error |

</intent-contract>

## Code Map

- `src/core/enrichment.py` -- NEW. Canonical `EnrichmentTaskClass(str, Enum)` (`visual`, `sentiment`, `deal_verdict`, `valuation`, `embedding`) + `EnrichmentBackend(str, Enum)` (`ollama`, `lmstudio`, `gemini`, `gemma`) with `LOCAL_BACKENDS`/`CLOUD_BACKENDS` frozensets and an `is_cloud_backend` helper. Framework-free, no adapter/api imports.
- `src/infra/config.py` -- `AIConfig` (lines ~157-192) gains `enrichment_routing: dict[str, str]` (default_factory → all task classes to `ollama`) and the file's first `@model_validator(mode="after")` enforcing the three checks; imports the core enums (infra→core is the sanctioned direction; `ConfigError` is already imported from core).
- `configs/app_config.yaml` -- document the `ai.enrichment_routing:` block (all-local) with semantics: map is backfill-eligibility only; live path always local; cloud values allowed here, forbidden on `ai.backend`.
- `src/tests/unit/test_enrichment.py` -- NEW. TDD unit tests for the enums + backend classification helpers.
- `src/tests/unit/test_config.py` -- add validation branch tests (default/unknown-backend/unknown-task-class/cloud-eligible/legacy-cloud-scalar/unknown-scalar/local-scalar), reusing the autouse `_clear_config_env` fixture + `MINIMAL_YAML`/`_write_yaml` helpers.

## Tasks & Acceptance

**Execution:**
- [x] `src/core/enrichment.py` -- create the canonical enums + `LOCAL_BACKENDS`/`CLOUD_BACKENDS`/`is_cloud_backend` -- one shared vocabulary (AD-1, canonical-vocabulary convention).
- [x] `src/tests/unit/test_enrichment.py` -- TDD: assert member values equal the canonical strings, cloud/local classification, and that `EnrichmentTaskClass`/`EnrichmentBackend` round-trip as `str`.
- [x] `src/infra/config.py` -- add `enrichment_routing` field + `@model_validator(mode="after")` doing all three checks with clear key-naming `ValueError`s (wrapped to `ConfigError` by `load_config`).
- [x] `src/tests/unit/test_config.py` -- add the I/O-matrix branch tests (valid/invalid/legacy-scalar) via `load_config(temp_yaml)`.
- [x] `configs/app_config.yaml` -- add documented `ai.enrichment_routing:` all-local block.

**Acceptance Criteria:**
- Given the codebase, when this story lands, then a single enum of enrichment task classes exists in `src/core/enrichment.py` with no adapter/api imports, and the routing map in `AppConfig` is keyed by it.
- Given an invalid backend/task-class combination or the legacy cloud scalar, when config loads, then startup fails with a `ConfigError` naming the offending key — never a mid-pipeline failure.
- Given the default shipped `configs/app_config.yaml`, when config loads, then all task classes route to a local backend and validation passes.
- Given the AI client factory tests that mock `cfg.ai` directly, when this lands, then they still pass (the validator runs in `load_config`, not `create_ai_client`) — no live-routing behavior changes in this story.

## Design Notes

The routing map is **backfill-eligibility only** (AD-13): the live/incremental path always uses local backends (enforced in story 1.2), so cloud (`gemini`/`gemma`) is a legal *routing value* but an illegal *scalar `ai.backend`* (the scalar is the live-path selector). This is why the same validator both accepts `sentiment: gemma` in the map and rejects `ai.backend: gemma`.

`VALUATION` is statistical (no model call) and simply carries no cloud routing — it exists in the enum so coverage (story 1.4) and backfill scope (story 1.3) speak the same words; those stories adopt the enum, this story does not edit their files (sequencing gates 1.3←1.1, 1.4←1.1). The routing map is the source of truth downstream stories index by task class, so the validator requires it to be **total** — every `EnrichmentTaskClass` must have an entry (a partial map fails fast at load rather than surfacing as a `KeyError` mid-pipeline). Omitting the whole block falls back to the all-local `default_factory`.

Validator sketch (single `@model_validator(mode="after")` on `AIConfig`, using the public `is_valid_backend`/`is_valid_task_class`/`is_cloud_backend` helpers from `core.enrichment`; the "expected one of …" lists are derived from the enums so they cannot drift):
```python
if not is_valid_backend(self.backend):
    raise ValueError(f"ai.backend: unknown backend '{self.backend}' (expected one of {valid_backends})")
if is_cloud_backend(self.backend):
    raise ValueError("ai.backend: cloud backend on the live path; cloud is backfill-only — route it via ai.enrichment_routing")
for tc, be in self.enrichment_routing.items():
    if not is_valid_task_class(tc): raise ValueError("ai.enrichment_routing: unknown task class ...")
    if not is_valid_backend(be):   raise ValueError(f"ai.enrichment_routing.{tc}: unknown backend ...")
missing = [tc.value for tc in EnrichmentTaskClass if tc.value not in self.enrichment_routing]
if missing: raise ValueError(f"ai.enrichment_routing: missing task classes {missing} — every task class must be routed")
return self
```

## Spec Change Log

### 2026-08-05 — Review pass 1 (patch-level, no code re-derivation)
- **Triggering finding:** both adversarial reviewers flagged that the routing map only validated *present* keys, so a partial/empty map (or a partial `IMOVEIS_AI__ENRICHMENT_ROUTING__*` env override) passed validation and would surface as a `KeyError` when stories 1.2/1.3/1.4 index `routing[task_class]`.
- **Amended:** Design Notes — the map is now required to be **total** (validator raises on missing task classes). Superseded the earlier "may omit a task class; only present keys are validated" wording.
- **Known-bad state avoided:** silent partial routing that becomes a mid-pipeline `KeyError` in a downstream story instead of a clear config-load error.
- **KEEP:** cloud (`gemini`/`gemma`) stays legal as a routing *value* (backfill-eligibility) and illegal as the scalar `ai.backend`; the all-local `default_factory` (complete by construction) and the documented shipped-YAML block are preserved.

## Review Triage Log

### 2026-08-05 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 3 (medium 1, low 2)
- defer: 0
- reject: 9
- addressed_findings:
  - `[medium]` `[patch]` Partial/empty routing map silently accepted (both hunters) — added an exhaustiveness check so the map must cover every `EnrichmentTaskClass`; also converts partial env overrides into a clear startup error. Updated the cloud-value test to a full map + added a partial-map regression test.
  - `[low]` `[patch]` Private `Enum._value2member_map_` + inconsistent membership mechanisms + hardcoded "expected one of …" literals — added public `is_valid_backend`/`is_valid_task_class` helpers in `core.enrichment`, used them throughout the validator, and derived the message lists from the enums.
  - `[low]` `[patch]` Comments/docstring read as current-state — clarified the `enrichment_routing` field comment and module docstring to mark routing consumption as story-1.2 future state.
  - Rejected (9): `create_ai_client` gemini branch "regression" (the startup rejection is the story's mandated AD-13 behavior; `client.py` is story 1.2's file); cloud-routing-without-`GEMINI_API_KEY` at load (would violate NFR-1 degrade-to-local); frozen dict in-place mutation, duplicate YAML keys, scalar-env-over-dict (pre-existing repo-wide behaviors); factory-vs-YAML drift (now a loud error via exhaustiveness); `backend` bare-str typing (kept for clearer errors).

## Verification

**Commands:**
- `bash scripts/agent/validate.sh fast` -- expected: lint + unit green (new `test_enrichment.py` + `test_config.py` branches pass).
- `bash scripts/agent/validate.sh all` -- expected: full gate green (run by `finish-feature.sh`). `validate-ai.sh` is NOT required — no AI prompt/client change. Contract/alembic hooks do not trigger (no API-schema/DB change).

## Auto Run Result

Status: **done** (1 review pass, patch-level only — no intent-gap/bad-spec loopback).

**Implemented change:** A single canonical enrichment vocabulary (`EnrichmentTaskClass` / `EnrichmentBackend` + local/cloud classification and validity helpers) in `src/core/enrichment.py`, and a per-task-class `enrichment_routing` map on `AIConfig` that supersedes the scalar `ai.backend`, with the file's first `@model_validator` failing fast at config load on: unknown/cloud scalar backend, unknown routing task class/backend, and a non-total routing map. Default (and shipped YAML) route every task class to local Ollama.

**Files changed:**
- `src/core/enrichment.py` — NEW canonical enums + `LOCAL_BACKENDS`/`CLOUD_BACKENDS` + `is_cloud_backend`/`is_valid_backend`/`is_valid_task_class`.
- `src/infra/config.py` — `AIConfig.enrichment_routing` field + `@model_validator(mode="after")` (backend/task-class/cloud-on-live/exhaustiveness checks, enum-derived messages).
- `configs/app_config.yaml` — documented all-local `ai.enrichment_routing` block (backfill-vs-live semantics).
- `src/tests/unit/test_enrichment.py` — NEW TDD unit tests (values, partition, is_cloud/valid helpers, str-membership).
- `src/tests/unit/test_config.py` — validation branch tests (default/unknown-backend/unknown-task-class/cloud-value/partial-map/cloud-scalar/unknown-scalar/local-scalar).
- Plus feature doc `docs/features/v0.13-s1.1-*.md` and sprint-status (`1-1 → done`, `epic-1 → in-progress`).

**Review findings breakdown:** 3 patches applied (1 medium: routing-map exhaustiveness; 2 low: public validity helpers/enum-derived messages, comment/docstring precision). 0 deferred. 9 rejected (see Review Triage Log — intended AD-13 behavior, NFR-1 conflicts, pre-existing repo-wide patterns).

**Follow-up review recommended:** false — the fixes are localized to one validator + the vocabulary module, low-consequence, and fully covered by new tests; no API/security/data-shape impact.

**Verification:** `bash scripts/agent/validate.sh fast` → green twice (post-implementation and post-review-patch): 1416 passed, 1 skipped; pre-commit lint clean, no fixer modifications. Full `validate.sh all` runs as part of `finish-feature.sh` at merge.

**Residual risks:** none material. The scalar `ai.backend` cloud branch in `src/adapters/ai/client.py` is now unreachable via a validated config and is scheduled for refactor in story 1.2 (left untouched to respect scope).
