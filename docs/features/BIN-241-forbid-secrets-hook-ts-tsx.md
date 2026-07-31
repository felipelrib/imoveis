# forbid-hardcoded-secrets hook — extend scan to *.ts/*.tsx

> Feature branch: `feat/bin-241-forbid-hardcoded-secrets-ts-tsx` · Linear: `BIN-241` · Status: implemented

## Problem

The pre-commit `forbid-hardcoded-secrets` hook greps `src/` and `frontend/src/`
for the forbidden markers `imoveis_secret` / `dev-secret-key`, but restricted the
scan to `--include="*.py" --include="*.js" --include="*.jsx"`.

After the v0.11 frontend TypeScript migration ([BIN-160](https://linear.app/felipelrib/issue/BIN-160)),
**all** SPA source under `frontend/src` is `.ts`/`.tsx`, so the hook no longer
scanned any frontend application source. `.ts`/`.tsx` in `src/` were also never
covered (none exist today, but the omission was latent).

This is scan-coverage hygiene, not an active leak — the migrated files were
secret-scanned during the migration and contain no secrets.

## Approach

- Add `--include="*.ts" --include="*.tsx"` to the existing `grep` in the
  `forbid-hardcoded-secrets` hook `entry`, keeping the existing extensions.
- Reviewed the other `local` hooks that enumerate extensions
  (`forbid-only`, `forbid-print`, `forbid-fstring-sql`): they scan `src/`
  (Python backend) only, not `frontend/src/`, so none needed the change.
  `forbid-hardcoded-secrets` is the only frontend-facing extension-scoped hook.

## Changes

Files touched:

```
 .pre-commit-config.yaml                          | WHAT CHANGED — added --include="*.ts" --include="*.tsx" to forbid-hardcoded-secrets entry
 docs/features/BIN-241-forbid-secrets-hook-ts-tsx.md | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. Plant a marker in a `.ts` and a `.tsx` file under `frontend/src/`, then run
   the hook's grep — it must exit non-zero (hook fails):

   ```bash
   printf 'const x = "imoveis_secret";\n' > frontend/src/__probe.tsx
   printf 'const y = "dev-secret-key";\n' > frontend/src/__probe.ts
   bash -c '! grep -rnP "(imoveis_secret|dev-secret-key)" src/ frontend/src/ --include="*.py" --include="*.js" --include="*.jsx" --include="*.ts" --include="*.tsx"'
   echo "exit=$?  # 1 = secret detected (hook would block the commit)"
   rm -f frontend/src/__probe.tsx frontend/src/__probe.ts
   ```

2. Confirmed locally: the updated hook flags both planted files; the old
   (pre-change) glob missed them.

## Notes / Follow-ups

- Surfaced as a follow-up across the v0.11 migration feature docs
  ([BIN-161](https://linear.app/felipelrib/issue/BIN-161)/163/164/165).
- No production/runtime code changed — pre-commit config only.
