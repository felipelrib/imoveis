# Pin backend dependencies / add requirements lockfile

> Feature branch: `feat/pin-requirements-lockfile` · Linear: `BIN-138` · Status: implemented

## Problem

`requirements.txt` only version-constrained two packages (`sqlalchemy>=2.0.51`, `pydantic>=2.13.4`); every other backend dependency (`fastapi`, `httpx`, `celery[redis]`, `onnxruntime`, `python-jose[cryptography]`, `beautifulsoup4`, etc.) was unpinned, with no transitive-dependency lockfile. Running `pip install -r requirements.txt` on two different days could resolve different transitive versions, producing non-reproducible builds/CI runs and silent breakage if e.g. `python-jose` or `celery` shipped a breaking minor release.

## Approach

- Adopted the standard `pip-tools` workflow: `requirements.in` is now the hand-edited source of truth (loose, top-level dependencies — same content `requirements.txt` held before this change), and `requirements.txt` is a fully pinned lockfile generated via `pip-compile requirements.in --output-file=requirements.txt --strip-extras`, pinning every direct **and** transitive dependency to an exact version.
- CI and both Docker images (`Dockerfile.api`, `Dockerfile.worker`) already install from `requirements.txt` unchanged — no workflow/Dockerfile logic needed to change, only the *contents* of that file went from loose to fully pinned. This keeps the change low-risk/zero-behavior-change for the install command itself, while making the resolved dependency set reproducible.
- Generated the lockfile inside a `python:3.11-slim` container (matching the Python version CI and both Dockerfiles use) rather than the host's Python 3.14 interpreter, so the pinned wheels are guaranteed compatible with what actually ships.
- Verified the generated `requirements.txt` installs cleanly end-to-end in a fresh `python:3.11-slim` container with build deps (`gcc`, `libpq-dev`) present, mirroring `Dockerfile.api`/`Dockerfile.worker`.
- Documented the regeneration/upgrade process in `docs/setup.md` (`pip-compile requirements.in --output-file=requirements.txt --strip-extras [--upgrade | --upgrade-package <pkg>]`), including the Python-3.11 requirement and the "rebuild the Docker image before trusting the change" reminder.
- Added a one-line comment above `COPY requirements.txt` in both Dockerfiles pointing at the new docs section, so a future reader who edits it directly is redirected to the lockfile workflow.

## Changes

Files touched:

```
 requirements.in       | NEW — hand-edited source deps (previous requirements.txt content, unpinned/loose)
 requirements.txt      | CHANGED — now a pip-compile-generated lockfile, every direct+transitive dep pinned exactly
 docs/setup.md         | NEW "Dependency lockfile" section documenting the pip-compile regenerate/upgrade workflow
 Dockerfile.api        | Comment pointing COPY requirements.txt at the lockfile docs section
 Dockerfile.worker     | Comment pointing COPY requirements.txt at the lockfile docs section
 docs/features/96-pin-requirements-lockfile.md | NEW — this doc
```

## New Dependencies

None added at runtime. All existing `requirements.in` top-level packages resolved to the same or a compatible pinned version already in use (`sqlalchemy==2.0.51`, `pydantic==2.13.4` match the pre-existing floor constraints exactly). `pip-tools` itself is only needed transiently to regenerate the lockfile (not added to `requirements.in`/`requirements.txt` — it's a one-off dev tool, documented in `docs/setup.md`, installed with `pip install pip-tools` when regenerating).

## How to Test

1. Confirm the lockfile installs cleanly and matches what CI/Docker will get:
   ```bash
   docker run --rm -v "$PWD":/app -w /app python:3.11-slim pip install --no-cache-dir -r requirements.txt
   ```
2. Rebuild the API/worker images and confirm they still build and start:
   ```bash
   docker compose --env-file .env.local build api worker
   ```
3. Full gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- `requirements.in` intentionally keeps the two pre-existing floor constraints (`sqlalchemy>=2.0.51`, `pydantic>=2.13.4`) rather than pinning exact versions there — `requirements.txt` is where the exact pin lives; `requirements.in` stays the "what we want" file.
- `pip-audit --requirement requirements.txt` (already run in `.github/workflows/nightly.yml`) now audits the exact resolved versions instead of whatever was installed at scan time — no workflow change needed, but audit results become deterministic per commit.
- Dependabot's `pip` ecosystem entry in `.github/dependabot.yml` auto-detects `requirements.in` + `requirements.txt` pip-compile pairs in the same directory; no config change required, but future Dependabot PRs will now bump `requirements.in` and regenerate `requirements.txt` together instead of bumping the single flat file.
- Follow-up (not in this ticket's scope): consider a CI check that fails if `requirements.txt` is stale relative to `requirements.in` (e.g. re-run `pip-compile --dry-run` and diff) to catch hand-edits of the lockfile. Left out here to keep this a low-risk, non-behavior-changing chore per BIN-138's scope.
- Parent epic: BIN-128 (2026-07-29 technical debt remediation audit).
