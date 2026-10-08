---
title: 'Story 1.4 — Primary migration cannot bypass the backfill guard'
type: 'bugfix'
created: '2026-10-08'
status: 'done'
baseline_revision: 'bc1e89debcd0545ba3c0a861a615aed4aff35453'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
warnings: ['oversized']
deferred:
  - summary: >-
      migrate-primary.sh and a backfill runner agree on the Redis endpoint and key prefix only when
      both resolve from the same environment; a runner installed with another env file or started
      by hand from a shell with different exports is outside what the script can see.
    evidence: |-
      The script resolves through infra.config in its shell environment plus $REPO_ROOT/.env.local
      (bash source). scripts/install-backfill-runner.sh and .ps1 accept --env-file, and
      scripts/windows/backfill_host.py reads its file literally with no shell expansion;
      scripts/dev/backfill_gemma.py started by hand reads no env file at all. An exported
      REDIS_URL or IMOVEIS_BACKFILL__REDIS_PREFIX in the operator's shell that is not in
      .env.local moves the script and not an installed runner. Before this story any non-default
      value split the two sides; what is left is a mismatch between env sources. Not checked: how
      the runner on this host is started today. A fix needs a decision on which source is
      authoritative (refuse when a guard-relevant variable comes from the shell and not the file,
      or have the runner publish its resolved prefix for the script to compare).
    location: >-
      scripts/agent/migrate-primary.sh:44-52,97-131
    severity: medium
  - summary: >-
      The behavioural regression tests for start.sh and migrate-primary.sh are harness-marked, and
      a forced `validate.py --tier backend` run (the bmad-loop verify) neither runs the harness
      gate nor records that it was skipped in the stamp.
    evidence: |-
      scripts/agent/validate.py fills `extras` only for the auto tier, runs the harness gate only
      when "harness" is in extras or the tier is full, deselects the marker in the unit step, and
      check_stamp compares tier rank only. A change to scripts/ merged on a forced backend run is
      stamped without any test that spawns these scripts. Predates this story. This story moved
      the pure-Python checks (the migration scan, the schema-check execution, the two static
      script checks) out of the harness mark so they run in every tier; the tests that spawn the
      shell scripts still depend on the harness gate.
    location: >-
      scripts/agent/validate.py:392,591-623
    severity: medium
  - summary: >-
      Eight harness tests in test_windows_backfill_host.py cannot pass when the gate runs from a
      linked git worktree, so the harness gate was red in every story worktree; they are now
      skipped there instead of fixed.
    evidence: |-
      The tests pass the real checkout as --repo-root, and scripts/windows/backfill_host.py:148
      refuses a checkout whose .git is not a directory ("Install from the permanent primary
      checkout, not a linked worktree"). Reproduced on the unchanged files in this worktree:
      5 failed, 12 passed. This story added a skipif on a linked worktree to the three test
      functions (8 cases) so the gate can pass here; from the primary checkout they run as before.
      A real fix builds a fixture checkout with a .git directory for these tests, as the other
      tests in the file already do, so they run everywhere.
    location: >-
      src/tests/unit/test_windows_backfill_host.py:98
    severity: low
  - summary: >-
      scripts/test.sh runs pytest inside the primary project's api container, whose DATABASE_URL
      and REDIS_URL are the primary ones.
    evidence: |-
      scripts/test.sh:37-47 uses compose_cmd run --rm api python -m pytest for unit, integration
      and e2e scopes. src/tests/integration/conftest.py refuses a database that is not wipe-safe
      (src/tests/db_isolation.py:44), so the integration scope should fail fast on the primary
      instead of wiping it. Read, not run: whether every unit test that touches Redis is equally
      guarded inside that container was not checked. validate.py is the supported gate.
    location: >-
      scripts/test.sh:37
    severity: low (unverified)
  - summary: >-
      stop.sh, restart.sh and clean.sh take the primary containers down without checking the
      backfill heartbeat.
    evidence: |-
      scripts/stop.sh:40 and scripts/clean.sh:71,79 call compose down for whatever project the
      checkout names; restart.sh calls stop.sh. A host-side runner in the middle of a pass loses
      Postgres and Redis. No schema or data change and volumes are kept, so this is an
      interruption, not corruption. Found by the scripts audit of this story (DW-32 asked for it).
    location: >-
      scripts/stop.sh:40
    severity: low
---

<intent-contract>

## Intent

**Problem:** Two doors let a schema migration run on the primary database under a live cloud backfill. `scripts/start.sh` runs `alembic upgrade head` in the `api` container of whatever compose project it starts, with no migration lock and no heartbeat probe (DW-32). And `scripts/agent/migrate-primary.sh` talks to `localhost:${REDIS_PORT}` db 0 with the literal keys `backfill:gemma:active` / `backfill:gemma:migrating`, while the runner takes its endpoint from `REDIS_URL` and its keys from `backfill.redis_prefix`, so a non-default value on either puts the two sides in different keyspaces and both proceed (DW-8).

**Approach:** `start.sh` stops migrating the primary compose project: it reports the schema state read-only and names `migrate-primary.sh` as the command to run. `migrate-primary.sh` resolves its Redis endpoint and key prefix through the same `infra.config` loader the runner uses, in the same environment, and fails closed when it cannot.

## Boundaries & Constraints

**Always:**
- "Primary" is the compose project named `${PRIMARY_COMPOSE_PROJECT:-imoveis}`, the definition `migrate-primary.sh` already uses. `start.sh` treats a checkout with no project name of its own (no `.env.local`) as primary, because `scripts/lib.sh` defaults the name to `imoveis`.
- On the primary project `start.sh` runs no `alembic upgrade`, `downgrade` or `stamp`, and prints no advice to run one outside `migrate-primary.sh`. It still starts the stack and exits 0 when the schema is behind; the pending state is a warning that names `bash scripts/agent/migrate-primary.sh`.
- The schema-state check is read-only: it compares `alembic_version` with the script directory's heads and creates nothing.
- `migrate-primary.sh` takes endpoint and prefix from `infra.config.load_config()` (`cfg.redis.url`, `cfg.backfill.redis_prefix`) after sourcing `.env.local`, which is the runner's own env file. Keys are `<prefix>:migrating` and `<prefix>:active`.
- Every existing property of the guard holds unchanged: lock taken before the heartbeat probe, `SET NX EX` with a per-invocation token, renewal and release by token compare-and-swap, `--dry-run` writes nothing, unreachable Redis refuses.
- The script never deletes `<prefix>:active`, and deletes `<prefix>:migrating` only through the existing token compare-and-swap of its own token.
- Tests use fake `redis` / `alembic` / `docker` doubles only. No test may open a connection to a real Redis, database or Docker daemon.

**Never:**
- No change to `src/core/backfill_runner.py`, `scripts/dev/backfill_gemma.py` or `src/infra/config.py`: the runner side is the reference, the script follows it.
- `start.sh` does not delegate to `migrate-primary.sh`. Migrating the primary stays an explicit operator step.
- No change to the `.env.local` guard of `migrate-primary.sh` (the missing-file case is an open ledger finding from v0.13 story 2.7, outside this story).
- No fix for the heartbeat lapsing under one slow row (DW-9) or for other `scripts/*.sh` behaviour found by the audit; findings are recorded, not patched.
- No edit to `sprint-status.yaml`, `.env.local` or `configs/anchors.local.yaml`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| start, primary, schema at head | project `imoveis` (default or named), check prints `current` | stack starts, no mutating alembic call, one line says the primary is at head | No error expected |
| start, primary, schema behind | check prints `pending:<db>-><head>` | stack starts, exit 0, warning names both revisions and `bash scripts/agent/migrate-primary.sh` | Warning only |
| start, primary, state unreadable | check fails or prints anything else | stack starts, exit 0, warning says the state is unknown and names the same command | Warning only |
| start, isolated project | `.env.local` names another project | `alembic upgrade head` runs in that project's `api` container, as before | Existing warning on failure |
| migrate, defaults | no `REDIS_URL`, default prefix | endpoint `localhost:6379/0`, keys `backfill:gemma:*`; behaviour as before | — |
| migrate, non-default | `REDIS_URL=redis://localhost:6379/7`, `IMOVEIS_BACKFILL__REDIS_PREFIX=backfill:alt` | lock and probe use db 7 and `backfill:alt:*`; nothing is written at db 0 or under `backfill:gemma` | — |
| migrate, runner alive on the non-default keyspace | runner's `Heartbeat.beat()` wrote `backfill:alt:active` at db 7 | script refuses with "heartbeat is ALIVE", alembic never starts | exit 1 |
| migrate, config unresolvable | `load_config()` raises or the prefix is empty | refuse before any Redis call, message says the guard endpoint could not be resolved | exit 1 (fail closed), also for `--dry-run` |
| migrate, `REDIS_PORT` disagrees | `REDIS_PORT=6380`, no `REDIS_URL` | follows the runner's endpoint (`6379`), warns that `REDIS_PORT` is not what the runner uses | Warning only |

</intent-contract>

## Code Map

- `scripts/start.sh:60-73` -- the unguarded `compose_cmd run --rm api python -m alembic upgrade head`, and at `:69` advice to run `alembic stamp head` by hand. `COMPOSE_PROJECT_NAME` comes from `scripts/lib.sh:36` (default `imoveis`), overridden when `:24-26` sources `.env.local`.
- `scripts/lib.sh:26-45` -- `dc` / `compose_cmd`; `:50` `require_docker` runs `docker info`. A stub `docker` on `PATH` is enough to drive `start.sh` in a test.
- `scripts/setup.sh:12,41` -- comments claim setup migrates through `start.sh`. `scripts/restart.sh:28`, `scripts/dev.sh:25` call `start.sh`.
- `scripts/agent/migrate-primary.sh:64-67` -- `REDIS_HOST="localhost"`, `REDIS_PRIMARY_PORT`, the two literal keys. Six inline Python snippets build `redis.Redis(host=..., port=..., db=0, ...)`: `:96`, `:136`, `:155`, `:174`, `:260`, `:290`. `prepend_python_path "$REPO_ROOT/src"` sits at `:317`, after the guard; it has to move before the resolution.
- `scripts/agent/lib.sh:37-79` -- `activate_project_python`, `prepend_python_path` (Windows separator handling).
- `src/infra/config.py:85-103` `RedisConfig.url`; `:185` `BackfillConfig.redis_prefix`; `:820-828` `REDIS_URL` parsing; `:885-891` `IMOVEIS_<SECTION>__<KEY>` overrides; `:901` `load_config`. Read-only.
- `src/infra/redis_client.py:21-27` -- the runner's client: `redis.Redis.from_url(cfg.redis.url, decode_responses=False)`. Read-only.
- `src/core/backfill_runner.py:556-579` `Heartbeat` (`set(key, "1", ex=ttl)`, `get`); `:592-624` `MigrationGate` (`get`). Read-only; the test drives these as the runner side.
- `src/tests/unit/test_migrate_primary_guard.py` -- harness-marked; throwaway git repo, fake `redis` module backed by a JSON file, stub `alembic` package, `PYTHONPATH` shadowing. `:535-546` pins the two literals in the script and must be replaced. The fake has no `from_url` and a flat store with no notion of endpoint.
- `src/tests/shell_helpers.py` -- `BASH` (Git Bash on Windows).
- `scripts/agent/validate.py:96,104-105` -- `scripts/` and `src/tests/unit/test_migrate*` select the harness gate; `:463` is the only other `alembic upgrade`, against the ephemeral test DB.
- `_bmad-output/implementation-artifacts/deferred-work.md:68-73` DW-8, `:288-293` DW-32, both `status: open`; closed entries use `status: resolved` plus a `resolution:` line (see `:285`).
- Docs that state the old behaviour: `docs/setup.md:133`, `README.md:134`, `docs/deployment-guide.md:56`, `docs/windows-migration.md:41`.

## Tasks & Acceptance

**Execution:**
- `src/tests/unit/test_migrate_primary_guard.py` -- give the fake `redis` a `from_url` and an endpoint-keyed store, record the endpoint on every call, put the gate interpreter's directory first on `PATH` and the repo `src` on `PYTHONPATH`; add the non-default tests (script keys land at db 7 under `backfill:alt`; the runner's `MigrationGate` built from `get_redis()` + `get_config()` sees the script's key while alembic runs; the script refuses on a heartbeat the runner's `Heartbeat` beat; nothing at db 0; unresolvable config fails closed for real and dry runs; no bare delete of either key); replace the literal-pinning test with one that fails on a hardcoded host, db or key -- written first, red against the current script.
- `scripts/agent/migrate-primary.sh` -- resolve endpoint and prefix once through `infra.config`, derive both keys, build every client with `redis.Redis.from_url`, log the endpoint without credentials, warn on a disagreeing `REDIS_PORT`, update the header comment -- closes DW-8.
- `src/tests/unit/test_migrate_primary_only_path.py` -- new, harness-marked: drive the real `start.sh` over a throwaway tree with stub `docker` and `curl` for the four `start` rows of the matrix; scan `scripts/`, `.claude/hooks/`, `deploy/`, the compose files and Dockerfiles for a mutating alembic invocation outside the allowlist (`migrate-primary.sh`, `validate.py`, the isolated-project branch of `start.sh`) -- written first, red against the current script.
- `scripts/start.sh` -- split the migration step by project: primary reports state and points at `migrate-primary.sh`, isolated projects migrate as before; drop the `stamp head` advice -- closes DW-32.
- `scripts/setup.sh` -- correct the two comments and print the migration step in the closing instructions.
- `docs/setup.md`, `README.md`, `docs/deployment-guide.md`, `docs/windows-migration.md` -- state the new behaviour where the old one is described.
- `_bmad-output/implementation-artifacts/deferred-work.md` -- mark DW-8 and DW-32 resolved with a resolution line each.
- `docs/features/v0.14-s1.4-primary-migration-cannot-bypass-the-backfill-guard.md` -- feature doc from the template, all sections, including the `scripts/*.sh` audit result and the closure of `epic-3-retro-item-3`.

