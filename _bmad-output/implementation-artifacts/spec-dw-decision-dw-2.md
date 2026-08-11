---
title: 'DW-2: advisory dependency audit gate (audit-deps.sh, warn-only in validate.sh all)'
type: 'chore'
created: '2026-08-11'
status: 'done'
baseline_revision: 'a63e8cdaee3755a7dae29757450c8e71f7e28554'
final_revision: '6bef89c'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** CI retirement (v0.13-fu1 / OQ-4) deleted the Trivy filesystem scan and the nightly `pip-audit`/`npm audit` jobs on the premise that local gates covered them, but no local gate audits anything — so nothing in the repo scans dependencies for known vulnerabilities, and Dependabot is advisory-only with no checks on bot PRs.

**Approach:** Add `scripts/agent/audit-deps.sh` — a self-contained advisory audit running `pip-audit` against `requirements.txt` and `npm audit` against `frontend/` — and wire it into `validate.sh all` only, as a stage that prints findings plus a summary count and never influences the gate's exit code. Missing tools or an unreachable network degrade to an explicit skip so offline merges still work.

## Boundaries & Constraints

**Always:**
- The audit stage is **advisory**: it must never mutate `rc` in `validate.sh`, and `audit-deps.sh` must exit `0` in its default mode regardless of findings, tool absence, or network failure.
- Preserve the exact terminal strings `VALIDATION PASSED` / `VALIDATION FAILED (rc=…)` and the `log`/`ok`/`warn`/`die` helpers from `scripts/agent/lib.sh` — docs and agents grep for them.
- Degradation must be *visible*: a skipped python or frontend audit prints a `warn` line naming the reason (tool missing / audit could not run), never silence.
- The stage runs in `validate.sh all` only. `fast` and `backend` stay untouched.
- Escalation path documented as: a real finding is resolved by a deliberate dependency bump (revalidated through the normal gate), never by muting the tool or adding a suppression.

