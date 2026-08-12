"""Hosting contract for the cloud backfill supervisor (story v0.13-s3.1, ADR 0006).

``POST /admin/backfill/start`` only records a request; the thing that consumes it
is ``scripts/dev/backfill_gemma.py --serve``, which until now had no committed
home at all (DW-27). The home is ``deploy/systemd/imoveis-backfill-serve.service.in``
plus ``scripts/install-backfill-runner.sh``, and these tests drive the real
installer in its unprivileged modes (``--print`` / ``--check`` / ``--help`` /
``--status``) over ``tmp_path`` fixtures.

What is locked here is everything that can silently rot:

* the rendered unit's directives *and the section each one lives in* — systemd
  ignores ``StartLimitIntervalSec`` outside ``[Unit]`` and ``WantedBy`` outside
  ``[Install]`` without a word of complaint;
* the ones whose *absence* is a production failure (``Restart=always``,
  ``StartLimitIntervalSec=0``, a ``TimeoutStopSec`` at least as long as the
  backfill lease TTL);
* the ``ExecStart`` target actually existing in the repo — a path pin, because
  the whole point of committing the unit is that moving the script breaks a
  test instead of breaking the operator's next reboot;
* that a re-install actually takes effect (``systemctl restart``, never the
  no-op ``enable --now`` on an already-running unit);
* that no value from the env file is ever echoed (only variable NAMES), NFR-3;
* that the installer performs no container-stack action, so the primary compose
  project stays inviolable.

Hermetic by construction: no network, no container runtime, no ``sudo``, no
``systemctl`` side effects, and never the developer's own ``.env.local`` — every
invocation passes an explicit ``--env-file``. Install mode is only ever exercised
on a *simulated* linked worktree, behind a stub ``sudo``/``systemctl`` on
``PATH`` that records any privileged call the guard failed to prevent.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest
import yaml

from infra.config import BackfillConfig

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALLER = REPO_ROOT / "scripts" / "install-backfill-runner.sh"
TEMPLATE = REPO_ROOT / "deploy" / "systemd" / "imoveis-backfill-serve.service.in"
RUNNER_REL = "scripts/dev/backfill_gemma.py"
CONFIG_YAML = REPO_ROOT / "configs" / "app_config.yaml"

_SECRET = "not-a-real-key-3f9c1a"


def _run(*args: str, timeout: int = 60, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALLER), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, **(env or {})},
    )


def _write_env(tmp_path: Path, body: str, name: str = "env.local") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _complete_env(tmp_path: Path) -> Path:
    return _write_env(
        tmp_path,
        f"GEMINI_API_KEY={_SECRET}\n"
        "DATABASE_URL=postgresql://imoveis:pw@localhost:5432/realestate\n"
        "REDIS_URL=redis://localhost:6379/0\n",
    )


def _parsed(unit_text: str) -> list[tuple[str, str, str]]:
    """``(section, key, value)`` per effective directive — the template is heavily commented."""
    section = ""
    parsed: list[tuple[str, str, str]] = []
    for raw in unit_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        parsed.append((section, key.strip(), value.strip()))
    return parsed


def _values(unit_text: str, key: str, section: str) -> list[str]:
    return [value for sect, name, value in _parsed(unit_text) if name == key and sect == section]


def _directive(unit_text: str, key: str, section: str) -> str:
    """The single ``key=`` value inside ``[section]`` — a directive in the wrong section fails."""
    found = _values(unit_text, key, section)
    if len(found) != 1:
        elsewhere = [(s, v) for s, k, v in _parsed(unit_text) if k == key]
        raise AssertionError(
            f"expected exactly one {key}= in [{section}], got {found} (all occurrences: {elsewhere})\n{unit_text}"
        )
    return found[0]


def _configured_lease_ttl() -> int:
    """Effective ``backfill.lease_ttl_seconds`` (YAML wins over the model default)."""
    data = yaml.safe_load(CONFIG_YAML.read_text(encoding="utf-8")) or {}
    value = (data.get("backfill") or {}).get("lease_ttl_seconds")
    if isinstance(value, int):
        return value
    return BackfillConfig().lease_ttl_seconds


@pytest.mark.unit
class TestInstallerArtifacts:
    def test_installer_exists_and_is_executable(self):
        assert INSTALLER.exists(), f"{INSTALLER} is missing"
        assert os.access(INSTALLER, os.X_OK), f"{INSTALLER} must be executable"

    def test_unit_template_is_committed(self):
        assert TEMPLATE.exists(), f"{TEMPLATE} is missing"
        body = TEMPLATE.read_text(encoding="utf-8")
        for token in ("@@USER@@", "@@REPO_ROOT@@", "@@PYTHON@@", "@@ENV_FILE@@", "@@TIMEOUT_STOP@@"):
            assert token in body, f"template lost its {token} placeholder"

    def test_installer_performs_no_container_stack_action(self):
        """Primary-stack inviolability: no compose/container CLI call, ever."""
        body = INSTALLER.read_text(encoding="utf-8").lower()
        assert "docker" not in body, "the installer must not invoke any container tooling"
        assert "podman" not in body

    def test_reinstall_restarts_instead_of_enable_now(self):
        """`enable --now` no-ops on a running unit: a re-install would keep the OLD ExecStart.

        Source-level assertion by necessity — the behaviour needs root and a live systemd.
        """
        body = INSTALLER.read_text(encoding="utf-8")
        assert "systemctl restart" in body, "install must restart the unit so a re-install takes effect"
        assert "enable --now" not in body, "`enable --now` silently no-ops on an already-active unit"


@pytest.mark.unit
class TestRenderedUnit:
    def test_print_renders_every_required_directive(self, tmp_path):
        env_file = _complete_env(tmp_path)
        result = _run("--print", "--user", "opuser", "--python", "/bin/sh", "--env-file", str(env_file))

        assert result.returncode == 0, result.stderr
        unit = result.stdout
        assert "@@" not in unit, "an unrendered placeholder survived"

        assert _directive(unit, "User", "Service") == "opuser"
        assert _directive(unit, "WorkingDirectory", "Service") == str(REPO_ROOT)
        assert _directive(unit, "EnvironmentFile", "Service") == str(env_file)
        assert _directive(unit, "ExecStart", "Service") == f"/bin/sh {REPO_ROOT / RUNNER_REL} --serve"
        assert _directive(unit, "Type", "Service") == "simple"
        assert _directive(unit, "Restart", "Service") == "always"
        assert _directive(unit, "RestartSec", "Service") == "10"
        assert _directive(unit, "KillSignal", "Service") == "SIGTERM"
        assert _directive(unit, "SyslogIdentifier", "Service") == "imoveis-backfill-serve"
        assert _directive(unit, "NoNewPrivileges", "Service") == "yes"
        # A restart limit must never park the unit in `failed` — and systemd only
        # honours StartLimitIntervalSec in [Unit].
        assert _directive(unit, "StartLimitIntervalSec", "Unit") == "0"
        assert _directive(unit, "WantedBy", "Install") == "multi-user.target"

    def test_environment_carries_pythonpath_and_unbuffered_output(self, tmp_path):
        """Unbuffered stdout: without it `journalctl -f` shows nothing for long stretches."""
        env_file = _complete_env(tmp_path)
        result = _run("--print", "--python", "/bin/sh", "--env-file", str(env_file))
        assert result.returncode == 0, result.stderr

        environment = _values(result.stdout, "Environment", "Service")
        assert "PYTHONPATH=src" in environment
        assert "PYTHONUNBUFFERED=1" in environment

    def test_boot_ordering_is_after_without_requires(self, tmp_path):
        """Docker Desktop hosts have no docker.service; Requires= would refuse to start."""
        env_file = _complete_env(tmp_path)
        result = _run("--print", "--python", "/bin/sh", "--env-file", str(env_file))
        assert result.returncode == 0, result.stderr
        after = _directive(result.stdout, "After", "Unit")
        assert "network-online.target" in after
        assert "docker.service" in after
        assert not [key for _, key, _ in _parsed(result.stdout) if key == "Requires"]

    def test_execstart_target_exists_in_the_repo(self, tmp_path):
        """Path pin: moving the runner must break this test, not the operator's reboot."""
        env_file = _complete_env(tmp_path)
        result = _run("--print", "--python", "/bin/sh", "--env-file", str(env_file))
        assert result.returncode == 0, result.stderr

        exec_start = _directive(result.stdout, "ExecStart", "Service")
        script = Path(exec_start.split()[1])
        assert script.is_absolute(), "systemd resolves ExecStart as given — it must be absolute"
        assert script == REPO_ROOT / RUNNER_REL
        assert script.is_file(), f"{script} does not exist"

    def test_stop_timeout_is_at_least_the_lease_ttl(self, tmp_path):
        """A shorter timeout SIGKILLs a lease-holding run half-written mid-property."""
        env_file = _complete_env(tmp_path)
        result = _run("--print", "--python", "/bin/sh", "--env-file", str(env_file))
        assert result.returncode == 0, result.stderr
        timeout_stop = int(_directive(result.stdout, "TimeoutStopSec", "Service"))
        assert timeout_stop >= _configured_lease_ttl()

    def test_print_needs_no_valid_host_and_exits_zero(self, tmp_path):
        """Rendering for inspection is advisory-only: a broken env warns, never fails."""
        result = _run("--print", "--python", str(tmp_path / "absent-python"), "--env-file", str(tmp_path / "absent-env"))
        assert result.returncode == 0, result.stderr
        assert "@@" not in result.stdout
        assert "GEMINI_API_KEY" in result.stderr or "Env file not found" in result.stderr

    def test_sed_metacharacters_in_a_value_render_literally(self, tmp_path):
        """An unescaped `&` re-expands the match: `--user 'a&b'` used to render `a@@USER@@b`."""
        env_file = _complete_env(tmp_path)
        result = _run("--print", "--user", "a&b", "--python", "/bin/sh", "--env-file", str(env_file))

        assert result.returncode == 0, result.stderr
        assert _directive(result.stdout, "User", "Service") == "a&b"
        assert "@@" not in result.stdout

    def test_unresolved_placeholder_is_never_rendered_out(self, tmp_path):
        """A template placeholder the installer does not know must fail loudly, not ship."""
        fake_root = tmp_path / "imoveis-copy"
        (fake_root / "deploy" / "systemd").mkdir(parents=True)
        (fake_root / "deploy" / "systemd" / TEMPLATE.name).write_text(
            TEMPLATE.read_text(encoding="utf-8").replace("@@USER@@", "@@UNKNOWN@@"), encoding="utf-8"
        )
        env_file = _complete_env(tmp_path)

        result = _run("--print", "--repo-root", str(fake_root), "--python", "/bin/sh", "--env-file", str(env_file))

        assert result.returncode != 0
        assert "@@UNKNOWN@@" in result.stderr
        assert "@@UNKNOWN@@" not in result.stdout


