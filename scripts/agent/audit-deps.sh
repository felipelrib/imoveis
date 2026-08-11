#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# audit-deps.sh [--strict]
#
# Advisory dependency vulnerability audit: `pip-audit` over requirements.txt
# and `npm audit` over frontend/. Restores the dependency-scanning visibility
# lost when CI was retired (v0.13-fu1) — Dependabot alone is advisory-only.
#
# ADVISORY BY CONSTRUCTION: wired into `validate.sh all` as a stage that never
# influences the gate's exit code. Default mode ALWAYS exits 0 — findings,
# missing tools, and an unreachable network are all reported, never fatal.
# Degradation is always announced with a [WARN] line, never silent.
#
#   --strict   deliberate operator runs only: identical output, exit 1 when
#              findings exist OR when either audit degraded (a skip is not a
#              clean bill of health). NEVER pass this from validate.sh.
#
# $AUDIT_TIMEOUT (default 180s) bounds each tool call — an advisory stage of the
# merge gate must never hang finish-feature.sh against a stalled registry.
#
# Escalation path: act on a finding with a deliberate dependency bump,
# revalidated through the normal gate. Never mute the tool, and never add a
# suppression/ignore file.
#
# Tool resolution: $PIP_AUDIT_BIN / $NPM_BIN (default `pip-audit` / `npm`),
# with $REPO_ROOT/.venv/bin preferred on PATH. Tests stub the two vars.
# ---------------------------------------------------------------------------
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"   # NOTE: lib.sh sets -euo pipefail — guard every tool call.

STRICT=false
for arg in "${@}"; do
  case "$arg" in
    --strict) STRICT=true ;;
    *) die "usage: audit-deps.sh [--strict]" ;;
  esac
done

# Project venv tools (pip-audit installed by setup-tools.sh) win over system ones.
if [ -d "$REPO_ROOT/.venv/bin" ]; then
  export PATH="$REPO_ROOT/.venv/bin:$PATH"
fi

PIP_AUDIT_BIN="${PIP_AUDIT_BIN:-pip-audit}"
NPM_BIN="${NPM_BIN:-npm}"

# The overrides exist for tests/offline debugging, but they are honoured in real
# runs too — and validate.sh sources .env.local with `set -a`. Say out loud when
# the audit is not running the tools it claims to run.
[ "$PIP_AUDIT_BIN" != "pip-audit" ] && warn "PIP_AUDIT_BIN override active: $PIP_AUDIT_BIN (not the real pip-audit)"
[ "$NPM_BIN" != "npm" ] && warn "NPM_BIN override active: $NPM_BIN (not the real npm)"

# Bound every network call. A hung registry must degrade to a visible skip, not
# stall the merge gate. `timeout` is coreutils; fall back to running unbounded
# where it is unavailable rather than failing the audit outright.
AUDIT_TIMEOUT="${AUDIT_TIMEOUT:-180}"
# An empty or malformed value makes every `timeout` call exit 125, which the
# callers would read as "offline" — silently disabling the audit with a misleading
# reason. `0` is rejected too: coreutils reads `timeout 0` as "no limit", so the
# one value that voids this guarantee must not pass the guard that enforces it.
# Coreutils duration suffixes are accepted because the docs tell readers to tune
# this value and `30s`/`2m` are the natural way to write it.
_valid_timeout() {
  case "$1" in
    ''|*[!0-9smhd]*) return 1 ;;   # digits plus at most a unit suffix
    *[smhd]?*)       return 1 ;;   # a suffix may only be the last character
    [smhd]*)         return 1 ;;   # must start with a magnitude
  esac
  local n="${1%[smhd]}"
  case "$n" in
    ''|*[!0-9]*) return 1 ;;
  esac
  [ "$((10#$n))" -gt 0 ]           # rejects 0, 0s, 00 — "no limit" is not a bound
}
if ! _valid_timeout "$AUDIT_TIMEOUT"; then
  warn "invalid AUDIT_TIMEOUT='${AUDIT_TIMEOUT}' (want a positive duration: 180, 30s, 2m) — falling back to 180"
  AUDIT_TIMEOUT=180
fi

