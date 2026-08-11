"""Invariant lock for the advisory dependency audit (v0.13-fu9).

CI retirement (v0.13-fu1) deleted the Trivy/pip-audit/npm-audit jobs, so
``scripts/agent/audit-deps.sh`` is now the only thing scanning dependencies for
known vulnerabilities. Two properties must never silently regress:

1. **Advisory** — the stage runs in ``validate.sh all`` only and can never turn
   a green gate red (no ``rc=1``, no ``--strict`` from validate.sh).
2. **Visibly degrading** — a missing tool or an unreachable network prints a
   ``[WARN]`` skip line and still exits 0, so offline merges keep working.

The subprocess test stubs ``PIP_AUDIT_BIN``/``NPM_BIN`` with ``/bin/false`` so
it exercises the real script without touching the network.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_SCRIPTS = REPO_ROOT / "scripts" / "agent"
AUDIT_SH = AGENT_SCRIPTS / "audit-deps.sh"
VALIDATE_SH = AGENT_SCRIPTS / "validate.sh"
SETUP_TOOLS_SH = AGENT_SCRIPTS / "setup-tools.sh"


def _scope_arm(scope: str) -> str:
    """Return the body of one ``case "$SCOPE"`` arm in validate.sh."""
    source = VALIDATE_SH.read_text()
    match = re.search(rf"^  {scope}\)\n(.*?)^    ;;$", source, re.MULTILINE | re.DOTALL)
    assert match, f"could not locate the '{scope})' arm in validate.sh"
    return match.group(1)


def _run_audit_body() -> str:
    source = VALIDATE_SH.read_text()
    match = re.search(r"^run_audit\(\) \{\n(.*?)^\}$", source, re.MULTILINE | re.DOTALL)
    assert match, "validate.sh no longer defines run_audit()"
    return match.group(1)


@pytest.mark.unit
class TestAuditDepsScript:
    def test_script_exists_and_is_executable(self):
        assert AUDIT_SH.exists(), f"{AUDIT_SH} is missing"
        assert os.access(AUDIT_SH, os.X_OK), f"{AUDIT_SH} must be executable"

    def test_script_sources_lib_helpers(self):
        """Repo convention: agent scripts reuse lib.sh's log/ok/warn/die + REPO_ROOT."""
        body = AUDIT_SH.read_text()
        assert 'source "$HERE/lib.sh"' in body
        assert "$REPO_ROOT" in body

    def test_setup_tools_declares_pip_audit_in_the_tools_array(self):
        """pip-audit is a gate-only tool: declared in PYTHON_TOOLS, never in
        requirements.txt (the pip-compile'd runtime lockfile for the API image).

        Asserts the ARRAY, not the file text — the file also carries a comment
        mentioning pip-audit, which would keep a bare substring check green even
        if the tool were dropped from PYTHON_TOOLS.
        """
        array = re.search(r"^PYTHON_TOOLS=\((.*?)\)$", SETUP_TOOLS_SH.read_text(), re.MULTILINE)
        assert array, "setup-tools.sh no longer defines PYTHON_TOOLS=(...)"
        assert "pip-audit" in array.group(1).split()
        assert "pip-audit" not in (REPO_ROOT / "requirements.txt").read_text()
        assert "pip-audit" not in (REPO_ROOT / "requirements.in").read_text()

    def test_network_calls_are_bounded_by_a_timeout(self):
        """An advisory stage of the merge gate must not hang finish-feature.sh
        against a stalled package registry."""
        body = AUDIT_SH.read_text()
        assert "AUDIT_TIMEOUT" in body
        for call in ('_timeout "$PIP_AUDIT_BIN"', '_timeout "$NPM_BIN"'):
            assert call in body, f"unbounded network call: {call} is not wrapped"
        assert "UNBOUNDED" in body, (
            "the no-timeout path must warn that calls are unbounded"
        )

    def test_timeout_is_resolved_outside_any_command_substitution(self):
        """``_timeout`` must not call ``warn`` (or any other stdout writer).

        It runs only inside ``out="$(_timeout ...)"``, and ``lib.sh``'s ``warn``
        writes to STDOUT — so a warning emitted from there is captured into the
        tool's JSON instead of the log, makes the payload unparseable, and turns
        the whole audit into a bogus "offline" skip whose real cause is never
        printed. The probe therefore belongs at init, where it is visible.
        """
        body = AUDIT_SH.read_text()
        # The single-line alternative must come FIRST: alternation is ordered, and
        # the multi-line pattern would otherwise run past a one-line definition to
        # the next `^}` in the file and swallow half the script.
        fn = re.search(
            r"^_timeout\(\)\s*\{[^\n]*\}[ \t]*$|^_timeout\(\)\s*\{.*?^\}",
            body,
            re.DOTALL | re.MULTILINE,
        )
        assert fn, "audit-deps.sh no longer defines _timeout()"
        assert not re.search(r"\b(warn|ok|log)\b", fn.group(0)), (
            f"_timeout must not write to stdout, found: {fn.group(0)!r}"
        )


