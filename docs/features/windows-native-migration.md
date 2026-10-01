# Native Windows development migration

Development now targets `C:\Workfolder\imoveis` with native Python 3.11 and
Git Bash while Docker Desktop retains the existing Linux application/data
containers. Windows previously used the Linux dependency lock, POSIX virtualenv
paths and module-path separators; shell fixtures could silently launch WSL.

## Changes

- A generated Windows dependency lock preserves shared Linux pins and resolves
  platform dependencies. Shared gate helpers select a runnable native project
  interpreter, canonicalize Git roots and construct native `PYTHONPATH`.
- Shell files use LF. Shell fixtures explicitly resolve Git Bash and preserve
  path, worktree isolation, allowlist and primary-protection assertions.
- A user Task Scheduler host provides sign-in startup and recovery for the
  existing backfill supervisor. Its tests exercise actual child processes with
  the existing serve/signal handlers and isolated Redis/enrichment doubles:
  idle shutdown, active drain, crash retry, duplicate ownership, stale nonce,
  timeout, literal config and secret-safe preflight, including the existing Linux
  warning when the configured database name is the default instead of the corpus.
- Setup, hosting ADR, migration inventory and harness rules describe native
  operation. Private configuration, image cache and recovery archives stay out
  of Git; PostgreSQL, Redis and Docker image storage are reused in place.

## Verification record

The sanctioned fast gate established the old native failures before the gate
fixes, then passed 2,129 existing tests with 2 skips. The new supervisor tests
were recorded red before implementation (9 missing-module errors and one
missing-installer failure). Full native acceptance and live task evidence are
recorded in [the migration checklist](../windows-migration.md).

A complete SHA256 comparison verified all 387,859 copied host-cache images.
Native Ollama inference and a live property-grid smoke check succeeded. A
custom-format PostgreSQL recovery archive was verified readable; no restore
rehearsal or primary schema repair was performed.

The unrelated feature/operator/dependency backlog remains tracked separately.
Historical WSL state is retained for recovery; the old paused BMad run is not
resumed automatically. See [setup](../setup.md) for commands and
[ADR 0006](../adr/0006-backfill-runner-hosting.md) for hosting semantics.