# Resolve the bound ONCE, here — never inside _timeout. `warn` writes to STDOUT,
# and _timeout only ever runs inside a command substitution that captures the
# tool's JSON: a warning emitted from there is swallowed into the payload, makes
# it unparseable, and turns every audit into a bogus "offline" skip whose real
# cause is never printed. Probe the long option too — a non-GNU `timeout`
# (busybox) satisfies `command -v` but rejects --kill-after, failing the same way.
TIMEOUT_CMD=()
if command -v timeout >/dev/null 2>&1; then
  # --kill-after: a tool that ignores SIGTERM must not outlive the bound and
  # hang the merge gate anyway.
  if timeout --kill-after=1 1 true >/dev/null 2>&1; then
    TIMEOUT_CMD=(timeout --kill-after=30 "$AUDIT_TIMEOUT")
  elif timeout -k 1 1 true >/dev/null 2>&1; then
    TIMEOUT_CMD=(timeout -k 30 "$AUDIT_TIMEOUT")
  fi
fi
if [ "${#TIMEOUT_CMD[@]}" -eq 0 ]; then
  # Never silent: the "bounded network call" guarantee does not hold here.
  warn "no usable \`timeout\` — audit calls run UNBOUNDED (a stalled registry can hang this stage)"
fi
# ${arr[@]+...} so `set -u` tolerates the empty (unbounded) case on bash < 4.4.
_timeout() { ${TIMEOUT_CMD[@]+"${TIMEOUT_CMD[@]}"} "$@"; }
# `timeout` reports 124 on SIGTERM, 137 when --kill-after had to SIGKILL.
_timed_out() { [ "$1" -eq 124 ] || [ "$1" -eq 137 ]; }

# Python is only used to PARSE the audit JSON — never to scrape human output.
PYTHON_BIN=""
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
elif [ -x "$REPO_ROOT/.venv/bin/python3" ]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

cd "$REPO_ROOT"

PY_SUMMARY="skipped"
NPM_SUMMARY="skipped"
FINDINGS=0

# --- Parsers ---------------------------------------------------------------
# Both read the tool's JSON on stdin and print "<count>" on line 1 followed by
# zero or more human-readable finding lines. A non-zero exit means the payload
# was unparseable/degraded, which the callers turn into a visible skip.
#
# The programs are held in variables and run via `python -c` on purpose:
# `python - <<'PY'` would take the *program* from stdin, leaving sys.stdin at
# EOF so the piped JSON could never be read.

PIP_PARSER="$(cat <<'PY'
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)

# pip-audit >=2 emits {"dependencies": [...]}; older versions a bare list.
deps = data.get("dependencies") if isinstance(data, dict) else data
if not isinstance(deps, list):
    sys.exit(1)

lines = []
unaudited = 0
audited = 0
for dep in deps:
    if not isinstance(dep, dict):
        continue
    # pip-audit stamps skip_reason on packages it could not resolve. Those were
    # NOT audited — never let them read as "no known advisories".
    if dep.get("skip_reason"):
        unaudited += 1
        continue
    audited += 1
    for vuln in dep.get("vulns") or []:
        if not isinstance(vuln, dict):
            continue
        fix = ", ".join(str(v) for v in (vuln.get("fix_versions") or [])) or "none published"
        lines.append(
            "    {name} {version} — {vid} (fix: {fix})".format(
                name=dep.get("name", "?"),
                version=dep.get("version", "?"),
                vid=vuln.get("id", "?"),
                fix=fix,
            )
        )

# Zero packages actually audited (empty resolution, or skip_reason on every one)
# is a DEGRADED run, not a clean one. Exit 2 so the caller reports `skipped`
# instead of a green "0 advisories" over a tree nothing looked at.
if audited == 0:
    sys.exit(2)

# Line 1 is the advisory COUNT; the unaudited note is context, not a finding,
# so it is printed after the findings without inflating the count.
print(len(lines))
for line in lines:
    print(line)
if unaudited:
    print("    note: {n} package(s) skipped by pip-audit — not audited".format(n=unaudited))
PY
)"

NPM_PARSER="$(cat <<'PY'
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)

if not isinstance(data, dict) or data.get("error"):
    sys.exit(1)

meta = data.get("metadata")
counts = meta.get("vulnerabilities") if isinstance(meta, dict) else None
if not isinstance(counts, dict):
    sys.exit(1)

# Zero packages resolved is a DEGRADED run, not a clean one — the same hole the
# pip parser closes with exit 2. npm reports the resolved tree size in
# metadata.dependencies (an object on npm >=7, a bare int on npm 6). Without
# this, an empty or unresolvable lockfile yields a green "0 npm advisories" and
# `--strict` exits 0 over a tree nothing ever looked at.
deps = meta.get("dependencies")
if isinstance(deps, dict):
    deps = deps.get("total")