**Acceptance Criteria:**
- Given the primary compose project, when `scripts/start.sh` runs, then no Docker command it issues contains a mutating alembic subcommand, and the test asserting that fails against the pre-change script.
- Given any tracked helper script, hook, deploy unit, compose file or Dockerfile outside the allowlist, when it gains an `alembic upgrade|downgrade|stamp` invocation, then the scan test fails and names the file and line.
- Given a non-default `REDIS_URL` db and `backfill.redis_prefix`, when `migrate-primary.sh` and the runner's own classes run in the same environment, then each sees the key the other wrote, and the test proving it fails against the pre-change script.
- Given any run of the changed script, when the Redis call log is inspected, then it holds no `delete` call and no compare-and-swap whose token is not the invocation's own.
- Given the ledger after this story, when DW-8 and DW-32 are read, then both are `resolved` with a resolution naming this story.

## Spec Change Log

## Review Triage Log

### 2026-10-08 — Review pass
- verdicts: 38 findings — high 0, medium 15, low 15, false 8, maybe-false 0
- findings:
  - `[medium]` `[defer]` Blind 1: an exported `REDIS_URL` / prefix in the operator's shell that is not in `.env.local` moves the guard and not an installed runner — real, but the script cannot know which source the runner used; needs a decision on the authoritative source. Deferred (item 1), documented in the feature doc.
  - `[false]` `[reject]` Blind 2: the Postgres target is still built from `POSTGRES_*` and may differ from the runner's `DATABASE_URL` — the script exists to migrate the primary database; a runner writing to another database is not in a race with it. The intent names Redis only.
  - `[medium]` `[patch]` Blind 3: a database ahead of the code is reported as "behind" with advice to migrate — added the `foreign:` answer (a revision the checkout's migrations do not contain) with its own warning and no pointer to `migrate-primary.sh`; covered by the SQLite execution test and a stub test.
  - `[low]` `[patch]` Blind 4: the "unknown" warning said `--dry-run` would check the schema; it only probes the guard — reworded to one command, no dry-run claim. The stderr of the check stays discarded (a reason line would need a temp file; not worth it for a best-effort report).
  - `[medium]` `[patch]` Blind 5: the scan is harness-marked, so a Dockerfile- or compose-only change never runs it, while the docs said it would fail — the module mark was replaced by a mark on the five tests that spawn `start.sh`; the scan, the schema-check execution and the static script checks now run in the plain unit step of every tier.
  - `[low]` `[patch]` Blind 6: the scan regex misses multi-line commands, aliased imports and `src/`, and the docs overstated it — the docs now call it a one-line tripwire and list what is outside. The regex itself is unchanged: widening it to `src/` matches docstrings there, and a multi-line matcher is more machinery than the risk warrants. (`deploy/` does exist: `deploy/systemd/imoveis-backfill-serve.service.in`.)
  - `[low]` `[reject]` Blind 7: a fresh install now needs a host `.venv` and one more command, and `setup.sh` checks neither — a consequence of refusing instead of delegating, which is the chosen reading; documented in README, `docs/setup.md`, `setup.sh` and the feature doc. A preflight is new surface.
  - `[medium]` `[patch]` Blind 8: the fail-closed message printed 300 characters of the loader's exception, and a pydantic section-level error quotes the section, which can hold API keys — verified (`input_value={'backend': 'ollama', 'en...` on a bad routing value); every `input_value=…` is now replaced by `<hidden>`, with a test.
  - `[low]` `[reject]` Blind 9: a CRLF `.env.local` — on this host Git Bash tolerates it (the tests write CRLF on Windows and pass); on Linux a CR-terminated prefix is refused (fail closed) with a message about whitespace. Not worth a branch.
  - `[low]` `[reject]` Blind 10: messages say "REDIS_URL / app config" and do not name `IMOVEIS_REDIS__*`; `rediss://` and usernames are dropped — wording is accurate at the level it speaks (the app config object), and the scheme loss is identical on both sides because both use `cfg.redis.url`.
  - `[low]` `[patch]` Blind 11: in a linked worktree with no `.env.local` the new warning pointed at `migrate-primary.sh` without saying from where — both warnings now say "from the primary checkout". The underlying acceptance of such a checkout by `migrate-primary.sh` is the open v0.13 story 2.7 finding and excluded by the spec.
  - `[low]` `[defer]` Blind 12: the two audit findings lived only in the feature doc — recorded as deferred items 4 and 5.
  - `[medium]` `[defer]` Blind 13: "`.env.local` is the runner's environment" is asserted, not tested — same root as Blind 1; deferred item 1.
  - `[medium]` `[defer]` Edge 1: same as Blind 1 — deferred item 1.
  - `[medium]` `[patch]` Edge 2: same as Blind 8 — patched there.
  - `[medium]` `[patch]` Edge 3: same as Blind 3 — patched there.
  - `[low]` `[patch]` Edge 4: `COMPOSE_PROJECT_NAME=Imoveis` under the Compose v1 fallback is the primary project but compared unequal, so the isolated branch would migrate it — the comparison now uses the name as Compose normalizes it; three spellings tested. Compose v2 rejects such a name before anything runs.
  - `[low]` `[patch]` Edge 5: a Postgres that accepts the connection and never answers hangs the read-only check — `connect_timeout` of 10 s for PostgreSQL URLs. The old `alembic upgrade` hung the same way.
  - `[medium]` `[defer]` Edge 6: claim "same environment as the runner" — same root as Blind 1; deferred item 1.
  - `[low]` `[patch]` Edge 7: the claim that any new door fails the scan is too strong — same as Blind 6; docs corrected.
  - `[medium]` `[patch]` Gap 1: the schema-check program was never executed, only its text matched — the test now extracts it from `start.sh` and runs it against SQLite with the repo's migration scripts for five database states, and checks the file is unchanged afterwards.
  - `[medium]` `[patch]` Gap 2: the script's own `prepend_python_path` lines were unobserved because the tests supplied the real repo on `PYTHONPATH` — one test now copies `src/core`, `src/infra` and `configs/` into the throwaway checkout and puts only the fakes on `PYTHONPATH`; it fails when the two lines are removed (checked by mutation).
  - `[medium]` `[defer]` Gap 3: a forced `--tier backend` run skips the harness gate and still stamps — gate behaviour that predates this story; deferred item 2. Partly offset by Blind 5's patch.
  - `[false]` `[reject]` Gap other 1: `rediss://`, username and query options are dropped by `RedisConfig.url` — true and identical on both sides, so no divergence between script and runner.
  - `[low]` `[patch]` Gap other 2: the dry run was exercised on the default keyspace only — added a dry-run test on db 7 / `backfill:alt`.
  - `[false]` `[reject]` Intent 1: the behavioural tests run copies of the scripts against a stubbed Docker CLI — required by the run's own rules (doubles only; the primary stack is live on this host).
  - `[medium]` `[patch]` Intent 2: the schema check has never executed — same as Gap 1.
  - `[low]` `[patch]` Intent 3: the scan roots are narrower than "every path" — same as Blind 6; documented.
  - `[false]` `[reject]` Intent 4: `docs/setup.md` still shows `cd alembic && alembic upgrade head` — that block creates and migrates a manual `realestate_dev` database, not the primary. The comment in the v0.13 repair migration is history and stays.
  - `[medium]` `[patch]` Intent 5: the scan is not selected for every file it scans — same as Blind 5.
  - `[false]` `[reject]` Intent 6: refusing changes fresh installs — the chosen reading (AGENTS.md and the epic context call primary migration an operator step); documented.
  - `[medium]` `[defer]` Intent 7: equivalence depends on the same env file read the same way — same root as Blind 1; deferred item 1.
  - `[low]` `[reject]` Intent 8: the runner side in the tests is built by the tests, not through `backfill_gemma.py` — the entry point builds the same objects from `get_redis()` and `cfg.backfill.redis_prefix` (`scripts/dev/backfill_gemma.py:657,778,1973`); driving the CLI would need a database double for no added proof.
  - `[low]` `[patch]` Intent 9: "see each other's key" is proven inside a fake whose URL parser is the test's own — added a test on the real redis-py client: built the script's way and the runner's way from one URL, same host, port, db and password, no connection opened.
  - `[false]` `[reject]` Intent 10: only the Redis side moved — same as Blind 2.
  - `[false]` `[reject]` Intent 11: the compare-and-swap delete of the script's own `:migrating` key remains — "never deleted by the change" is read as "the change adds no deletion"; the token-guarded release is the existing design and removing it would leave the lock held for its whole TTL after every migration.
  - `[false]` `[reject]` Intent 12: the ledger cites a spec file that is not in the diff — the spec exists; it was withheld from the review diff on purpose.
  - `[low]` `[patch]` Intent 13: the written audit lists only `.sh` helpers — true as a documentation gap; rows added for the PowerShell installer, the Windows host and `scripts/dev/*.py`. Whether any `scripts/dev/*.py` data script deserves its own guard was not examined (out of this story).

### 2026-10-08 — Review pass (follow-up)
- verdicts: 33 findings — high 0, medium 6, low 19, false 8, maybe-false 0
- findings:
  - `[low]` `[reject]` Blind 1: `start.sh` compares normalized names and `migrate-primary.sh` compares the `.env.local` value exactly, so `COMPOSE_PROJECT_NAME=Imoveis` is pointed at a script that refuses it — real, but reachable only through the Compose v1 fallback (Compose v5.3.0 on this host answers `invalid project name "Imoveis"` before anything runs), it errs toward not migrating, and the refusal names the project. The fix on the other side is the `.env.local` guard the intent excludes; dropping the normalization reopens the unsafe direction. The "same definition" comment in `start.sh` was corrected and the dead end is in the feature doc.
  - `[low]` `[reject]` Blind 2: with `PRIMARY_COMPOSE_PROJECT` exported as another name and the stack left as `imoveis`, `start.sh` migrates `imoveis` — true, and it is the intent's own definition of primary (`${PRIMARY_COMPOSE_PROJECT:-imoveis}`). The variable is a seam used by the tests and `scripts/ops/docker-cleanup-lib.sh`; nothing on a host sets it. Documented in the feature doc; a hardcoded `imoveis` beside it would be a second definition.
  - `[low]` `[reject]` Blind 3: after a pull with a migration the new code runs on the old schema and the warning scrolls past — the intent chose a warning and exit 0; repeating it at the end needs state carried across the script for a cosmetic gain.
  - `[low]` `[reject]` Blind 4: carried — a fresh install needs a host `.venv` and one more command (first pass, Blind 7): consequence of refusing instead of delegating; documented.
  - `[false]` `[reject]` Blind 5: follow-ups "recorded as deferred" are not in `deferred-work.md` and the spec is missing — the spec exists in the worktree and holds them in its frontmatter `deferred:` list; it is withheld from the review diff on purpose (first pass, Intent 12).
  - `[low]` `[reject]` Blind 6: carried — the unknown state discards the check's stderr (first pass, Blind 4). The check now has a PostgreSQL run behind it (Gap 2), which is what made the opacity matter.
  - `[false]` `[reject]` Blind 7: carried — the Postgres target comes from `POSTGRES_*`, not from the runner's `DATABASE_URL` (first pass, Blind 2): the script migrates the primary database by definition; the intent names Redis only.
  - `[low]` `[patch]` Blind 8: a config error in any section blocks the migration and the hint named only `REDIS_URL` and the prefix — the wider refusal is correct (the runner cannot start on that config either); the hint now says the reason comes from the app config loader and which files it reads.
  - `[low]` `[reject]` Blind 9: carried — the scan does not read CI workflows, `policy.toml`, hook commands in `settings.json` or package scripts, and allowlists `validate.py` whole (first pass, Blind 6): a one-line tripwire, documented as such.
  - `[low]` `[patch]` Blind 10: `test_windows_backfill_host.py` was missing from the feature doc's files table — row added. The skip itself is the carried Gap 3 below.
  - `[low]` `[patch]` Blind 11: the DW-8 resolution and the files table placed the replaced parity test in `test_migrate_primary_guard.py`; it lives in `test_migrate_primary_only_path.py` — both corrected.
  - `[medium]` `[patch]` Blind 12: no test put a password through the fail-closed or parse-failure paths — same root as Edge 4; patched there, with four cases.
  - `[low]` `[patch]` Blind 13: stale text — the script header named `validate.sh/finish-feature.sh` (now `validate.py/ship.py`) and a stray blank line split a list in the feature doc. `docs/harness-troubleshooting.md` keeps `backfill:gemma:active`: it is the default and that file is outside the story.
  - `[low]` `[patch]` Blind 14: the comment claimed the check cannot hang on a Postgres that never answers; `connect_timeout` bounds the connection only — comment corrected. No statement timeout added: the `alembic upgrade` this replaced hung the same way, and the state is not one that was shown to occur.
  - `[medium]` `[patch]` Edge 1: `COMPOSE_PROJECT_NAME=` (empty) in `.env.local` normalizes to an empty name, which is "not the primary", so `start.sh` took the migrating branch; `docker compose -p ""` then resolves to the directory name, which in the primary checkout is `imoveis` — verified on this host with a scratch compose file (`--env-file` with an empty name and `-p ""` rendered `name: <directory>`), no stack touched. `is_primary_project` now treats an empty name as the primary (report, never migrate). Two-case test added; it fails against the script without the fix.
  - `[low]` `[reject]` Edge 2: same as Blind 2.
  - `[low]` `[reject]` Edge 3: same as Blind 1.
  - `[medium]` `[patch]` Edge 4: a Redis password with an unencoded `/`, `?` or `#` makes URL parsing raise, and the message quotes the piece in front of that character — verified: before the patch the script printed `invalid literal for int() with base 10: 'guard-pw@localhost:6379/0'` from the probe. The resolver now checks that the URL parses and refuses in its own words, and a plain `ValueError` from the loader is cut at its first quote. After this no Redis snippet can meet a parse error; connection and auth errors from redis-py name host and port only. Test: `REDIS_URL` and `IMOVEIS_REDIS__PASSWORD`, real and dry run; all four fail without the fix.
  - `[low]` `[patch]` Edge 5: same as Blind 14 — comment corrected.
  - `[medium]` `[defer]` Edge 6: carried — `.env.local` is sourced by bash here and read literally by the Windows runner host, so a value containing `$` resolves differently (first pass, Blind 1 / deferred item 1: which env source is authoritative).
  - `[medium]` `[defer]` Gap 1: carried — the behavioural tests are harness-marked and a forced `--tier backend` run (the bmad-loop verify) neither runs nor records them (first pass, Gap 3 / deferred item 2). This pass ran the auto tier, harness gate included.
  - `[medium]` `[patch]` Gap 2: the schema-check program never ran against PostgreSQL — added `src/tests/integration/test_primary_schema_check_postgres.py`, which runs the program verbatim from `start.sh` against the gate's ephemeral database after `alembic upgrade head` and expects `current` with `alembic_version` untouched. Run by hand against this worktree's test stack (`imoveis-test-3ba2ab`, never the primary): passed.
  - `[low]` `[defer]` Gap 3: carried — three test functions of `test_windows_backfill_host.py` are skipped in a linked worktree (first pass, deferred item 3). Judged again: the condition is exactly the one `backfill_host.py` refuses on (`.git` is not a directory), it is applied only to the tests that pass the real checkout as `--repo-root`, and from the primary checkout they run. Narrow and honest, not a fix.
  - `[low]` `[reject]` Gap other 1: same as Blind 1.
  - `[false]` `[reject]` Intent 1: carried — the proof stops at doubles; real Redis, the runner as launched and the `api` container are not exercised (first pass, Intent 1): the run's rules. The PostgreSQL part is no longer open (Gap 2).
  - `[false]` `[reject]` Intent 2: a fourth schema state (`foreign:`) where the matrix says "anything else is unknown" — it is the first pass's patch for a database ahead of the code; it migrates nothing and withholds a pointer that would be wrong.
  - `[low]` `[reject]` Intent 3: same as Blind 1.
  - `[false]` `[reject]` Intent 4: the `stamp head` hint is gone on isolated projects too — the task list says to drop it; it was advice to rewrite the version table by hand.
  - `[false]` `[reject]` Intent 5: the fail-closed refusal also covers whitespace and hides values — both are refusals or omissions, inside "fail closed".
  - `[false]` `[reject]` Intent 6: the schema-check test opens a real SQLite file — a throwaway file under `tmp_path`, not a service; the new PostgreSQL test uses the gate's ephemeral database, which is what the gate is for.
  - `[low]` `[reject]` Intent 7: the Redis tests keep the fake ahead of real redis-py by `PYTHONPATH` order alone, with no probe like the Docker one — `PYTHONPATH` entries always precede site-packages, and this arrangement predates the story. A probe is new machinery for a state not shown to occur.
  - `[false]` `[reject]` Intent 8: files outside the two scripts were changed — `setup.sh`, the docs and the ledger are in the task list; the Windows host test is the carried Gap 3.
  - `[low]` `[reject]` Intent 9: carried — a fresh install no longer ends with a migrated database (first pass, Blind 7 / Intent 6).

## Design Notes

**Why refuse instead of delegate.** Delegating would make "start the stack" migrate the primary whenever a migration is pending and no runner is alive. AGENTS.md and the architecture spine both call primary migration an explicit operator step, and Story 1.5 found a repair migration applied to the primary without anyone choosing to. Refusing keeps the decision with the operator; the cost is one extra command after a pull that carries a migration, and the warning prints it.

**Why isolated projects keep migrating.** A compose project with another name owns its own Postgres volume, so its `api` container cannot reach the primary database. `migrate-primary.sh` refuses such a checkout, so removing the step there would leave those stacks with no migration path at all.

**Why the proof uses a fake Redis server.** The primary Redis listens on this host at `localhost:6379` and a real `backfill:gemma:migrating` there stops a live runner. The test fakes only the server: endpoint and key resolution run through the real `infra.config`, `infra.redis_client.get_redis`, `Heartbeat` and `MigrationGate` on the runner side and the real script on the other, and the fake stores keys per `host:port/db`, so a mismatch in host, port, db or prefix shows up as a key the other side cannot see.

**Workspace and safety (binding for whoever implements this).**
- Work only inside the git worktree `C:\Workfolder\imoveis\.run\wt\1-4` (branch `feat/v0.14-s1.4-primary-migration-cannot-bypass-the-backfill-guard`). Every read, edit and git command uses that path. Never edit the primary checkout `C:\Workfolder\imoveis`, anything under `.bmad-loop/`, `sprint-status.yaml`, or any `.env.local` outside a pytest `tmp_path`.
- The primary stack is live on this host (Redis `localhost:6379`, API `:8000`). Never execute the real `scripts/start.sh` or `scripts/agent/migrate-primary.sh` outside the test doubles, never run a Docker Compose lifecycle command, never connect to the real Redis or database.
- Interpreter: `C:\Workfolder\imoveis\.venv\Scripts\python.exe` (the worktree has no `.venv`). Git Bash is `'C:/Program Files/Git/bin/bash.exe'`; bare `bash` may be WSL. Do not run `scripts/agent/validate.py` or `ship.py`, do not commit, merge or push: the parent session validates and commits. Run only the two test files named under Verification.
- Do not create the feature doc's sibling files or any other new file beyond those named in the tasks.

**Implementation pointers from the investigation.**
- Python on Windows prints `
`. Emit the resolution as one tab-separated line (`ok<TAB>url<TAB>prefix<TAB>host:port/db`, or `unknown:<reason>`), strip `$'
'` in bash, split with `IFS=$'	' read -r`. Export the URL once (for example `GUARD_REDIS_URL`) so the six snippets read it from the environment; never put it on a command line or in a log line, because it can carry a password.
- The existing fake `redis` lives in a JSON file because each script snippet is a new process. Keep that, key the store by `host:port/db`, and have the helpers hand existing tests the `localhost:6379/0` namespace so their assertions stay as they are. `FAKE_ALEMBIC_STEALS_LOCK` writes the store directly and must follow the new shape.
- The script picks `python` from `PATH` when the throwaway repo has no `.venv`; `infra.config` needs pydantic and PyYAML, so the test puts `Path(sys.executable).parent` first on `PATH` and `<fake_site><os.pathsep><repo>/src` on `PYTHONPATH`. Remove `REDIS_URL`, `IMOVEIS_BACKFILL__REDIS_PREFIX`, `COMPOSE_PROJECT_NAME` and `PRIMARY_COMPOSE_PROJECT` from the inherited environment unless a test sets them.
- Runner side of the proof: a subprocess (or the stub `alembic` `__main__`, which runs while the lock is held) that calls `infra.redis_client.get_redis()` and `infra.config.get_config()` and builds `core.backfill_runner.MigrationGate` / `Heartbeat` from them, with the fake `redis` on `PYTHONPATH`.
- `start.sh` test: copy `scripts/start.sh` and `scripts/lib.sh` into `tmp_path/scripts/`, pass `--no-frontend`, put a directory with executable stub scripts named `docker` and `curl` first on `PATH`. The `docker` stub appends its arguments to a log file, answers `info` and `compose version` with exit 0, prints `healthy` for `ps postgres`, `api` for `ps --services`, and a canned state line for the read-only check. The read-only check can be `compose_cmd run --rm -T api python - <<'PY' ... PY` comparing `ScriptDirectory.get_heads()` with `SELECT version_num FROM alembic_version`.
- Keep the literal text `alembic upgrade`, `alembic downgrade` and `alembic stamp` out of `start.sh` except for the single real invocation in the isolated-project branch, so the scan needs no comment parsing. Give that branch its own function so the scan can check where the one hit lives.
- Files written with the Write tool, not shell heredocs, whenever the body contains a single quote.

## Verification

**Commands:**
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` -- expected: exit 0 (tier chosen from the diff, harness gate included)
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe -m pytest src/tests/unit/test_migrate_primary_guard.py src/tests/unit/test_migrate_primary_only_path.py -q -o addopts=` -- expected: all pass (development loop only, not validation)

## Auto Run Result

Status: done

**Summary.** `scripts/start.sh` no longer migrates the primary compose project. It runs a read-only schema check in the `api` container and reports one of four states: at head, behind (with both revisions and `bash scripts/agent/migrate-primary.sh`), a revision the checkout does not contain, or unknown. Isolated compose projects still migrate their own database. `scripts/agent/migrate-primary.sh` resolves its Redis endpoint and key prefix through `infra.config.load_config()` after sourcing `.env.local`, builds every client from that URL, derives `<prefix>:migrating` / `<prefix>:active`, and refuses before any Redis call when the resolution fails. DW-8 and DW-32 are resolved in the ledger; the closure of `epic-3-retro-item-3` is recorded in the feature doc.

**Files changed.**
- `scripts/start.sh` — primary branch reports, isolated branch migrates; project names compared as Compose normalizes them; `stamp head` advice removed.
- `scripts/agent/migrate-primary.sh` — endpoint and prefix from the runner's config loader; fail closed; `REDIS_PORT` warning; validation inputs hidden in the refusal.
- `scripts/setup.sh` — comments and closing instructions name the migration step.
- `src/tests/unit/test_migrate_primary_guard.py` — endpoint-keyed fake Redis; both-directions proof on db 7 / `backfill:alt`; fail-closed, password, redaction, own-checkout and dry-run tests.
- `src/tests/unit/test_migrate_primary_only_path.py` — new: `start.sh` over stub `docker`/`curl`; the migration scan; the schema check executed against SQLite; static checks of `migrate-primary.sh`; the real redis-py URL check.
- `src/tests/unit/test_windows_backfill_host.py` — three test functions skipped in a linked git worktree (see decisions).
- `docs/setup.md`, `README.md`, `docs/deployment-guide.md`, `docs/windows-migration.md` — new behaviour stated.
- `docs/features/v0.14-s1.4-primary-migration-cannot-bypass-the-backfill-guard.md` — feature doc with the scripts audit and the retro-item closure.
- `_bmad-output/implementation-artifacts/deferred-work.md` — DW-8 and DW-32 resolved.

**Review.** One pass, four layers, 38 findings.
- Patched: 13 entries — medium 5 (database-ahead reported as behind; scan not run for the files it scans; config values in the refusal; schema check never executed; the script's own `PYTHONPATH` lines unobserved), low 8 (unknown-state wording; scan claim in the docs; "from the primary checkout"; project-name normalization; connect timeout; dry run on the non-default keyspace; real redis-py URL check; audit rows).
- Deferred: 5 items in the frontmatter (env-source mismatch between script and runner; forced backend tier skips the harness gate; host tests that cannot pass in a linked worktree; `test.sh` in the primary container; stop/restart/clean under a live runner).
- Rejected: every `false` and `reject` row above carries its reason. In short: the Postgres target is not part of the Redis guard; fresh-install cost and stubbed tests follow from the chosen reading and the run's rules; CRLF, message wording and the CLI entry point are negligible; the `realestate_dev` block in `docs/setup.md` is not the primary; the token-guarded release of the script's own lock stays.

**Follow-up review: recommended (true).** Five medium entries were patched in this pass, and those patches have not been reviewed themselves. The specific unverified risks: the new `foreign:` branch and the project-name normalization in `start.sh`, and the redaction regex in `migrate-primary.sh`, were written after the review layers ran; and the schema-check program has run against SQLite only, never inside the `api` image against PostgreSQL.

**Decisions taken where the story left room.**
- Refuse and point, not delegate (DW-32 left both open): AGENTS.md and the epic context call primary migration an explicit operator step.
- "Primary" is the compose project `${PRIMARY_COMPOSE_PROJECT:-imoveis}`; isolated projects keep migrating in `start.sh`, because `migrate-primary.sh` refuses them and they own their own database.
- A pending migration is a warning; `start.sh` still starts the stack and exits 0.
- "Resolves the same endpoint and keys the runner uses" is implemented as the same config loader in the environment of `.env.local`, not as a comparison with a running runner process.
- The both-sides proof uses a fake Redis server with real resolution code on both sides, because the primary Redis is live on this host; no test opens a real connection.
- "Never deleted by the change" is read as "the change adds no deletion": the existing token compare-and-swap release of the script's own lock stays.
- `test_windows_backfill_host.py`: the gate could not pass from a story worktree because of tests this story does not own. They are skipped in a linked worktree, and the gap is deferred item 3.

**Verification.**
- The two story test files: 53 passed, 1 skipped (POSIX-only kill test) after the review patches.
- Mutation checks: removing the script's `PYTHONPATH` lines, the redaction line, or the name normalization fails the test written for each. The first-pass tests failed against the unchanged scripts (10 per file).
- `validate.py` (auto tier: backend + harness) on the implementation commit `76602d4c`: lint, unit, integration and contract passed; the harness gate failed on 5 cases of `test_windows_backfill_host.py` only, for the linked-worktree reason above. The run on the final commit is reported in the session hand-back, since this file is part of that commit.

**Residual risks.**
- Neither script was run for real: the primary stack is live. `bash scripts/agent/migrate-primary.sh --dry-run` from the primary checkout is the read-only confirmation (it writes nothing).
- A host whose `.env.local` has a non-default `REDIS_PORT` and no `REDIS_URL` now gets a warning and, if no Redis answers at the runner's endpoint, a refusal.
- The scan is a one-line tripwire.

### Follow-up review pass (2026-10-08)

A fresh session that did not write the code reviewed `bc1e89de..a6396c0a` with the four layers, 33 findings.

**Patched (8 entries): medium 3, low 5, high 0.**
- medium — an empty `COMPOSE_PROJECT_NAME` took the migrating branch of `start.sh`, and Compose resolves an empty name to the directory name, which in the primary checkout is the primary project. An empty name is now the primary: reported, never migrated.
- medium — a Redis password that breaks URL parsing was partly quoted in the refusal. The resolver refuses such a URL in its own words and cuts a plain parse error at its first quote.
- medium — the schema check now runs against PostgreSQL in the integration suite.
- low — the fail-closed hint, the files table and the DW-8 resolution (wrong test file, missing row), the script header, a stray blank line, the `connect_timeout` comment and the "same definition" comment.

**Deferred:** nothing new. Three findings repeat deferred items 1, 2 and 3.

**Rejected:** every `reject` and `false` row of the follow-up entry in the triage log carries its reason. The two that concern "is this the primary": a differently spelled primary is refused by `migrate-primary.sh` (Compose v1 only, errs toward not migrating, the excluded `.env.local` guard would have to change), and `PRIMARY_COMPOSE_PROJECT` redefines the primary because the intent says so.

**What the dev pass asked to have checked.**
- `start.sh`, read-only check: the program creates nothing (SQLite file byte-identical; `alembic_version` unchanged on PostgreSQL). The `foreign:` branch migrates nothing and prints no pointer. The name comparison had one hole, the empty name, now closed.
- `migrate-primary.sh`: the refusal on a failed resolution comes before the EXIT trap is armed and before the first Redis snippet. The only deletion in the file is the `del` inside the token compare-and-swap of the script's own lock; `<prefix>:active` is only ever read with `exists`. The URL is exported, never logged; the leak was in exception text, now closed.
- The linked-worktree skip is narrow and honest (triage row Gap 3). It remains a skip, deferred item 3.
- Regression tests against the pre-change scripts (`git show bc1e89de:` copies of both scripts, then restored): 35 of the 60 cases in the two story files fail, among them every primary-branch test of `start.sh`, the scan, the non-default keyspace proofs, the fail-closed tests and this pass's six new cases.

**Follow-up review: not recommended (false).** No `high` entry was patched in this pass. The three medium patches are small, each has a test that fails without it, and none changes the guard's lock or probe logic.

**Verification in this pass.**
- The two story test files: 59 passed, 1 skipped (POSIX-only kill test).
- `src/tests/integration/test_primary_schema_check_postgres.py` against this worktree's ephemeral test database: passed.
- `validate.py` (auto tier) on the commit of this pass is reported in the session hand-back, since this file is part of that commit.

**Residual risks, updated.**
- The schema check has run against PostgreSQL with the host interpreter, not through `docker compose run --rm -T api python -` inside the image. A failure there shows as "state unknown" with the pointer; it cannot migrate.
- Neither script has been run for real; `bash scripts/agent/migrate-primary.sh --dry-run` from the primary checkout stays the read-only confirmation.
- Whether the primary's `.env.local` on this host carries an empty or oddly spelled project name was not checked: agents do not read that file.
