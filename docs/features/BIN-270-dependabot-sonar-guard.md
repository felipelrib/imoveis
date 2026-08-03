# CI Sonar guard for Dependabot — skip SonarCloud steps when `SONAR_TOKEN` is absent

> Feature branch: `feat/dependabot-sonar-guard` · Linear: `BIN-270` · Status: implemented

## Problem

Every Dependabot PR failed the `unit` CI check, turning the `unit` status red even
for trivial patch bumps (e.g. `recharts 3.10.0 → 3.10.1`) that cannot touch Python
code. The actual pytest suite passed in all of them; the failure came from the
`SonarCloud Scan` step exiting with "Not authorized".

Root cause: **Dependabot-triggered workflow runs cannot read Actions secrets.** They
only have access to a *separate* Dependabot secrets store, which is empty here, so
`secrets.SONAR_TOKEN` resolves to `""` and the scanner authenticates with an empty
token. This is by-design GitHub behaviour, not a repo misconfiguration.

The red check made the whole Dependabot backlog look unmergeable and hid which PRs
had *genuine* failures (e.g. major-version breakage) versus this spurious one.

## Approach

- Expose `SONAR_TOKEN` at the **`unit` job** level (`env:`) so its value is
  referenceable from a step `if:` expression (step-level `env` is not available to
  that same step's `if:`).
- Guard both Sonar steps — `Disable SonarCloud Automatic Analysis` and
  `SonarCloud Scan` — with `if: ${{ env.SONAR_TOKEN != '' }}`.
  - Normal PRs / pushes: token present → steps run exactly as before.
  - Dependabot runs (and forks without secret access): token empty → steps skip →
    `unit` job goes green on the real test result alone.
- Chosen over the alternatives:
  - `if: github.actor != 'dependabot[bot]'` — narrower; misses forks and any other
    secret-less context. Token-presence covers all of them.
  - Adding the token to the Dependabot secrets store — a real option, but it exposes
    the Sonar token to dependency-update runs for no analysis value (a dep bump adds
    no new source lines to scan). Left as an optional owner follow-up, not required
    for correctness.

## Changes

Files touched:

```
 .github/workflows/ci.yml                        | CHANGED — job-level SONAR_TOKEN env + `if:` guards on both Sonar steps
 docs/features/BIN-270-dependabot-sonar-guard.md | NEW — this doc
```

## New Dependencies

None.

## How to Test

CI-workflow behaviour is verified on GitHub, not locally:

1. On a **normal** PR (human/agent branch), confirm the `unit` job still runs the
   `SonarCloud Scan` step (token present) and reports to SonarCloud.
2. On a **Dependabot** PR, confirm the `unit` job passes with both Sonar steps shown
   as *skipped* rather than failed. (Existing open Dependabot PRs must be rebased —
   `@dependabot rebase` — so their merge commit picks up the updated workflow.)
3. YAML sanity locally:
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
   ```

## Notes / Follow-ups

- **Optional owner action:** to get real Sonar analysis on dependency PRs too, add
  the secrets to the Dependabot store (values are not readable from the Actions
  store, so this must be done by someone who holds the token):
  ```bash
  gh secret set SONAR_TOKEN --app dependabot
  gh secret set SONAR_ORGANIZATION --app dependabot
  ```
  With those present, `env.SONAR_TOKEN` is non-empty on Dependabot runs and the Sonar
  steps execute normally — no workflow change needed.
- Related: this was found while clearing the open Dependabot backlog. `#186` / `#188`
  / `#189` (patch/minor, Sonar-only failure) were merged; `#199` (postgis 15→17),
  `#187` (@eslint/js 9→10) and `#33` (maplibre-gl 5→6) were handled separately on
  their own merits.
