# Brownfield: current harness state (verified 2026-08-05)

Findings from live inspection this session; line numbers current as of branch `feat/v0-13-implementation-readiness` @ `8265353`.

## Why the primary DB resets

| Site | Behavior | Consequence |
|---|---|---|
| `scripts/agent/validate.sh:48-50` | `COMPOSE=(dc --env-file .env.local -p "${COMPOSE_PROJECT_NAME:-imoveis}")` | Every compose call below targets the **primary** project by default |
| `validate.sh:147` | `up -d postgres redis` (integration stage) | Env/port drift between how the dev stack was started and `.env.local` ⇒ compose **recreates the primary Postgres container** |
| `validate.sh:149`, `:164` | `run --rm api alembic upgrade head` | Migrates the **primary `realestate` DB** during validation |
| `validate.sh:186` | `run --rm api alembic check` | Reads primary; also spins api containers in the primary project |
| `scripts/agent/teardown.sh:62` | `down -v --rmi local` for non-primary projects | Guard at `:52` trusts `COMPOSE_PROJECT_NAME` env alone — unset/wrong value defaults to `imoveis` (`:47`), relying on a single string compare to protect primary |
| `scripts/agent/finish-feature.sh` | runs `validate.sh all` | Inherits all of the above transitively |

Existing isolation that already works and must be kept: `ensure-test-db.sh` provisions/migrates `realestate_test` **on the same server** (DB-level isolation); `validate.sh:55-84` re-points host pytest `DATABASE_URL`/`REDIS_URL` at `realestate_test` / Redis DB 15. The gap is purely **container-level**: tests never write primary, but the scripts cycle its containers and migrate its schema.

## Skill + doc inventory (surgery targets)

- Non-BMad `.claude/skills/` (7): `feature-pipeline`, `babysit-pr`, `code-review`, `epic-completion`, `harness-retrospect`, `imoveis-planning-bridge`, `security-scan`. Dispositions: see `skill-dispositions.md`.
- Living docs still instructing the retired regime: `docs/harness-troubleshooting.md`, `docs/development-guide.md`, `docs/deployment-guide.md`, `docs/source-tree-analysis.md`, ADRs 0001–0004 (0005 is current). Legacy `docs/features/BIN-*` and `docs/chats_history/` are history — untouchable.
- `project-context.md` rules that flip post-surgery: line 82 ("validate.sh/finish-feature.sh recreate the primary Postgres container — never run concurrently with a long DB job") and line 87 ("BMad dev-side skills must NOT replace the feature-pipeline gates").
- CLAUDE.md (project): mandates feature-pipeline for ticket→ship, forbids BMad dev skills, references all 7 skills by name in session lifecycle/babysit/epic-completion sections.

## GitHub surface inventory (verified)

`.github/workflows/`: `ci.yml` (PR/push merge gate + Sonar), `docs.yml` (MkDocs build check + Pages deploy on main), `nightly.yml` (03:00 UTC: full unit+integration suite, dependency audit, live scraper drift canary). Plus `.github/dependabot.yml`, `sonar-project.properties`, and a local-usable `.pre-commit-config.yaml` (CI runs it on ALL files; local `validate.sh` only flake8's `src/` — the parity gap CAP-9 closes).

## Environment facts that bend the design

- `.env.local` is the single source of compose env; bare `docker compose up` without it drifts ports (known incident class).
- Worktree checkouts (`.claude/worktrees/`) have no `.venv`/`.env.local` (`setup-worktree.sh` provisions; writes its own `COMPOSE_PROJECT_NAME`, `setup-worktree.sh:144`).
- `docker-cleanup.sh` semantics to preserve: keep primary `imoveis-*` images + third-party bases + running-project images; never volumes.
- A long-running Gemma backfill (`backfill_gemma.py --continuous`, Redis-paced `backfill:gemma`) may be writing to primary at any time — the motivating workload for CAP-1.