if isinstance(deps, int) and deps <= 0:
    sys.exit(2)

severities = ("critical", "high", "moderate", "low", "info")
total = counts.get("total")
if not isinstance(total, int):
    total = sum(v for k, v in counts.items() if k in severities and isinstance(v, int))

print(total)
for sev in severities:
    n = counts.get(sev)
    if isinstance(n, int) and n > 0:
        print("    {sev}: {n}".format(sev=sev, n=n))

# Name the affected packages. A severity histogram alone cannot be triaged — it
# was exactly what hid a high-severity DIRECT runtime dependency behind "5 high,
# transitive toolchain noise". isDirect and fix availability are the two facts
# that decide whether a finding matters, so print them instead of telling the
# reader to go re-run `npm audit --json` by hand.
vulns = data.get("vulnerabilities")
if isinstance(vulns, dict):
    rank = {s: i for i, s in enumerate(severities)}
    rows = [v for v in vulns.values() if isinstance(v, dict)]
    rows.sort(key=lambda v: (rank.get(v.get("severity"), 99), str(v.get("name", ""))))
    for v in rows:
        fix = v.get("fixAvailable")
        if isinstance(fix, dict):
            fix_txt = "fix: {n}@{ver}".format(n=fix.get("name", "?"), ver=fix.get("version", "?"))
        elif fix:
            fix_txt = "fix available"
        else:
            fix_txt = "no fix published"
        print(
            "    {name} ({sev}, {direct}) — {fix}".format(
                name=v.get("name", "?"),
                sev=v.get("severity", "?"),
                direct="DIRECT dependency" if v.get("isDirect") else "transitive",
                fix=fix_txt,
            )
        )
PY
)"

parse_pip_audit() { "$PYTHON_BIN" -c "$PIP_PARSER"; }
parse_npm_audit() { "$PYTHON_BIN" -c "$NPM_PARSER"; }

# _report <label> <parsed-output>: prints the findings and sets REPORT_COUNT
# (a global, so the ok/warn lines stay on stdout instead of being swallowed by
# a command substitution). REPORT_COUNT="" means the payload was unparseable.
REPORT_COUNT=""
_report() {
  local label="$1" parsed="$2" count rest
  REPORT_COUNT=""
  count="${parsed%%$'\n'*}"
  count="${count%$'\r'}"   # a python emitting CRLF must not read as unparseable
  case "$count" in
    ''|*[!0-9]*) return 0 ;;
  esac
  if [ "$count" -gt 0 ]; then
    warn "$label: $count known advisories"
  else
    ok "$label: no known advisories"
  fi
  # Detail lines (per-finding rows, severity breakdown, "not audited" notes)
  # print for both branches — a zero count can still carry context.
  if [ "$parsed" != "$count" ]; then
    rest="${parsed#*$'\n'}"
    printf '%s\n' "$rest"
  fi
  REPORT_COUNT="$count"
}

# --- Python (requirements.txt) ---------------------------------------------
audit_python() {
  if [ -z "$PYTHON_BIN" ]; then
    warn "python not found — skipping python audit"
    return 0
  fi
  if ! command -v "$PIP_AUDIT_BIN" >/dev/null 2>&1; then
    warn "pip-audit not installed — skipping python audit (setup-tools.sh installs it)"
    return 0
  fi
  if [ ! -f "$REPO_ROOT/requirements.txt" ]; then
    warn "requirements.txt not found — skipping python audit"
    return 0
  fi

  log "Python: pip-audit over requirements.txt"
  local out parsed
  # pip-audit exits non-zero for "vulns found" too — the JSON, not the exit
  # code, is what distinguishes findings from a genuine tool/network failure.
  local trc=0
  out="$(_timeout "$PIP_AUDIT_BIN" --requirement requirements.txt --format json --progress-spinner off 2>/dev/null)" || trc=$?
  # Distinguish "the bound fired" from "offline": telling an operator the network
  # is down when the audit was actually too slow invites them to LOWER
  # AUDIT_TIMEOUT, which disables the audit permanently.
  if _timed_out "$trc"; then
    warn "python audit timed out after ${AUDIT_TIMEOUT} — skipping (raise AUDIT_TIMEOUT if the link is slow)"
    return 0
  fi
  parsed=""
  local prc=0
  if [ -n "$out" ]; then
    parsed="$(printf '%s' "$out" | parse_pip_audit)" || prc=$?
  fi
  # Exit 2 is the parser's "nothing was actually audited" signal (empty
  # resolution, or skip_reason on every package). Distinct message, same
  # outcome: PY_SUMMARY stays `skipped`, so the run reads DEGRADED.
  if [ "$prc" -eq 2 ]; then
    warn "python audit resolved no auditable packages — skipping (NOT a clean result)"
    return 0
  fi
  if [ -z "$parsed" ]; then
    warn "python audit could not run (offline or tool error) — skipping"
    return 0
  fi

  _report "python" "$parsed"
  if [ -z "$REPORT_COUNT" ]; then
    warn "python audit could not run (offline or tool error) — skipping"
    return 0
  fi
  PY_SUMMARY="$REPORT_COUNT"
  FINDINGS=$((FINDINGS + REPORT_COUNT))
}