**Block If:**
- Wiring the stage into `all` would require changing how `rc` is aggregated for any existing stage.
- `pip-audit` cannot be made available without editing `requirements.txt` (the pip-compile'd runtime lockfile).

**Never:**
- Never make the audit merge-blocking, and never add `--strict` to the `validate.sh` invocation.
- Never regenerate `requirements.txt` / `package-lock.json` as part of this work; no dependency bumps here.
- Never add entries to `.trivyignore` or introduce a new suppression/ignore file.
- No refactoring of unrelated `validate.sh` stages.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Both audits run, no findings | `pip-audit` + `npm` present, network up | `ok` lines for each; summary `0 python + 0 npm advisories`; exit 0 | No error expected |
| Findings present | `pip-audit`/`npm audit` report vulnerabilities | Findings printed; `warn` summary with per-source counts; exit 0 | Advisory only — never fails |
| `pip-audit` absent | `command -v pip-audit` fails | `warn "pip-audit not installed — skipping python audit"`; npm audit still attempted; exit 0 | Skip, not failure |
| Network unreachable | audit tool exits non-zero with no parseable JSON | `warn "… audit could not run (offline or tool error) — skipping"`; exit 0 | Skip, not failure |
| No `frontend/` or no lockfile | directory or `package-lock.json` missing | `warn "… — skipping npm audit"`; exit 0 | Skip, not failure |
| Operator strict run | `audit-deps.sh --strict`, findings exist | Same output; exit 1 | Intentional non-zero for deliberate operator checks only |

</intent-contract>

## Code Map

- `scripts/agent/audit-deps.sh` -- NEW. The advisory audit; sources `lib.sh`, prefers `$REPO_ROOT/.venv/bin` on PATH, resolves tools via `PIP_AUDIT_BIN`/`NPM_BIN` (default `pip-audit`/`npm`) so tests can stub them.
- `scripts/agent/validate.sh` -- add `run_audit()` calling the script; append to the `all` case arm only. Follow the existing informational-only precedent (the `alembic check` block in `run_contract`): `&& ok … || warn …`, never `rc=1`.
- `scripts/agent/lib.sh` -- source of `REPO_ROOT`, `log`/`ok`/`warn`/`die`. Read-only here.
- `scripts/agent/setup-tools.sh` -- `PYTHON_TOOLS` array is this repo's de-facto dev-tool declaration (holds `pre-commit`, `flake8`, `isort`, `autoflake`, `pytest-timeout` — none of which are in `requirements.in`). Add `pip-audit` here.
- `requirements.in` / `requirements.txt` -- pip-compile'd **runtime** lockfile feeding the Docker image. Do NOT touch.
- `src/tests/unit/test_no_fstring_sql_lint.py` -- precedent for text-asserting `validate.sh` contents from a unit test.
- `src/tests/unit/test_audit_deps_gate.py` -- NEW. Wiring assertions + a stubbed-tool subprocess run of the degradation path.
- `docs/development-guide.md` (§ Validation), `docs/harness-troubleshooting.md` (§ Validation), `docs/deployment-guide.md` (§ Merge gate & automation), `README.md` (§ Code Quality), `CLAUDE.md` (§ Validation & finishing) -- gate documentation surfaces.

## Tasks & Acceptance

**Execution:**
- [x] `scripts/agent/audit-deps.sh` -- create the advisory audit (see Design Notes for shape) -- restores dependency vulnerability visibility lost with CI.
- [x] `scripts/agent/validate.sh` -- add `run_audit()` and call it from the `all` arm only -- makes the audit part of the pre-merge gate without blocking it.
- [x] `scripts/agent/setup-tools.sh` -- add `pip-audit` to `PYTHON_TOOLS` -- declares it as a dev requirement through this repo's existing mechanism.
- [x] `src/tests/unit/test_audit_deps_gate.py` -- assert the script exists/executable, is wired into `all` but absent from `fast`/`backend`, never sets `rc`, and (subprocess, stubbed `PIP_AUDIT_BIN`/`NPM_BIN`) exits 0 while printing skip warnings when both tools fail -- locks the advisory + degradation invariants.
- [x] `docs/development-guide.md` -- document the stage under § Validation with the escalation path -- primary gate documentation.
- [x] `docs/harness-troubleshooting.md` -- add a `## Dependency audit (audit-deps.sh)` section covering skip semantics and the bump-don't-mute rule.
- [x] `docs/deployment-guide.md` -- add the audit to the parenthesized `validate.sh all` stage enumeration and note it is non-gating.
- [x] `README.md` -- replace the stale parallel-CI-jobs bullet (which still names a deleted `security-scan` job) with the local advisory-audit line.
- [x] `CLAUDE.md` -- note the advisory audit stage in § Validation & finishing (Cursor mirror `.cursor/rules/imoveis-core.mdc` synced too — gitignored, not in the diff).
- [x] `docs/features/v0.13-fu9-dependency-audit-gate.md` -- feature doc from `docs/features/_template.md` (all sections).
- [x] `_bmad-output/implementation-artifacts/sprint-status.yaml` -- mint `v0.13-fu9-dependency-audit-gate` (in-progress at start, `done` after merge).

**Acceptance Criteria:**
- Given `pip-audit` and `npm` are unavailable or offline, when `bash scripts/agent/validate.sh all` runs, then the audit stage prints skip warnings and the run's pass/fail verdict is identical to what it would have been without the stage.
- Given the audit reports vulnerabilities, when `validate.sh all` completes with all other stages green, then it still prints `VALIDATION PASSED` and exits 0.
- Given `bash scripts/agent/validate.sh fast` or `backend` runs, when the run completes, then no audit output appears.
- Given a reader follows `docs/development-guide.md`, when they look for how to act on a critical advisory, then they find "bump the dependency deliberately and revalidate; do not mute the tool".

## Spec Change Log

## Review Triage Log

### 2026-08-11 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 11: (high 0, medium 6, low 5)
- defer: 2: (high 0, medium 2, low 0)
- reject: 11
- addressed_findings:
  - `[medium]` `[patch]` Partial degradation suppressed the "not fully audited" warning — the degraded branch was an `elif` on `FINDINGS -eq 0`, so a run with python findings + a skipped npm audit read as complete. Split `DEGRADED` out; the warning now fires independently of findings, and the summary line itself reads amber instead of `[OK]`.
  - `[medium]` `[patch]` `--strict` exited 0 when nothing was audited, so an operator security check could not distinguish "clean" from "did not run". Now exits 1 on findings **or** degradation; the test that locked the old behavior was inverted.
  - `[medium]` `[patch]` `validate.sh run_audit` printed a green `[OK] dependency audit complete` even for a fully degraded run, because the script always exits 0 by construction. Dropped the trailing `&& ok`; the script's own summary is the stage verdict.
  - `[medium]` `[patch]` No timeout on a network stage appended to the merge gate — a stalled registry would hang `validate.sh all` and therefore `finish-feature.sh` indefinitely. Both tool calls now run under `timeout $AUDIT_TIMEOUT` (default 180s), with a fallback when `timeout` is absent.
  - `[medium]` `[patch]` The JSON parsers — the only real logic, and the basis of the whole "JSON decides, not the exit code" argument — had zero coverage; the advisory invariant (findings ⇒ still exit 0) was also untested. Added `TestAuditParsing`: 9 tests driving real pip-audit/npm payloads through the script via stubs (counts, clean, skip_reason, npm `error`, partial degradation, all three `--strict` outcomes).
  - `[medium]` `[patch]` The feature doc told readers npm findings were "build-time only … rather than mass-bumped". Verified against `npm audit --json`: `react-router-dom` is high severity, `isDirect: true`, fix available, and a direct runtime dependency in `frontend/package.json`. Corrected the baseline, flagged the direct advisory, and replaced the blanket dismissal with an `isDirect` triage instruction plus a note that the counts are not a prod/dev split.
  - `[low]` `[patch]` `test_setup_tools_declares_pip_audit` asserted a bare substring, which the same diff's new comment kept green even if `pip-audit` were dropped from `PYTHON_TOOLS`. Now asserts membership of the parsed array.
  - `[low]` `[patch]` `test_validate_never_passes_strict` grepped for the literal `audit-deps.sh --strict`, defeated by whitespace or variable indirection. Now asserts every `bash "$HERE/audit-deps.sh"` invocation carries no arguments at all.
  - `[low]` `[patch]` The degradation test used `/bin/false`, which passes `command -v` — so the five "tool not installed / no lockfile" skip branches were never executed. Added a test driving the `command -v` branches with unresolvable binary names.
  - `[low]` `[patch]` pip-audit stamps `skip_reason` on packages it cannot resolve; those were folded into "no known advisories". Now counted and printed as "not audited" (as context, not inflating the advisory count), and `_report` prints detail lines on the zero-count branch too.
  - `[low]` `[patch]` `docs/harness-troubleshooting.md` told readers to distrust a `"0 + 0"` summary, which a degraded run never prints (it prints `skipped`). Corrected, and documented the new degraded/strict/timeout semantics across the three gate docs.

Deferred findings (2) are recorded in `## Design Notes` → *Deferred* below rather than appended to `deferred-work.md`: the invoking orchestrator explicitly reserved that ledger ("Do NOT edit the deferred-work ledger; the orchestrator records resolution"). They are surfaced in the run report for the orchestrator to ledger.

Rejected (11, summarized): `pip-audit` installing during `fast`/`backend` via `setup-tools.sh` (consistent with the seven tools already installed there, and accurately documented); unreachable defensive guards in `_report`; parsers-as-heredocs (the spec's chosen shape); the escalation rule appearing in six docs (each surface was an explicit spec task); the gitignored Cursor-mirror drift (documented, inherent to the mirror); the branch carrying no story key (orchestrator-owned); `.npmrc` suppression and npm `info`-level counting (speculative — no `.npmrc` in this repo); Windows `.venv/Scripts` layout (`validate.sh` makes the same `.venv/bin` assumption); DW-2's ledger status (orchestrator-owned); and "no persisted artifact / baseline diff" (the human explicitly chose the advisory log-only option).

### 2026-08-11 — Review pass (follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 11: (high 0, medium 3, low 8)
- defer: 2: (high 0, medium 2, low 0)
- reject: 11
- addressed_findings:
  - `[medium]` `[patch]` **A tree where nothing was audited reported `[OK] 0 python advisories`, and `--strict` exited 0 on it.** Both reviewers found this independently and it was reproduced: with `skip_reason` on every package (or an empty pip-audit resolution) the advisory count is legitimately `0`, so the previous pass's own degradation work was bypassed — contradicting the three docs it had just written ("a degraded source reads `skipped`, never `0`"). The pip parser now exits `2` when zero packages were actually audited; the caller reports `python audit resolved no auditable packages — skipping (NOT a clean result)`, leaves `PY_SUMMARY=skipped`, and the run reads `DEGRADED` with `--strict` exiting 1. Partial skips still count, with the existing "not audited" note.
  - `[medium]` `[patch]` npm findings were printed as a bare severity histogram — untriageable, and exactly what hid a high-severity **direct runtime** dependency behind "5 high, transitive toolchain noise" in the previous pass (which had to run `npm audit --json` by hand to discover it). The parser now prints `pkg (severity, DIRECT dependency|transitive) — fix: …` per package; the real run surfaces `react-router-dom (high, DIRECT dependency)` straight from the gate log.
  - `[medium]` `[patch]` The `--strict` invariant lock — the thing standing between an advisory stage and a merge-blocking one — was defeated by a backslash line continuation, the exact form `validate.sh` already uses to invoke the script. Verified: injecting `--strict` on a continuation line kept the test green. The regex now follows continuations (with the continuation alternative ordered before the character class, or it re-breaks the same way).
  - `[low]` `[patch]` `test_run_audit_never_sets_rc` asserted the substring `"rc="`, which `rc+=1` does not contain. Now matches assignment *forms* while still permitting reads; added a lock that the script is run with `bash`, not `source` (sourcing it would let its `die` kill `validate.sh` outright, since `lib.sh` sets `-e`).
  - `[low]` `[patch]` A non-numeric or empty `AUDIT_TIMEOUT` made every `timeout` call exit 125, which the callers read as "offline" — silently disabling the audit while blaming the network. Verified, then guarded: fall back to 180 with a `[WARN] invalid AUDIT_TIMEOUT`. The docs actively suggest tuning this value, so the typo was reachable.
  - `[low]` `[patch]` The "every network call is bounded" guarantee had a silent unbounded fallback when coreutils `timeout` is absent. It now warns that calls run UNBOUNDED, and the bound gained `--kill-after=30` so a tool ignoring SIGTERM cannot outlive it.
  - `[low]` `[patch]` The count line was parsed with a strict digit test, so a python emitting CRLF would make every audit read as unparseable. Strip the trailing CR.
  - `[low]` `[patch]` `PIP_AUDIT_BIN`/`NPM_BIN` are honoured in real runs, and `validate.sh` sources `.env.local` with `set -a` — a stray line could silently redirect what the security audit executes. An active override now announces itself.
  - `[low]` `[patch]` `run_audit` spent up to two 180s network calls after the gate had already failed. It now short-circuits on `rc != 0` (a read, never an assignment — locked by test).
  - `[low]` `[patch]` Coverage for the branches the change turns on: all-skipped and empty pip resolutions, `--strict` on a python-side non-audit, the bare-list pip payload (pip-audit <2), the npm `total`-missing severity sum, npm per-package detail, the `AUDIT_TIMEOUT` fallback, and the override warnings. 21 → 31 tests.
  - `[low]` `[patch]` Docs corrected where they now described behavior the code did not have: the skip-semantics bullet (rewritten around "a count of `0` means audited-and-clean, never did-not-audit"), the npm triage instruction (the tool reports `isDirect` itself now), plus the previously undocumented network egress on the merge path, the timeout caveats, and the skip-on-red behavior.

Deferred (2) were appended to `deferred-work.md` as **DW-24** (Trivy filesystem/base-image coverage still unreplaced; `.trivyignore` is an accepted-risk register no scanner reads, which keeps the summary permanently amber) and **DW-25** (`react-router-dom` high/direct/fixable and `cryptography` PYSEC-2026-3552 found by the audit's first run, tracked nowhere). Existing ledger entries were not modified, re-opened, or rewritten — the orchestrator owns those.

Rejected (11, summarized): the header's "default mode ALWAYS exits 0" vs `die` on bad usage (the sentence scopes itself to findings/tools/network, and `validate.sh` passes no arguments); `pip-audit` installing unpinned into the test interpreter on every scope (identical in kind to the seven tools already there — re-rejected, as in the prior pass); the permanent-amber/no-baseline-ratchet critique and the "nobody reads output above the verdict line" critique (both are consequences of the human-chosen advisory-log-only option, and the ratchet question is now carried by DW-24); a nightly `--strict` run as an unconsidered middle ground (alternative design, outside the chosen option); `FINDINGS` summing per-vuln and per-package units with no severity threshold; `_scope_arm`'s indentation-sensitive regex; the subprocess tests' implicit dependence on `frontend/package-lock.json`; `finish-feature.sh`'s `derive_story_key` not parsing bmad-loop branch names (pre-existing, orchestrator-owned); the ledger reading `done` while sprint-status reads `in-progress` (the orchestrator's own uncommitted sweep edit); and the contract being restated across six doc surfaces (each was an explicit spec task).

### 2026-08-11 — Review pass (follow-up 2)

- intent_gap: 0
- bad_spec: 0
- patch: 11: (high 0, medium 3, low 8)
- defer: 0
- reject: 15
- addressed_findings:
  - `[medium]` `[patch]` **On a host without coreutils `timeout` the audit did not run at all, and blamed the network for it.** `lib.sh`'s `warn` writes to **stdout**, and `_timeout` is only ever called inside `out="$(_timeout …)"` — so the `UNBOUNDED` warning was captured into the JSON payload instead of the log, made it unparseable, and produced two `audit could not run (offline or tool error)` skips. Reproduced end-to-end with a `timeout`-free PATH and valid stubs: both sources skipped, the UNBOUNDED notice nowhere in the output. The probe now happens **once at startup**, outside any command substitution; `_timeout` writes nothing. Same defect class as the `AUDIT_TIMEOUT` one the previous pass fixed, one function away. The probe also tries `--kill-after=1` and falls back to `-k`, so a non-GNU `timeout` (which satisfies `command -v` but rejects the long option) no longer fails every call the same way.
  - `[medium]` `[patch]` **The npm side had no "nothing was audited" detector — the exact hole the previous pass closed on the python side.** `NPM_PARSER` read only `metadata.vulnerabilities` and ignored `metadata.dependencies`. Reproduced: an npm payload with `dependencies.total: 0` and `vulnerabilities.total: 0` printed `[OK] npm: no known advisories`, `[OK] Audit summary: 0 python + 0 npm advisories`, and `--strict` exited **0** — contradicting the three docs this change wrote ("a degraded source reads `skipped`, never `0`"). The parser now exits 2 when the resolved tree is empty (npm ≥7 object and npm 6 bare-int shapes), the caller mirrors the python branch, and `--strict` exits 1. A genuinely resolved clean tree is still clean — locked by its own test.
  - `[medium]` `[patch]` **`AUDIT_TIMEOUT=0` passed the new numeric guard, and coreutils reads `timeout 0` as *no limit*.** Verified both halves: no `invalid AUDIT_TIMEOUT` warning, and `timeout --kill-after=30 0 sleep 3` ran the full 3s. The one value that voids the "every network call is bounded" guarantee was the one value the guard waved through, leaving `finish-feature.sh` hangable on a stalled registry. Now rejected (`0`, `0s`, `00`) with the loud fallback; the guard simultaneously **accepts** the coreutils durations `30s`/`2m` it used to reject, which matters because the docs actively tell readers to tune this value.
  - `[low]` `[patch]` A tool killed by the bound (exit 124, or 137 after `--kill-after`) was reported as "offline or tool error". The natural reaction to a bogus offline report is to *lower* `AUDIT_TIMEOUT` — permanently disabling the audit. Timeouts now get their own message naming the bound and telling the operator to raise it.
  - `[low]` `[patch]` `test_network_calls_are_bounded_by_a_timeout` was a source-text grep for the string `UNBOUNDED`, which is exactly why it stayed green on the fully-broken fallback proven above — it asserted the branch *existed*, never that it was reachable. Replaced with a behavioral test that builds a `timeout`-free PATH and asserts the audit still runs and still announces itself, plus a lock that `_timeout` never calls `warn`/`ok`/`log` (the property that made the bug possible).
  - `[low]` `[patch]` No test asserted the arguments passed to either tool — every stub `cat`s a heredoc and ignores `argv`. Dropping `--format json` (pip-audit defaults to `columns`) or npm's `--json` would make every real run unparseable, a permanent silent "offline" skip, with all tests green. Added an argv-recording stub asserting `--format json`, `--requirement requirements.txt`, and `audit --json` — the exact point where the "JSON decides, not the exit code" invariant is established.
  - `[low]` `[patch]` The stage banner was printed twice in near-identical wording (`validate.sh` `run_audit` and `audit-deps.sh` itself) — two sources of one sentence, already drifting. Dropped `validate.sh`'s; the script announces itself as its first line and still does so when run standalone.
  - `[low]` `[patch]` The feature doc contradicted itself within 40 lines: the summary bullet said `--strict` exits 1 on findings **or** degradation, its How-to-Test step 3 said "only when findings exist". On this repo the step exits 1 anyway (findings exist), so a reader would never learn the doc was stale.
  - `[low]` `[patch]` Coverage for everything this pass turned on: npm zero-resolution in both npm shapes, `--strict` over a non-audited npm tree, the resolved-clean counter-case, `AUDIT_TIMEOUT` zero/suffix forms, the `timeout`-absent path, and the argv lock. 31 → 44 tests.
  - `[low]` `[patch]` `docs/harness-troubleshooting.md` corrected where it now described behavior the code lacked: the `AUDIT_TIMEOUT` bullet (zero rejected, suffixes accepted, why the probe is at startup), a new timed-out-vs-offline bullet, and the "count of `0`" bullet extended to name the npm-side check.
  - `[low]` `[patch]` My own new `_timeout`-purity regex initially matched greedily past the one-line function to the next `^}` and swallowed half the script (caught by the gate, not by inspection). Ordered the single-line alternative first, with a comment — the same ordering trap the previous pass hit on the `--strict` continuation regex.

No findings were deferred this pass: the standing items reviewers re-raised (unreplaced Trivy coverage, permanent amber with no baseline/ratchet, the unbumped `react-router-dom`/`cryptography` advisories) are already carried by **DW-24** and **DW-25**. No ledger entry was created, modified, re-opened, or rewritten — the orchestrator owns those.

Rejected (15, summarized): `FINDINGS` mixing per-vuln and per-package units with no severity floor, and npm `info`-severity counting (both re-rejected for the third pass); requiring explicit opt-in for `PIP_AUDIT_BIN`/`NPM_BIN` rather than the announce-and-proceed already shipped; the summary line having three shapes / not being a greppable contract string like `VALIDATION PASSED`; the unaudited window left by skip-on-red; the orphaned `.trivyignore` and permanent-amber critique (DW-24); the frozen `<intent-contract>` I/O matrix not describing the `--strict` degradation semantics added by review (the contract is frozen by design and every deviation is recorded here); `review_loop_iteration: 0` and `status: in-review` read as inconsistency (both are this workflow's own in-flight state — step-01 resets the counter for a fresh follow-up review); sprint-status `in-progress` vs the ledger's DW-2 `done` (orchestrator-owned, and sprint-status flips only after the merge lands); `--help` exiting 1 through `die`; the subprocess tests' dependence on live repo state and their decorative `subprocess.run(timeout=180)` under `pytest --timeout=30`; a `~/.local/bin` PATH addition for `pip-audit` (setup-tools.sh installs into the running interpreter); the CRLF edge in `_report`'s detail-line branch; behavioral constants restated across five doc surfaces (each an explicit spec task); and `_stub`'s heredoc breaking on a payload containing a bare `JSON` line.

## Design Notes

**Why not `requirements.in`:** `requirements.txt` is the `pip-compile --strip-extras` runtime lockfile that builds the API image. Adding `pip-audit` there ships an audit tool (and its transitive deps) into production and requires a network `pip-compile` regeneration inside an unattended run. `setup-tools.sh`'s `PYTHON_TOOLS` is where every other gate-only tool is declared and is auto-invoked by `validate.sh`; that is the faithful reading of "dev requirements" for this repo. Note this deviation in the feature doc.

**Script shape** (parse JSON, never scrape human output):

```bash
# pip-audit: exit 1 also means "vulns found" — distinguish by JSON parseability.
out="$("$PIP_AUDIT_BIN" --requirement requirements.txt --format json --progress-spinner off 2>/dev/null)" || true
# valid JSON -> count vulns (dict with .dependencies, or a bare list in older versions)
# unparseable -> warn "… could not run (offline or tool error) — skipping"
```

**Deferred** (recorded here by the first pass, whose invocation reserved the whole ledger; the follow-up pass's invocation narrowed that to *existing* entries, so both were appended as **DW-24** and **DW-25**):

1. `[medium]` The audit found real, fixable advisories on its first run and they are tracked nowhere but the feature doc: `react-router-dom` (high, direct runtime dep, fix available) and `cryptography 49.0.0` → 50.0.0 (PYSEC-2026-3552). The detector shipped; the vulnerabilities it found did not get a bump story. Evidence: `npm audit --json` shows `isDirect: true, fixAvailable: true`; `grep -i "bump\|cryptography\|react-router" sprint-status.yaml` returns nothing.
2. `[medium]` DW-2's problem statement names both the deleted Trivy filesystem scan **and** the nightly dependency audits, but the human-chosen option only restores dependency-manifest scanning. Container/OS-package/filesystem CVE coverage remains absent (`.trivyignore` survives as history with nothing reading it). Now stated as a scope caveat in `docs/development-guide.md` and `docs/harness-troubleshooting.md`, but no work item exists.

`npm audit --json` in `frontend/` yields `.metadata.vulnerabilities` (`critical`/`high`/…/`total`); an `error` key or a missing `metadata` means degraded → skip. Use the resolved python binary (`.venv/bin/python` → `python3` → `python`) with a heredoc parser; if no python is available, skip both counts with a warn.

## Verification

**Commands:**
- `bash scripts/agent/audit-deps.sh` -- expected: exit 0, prints a summary line, whether or not findings exist.
- `PIP_AUDIT_BIN=/bin/false NPM_BIN=/bin/false bash scripts/agent/audit-deps.sh; echo "EXIT=$?"` -- expected: `EXIT=0` with two skip `[WARN]` lines.
- `bash scripts/agent/validate.sh fast` -- expected: passes; no audit output in the log.
- `bash scripts/agent/validate.sh all > /tmp/val.log 2>&1; echo "EXIT=$?"` -- expected: audit stage appears; final line `VALIDATION PASSED`.

## Auto Run Result

Status: `done`

**Implemented change.** DW-2 resolved: dependency vulnerability scanning is back in the harness as an advisory stage. `scripts/agent/audit-deps.sh` runs `pip-audit` over `requirements.txt` and `npm audit` over `frontend/`, parses each tool's JSON (never its exit code, which conflates "vulns found" with "tool failed"), prints per-finding detail plus a summary, and always exits 0 in default mode. It is wired into `validate.sh all` only — `fast`/`backend`/`frontend` are untouched — through a `run_audit()` that never assigns `rc`. Missing tools, a missing lockfile, an unreachable network, a timeout, or a resolution that audited nothing all degrade to a visible `[WARN] … skipping` plus an explicit `DEGRADED RUN` line; every network call is bounded by `$AUDIT_TIMEOUT` (180s default, `--kill-after=30`). `--strict` is an operator-only mode that exits 1 on findings or degradation.

This second follow-up pass closed three defects in the degradation machinery itself — the part of the change everything else rests on. On a host without coreutils `timeout` the audit **did not run at all** and reported the network as the cause; the npm side had no "nothing was audited" detector, so an empty lockfile read as `[OK] 0 npm advisories` with `--strict` exiting 0; and `AUDIT_TIMEOUT=0` passed the guard while meaning *no limit* to coreutils. All three were reproduced before being fixed, and all three were invisible to the previous pass's tests.

**Files changed.**

- `scripts/agent/audit-deps.sh` — the advisory audit. This pass: `timeout` probed once at startup (never inside the command substitution that captures the JSON) with a non-GNU `-k` fallback; npm zero-resolution treated as degradation; `AUDIT_TIMEOUT` rejects `0` and accepts `30s`/`2m`; timeouts distinguished from offline.
- `scripts/agent/validate.sh` — `run_audit()` called from the `all` arm only; short-circuits when the gate is already red (reads `rc`, never assigns it). This pass: dropped the duplicated stage banner.
- `scripts/agent/setup-tools.sh` — `pip-audit` added to `PYTHON_TOOLS` (gate-only dev tool; `requirements.in`/`.txt` deliberately untouched).
- `src/tests/unit/test_audit_deps_gate.py` — 44 tests (was 31). This pass: the `timeout`-bound test was a source-grep that passed on the fully-broken path, now behavioral; added an argv lock (nothing asserted `--format json` / `--json`), a `_timeout`-writes-nothing lock, and coverage for every branch this pass added.
- `docs/development-guide.md`, `docs/harness-troubleshooting.md`, `docs/deployment-guide.md`, `README.md`, `CLAUDE.md` — gate documentation + the bump-don't-mute escalation path; corrected where they described behavior the code lacked.
- `docs/features/v0.13-fu9-dependency-audit-gate.md` — feature doc; fixed a `--strict` self-contradiction between its summary and its How-to-Test step.
- `_bmad-output/implementation-artifacts/deferred-work.md` — **untouched this pass** (DW-24/DW-25 were appended by the previous pass).
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `v0.13-fu9-dependency-audit-gate: in-progress`.

**Review findings breakdown.** 0 intent_gap · 0 bad_spec · 11 patches applied (3 medium, 8 low) · 0 deferred (the standing items are already DW-24/DW-25) · 15 rejected. See the 2026-08-11 follow-up-2 entry in the Review Triage Log.

**Verification performed.**

- `bash scripts/agent/validate.sh fast` → `VALIDATION PASSED`, 1743 passed / 1 skipped, all 44 audit-gate tests PASSED; `grep -c "Dependency audit"` on the log returns 0 — the stage does not leak into the inner loop.
- Reproduced each defect before fixing it. `timeout`-free PATH + valid stubs → both sources skipped with "offline or tool error", no `UNBOUNDED` line anywhere; after the fix → warning printed, both audits actually run. npm `dependencies.total: 0` → `[OK] npm: no known advisories` + `--strict` EXIT=0; after → `resolved no auditable packages`, `skipped npm`, `DEGRADED RUN`, `--strict` EXIT=1. `AUDIT_TIMEOUT=0` accepted with no warning, and `timeout --kill-after=30 0 sleep 3` ran the full 3s; after → rejected with the loud fallback.
- Guard matrix re-checked: `0`/`0s`/`00`/`abc` rejected; `30s`/`2m`/`180` accepted; a resolved-but-clean npm tree still reports clean and `--strict` still exits 0 (no false degradation).
- Real run → EXIT=0, 2 python (`cryptography` PYSEC-2026-3552 fix 50.0.0; `ecdsa` PYSEC-2026-1325 no fix) + 6 npm listed per package including `react-router-dom (high, DIRECT dependency)`.
- `validate.sh all` not run in this session — `finish-feature.sh` owns it.

**Residual risks.**

- The audit is permanently amber: the known-unfixable `ecdsa` advisory is reported every run, suppressions are forbidden by design, and there is no baseline or ratchet — so a *new* critical does not stand out from the standing set. Inherent to the chosen advisory-log-only option; carried as DW-24.
- Container/OS-package CVE coverage (the retired Trivy filesystem scan) is still absent — DW-24.
- The advisories the audit found are not yet bumped — DW-25.
- Three consecutive review passes have each found medium-severity defects in this script's degradation paths, every one of them a variant of "a degraded run reports as clean or blames the wrong cause". The paths are now directly tested rather than grep-asserted, but the pattern is worth noting.
- `setup-tools.sh` installs `pip-audit` into the active interpreter on the first `validate.sh` run of any scope (same mechanism as the seven tools already there), which on a `.venv`-less host means `pip install --break-system-packages`.
- `validate.sh all`, and therefore every `finish-feature.sh`, makes outbound calls to PyPI/OSV and the npm registry (documented in `docs/harness-troubleshooting.md`).
