---
title: 'Runner env contract — correct enablement surface, honest preflight, no test-gate collision'
type: 'bugfix'
created: '2026-08-12'
status: 'awaiting-operator'
baseline_revision: 'a5d6ec134eaf8744e1e382fc523947476ca72560'
final_revision: '6296e0690cc58a9818efe7a73ffb1de0f1f86627'
review_loop_iteration: 1
followup_review_recommended: true
operator_actions:
  - 'Restart the supervisor so it re-reads the env file: `sudo systemctl restart imoveis-backfill-serve`. systemd reads `EnvironmentFile=` only at unit start, so a unit that started before the three `IMOVEIS_AI__ENRICHMENT_ROUTING__*` lines were added to .env.local is still resolving the all-local map and crash-looping.'
  - 'Confirm the restart took: `systemctl status imoveis-backfill-serve` shows active (running) and `journalctl -u imoveis-backfill-serve -n 50` shows no startup refusal about routing or GEMINI_API_KEY.'
  - 'From the primary checkout on main after this merges, run `bash scripts/install-backfill-runner.sh --check` and confirm it prints "Effective backfill routing: gemma for visual sentiment deal_verdict" with no routing warning. (Verified during this run against your current .env.local — it passed, where the pre-fix installer warned the unit "would exit at startup and restart forever".)'
  - 'Press Start on the Operações backfill card with no run in flight and confirm a run begins and the status endpoint reports runner_present true — the end-to-end check no agent can perform.'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
  - '{project-root}/docs/features/v0.13-s3.1-backfill-runner-hosting.md'
  - '{project-root}/docs/adr/0006-backfill-runner-hosting.md'
warnings: ['multiple-goals', 'oversized']
---

<intent-contract>

## Intent

**Problem:** Story 3.1's operator runbook tells the operator to enable the cloud backfill by editing the **committed** `configs/app_config.yaml` — which fails `test_enrichment_routing_default_all_local` (story 1.1's NFR-1 AC) and so leaves only two bad outcomes: commit it and redden `validate.sh` for every later story, or leave it uncommitted and break the loop's clean-worktree precondition. The installer's `routing_has_cloud_backend()` compounds it by awk-grepping the YAML only, so a host correctly configured through the env override the unit already reads is told the unit "would exit at startup and restart forever" (DW-31). Separately, `.env.local` is simultaneously the unit's `EnvironmentFile=` and the file `validate.sh:60` sources wholesale into pytest, so any operator variable becomes ambient suite env — observed 2026-08-12 when the routing override made an unrelated Redis test fail on a partial routing map (DW-33).

**Approach:** Make the **per-host env override the single sanctioned enablement surface** (`IMOVEIS_AI__ENRICHMENT_ROUTING__{VISUAL,SENTIMENT,DEAL_VERDICT}=gemma` in the git-ignored `.env.local`) and say so on every operator-facing surface; teach the installer's preflight to resolve the **effective** routing map (YAML overlaid with the env file's overrides, mirroring `_apply_env_overrides` precedence) instead of one of its two inputs; and close the env collision structurally at the boundary that creates it — `validate.sh` / `finish-feature.sh` load `.env.local` through a **workspace-identity allowlist** in `scripts/agent/lib.sh` instead of `set -a; source`, with a suite-wide `src/tests/conftest.py` guard as the invocation-independent net that the per-module `test_celery_app.py` guard folds into.

## Boundaries & Constraints