# --- Frontend (npm) ---------------------------------------------------------
audit_npm() {
  if [ -z "$PYTHON_BIN" ]; then
    warn "python not found — skipping npm audit"
    return 0
  fi
  if [ ! -d "$REPO_ROOT/frontend" ]; then
    warn "no frontend/ — skipping npm audit"
    return 0
  fi
  if [ ! -f "$REPO_ROOT/frontend/package-lock.json" ]; then
    warn "frontend/package-lock.json not found — skipping npm audit"
    return 0
  fi
  if ! command -v "$NPM_BIN" >/dev/null 2>&1; then
    warn "npm not installed — skipping npm audit"
    return 0
  fi

  log "Frontend: npm audit over frontend/package-lock.json"
  local out parsed
  # Same contract as pip-audit: non-zero exit means "vulns found" as often as
  # it means "failed", so only the JSON decides.
  local trc=0
  out="$( ( cd "$REPO_ROOT/frontend" && _timeout "$NPM_BIN" audit --json ) 2>/dev/null )" || trc=$?
  if _timed_out "$trc"; then
    warn "npm audit timed out after ${AUDIT_TIMEOUT} — skipping (raise AUDIT_TIMEOUT if the link is slow)"
    return 0
  fi
  parsed=""
  local prc=0
  if [ -n "$out" ]; then
    parsed="$(printf '%s' "$out" | parse_npm_audit)" || prc=$?
  fi
  # Exit 2 is the parser's "nothing was actually audited" signal, mirroring the
  # python side: NPM_SUMMARY stays `skipped`, so the run reads DEGRADED.
  if [ "$prc" -eq 2 ]; then
    warn "npm audit resolved no auditable packages — skipping (NOT a clean result)"
    return 0
  fi
  if [ -z "$parsed" ]; then
    warn "npm audit could not run (offline or tool error) — skipping"
    return 0
  fi

  _report "npm" "$parsed"
  if [ -z "$REPORT_COUNT" ]; then
    warn "npm audit could not run (offline or tool error) — skipping"
    return 0
  fi
  NPM_SUMMARY="$REPORT_COUNT"
  FINDINGS=$((FINDINGS + REPORT_COUNT))
}

log "Dependency audit (advisory — never blocks the merge gate)"
audit_python
audit_npm

DEGRADED=false
if [ "$PY_SUMMARY" = "skipped" ] || [ "$NPM_SUMMARY" = "skipped" ]; then
  DEGRADED=true
fi

if [ "$FINDINGS" -gt 0 ]; then
  warn "Audit summary: ${PY_SUMMARY} python + ${NPM_SUMMARY} npm advisories — bump the dependency deliberately and revalidate; do not mute the tool"
elif [ "$DEGRADED" = true ]; then
  # Never [OK] a run that audited nothing — the summary itself must read amber.
  warn "Audit summary: ${PY_SUMMARY} python + ${NPM_SUMMARY} npm"
else
  ok "Audit summary: ${PY_SUMMARY} python + ${NPM_SUMMARY} npm advisories"
fi

# A skip is NOT a clean bill of health. This warns independently of FINDINGS —
# a partially degraded run with findings in the other source must still say so.
if [ "$DEGRADED" = true ]; then
  warn "DEGRADED RUN: dependencies were NOT fully audited (see the skip lines above) — this is not a clean result"
fi

if [ "$STRICT" = true ] && { [ "$FINDINGS" -gt 0 ] || [ "$DEGRADED" = true ]; }; then
  warn "--strict: exiting 1 (${FINDINGS} finding(s), degraded=${DEGRADED}) — operator mode only; validate.sh never passes --strict"
  exit 1
fi
exit 0