@pytest.mark.unit
class TestPreflight:
    @pytest.mark.parametrize(
        "body, missing",
        [
            ("DATABASE_URL=postgresql://x@localhost:5432/realestate\n", "GEMINI_API_KEY"),
            (f"GEMINI_API_KEY={_SECRET}\n", "DATABASE_URL"),
            (f"GEMINI_API_KEY=\nDATABASE_URL={_SECRET}\n", "GEMINI_API_KEY"),
        ],
    )
    def test_incomplete_env_contract_fails_check_naming_the_variable(self, tmp_path, body, missing):
        env_file = _write_env(tmp_path, body)
        result = _run("--check", "--python", "/bin/sh", "--env-file", str(env_file))

        assert result.returncode != 0
        assert missing in result.stderr

    def test_exported_key_fails_because_systemd_is_not_a_shell(self, tmp_path):
        """`EnvironmentFile=` keeps the literal `export ` prefix, so the variable ends up unset."""
        env_file = _write_env(
            tmp_path,
            f"export GEMINI_API_KEY={_SECRET}\n"
            "DATABASE_URL=postgresql://u:p@localhost:5432/realestate\n",
        )
        result = _run("--check", "--python", "/bin/sh", "--env-file", str(env_file))

        assert result.returncode != 0
        assert "GEMINI_API_KEY" in result.stderr
        assert "export" in result.stderr
        assert _SECRET not in result.stderr

    def test_crlf_env_file_fails_preflight(self, tmp_path):
        """A WSL-authored CRLF file gives every value a trailing \\r inside the service."""
        env_file = _write_env(
            tmp_path,
            f"GEMINI_API_KEY={_SECRET}\r\nDATABASE_URL=postgresql://u:p@localhost:5432/realestate\r\n",
        )
        result = _run("--check", "--python", "/bin/sh", "--env-file", str(env_file))

        assert result.returncode != 0
        assert "CRLF" in result.stderr

    def test_config_default_database_name_warns(self, tmp_path):
        """The whole reason DATABASE_URL is required: the config default DB is not `realestate`."""
        env_file = _write_env(
            tmp_path,
            f"GEMINI_API_KEY={_SECRET}\nDATABASE_URL=postgresql://u:p@localhost:5432/imoveis\n",
        )
        result = _run("--check", "--python", "/bin/sh", "--env-file", str(env_file))

        assert "realestate" in result.stderr
        assert "DATABASE_URL" in result.stderr

    def test_no_env_value_is_ever_echoed(self, tmp_path):
        """NFR-3: only variable NAMES appear — never the value behind one."""
        env_file = _write_env(
            tmp_path,
            f"GEMINI_API_KEY={_SECRET}\nDATABASE_URL=postgresql://u:{_SECRET}@localhost:5432/realestate\n",
        )
        for mode in ("--print", "--check"):
            result = _run(mode, "--python", "/bin/sh", "--env-file", str(env_file))
            assert _SECRET not in result.stdout, f"{mode} leaked an env value on stdout"
            assert _SECRET not in result.stderr, f"{mode} leaked an env value on stderr"

    def test_non_default_redis_port_without_redis_url_warns(self, tmp_path):
        env_file = _write_env(
            tmp_path,
            f"GEMINI_API_KEY={_SECRET}\n"
            "DATABASE_URL=postgresql://u:p@localhost:5432/realestate\n"
            "REDIS_PORT=6399\n",
        )
        result = _run("--check", "--python", "/bin/sh", "--env-file", str(env_file))
        assert "REDIS_URL" in result.stderr
        assert "REDIS_PORT" in result.stderr

    @pytest.mark.parametrize("line", ["REDIS_PORT=6379\n", "REDIS_PORT=6379 # default\n", 'REDIS_PORT="6379"\n'])
    def test_default_redis_port_does_not_warn(self, tmp_path, line):
        """An inline comment is not part of the value — `6379 # default` is still the default."""
        env_file = _write_env(
            tmp_path,
            f"GEMINI_API_KEY={_SECRET}\n"
            "DATABASE_URL=postgresql://u:p@localhost:5432/realestate\n" + line,
        )
        result = _run("--check", "--python", "/bin/sh", "--env-file", str(env_file))
        assert "REDIS_PORT" not in result.stderr

    def test_missing_interpreter_refuses_and_points_at_setup(self, tmp_path):
        env_file = _complete_env(tmp_path)
        missing_python = tmp_path / "venv" / "bin" / "python"
        result = _run("--check", "--python", str(missing_python), "--env-file", str(env_file))

        assert result.returncode != 0
        assert str(missing_python) in result.stderr
        assert "setup.sh" in result.stderr

    def test_force_downgrades_preflight_failures_to_warnings(self, tmp_path):
        """Escape hatch for hosts configuring key/DB via IMOVEIS_<SECTION>__<KEY> overrides."""
        fake_root = tmp_path / "elsewhere"
        fake_root.mkdir()
        args = ("--check", "--repo-root", str(fake_root), "--python", "/bin/sh", "--env-file", str(tmp_path / "absent"))

        refused = _run(*args)
        assert refused.returncode != 0

        forced = _run(*args, "--force")
        assert forced.returncode == 0, forced.stderr
        assert "WARN" in forced.stderr, "--force must still print what it is ignoring"
        assert "Env file not found" in forced.stderr