@pytest.mark.unit
class TestAuditStageWiring:
    def test_validate_defines_and_calls_run_audit_in_all(self):
        assert "run_audit" in _scope_arm("all")

    def test_audit_absent_from_fast_and_backend(self):
        assert "run_audit" not in _scope_arm("fast")
        assert "run_audit" not in _scope_arm("backend")
        assert "run_audit" not in _scope_arm("frontend")

    def test_run_audit_never_sets_rc(self):
        """Advisory: the stage must never mutate validate.sh's exit-code accumulator.

        Matches assignment *forms* (``rc=``, ``rc+=``, ``let rc``, ``((rc++))``)
        rather than the bare substring ``rc=`` — ``rc+=1`` contains no ``rc=``
        and would have slipped through. Reads of ``$rc`` stay allowed: the stage
        legitimately checks whether the gate already failed.
        """
        body = _run_audit_body()
        forbidden = re.search(r"\brc\s*(=|\+=)|\blet\s+rc|\(\(\s*rc", body)
        assert not forbidden, f"run_audit must not assign rc, found: {forbidden.group(0)!r}"

    def test_validate_never_passes_strict(self):
        """--strict is an operator-only mode; passing it from the gate would
        make dependency advisories merge-blocking.

        Matches any argument after the script path, not just the literal
        ``--strict``, so variable indirection cannot slip past. Backslash line
        continuations are *followed* rather than treated as a terminator — the
        script is already invoked across a continuation, so stopping at ``\\``
        would have let ``audit-deps.sh \\\\\\n --strict`` pass this lock.
        """
        # The continuation alternative must come FIRST: otherwise the character
        # class consumes the lone `\` and the match stops at the newline anyway.
        invocations = re.findall(
            r'bash "\$HERE/audit-deps\.sh"((?:\\\n|[^\n|&;])*)', VALIDATE_SH.read_text()
        )
        assert invocations, "validate.sh no longer invokes audit-deps.sh"
        for args in invocations:
            cleaned = args.replace("\\\n", " ").strip('" ')
            assert not cleaned, f"audit-deps.sh must be called with no arguments, got: {args!r}"

    def test_audit_runs_in_a_subshell_not_sourced(self):
        """``bash script`` not ``source script``: audit-deps.sh calls ``die`` on
        bad usage, and lib.sh sets ``-e`` — sourcing it would let the advisory
        stage kill validate.sh outright, taking the verdict with it."""
        body = _run_audit_body()
        assert 'bash "$HERE/audit-deps.sh"' in body
        assert not re.search(r"^\s*(source|\.)\s+\"?\$HERE/audit-deps\.sh", body, re.MULTILINE)

    def test_audit_is_skipped_once_the_gate_is_already_red(self):
        """The audit is the last stage and makes bounded network calls; spending
        minutes on it after validation already failed only delays a verdict."""
        body = _run_audit_body()
        assert re.search(r'\[\s*"\$rc"\s+-ne\s+0\s*\]', body), (
            "run_audit no longer short-circuits on an already-failed run"
        )

    def test_terminal_verdict_strings_unchanged(self):
        source = VALIDATE_SH.read_text()
        assert 'ok "VALIDATION PASSED"' in source
        assert 'warn "VALIDATION FAILED (rc=$rc)"' in source