**Always:**
- The shipped `configs/app_config.yaml` stays **all-local** and `test_enrichment_routing_default_all_local` keeps pinning it (NFR-1). Cloud opt-in is a per-host, git-ignored decision.
- Preflight honesty runs both ways: no warning for a host whose *effective* routing is cloud, and the warning still fires for a genuinely all-local host (no YAML cloud entry **and** no env override).
- The env allowlist is **default-deny**: a variable an operator adds to `.env.local` tomorrow does not reach pytest unless it is explicitly listed. `PLAYWRIGHT_PORT`, the workspace ports, `COMPOSE_PROJECT_NAME`, the test-DB selectors and `API_KEY`/`JWT_SECRET` keep working exactly as today.
- Secrets stay env-only (NFR-3): no key value is read back, printed or committed; only variable **names** appear in docs, messages and tests.
- The gate stays whole: no test weakened, skipped or marked xfail to reach green; `validate.sh` / `finish-feature.sh` stay primary-stack-safe (no compose action added).
- The suite-wide strip targets the generic `IMOVEIS_<SECTION>__<KEY>` override channel only — the suite's own `IMOVEIS_ALLOW_PRIMARY_*_WIPE` escape hatches carry no `__` and must survive.

**Block If:**
- Narrowing `.env.local` to the allowlist turns any currently-green stage red for a reason that is not a test asserting the old bleed — that means a stage genuinely depends on an operator variable and the allowlist decision needs a human.