@pytest.mark.unit
class TestEffectiveRoutingPreflight:
    """Preflight resolves the EFFECTIVE routing map — YAML *and* env override (DW-31).

    ``--serve`` reads routing through ``AppConfig``: the YAML map first, then the
    generic ``IMOVEIS_<SECTION>__<KEY>`` overrides on top (env wins). The env file
    IS the unit's ``EnvironmentFile=``, so a preflight that greps only the YAML
    lies in both directions — it told a host correctly enabled through the env
    override that the unit "would exit at startup and restart forever".

    The verdict is the one ``--serve`` itself computes
    (``backfill_gemma.py::_resolve_backfill_backend``): **every** class in the
    runner's default scope (``visual``, ``sentiment``, ``deal_verdict``) must
    resolve to a cloud backend, and they must all name the **same** one — one run
    drives one client and has no local mode. "At least one class is cloud" was the
    earlier reading and it certifies a host that crash-loops.

    The committed YAML stays all-local (NFR-1, pinned by
    ``test_config.py::test_enrichment_routing_default_all_local``), so the env
    override is the *only* enablement surface the operator may be pointed at.
    """

    #: Distinctive fragment of the partial-scope warning (some class stayed local).
    LOCAL_SCOPE_MARKER = "do not resolve to a cloud backend"
    #: Distinctive fragment of the same-backend warning (all cloud, two backends).
    MIXED_BACKEND_MARKER = "mixes cloud backends"
    #: The positive line: routing resolved, the run can start.
    READY_MARKER = "Effective backfill routing:"
    OVERRIDE_PREFIX = "IMOVEIS_AI__ENRICHMENT_ROUTING__"
    #: src/core/backfill_runner.py::DEFAULT_BACKFILL_SCOPE, in the installer's order.
    SCOPE_CLASSES = ("visual", "sentiment", "deal_verdict")

    @staticmethod
    def _env(tmp_path: Path, *extra: str) -> Path:
        """A complete runner env contract plus any routing override lines."""
        return _write_env(
            tmp_path,
            f"GEMINI_API_KEY={_SECRET}\n"
            "DATABASE_URL=postgresql://u:p@localhost:5432/realestate\n" + "".join(f"{line}\n" for line in extra),
        )

    @classmethod
    def _cloud_env(cls, tmp_path: Path, backend: str, *extra: str) -> Path:
        """The sanctioned enablement: every scoped class overridden to *backend*."""
        return cls._env(
            tmp_path,
            *(f"{cls.OVERRIDE_PREFIX}{name.upper()}={backend}" for name in cls.SCOPE_CLASSES),
            *extra,
        )

    @staticmethod
    def _repo_root_routing(tmp_path: Path, visual: str, *, whole_scope: bool = False) -> Path:
        """A stand-in checkout whose committed YAML routes cloud.

        ``whole_scope`` routes every class of the backfill scope to *visual* —
        the only shape a legacy host could have run on, since ``--serve`` needs
        all three. Otherwise only ``visual`` is routed there.
        """
        scoped = visual if whole_scope else "ollama"
        root = tmp_path / "legacy-checkout"
        (root / "configs").mkdir(parents=True)
        (root / "configs" / "app_config.yaml").write_text(
            "ai:\n"
            "  enrichment_routing:\n"
            f"    visual: {visual}\n"
            f"    sentiment: {scoped}\n"
            f"    deal_verdict: {scoped}\n"
            "    valuation: ollama\n"
            "    embedding: ollama\n",
            encoding="utf-8",
        )
        return root

    @classmethod
    def _classes_reported_local(cls, stderr: str) -> list[str]:
        """The task classes named on the line under the partial-scope warning."""
        lines = stderr.splitlines()
        index = next((i for i, line in enumerate(lines) if cls.LOCAL_SCOPE_MARKER in line), None)
        assert index is not None, f"no partial-scope warning in:\n{stderr}"
        return [word for word in lines[index + 1].split() if word in cls.SCOPE_CLASSES]

    @classmethod
    def _ready_line(cls, stderr: str) -> str:
        found = [line for line in stderr.splitlines() if cls.READY_MARKER in line]
        assert len(found) == 1, f"expected exactly one routing verdict line, got {found}\n{stderr}"
        return found[0]

    @pytest.mark.parametrize("backend", ["gemma", "gemini"])
    def test_env_override_to_cloud_reports_ready_without_a_routing_warning(self, tmp_path, backend):
        """The sanctioned enablement: shipped all-local YAML + the per-host overrides."""
        env_file = self._cloud_env(tmp_path, backend)
        result = _run("--check", "--force", "--python", "/bin/sh", "--env-file", str(env_file))

        assert result.returncode == 0, result.stderr
        assert self.LOCAL_SCOPE_MARKER not in result.stderr, "a correctly enabled host was told it would crash-loop"
        assert self.MIXED_BACKEND_MARKER not in result.stderr
        ready = self._ready_line(result.stderr)
        assert backend in ready, f"the verdict must name the resolved backend: {ready}"
        for task_class in self.SCOPE_CLASSES:
            assert task_class in ready

    def test_partial_scope_override_warns_naming_the_classes_still_local(self, tmp_path):
        """One class cloud is NOT enablement — ``--serve`` needs the whole scope.

        The regression for the false OK: under the earlier "at least one class is
        cloud" reading this host was certified ready and then crash-looped.
        """
        env_file = self._env(tmp_path, f"{self.OVERRIDE_PREFIX}VISUAL=gemma")
        result = _run("--check", "--force", "--python", "/bin/sh", "--env-file", str(env_file))

        assert self.LOCAL_SCOPE_MARKER in result.stderr, "a partially-routed host was certified ready"
        assert self._classes_reported_local(result.stderr) == ["sentiment", "deal_verdict"]
        assert self.READY_MARKER not in result.stderr

    def test_scope_split_across_two_cloud_backends_warns(self, tmp_path):
        """All three cloud but not the SAME cloud: one run drives one client."""
        env_file = self._env(
            tmp_path,
            f"{self.OVERRIDE_PREFIX}VISUAL=gemma",
            f"{self.OVERRIDE_PREFIX}SENTIMENT=gemini",
            f"{self.OVERRIDE_PREFIX}DEAL_VERDICT=gemma",
        )
        result = _run("--check", "--force", "--python", "/bin/sh", "--env-file", str(env_file))

        assert self.MIXED_BACKEND_MARKER in result.stderr
        assert self.LOCAL_SCOPE_MARKER not in result.stderr, "every class IS cloud-routed here"
        assert self.READY_MARKER not in result.stderr
        for named in ("gemma", "gemini"):
            assert named in result.stderr, "the warning must show which class went where"

    def test_all_local_host_warns_and_prescribes_the_env_override(self, tmp_path):
        """The warning must still fire — and must never send the operator to the YAML."""
        env_file = self._env(tmp_path)
        result = _run("--check", "--force", "--python", "/bin/sh", "--env-file", str(env_file))

        assert self.LOCAL_SCOPE_MARKER in result.stderr
        assert self._classes_reported_local(result.stderr) == list(self.SCOPE_CLASSES)
        for task_class in self.SCOPE_CLASSES:
            assert f"{self.OVERRIDE_PREFIX}{task_class.upper()}=gemma" in result.stderr
        assert "Do NOT edit" in result.stderr, "the warning must warn the operator off the committed YAML"
        assert "configs/app_config.yaml" in result.stderr

    def test_yaml_routed_host_still_does_not_warn(self, tmp_path):
        """A legacy host whose checked-out YAML routes the whole scope cloud is unchanged."""
        root = self._repo_root_routing(tmp_path, "gemma", whole_scope=True)
        env_file = self._env(tmp_path)
        result = _run("--check", "--force", "--repo-root", str(root), "--python", "/bin/sh", "--env-file", str(env_file))

        assert result.returncode == 0, result.stderr
        assert self.LOCAL_SCOPE_MARKER not in result.stderr
        assert self.MIXED_BACKEND_MARKER not in result.stderr
        assert "gemma" in self._ready_line(result.stderr)

    def test_override_sending_a_scoped_class_local_warns(self, tmp_path):
        """Env wins over YAML: an override to a local backend takes that class away."""
        root = self._repo_root_routing(tmp_path, "gemma", whole_scope=True)
        env_file = self._env(tmp_path, f"{self.OVERRIDE_PREFIX}SENTIMENT=ollama")
        result = _run("--check", "--force", "--repo-root", str(root), "--python", "/bin/sh", "--env-file", str(env_file))

        assert self.LOCAL_SCOPE_MARKER in result.stderr
        assert self._classes_reported_local(result.stderr) == ["sentiment"]

    def test_exported_routing_override_fails_because_systemd_is_not_a_shell(self, tmp_path):
        """`EnvironmentFile=` keeps the literal `export `, so the override never reaches the unit."""
        env_file = self._env(tmp_path, f"export {self.OVERRIDE_PREFIX}VISUAL=gemma")
        result = _run("--check", "--python", "/bin/sh", "--env-file", str(env_file))

        assert result.returncode != 0
        assert f"{self.OVERRIDE_PREFIX}VISUAL" in result.stderr
        assert "export" in result.stderr

    @pytest.mark.parametrize(
        "line, variable, reason",
        [
            # AppConfig validates backend names EXACTLY: `GEMMA` is a ConfigError
            # at startup, i.e. a crash loop behind a certified-OK install.
            (f"{OVERRIDE_PREFIX}VISUAL=GEMMA", f"{OVERRIDE_PREFIX}VISUAL", "not a known backend"),
            # A misspelled class is syntactically fine for systemd and fatal for AppConfig.
            (f"{OVERRIDE_PREFIX}VISUALS=gemma", f"{OVERRIDE_PREFIX}VISUALS", "not an enrichment task class"),
            # An empty override still REPLACES the YAML value with ''.
            (f"{OVERRIDE_PREFIX}VISUAL=", f"{OVERRIDE_PREFIX}VISUAL", "is empty"),
        ],
        ids=["wrong-case-backend", "unknown-task-class", "empty-value"],
    )
    def test_unusable_routing_override_fails_preflight(self, tmp_path, line, variable, reason):
        """Syntactically fine for systemd, fatal for AppConfig — preflight must refuse."""
        env_file = self._env(tmp_path, line)
        result = _run("--check", "--python", "/bin/sh", "--env-file", str(env_file))

        assert result.returncode != 0, result.stderr
        offending = [text for text in result.stderr.splitlines() if variable in text and reason in text]
        assert offending, f"no failure naming {variable} ({reason}) in:\n{result.stderr}"
        assert all("[FAIL]" in text for text in offending), f"reported as advisory, not fatal: {offending}"
        assert _SECRET not in result.stderr

    def test_shipped_config_stays_all_local(self):
        """NFR-1: the committed YAML routes every class local — enablement is per-host env."""
        routing = (yaml.safe_load(CONFIG_YAML.read_text(encoding="utf-8")) or {})["ai"]["enrichment_routing"]
        assert set(routing.values()) == {"ollama"}, "the committed config must stay all-local (NFR-1)"