def _stub(tmp_path: Path, name: str, payload: str) -> str:
    """Write an executable stub that prints ``payload`` on stdout and exits 0."""
    script = tmp_path / name
    script.write_text("#!/usr/bin/env bash\ncat <<'JSON'\n" + payload + "\nJSON\n")
    script.chmod(0o755)
    return str(script)


# Minimal payloads in each tool's real JSON shape.
PIP_CLEAN = '{"dependencies": [{"name": "fastapi", "version": "0.1", "vulns": []}], "fixes": []}'
PIP_ONE_VULN = (
    '{"dependencies": [{"name": "cryptography", "version": "49.0.0", '
    '"vulns": [{"id": "PYSEC-2026-3552", "fix_versions": ["50.0.0"]}]}], "fixes": []}'
)
PIP_BARE_LIST = '[{"name": "cryptography", "version": "49.0.0", "vulns": [{"id": "PYSEC-2026-3552", "fix_versions": ["50.0.0"]}]}]'
# One package audited, one skipped: a PARTIAL skip, which still yields a count.
PIP_SKIPPED = (
    '{"dependencies": [{"name": "fastapi", "version": "0.1", "vulns": []}, '
    '{"name": "weird-pkg", "skip_reason": "could not resolve"}], "fixes": []}'
)
# Nothing audited at all — every package skipped, or an empty resolution.
PIP_ALL_SKIPPED = '{"dependencies": [{"name": "weird-pkg", "skip_reason": "could not resolve"}], "fixes": []}'
PIP_EMPTY = '{"dependencies": [], "fixes": []}'
NPM_CLEAN = '{"metadata": {"vulnerabilities": {"critical": 0, "high": 0, "moderate": 0, "low": 0, "info": 0, "total": 0}}}'
NPM_TWO_HIGH = '{"metadata": {"vulnerabilities": {"critical": 0, "high": 2, "moderate": 0, "low": 0, "info": 0, "total": 2}}}'
# Real npm audit shape: the per-package section that carries isDirect/fixAvailable.
NPM_DIRECT_HIGH = (
    '{"vulnerabilities": {'
    '"react-router-dom": {"name": "react-router-dom", "severity": "high", "isDirect": true, '
    '"fixAvailable": {"name": "react-router-dom", "version": "7.9.4"}}, '
    '"nanoid": {"name": "nanoid", "severity": "moderate", "isDirect": false, "fixAvailable": false}}, '
    '"metadata": {"vulnerabilities": {"critical": 0, "high": 1, "moderate": 1, "low": 0, "info": 0, "total": 2}}}'
)
# `total` absent — the parser must sum the per-severity counts instead.
NPM_NO_TOTAL = '{"metadata": {"vulnerabilities": {"critical": 1, "high": 2, "moderate": 0, "low": 0, "info": 0}}}'
NPM_ERROR = '{"error": {"code": "ENETUNREACH", "summary": "registry unreachable"}}'
# npm resolved NOTHING (empty or unresolvable lockfile). `vulnerabilities.total`
# is legitimately 0 here, so only the dependency count separates this from a
# genuinely clean tree — the npm-side twin of PIP_ALL_SKIPPED/PIP_EMPTY.
NPM_NOTHING_AUDITED = (
    '{"metadata": {"vulnerabilities": {"critical": 0, "high": 0, "moderate": 0, "low": 0, '
    '"info": 0, "total": 0}, "dependencies": {"prod": 0, "dev": 0, "total": 0}}}'
)
# npm 6 reported metadata.dependencies as a bare integer.
NPM_NOTHING_AUDITED_V6 = (
    '{"metadata": {"vulnerabilities": {"critical": 0, "high": 0, "moderate": 0, "low": 0, '
    '"info": 0, "total": 0}, "dependencies": 0}}'
)
# The genuine clean result: a resolved tree of 388 packages with no advisories.
NPM_CLEAN_RESOLVED = (
    '{"metadata": {"vulnerabilities": {"critical": 0, "high": 0, "moderate": 0, "low": 0, '
    '"info": 0, "total": 0}, "dependencies": {"prod": 72, "dev": 316, "total": 388}}}'
)