**Never:**
- Do not touch `src/core/backfill_runner.py`, `scripts/dev/backfill_gemma.py`, the admin API, or any enrichment-write path — stories 3.2–3.4 own those files and run in parallel with this one.
- Do not add a second `EnvironmentFile` for the unit (rejected alternative — it doubles the operator's env contract and still does not stop `IMOVEIS_*` landing in `.env.local`).
- Do not fix the collision one test module at a time, and do not leave the 2026-08-12 `test_celery_app.py` `IMOVEIS_*` loop in place as a second copy.
- Do not change the committed YAML's routing values, `ai.backend`, or the live Celery path's behaviour.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Cloud via env override | YAML all-local; env file sets `IMOVEIS_AI__ENRICHMENT_ROUTING__VISUAL=gemma` | `--check` reports ready — **no** routing warning | exit 0 |
| Genuinely all-local | YAML all-local; env file sets no routing override | Routing warning naming the env override as the fix (never a YAML edit) | Warning only, install continues |
| Cloud in YAML (legacy host) | YAML routes `visual: gemma`; no override | No routing warning (unchanged) | exit 0 |
| Override sends cloud back local | YAML routes `visual: gemma`; env file sets that class `ollama` | Routing warning — effective map is all-local | Warning only |
| Override hidden from systemd | env file line is `export IMOVEIS_AI__ENRICHMENT_ROUTING__VISUAL=gemma` | Preflight failure: `EnvironmentFile=` is not a shell, the override would not reach the unit | exit ≠ 0 (warn under `--force`/`--print`) |
| Operator env vs the gate | `.env.local` fully populated (key, `DATABASE_URL`, all three routing overrides) | The gate's environment carries the allowlisted workspace keys and **none** of `IMOVEIS_*__*`, `GEMINI_API_KEY`, `DATABASE_URL` | No error; suite green |
| Missing env file | no `.env.local` | Allowlist loader is a no-op; validate falls back to its own defaults | No error |
| Suite-wide guard scope | `IMOVEIS_AI__X=y` and `IMOVEIS_ALLOW_PRIMARY_DB_WIPE=1` in `os.environ` | The first is stripped for every test, the second survives | No error |

</intent-contract>

## Code Map

- `scripts/install-backfill-runner.sh:246-260` -- `routing_has_cloud_backend()` (YAML-only awk) and its warning at `:349-354`; `env_value_of`/`env_key_uses_export` (`:203-232`) are the readers to reuse; the export-prefix fatal loop lives at `:324-333`.
- `scripts/agent/validate.sh:58-60` -- the `set -a; source "$REPO_ROOT/.env.local"` that creates the collision; `:64-69` seeds `API_KEY`/`JWT_SECRET` only when unset; `:100-102` overrides `DATABASE_URL`/`REDIS_URL` from the ephemeral stack; `:190` consumes `PLAYWRIGHT_PORT` via `lib.sh:308-314`.
- `scripts/agent/finish-feature.sh:46-51` -- the same raw source, and it invokes `validate.sh` as a child, so narrowing only one of the two leaves the bleed intact.
- `scripts/agent/lib.sh` -- shared helper home (`resolve_playwright_port` at `:308`); the allowlist loader belongs here.
- `scripts/agent/test-stack.sh:33`, `ensure-test-db.sh:21`, `run-services.sh:17`, `migrate-primary.sh:44` -- each re-sources `.env.local` in its **own** process; they keep full access and must not be narrowed.
- `src/infra/config.py:43,758-776,861-867` -- `_ENV_PREFIX`, `_set_nested`, `_apply_env_overrides`: `IMOVEIS_A__B__C` → `a.b.c`, merged leaf-wise, generic overrides last (they win over YAML).
- `src/infra/config.py:285-332` -- `AIConfig._validate_backends`; the totality check at `:321-331` is what a partial routing map trips.
- `src/tests/unit/test_config.py:582-589` -- `test_enrichment_routing_default_all_local`, the invariant that must keep passing; `:81-99` `_clear_config_env` (module-local, keeps its own job).
- `src/tests/unit/test_celery_app.py:74-85` -- the 2026-08-12 per-module `IMOVEIS_*` loop to fold away (the `REDIS_URL` delenv above it predates this and stays).
- `src/tests/unit/test_backfill_runner_hosting.py:40-70,370-380` -- `run_installer` helper + stubbed `sudo`/`systemctl`; the new preflight cases extend this module.
- `.env.local.example:29-45` / `docs/setup.md:353-361` / `docs/deployment-guide.md:43` / `docs/features/v0.13-s3.1-backfill-runner-hosting.md:119-141` / `docs/adr/0006-backfill-runner-hosting.md:73-78` -- the operator-facing surfaces that currently prescribe (or imply) the YAML edit.

## Tasks & Acceptance

**Execution:**
- [x] `scripts/install-backfill-runner.sh` -- replace `routing_has_cloud_backend()` with an effective-map resolver over (YAML block, env-file overrides) plus a `routing_override_keys` reader; extend the export-prefix fatal to routing override lines; rewrite the all-local warning to prescribe the env override and explicitly warn off the committed YAML -- the preflight must reflect what `--serve` resolves, not one of its inputs (DW-31).
- [x] `scripts/agent/lib.sh` -- add `load_workspace_env` (default-deny allowlist reader: last assignment wins, strips quotes/inline comments/CR, literal values) with the allowlist constant and a comment naming DW-33 -- one mechanism both gate scripts share.
- [x] `scripts/agent/validate.sh` + `scripts/agent/finish-feature.sh` -- replace both `set -a; source .env.local` blocks with `load_workspace_env` -- operator env stops entering the gate process at all.
- [x] `src/tests/conftest.py` -- new suite-wide autouse fixture stripping the generic `IMOVEIS_<SECTION>__<KEY>` channel, exposing the key-selection rule as an importable pure function -- the invocation-independent net; `IMOVEIS_ALLOW_PRIMARY_*_WIPE` must survive.
- [x] `src/tests/unit/test_celery_app.py` -- delete the 2026-08-12 `IMOVEIS_*` loop, keep the `REDIS_URL` delenv, and point the comment at the conftest guard -- folded, not duplicated.
- [x] `src/tests/unit/test_gate_env_isolation.py` -- new: run `load_workspace_env` against a fully-populated operator env file (built from `.env.local.example` plus the three routing overrides, `GEMINI_API_KEY`, `DATABASE_URL`) and assert the resulting environment carries the allowlisted keys and none of the excluded ones; source-pin that neither gate script raw-sources `.env.local`; cover the conftest rule (stripped vs surviving prefixes) and assert `os.environ` is free of `IMOVEIS_*__*` inside a test.
- [x] `src/tests/unit/test_backfill_runner_hosting.py` -- add the routing rows of the I/O matrix (override→cloud, all-local, YAML-cloud, override→local, `export`-hidden override) using env-file fixtures, asserting on the installer's stderr text -- the preflight branches are the DW-31 fix.
- [x] `.env.local.example` -- document the routing override block as the sanctioned per-host enablement, with the reason the committed YAML is not it.
- [x] `docs/setup.md` + `docs/deployment-guide.md` -- replace the "`ai.enrichment_routing` must route …" precondition with the env override; note that the gate reads only workspace-identity keys from `.env.local`.
- [x] `docs/adr/0006-backfill-runner-hosting.md` -- dated amendment recording the corrected enablement surface and the both-inputs preflight (do not rewrite the original decision).
- [x] `docs/features/v0.13-s3.1-backfill-runner-hosting.md` -- mark the `BUG (High)` follow-up resolved, pointing at this story's doc.
- [x] `docs/features/v0.13-s3.5-runner-env-contract.md` -- new feature doc from `_template.md` (all sections), recording the enablement decision, the allowlist choice and the two rejected DW-33 alternatives.
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- close DW-31 and DW-33 with their resolutions.
- [x] `CLAUDE.md` (+ the git-ignored `.cursor/rules/imoveis-core.mdc` mirror) -- one line each: cloud backfill is enabled per-host via env, and the gate reads `.env.local` through an allowlist.

**Acceptance Criteria:**
- Given a checkout whose `.env.local` carries the operator's full runner contract including the three routing overrides, when `bash scripts/agent/validate.sh backend` runs, then it is green and no test needs a per-module `IMOVEIS_*` guard to get there.
- Given an operator following any delivered surface (setup, deployment guide, env template, installer output, feature docs), when they enable the cloud backfill, then every one of those surfaces names the per-host env override and none prescribes an edit to the committed `configs/app_config.yaml`.
- Given `git diff` on the delivered branch, when reviewed, then no routing **value** in `configs/app_config.yaml` changed (comment-only edits are allowed, since the file's own prose is an operator-facing surface) and `test_enrichment_routing_default_all_local` still passes.
- Given the two gate scripts, when a future edit reintroduces a wholesale `source` of `.env.local`, then a unit test fails naming DW-33.

## Spec Change Log

**2026-08-12 — planner amendment (no review loopback).** The planned AC read "`configs/app_config.yaml` is untouched", and the Never list forbade changing "the committed YAML's routing values, `ai.backend`, or the live Celery path". Implementation surfaced that the file's own **prose comments** (the `v0.13-s1.3` NOTE and the `enrichment_routing` block header) instruct the operator to set the three classes to `gemma` *in that file* — the exact instruction AC-1 exists to eliminate, on the surface an operator reads first. Leaving it would have closed DW-31 everywhere except its most-read location. The AC was narrowed from "untouched" to "no routing **value** changed"; the Never list is unaffected (no value, no `ai.backend`, no live-path change). Verified: `validate.sh fast` green, `test_enrichment_routing_default_all_local` still pins the all-local invariant. **KEEP:** comment-only edits — any change to a routing *value* in that file is still out of bounds.

## Review Triage Log

### 2026-08-12 — Review pass (iteration 1)

- intent_gap: 0
- bad_spec: 0
- patch: 15: (high 1, medium 4, low 10)
- defer: 4: (medium 2, low 2)
- reject: 5: (medium 1, low 4)
- addressed_findings:
  - `[high]` `[patch]` **The new preflight certified a host `--serve` refuses to start on.** `routing_effective_has_cloud()` returned ready as soon as *one* class resolved cloud, but `_resolve_backfill_backend` requires **every** class in `DEFAULT_BACKFILL_SCOPE` (visual, sentiment, deal_verdict) to be cloud **and** on the **same** backend — it drives one client and has no local mode. So `…__VISUAL=gemma` alone, or a `gemma`+`gemini` split, passed `--check` and then crash-looped: DW-31's own defect, mirrored. Worse, a new test asserted the false OK as correct and the feature doc's recipe handed operators that same one-class fixture. Replaced with `routing_effective_value` + `routing_scope_verdict` (`ok` / `local <classes>` / `mixed <class>=<backend>,…`), mirroring the runner; tests and doc recipes corrected. *Note: the frozen I/O matrix row "env file sets `…__VISUAL=gemma` → reports ready" encodes the same mistake; it is superseded by the AC it serves ("the check reflects what `--serve` will actually resolve"), which has exactly one reading.*
  - `[medium]` `[patch]` Override **values** were unvalidated while `AppConfig`'s validators are case-sensitive and reject unknown names: `GEMMA`, `gemma1`, a misspelled class (`…__VISUALS`) and an empty value each passed preflight and are `ConfigError`s at startup. All four are now preflight failures naming the variable.
  - `[medium]` `[patch]` `load_workspace_env` mis-parsed a quoted value carrying an inline comment — `API_KEY="k" # generated` exported `"k"` *with quotes*, diverging from `set -a; source` and Compose's dotenv reader for the same file. Quote matching now ends at the closing quote; a `#` inside quotes still survives.
  - `[medium]` `[patch]` The conftest strip rule rested on a false premise. Its docstring claimed a prefixed name without `__` "addresses no config leaf", but `_apply_env_overrides` applies **every** `IMOVEIS_*` name — `IMOVEIS_AI=x` replaces the whole `ai` section with a string and survived the strip. Inverted to default-deny over the prefix with a named two-item preserve list (`IMOVEIS_ALLOW_PRIMARY_{DB,REDIS}_WIPE`, BIN-71/BIN-117).
  - `[medium]` `[patch]` The DW-33 source pin only matched a literal `.env.local`, so `source "$ENV_FILE"`, `set -a`, a variable path or `eval "$(cat …)"` would reintroduce the bleed and stay green. Now flags all of those, with a self-regression proving five bleed forms are caught and the sanctioned `lib.sh` sourcing is not.
  - `[low]` `[patch]` The all-local warning was factually wrong in the "override sent the only cloud class local" branch (it claimed the env file set no override that changes anything). Messages are now verdict-driven and accurate in every branch.
  - `[low]` `[patch]` New tests pinned literal values out of `.env.local.example`, so editing that operator template — which this story does — would redden the unit stage for an unrelated reason. Assertions are now structural (which keys survive, not which values).
  - `[low]` `[patch]` The feature doc claimed "No change to `configs/app_config.yaml`" while the diff reworded two comment blocks in it; the Files-touched table was also incomplete. Both corrected.
  - `[low]` `[patch]` `CLAUDE.md` / setup / deployment docs claimed operator env "never enters the gate process at all" — the loader filters a *file*, not an already-exported shell. Claim scoped to `.env.local`, with the conftest guard named as the origin-independent net.
  - `[low]` `[patch]` `.env.local.example`'s closing paragraph misdescribed the allowlist (omitted `POSTGRES_USER/PASSWORD/DB`, `PLAYWRIGHT_*`; pointed "above" at keys that are below; named `JWT_SECRET`, which the template never assigns).
  - `[low]` `[patch]` `test_auth.py` carried a third, now-dead copy of the `IMOVEIS_*` strip loop — folded into the conftest guard like `test_celery_app.py`'s. `test_config.py::_clear_config_env` keeps its own (it also clears the dedicated keys and the `lru_cache`), now with a comment saying why it coexists.
  - `[low]` `[patch]` The YAML routing parser stripped only double quotes, so `visual: 'gemma'` read as local.
  - `[low]` `[patch]` An existing-but-unreadable `.env.local` silently no-opped behind per-key grep permission errors; it now warns and falls back explicitly.
  - `[low]` `[patch]` The rewrite dropped the old fail-closed guard for a missing `configs/app_config.yaml` (a wrong `--repo-root` plus a cloud override went fully silent); restored as an explicit preflight failure.
  - `[low]` `[patch]` `test_preflight_never_edits_the_committed_config` exercised no installer code — renamed to `test_shipped_config_stays_all_local`, which is what it asserts.

## Design Notes

**Why the env override is the sanctioned surface.** `_apply_env_overrides` merges leaf-wise, so setting three classes leaves the YAML map total (story 1.1's validator demands totality), the scalar `ai.backend` stays local so the live Celery path is unaffected (AD-13), `embedding` still degrades local even for backfill (DW-5), and nothing enters git. The unit already reads the file via `EnvironmentFile=` — no unit change is needed.

**Effective-routing resolution stays in bash.** Preflight is a dependency-free, pre-install check that must still work on a host whose venv cannot import the app — that is one of the failures it exists to catch — and its branches are unit-tested hermetically by invoking the script. The cost is a second, three-line expression of the precedence rule (generic env wins over YAML); the tests pin both directions so the mirror cannot drift silently. Invoking `load_config()` from a root-privileged installer was rejected on that coupling.

```sh
# effective = YAML block, then env-file overrides laid on top
for key in $(routing_override_keys "$ENV_FILE"); do
  case "$(env_value_of "$ENV_FILE" "$key")" in
    gemma|gemini) return 0 ;;          # cloud wins outright
    *) overridden_local="$overridden_local ${key#$ROUTING_ENV_PREFIX} " ;;
  esac
done
# ... then scan the YAML pairs, skipping classes an override sent local
```

**Why the allowlist, not a second env file (DW-33).** Splitting the unit's `EnvironmentFile` from `.env.local` doubles the operator's contract (`GEMINI_API_KEY`/`DATABASE_URL` in two places), rewrites the installer/doc contract 3.1 just shipped, and still lets an operator put `IMOVEIS_*` in `.env.local`. Narrowing at the boundary fixes the whole class — including today's silent hazard that unit tests see the operator's primary `DATABASE_URL`, since `run_unit` runs before the ephemeral stack exports its own. The sub-scripts (`test-stack.sh`, `ensure-test-db.sh`, `migrate-primary.sh`) are separate processes that re-source the file themselves, so they are unaffected. The conftest guard is the second layer, not a duplicate: it is the only one that covers an `IMOVEIS_*` a developer exported in their own shell, which no file-reading loader can reach, and it is where the per-module `test_celery_app.py` guard folds. Its rule is **default-deny over the whole prefix** with two named survivors (`IMOVEIS_ALLOW_PRIMARY_{DB,REDIS}_WIPE`, BIN-71/BIN-117) — review corrected an earlier "only names containing `__`" rule, which let `IMOVEIS_AI=x` through to replace an entire config section with a string.

## Verification

**Commands:**
- `bash scripts/install-backfill-runner.sh --check --force --env-file <fixture>` -- expected: no routing warning when the fixture sets a `gemma` override; the warning (naming the env override) when it does not.
- `bash scripts/agent/validate.sh fast` -- expected: lint + unit green, including the new isolation and preflight tests.
- `bash scripts/agent/validate.sh backend` -- expected: green; this is the scope that proves the allowlist did not starve integration/contract of `DATABASE_URL`/`REDIS_URL`.
- `bash scripts/agent/validate.sh all` -- expected: full gate green (run by `finish-feature.sh`); the E2E stage proves `PLAYWRIGHT_PORT`/`API_PORT` survived the allowlist.

**Manual checks (if no CLI):**
- Installing the unit, restarting it and observing a real Start press are privileged host actions the agent cannot perform; they are owed to the operator.

## Auto Run Result

**Status:** `awaiting-operator` — every part an agent can do is implemented, reviewed, patched, validated and committed. What remains is host-side and privileged (see frontmatter `operator_actions`): the operator's own `.env.local` and the installed unit live outside this repo.

**Implemented change.** The per-host env override is now the single sanctioned way to enable the cloud backfill, and the installer's preflight tells the truth about it (DW-31); the merge gate no longer inherits the operator's runner env (DW-33).

- **Enablement (DW-31).** Every operator-facing surface — `.env.local.example`, `docs/setup.md`, `docs/deployment-guide.md`, the installer's messages, ADR 0006 (amendment), story 3.1's feature doc, `CLAUDE.md` + the Cursor mirror, and `configs/app_config.yaml`'s own prose — names `IMOVEIS_AI__ENRICHMENT_ROUTING__{VISUAL,SENTIMENT,DEAL_VERDICT}=gemma` in the git-ignored `.env.local`. None prescribes an edit to the committed YAML, whose routing values are unchanged and still pinned all-local by `test_enrichment_routing_default_all_local` (NFR-1).
- **Honest preflight (DW-31).** `routing_effective_value` lays the env file's overrides over the YAML block exactly as `_apply_env_overrides` does, and `routing_scope_verdict` judges the result the way `--serve` does: every class in the backfill scope cloud-routed, all on the same backend. It also fails the overrides that are fine for systemd and fatal for `AppConfig` — `export`-hidden, wrong case, unknown task class, empty value.
- **Gate isolation (DW-33).** `scripts/agent/lib.sh::load_workspace_env` is a default-deny allowlist reader used by both `validate.sh` and `finish-feature.sh`, so the cloud key, the primary `DATABASE_URL` and the `IMOVEIS_*` channel no longer reach pytest from that file. `src/tests/conftest.py` strips the whole `IMOVEIS_` prefix suite-wide (two named consent flags survive) as the origin-independent net, absorbing the per-module guards from `test_celery_app.py` and `test_auth.py`.

**Files changed** — `scripts/install-backfill-runner.sh` (effective-routing preflight), `scripts/agent/lib.sh` (+`load_workspace_env`), `scripts/agent/validate.sh`, `scripts/agent/finish-feature.sh`, `src/tests/conftest.py` (new), `src/tests/unit/test_gate_env_isolation.py` (new), `src/tests/unit/test_backfill_runner_hosting.py`, `src/tests/unit/test_celery_app.py`, `src/tests/unit/test_auth.py`, `src/tests/unit/test_config.py` (comment), `.env.local.example`, `docs/setup.md`, `docs/deployment-guide.md`, `docs/adr/0006-backfill-runner-hosting.md` (amendment), `docs/features/v0.13-s3.1-…md`, `docs/features/v0.13-s3.5-runner-env-contract.md` (new), `configs/app_config.yaml` (comments only), `CLAUDE.md` + the git-ignored Cursor mirror, `deferred-work.md`, `sprint-status.yaml`.

**Review findings.** One pass, two independent reviewers: 0 intent gaps, 0 spec defects, **15 patches applied** (1 high, 4 medium, 10 low), **4 deferred**, 5 rejected. The high one inverted a core behaviour: the new preflight accepted a single cloud-routed class, while `--serve` requires the whole backfill scope on one backend — so it certified hosts that crash-loop, with a new test and a doc recipe locking the false OK in.

**Verification.** `bash scripts/agent/validate.sh fast` green (lint: 12/12 pre-commit hooks, eslint OK; 2004 passed, 1 skipped). `bash scripts/agent/validate.sh backend` green (unit 2004, integration 102, contract 51; `alembic check` its usual informational PostGIS warn). AC-1 was proved end to end by re-running `backend` with a temporary `.env.local` replicating the operator's real file — cloud key, primary `DATABASE_URL`, all three routing overrides — green, then removed. The installer was exercised directly across all seven routing branches (all-three-cloud → ready line, single class → warns naming the two still-local classes, mixed backends → mixed warning, wrong case / unknown class / empty → non-zero without `--force`), and the partial-scope regression was confirmed to fail against the pre-patch installer. `validate.sh all` runs at the finish gate.

**Residual risks.**
- The privileged half is unverified by construction: the operator's real `.env.local` edit, the unit restart and a live Start press are host actions no agent can perform here.
- The precedence rule now exists twice (Python loader, bash preflight). Paired tests pin both directions, but a new cloud backend added to `core.enrichment` must also be added to the installer's `CLOUD_BACKENDS`.
- `ensure-test-db.sh` still re-sources `.env.local` in its own process; an operator `TEST_DATABASE_URL` can still redirect migrations away from the ephemeral DB (deferred, pre-existing).
- The runner's own crash-loop message still points at the committed YAML (deferred — that file is fenced by this story's intent contract).