@pytest.mark.unit
class TestInstallGuards:
    @staticmethod
    def _privileged_stubs(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
        """A stub `sudo`/`systemctl` first on PATH, so a guard regression is a test failure.

        With a warm sudo timestamp, only the worktree guard stands between this test and a
        real `sudo install` into /etc/systemd/system. The stubs record and refuse instead.
        """
        bin_dir = tmp_path / "stub-bin"
        bin_dir.mkdir()
        sudo_marker = tmp_path / "sudo-was-called"
        systemctl_marker = tmp_path / "systemctl-was-called"
        for name, marker in (("sudo", sudo_marker), ("systemctl", systemctl_marker)):
            stub = bin_dir / name
            stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{marker}"\nexit 97\n', encoding="utf-8")
            stub.chmod(0o755)
        return {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}, sudo_marker, systemctl_marker

    def test_install_refuses_from_a_linked_worktree(self, tmp_path):
        """A worktree path is disposable (teardown --remove); a unit pinned to it rots."""
        fake_root = tmp_path / "imoveis-wt-demo"
        fake_root.mkdir()
        (fake_root / ".git").write_text("gitdir: /home/op/imoveis/.git/worktrees/demo\n", encoding="utf-8")
        env_file = _complete_env(tmp_path)
        env, sudo_marker, systemctl_marker = self._privileged_stubs(tmp_path)

        result = _run("--repo-root", str(fake_root), "--python", "/bin/sh", "--env-file", str(env_file), env=env)

        assert result.returncode != 0
        assert "worktree" in result.stderr.lower()
        assert "/home/op/imoveis" in result.stderr, "the refusal must name the primary checkout"
        assert not sudo_marker.exists(), f"install escalated: {sudo_marker.read_text() if sudo_marker.exists() else ''}"
        called = systemctl_marker.read_text(encoding="utf-8") if systemctl_marker.exists() else ""
        for verb in ("enable", "restart", "daemon-reload"):
            assert verb not in called, f"install ran `systemctl {verb}` from a linked worktree"

    def test_check_reports_the_worktree_as_a_failure_too(self, tmp_path):
        """`--check` must not certify a checkout that install mode refuses."""
        fake_root = tmp_path / "imoveis-wt-demo"
        fake_root.mkdir()
        (fake_root / ".git").write_text("gitdir: /home/op/imoveis/.git/worktrees/demo\n", encoding="utf-8")
        env_file = _complete_env(tmp_path)

        result = _run("--check", "--repo-root", str(fake_root), "--python", "/bin/sh", "--env-file", str(env_file))

        assert result.returncode != 0
        assert "worktree" in result.stderr.lower()

    def test_uninstall_is_not_blocked_by_the_worktree_guard(self, tmp_path):
        """The unit lives in /etc, not the repo — a moved checkout is when you need uninstall."""
        fake_root = tmp_path / "imoveis-wt-demo"
        fake_root.mkdir()
        (fake_root / ".git").write_text("gitdir: /home/op/imoveis/.git/worktrees/demo\n", encoding="utf-8")
        env, sudo_marker, _ = self._privileged_stubs(tmp_path)

        result = _run(
            "--uninstall",
            "--repo-root",
            str(fake_root),
            "--unit-name",
            f"imoveis-test-{uuid.uuid4().hex}",
            env=env,
        )

        assert "worktree" not in result.stderr.lower()
        # It got as far as the privileged step (where the stub refuses) instead of the guard.
        assert sudo_marker.exists(), "uninstall stopped before its privileged step"
        assert "systemctl" in sudo_marker.read_text(encoding="utf-8")

    def test_unknown_argument_is_refused(self):
        result = _run("--nope")
        assert result.returncode != 0
        assert "Unknown argument" in result.stderr


@pytest.mark.unit
class TestCliSurface:
    def test_help_prints_the_header_not_the_source(self):
        """A hardcoded line range drifts: --help used to emit shell source."""
        result = _run("--help")

        assert result.returncode == 0, result.stderr
        assert "--uninstall" in result.stdout
        assert "--force" in result.stdout
        for leaked in ("set -euo pipefail", "_c()", "log()"):
            assert leaked not in result.stdout, f"--help leaked source: {leaked}"

    @pytest.mark.parametrize("bad", ["../../tmp/evil", "unit name", "a/b"])
    def test_invalid_unit_name_is_refused(self, bad):
        """The unit name becomes a root-written path under /etc/systemd/system."""
        result = _run("--status", "--unit-name", bad)

        assert result.returncode != 0
        assert "--unit-name" in result.stderr

    def test_option_without_a_value_explains_itself(self):
        """`set -e` on an empty shift used to exit 1 with no message at all."""
        trailing = _run("--check", "--user")
        assert trailing.returncode != 0
        assert "--user requires a value" in trailing.stderr

        swallowed = _run("--user", "--check")
        assert swallowed.returncode != 0
        assert "--user requires a value" in swallowed.stderr

    def test_status_of_an_uninstalled_unit_is_not_success(self):
        """Never-installed IS the DW-27 failure — it must not read as benign."""
        result = _run("--status", "--unit-name", f"imoveis-test-absent-{uuid.uuid4().hex}")

        assert result.returncode != 0
        assert "install" in result.stderr.lower()