def _run_audit(tmp_path, pip_payload, npm_payload, *args, **env_overrides):
    env = {
        **os.environ,
        "PIP_AUDIT_BIN": _stub(tmp_path, "pip-audit-stub", pip_payload),
        "NPM_BIN": _stub(tmp_path, "npm-stub", npm_payload),
        **env_overrides,
    }
    completed = subprocess.run(
        ["bash", str(AUDIT_SH), *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return completed.returncode, completed.stdout + completed.stderr


@pytest.mark.unit
class TestAuditParsing:
    """The parsers are the only real logic here, and the whole safety argument
    rests on them ("the JSON decides, not the exit code"). Drive real payloads
    through the script rather than asserting on its source text."""

    def test_counts_findings_from_both_sources(self, tmp_path):
        rc, out = _run_audit(tmp_path, PIP_ONE_VULN, NPM_TWO_HIGH)
        assert rc == 0, out
        assert "python: 1 known advisories" in out
        assert "cryptography 49.0.0 — PYSEC-2026-3552 (fix: 50.0.0)" in out
        assert "npm: 2 known advisories" in out
        assert "high: 2" in out
        assert "1 python + 2 npm advisories" in out

    def test_advisory_contract_holds_with_findings(self, tmp_path):
        """The core invariant: findings never make the script fail, so they can
        never turn validate.sh's verdict red."""
        rc, out = _run_audit(tmp_path, PIP_ONE_VULN, NPM_TWO_HIGH)
        assert rc == 0, out
        assert "DEGRADED RUN" not in out

    def test_clean_run_reports_zero_and_no_degradation(self, tmp_path):
        rc, out = _run_audit(tmp_path, PIP_CLEAN, NPM_CLEAN)
        assert rc == 0, out
        assert "python: no known advisories" in out
        assert "npm: no known advisories" in out
        assert "DEGRADED RUN" not in out

    def test_pip_audit_skipped_packages_are_not_reported_as_clean(self, tmp_path):
        """A package pip-audit could not resolve was NOT audited — it must not
        silently fold into 'no known advisories'."""
        rc, out = _run_audit(tmp_path, PIP_SKIPPED, NPM_CLEAN)
        assert rc == 0, out
        assert "1 package(s) skipped by pip-audit" in out

    @pytest.mark.parametrize("payload", [PIP_ALL_SKIPPED, PIP_EMPTY], ids=["all-skipped", "empty"])
    def test_a_tree_where_nothing_was_audited_is_degraded_not_clean(self, tmp_path, payload):
        """The hole this guards: when pip-audit resolves nothing (empty set, or
        skip_reason on every package) the advisory count is legitimately 0 — but
        reporting that as ``[OK] 0 advisories`` claims a clean bill of health for
        a tree nothing looked at, and let ``--strict`` exit 0 on it."""
        rc, out = _run_audit(tmp_path, payload, NPM_CLEAN)
        assert rc == 0, out
        assert "resolved no auditable packages" in out
        assert "python: no known advisories" not in out
        assert "skipped python" in out
        assert "DEGRADED RUN" in out

    def test_strict_fails_when_nothing_python_side_was_audited(self, tmp_path):
        rc, out = _run_audit(tmp_path, PIP_ALL_SKIPPED, NPM_CLEAN, "--strict")
        assert rc == 1, out

    def test_pip_bare_list_payload_is_parsed(self, tmp_path):
        """pip-audit <2 emits a bare list rather than {"dependencies": [...]}."""
        rc, out = _run_audit(tmp_path, PIP_BARE_LIST, NPM_CLEAN)
        assert rc == 0, out
        assert "python: 1 known advisories" in out
        assert "PYSEC-2026-3552" in out

    def test_npm_findings_name_the_package_direct_flag_and_fix(self, tmp_path):
        """A severity histogram cannot be triaged. ``isDirect`` and fix
        availability are what decide whether a finding matters — a high-severity
        *direct* runtime dependency must not hide inside '1 high'."""
        rc, out = _run_audit(tmp_path, PIP_CLEAN, NPM_DIRECT_HIGH)
        assert rc == 0, out
        assert "react-router-dom (high, DIRECT dependency) — fix: react-router-dom@7.9.4" in out
        assert "nanoid (moderate, transitive) — no fix published" in out

    def test_npm_total_missing_falls_back_to_summing_severities(self, tmp_path):
        rc, out = _run_audit(tmp_path, PIP_CLEAN, NPM_NO_TOTAL)
        assert rc == 0, out
        assert "npm: 3 known advisories" in out

    def test_invalid_audit_timeout_warns_instead_of_silently_disabling_the_audit(self, tmp_path):
        """A non-numeric AUDIT_TIMEOUT makes every ``timeout`` call exit 125,
        which reads as 'offline' — the audit would silently stop auditing while
        blaming the network."""
        rc, out = _run_audit(tmp_path, PIP_CLEAN, NPM_CLEAN, AUDIT_TIMEOUT="abc")
        assert rc == 0, out
        assert "invalid AUDIT_TIMEOUT" in out
        assert "python: no known advisories" in out, "audit must still run after the fallback"

    def test_binary_overrides_are_announced(self, tmp_path):
        """The stubs that make these tests possible also work in real runs, and
        validate.sh sources .env.local with `set -a` — an audit running something
        other than the real tools must say so."""
        rc, out = _run_audit(tmp_path, PIP_CLEAN, NPM_CLEAN)
        assert rc == 0, out
        assert "PIP_AUDIT_BIN override active" in out
        assert "NPM_BIN override active" in out

    def test_npm_error_payload_degrades_instead_of_counting_zero(self, tmp_path):
        """npm audit reports network failure as JSON with an `error` key — that
        is a degraded run, not a clean tree."""
        rc, out = _run_audit(tmp_path, PIP_CLEAN, NPM_ERROR)
        assert rc == 0, out
        assert "npm audit could not run" in out
        assert "DEGRADED RUN" in out

    def test_partial_degradation_still_announces_it_alongside_findings(self, tmp_path):
        """Regression guard: the degradation warning must not be suppressed just
        because the other source produced findings."""
        rc, out = _run_audit(tmp_path, PIP_ONE_VULN, NPM_ERROR)
        assert rc == 0, out
        assert "python: 1 known advisories" in out
        assert "DEGRADED RUN" in out

    def test_strict_exits_one_on_findings(self, tmp_path):
        rc, out = _run_audit(tmp_path, PIP_ONE_VULN, NPM_CLEAN, "--strict")
        assert rc == 1, out

    def test_strict_exits_zero_only_when_fully_audited_and_clean(self, tmp_path):
        rc, out = _run_audit(tmp_path, PIP_CLEAN, NPM_CLEAN, "--strict")
        assert rc == 0, out

    def test_strict_exits_one_when_nothing_was_audited(self, tmp_path):
        """An operator security check must not report green having audited
        nothing — 'did not run' is distinguishable from 'clean'."""
        rc, out = _run_audit(tmp_path, PIP_CLEAN, NPM_ERROR, "--strict")
        assert rc == 1, out

    @pytest.mark.parametrize(
        "payload", [NPM_NOTHING_AUDITED, NPM_NOTHING_AUDITED_V6], ids=["npm7-object", "npm6-int"]
    )
    def test_npm_tree_where_nothing_was_audited_is_degraded_not_clean(self, tmp_path, payload):
        """The npm-side twin of the pip 'nothing audited' guard.

        ``metadata.vulnerabilities.total`` is legitimately 0 for an empty or
        unresolvable lockfile, so counting it alone reported ``[OK] npm: no known
        advisories`` over a tree nothing looked at — and let ``--strict`` exit 0
        on it. Only ``metadata.dependencies`` distinguishes the two.
        """
        rc, out = _run_audit(tmp_path, PIP_CLEAN, payload)
        assert rc == 0, out
        assert "npm audit resolved no auditable packages" in out
        assert "npm: no known advisories" not in out
        assert "skipped npm" in out
        assert "DEGRADED RUN" in out

    def test_strict_fails_when_nothing_npm_side_was_audited(self, tmp_path):
        rc, out = _run_audit(tmp_path, PIP_CLEAN, NPM_NOTHING_AUDITED, "--strict")
        assert rc == 1, out

    def test_a_resolved_npm_tree_with_no_advisories_is_still_clean(self, tmp_path):
        """Guard the other direction: the dependency-count check must not turn a
        genuine clean result into a false degradation."""
        rc, out = _run_audit(tmp_path, PIP_CLEAN, NPM_CLEAN_RESOLVED, "--strict")
        assert rc == 0, out
        assert "npm: no known advisories" in out
        assert "DEGRADED RUN" not in out

    @pytest.mark.parametrize("value", ["0", "0s", "00"], ids=["zero", "zero-suffixed", "padded-zero"])
    def test_zero_audit_timeout_is_rejected(self, tmp_path, value):
        """coreutils reads ``timeout 0`` as *no limit*, so ``0`` is the one value
        that voids the bound this variable exists to enforce — it must not pass
        the guard that enforces it."""
        rc, out = _run_audit(tmp_path, PIP_CLEAN, NPM_CLEAN, AUDIT_TIMEOUT=value)
        assert rc == 0, out
        assert "invalid AUDIT_TIMEOUT" in out
        assert "python: no known advisories" in out, "audit must still run after the fallback"

    @pytest.mark.parametrize("value", ["30s", "2m", "180"], ids=["seconds", "minutes", "bare"])
    def test_coreutils_duration_suffixes_are_accepted(self, tmp_path, value):
        """The docs tell readers to tune AUDIT_TIMEOUT; ``30s``/``2m`` are the
        natural way to write a coreutils duration and must not be rejected."""
        rc, out = _run_audit(tmp_path, PIP_CLEAN, NPM_CLEAN, AUDIT_TIMEOUT=value)
        assert rc == 0, out
        assert "invalid AUDIT_TIMEOUT" not in out
        assert "python: no known advisories" in out

    def test_tools_are_invoked_with_the_json_flags_the_parsers_require(self, tmp_path):
        """Every other test stubs a tool that ignores its arguments, so dropping
        ``--format json`` (pip-audit defaults to columns) or npm's ``--json``
        would make every real run unparseable — a permanent silent "offline"
        skip — while the whole suite stayed green. Assert the argv."""
        recorded = tmp_path / "argv.txt"
        stub = tmp_path / "recording-stub"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$*" >> {recorded}\n'
            "cat <<'JSON'\n" + PIP_CLEAN + "\nJSON\n"
        )
        stub.chmod(0o755)
        npm_stub = tmp_path / "recording-npm-stub"
        npm_stub.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$*" >> {recorded}\n'
            "cat <<'JSON'\n" + NPM_CLEAN_RESOLVED + "\nJSON\n"
        )
        npm_stub.chmod(0o755)
        completed = subprocess.run(
            ["bash", str(AUDIT_SH)],
            cwd=str(REPO_ROOT),
            env={**os.environ, "PIP_AUDIT_BIN": str(stub), "NPM_BIN": str(npm_stub)},
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        argv = recorded.read_text()
        assert "--format json" in argv, f"pip-audit must request JSON, got: {argv!r}"
        assert "--requirement requirements.txt" in argv
        assert "audit --json" in argv, f"npm must request JSON, got: {argv!r}"

    def test_audit_still_runs_when_coreutils_timeout_is_unavailable(self, tmp_path):
        """``warn`` writes to STDOUT and ``_timeout`` runs inside the command
        substitution that captures the tool's JSON. Warning from there polluted
        the payload, so a host without ``timeout`` skipped BOTH audits and blamed
        the network, and the UNBOUNDED notice was swallowed with it."""
        shim = tmp_path / "nt"
        shim.mkdir()
        for directory in ("/usr/bin", "/bin", "/usr/local/bin"):
            src = Path(directory)
            if not src.is_dir():
                continue
            for entry in src.iterdir():
                if entry.name == "timeout":
                    continue
                target = shim / entry.name
                if not target.exists():
                    try:
                        target.symlink_to(entry)
                    except OSError:
                        pass
        if not (shim / "bash").exists() or not (shim / "git").exists():
            pytest.skip("could not build a timeout-free PATH shim on this host")

        env = {
            **os.environ,
            "PATH": str(shim),
            "PIP_AUDIT_BIN": _stub(tmp_path, "pip-audit-stub", PIP_CLEAN),
            "NPM_BIN": _stub(tmp_path, "npm-stub", NPM_CLEAN_RESOLVED),
        }
        completed = subprocess.run(
            ["bash", str(AUDIT_SH)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        out = completed.stdout + completed.stderr
        assert completed.returncode == 0, out
        assert "UNBOUNDED" in out, "the unbounded notice must reach the log, not the JSON payload"
        assert "python: no known advisories" in out, "the audit must still run unbounded"
        assert "npm: no known advisories" in out
        assert "could not run (offline or tool error)" not in out


@pytest.mark.unit
class TestAuditDegradation:
    def test_missing_tools_skip_out_loud(self):
        """Distinct from the stubbed-failure path below: this exercises the
        `command -v` branches, i.e. the tool is not installed at all."""
        env = {
            **os.environ,
            "PIP_AUDIT_BIN": "definitely-not-installed-pip-audit",
            "NPM_BIN": "definitely-not-installed-npm",
        }
        completed = subprocess.run(
            ["bash", str(AUDIT_SH)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        output = completed.stdout + completed.stderr
        assert completed.returncode == 0, output
        assert "pip-audit not installed" in output
        assert "npm not installed" in output
        assert "DEGRADED RUN" in output

    def test_exits_zero_and_warns_when_both_tools_fail(self):
        """The installed-but-failing path (offline, registry error, crash): the
        tool resolves, runs, and emits nothing parseable. Both audits must skip
        out loud, and the script must still exit 0."""
        env = {**os.environ, "PIP_AUDIT_BIN": "/bin/false", "NPM_BIN": "/bin/false"}
        completed = subprocess.run(
            ["bash", str(AUDIT_SH)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        output = completed.stdout + completed.stderr
        assert completed.returncode == 0, output
        assert "[WARN]" in output
        skips = [line for line in output.splitlines() if "skipping" in line]
        assert len(skips) >= 2, f"expected a visible skip per audit, got:\n{output}"
        assert "python" in output
        assert "npm" in output

    def test_strict_mode_fails_a_fully_degraded_run(self):
        """--strict is a deliberate operator security check: it must not report
        green when nothing was audited. Only the DEFAULT mode is unconditionally
        exit 0 (that is what keeps the gate advisory)."""
        env = {**os.environ, "PIP_AUDIT_BIN": "/bin/false", "NPM_BIN": "/bin/false"}
        completed = subprocess.run(
            ["bash", str(AUDIT_SH), "--strict"],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert completed.returncode == 1, completed.stdout + completed.stderr
