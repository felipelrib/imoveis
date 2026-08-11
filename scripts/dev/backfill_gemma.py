#!/usr/bin/env python
"""Resumable Gemma (free-tier) enrichment backfill runner (BIN-248).

Enriches un-enriched properties with Gemma 4 31B (free tier) + 768px image
downscaling — the best-quality option from the BIN-242 A/B — spread across days
under the free-tier RPD/TPM budget. It calls the shared ``run_enrichment``
orchestration directly (no GPU semaphore, no Celery ``ai`` queue), so it never
contends with the local, GPU-bound live workers, and paces on a Redis-backed
daily request budget that survives stop/restart.

Usage
-----
Like every dev script it talks to the DB via ``SessionLocal``, so point it at the
running stack with ``DATABASE_URL`` (the primary Compose Postgres publishes on the
host port from ``.env.local``, e.g. 5433). ``--dry-run`` / ``--status`` need only
the DB; a real run also needs ``GEMINI_API_KEY``.

    export DATABASE_URL="postgresql://<user>:<pass>@localhost:<port>/realestate"

    # Small trial run (writes real Gemma scores for 2 oldest un-enriched props):
    GEMINI_API_KEY=... PYTHONPATH=src python scripts/dev/backfill_gemma.py --limit 2

    # Full daily slice (stops at the daily budget, resume tomorrow):
    GEMINI_API_KEY=... PYTHONPATH=src python scripts/dev/backfill_gemma.py

    # Unattended: run to completion, auto-waiting across daily-budget resets
    # (best under tmux/nohup/systemd so it survives a closed terminal):
    GEMINI_API_KEY=... PYTHONPATH=src python scripts/dev/backfill_gemma.py --continuous

    # Faster: enrich several properties in parallel (each is ~3 sequential Gemma
    # calls, so latency — not quota — is the limit). Start conservative; the
    # client auto-backs-off if the 16K TPM ceiling throttles:
    GEMINI_API_KEY=... PYTHONPATH=src python scripts/dev/backfill_gemma.py --continuous --concurrency 4

    # Plan only — how many would run today, no API calls / no writes (no key needed):
    PYTHONPATH=src python scripts/dev/backfill_gemma.py --dry-run

    # Status: enriched vs *enrichable*, budget consumed today, honest ETA:
    PYTHONPATH=src python scripts/dev/backfill_gemma.py --status

    # Release rows the ledger retired, to retry them:
    PYTHONPATH=src python scripts/dev/backfill_gemma.py --reset-quarantine

    # Operator control of a run in progress (from any terminal; no lease taken):
    PYTHONPATH=src python scripts/dev/backfill_gemma.py --pause
    PYTHONPATH=src python scripts/dev/backfill_gemma.py --resume
    PYTHONPATH=src python scripts/dev/backfill_gemma.py --stop

A real run calls the live Gemma endpoint (free tier) and mutates DB scores.

Backend selection (v0.13-s1.3)
------------------------------
The runner no longer hardcodes Gemma: it asks ``ai.enrichment_routing`` for each
task class in its scope via ``resolve_enrichment_backend(..., for_backfill=True)``
— one config-owned source of truth for backend selection (FR-27 / AD-13). With
the shipped all-local default it therefore **refuses to start** until the
operator routes the scoped classes to a cloud backend and exports the key::

    ai.enrichment_routing.{visual,sentiment,deal_verdict}: gemma   # + GEMINI_API_KEY

Only one runner may work at a time: a real run takes the ``<prefix>:lease``
single-instance lease, and a second start is refused (exit 5) naming the holder.
``--status``, ``--dry-run`` and the control flags never take the lease.

Exit codes (``--continuous``)
----------------------------
An unattended run ends while nobody is watching, so the outcome is in the exit
code as well as the closing banner (v0.13-fu3):

===  ==========================================================================
0    complete — the candidate queue drained, nothing was retired
3    stalled — work remains but a full cycle made no progress; needs a look
4    complete, but N rows were quarantined unenriched (see the banner listing)
5    refused — another runner holds the lease (v0.13-s1.3)
6    stopped — an operator asked it to stop (``--stop`` / SIGINT / SIGTERM)
7    lease lost mid-run — another runner may have taken over, so this one exited
     rather than become a second writer (v0.13-s1.3)
8    blocked — ``scripts/agent/migrate-primary.sh`` holds the migration
     exclusion key, so no row was launched; with ``--continuous`` this only
     appears once the run has spent ``backfill.migration_wait_seconds`` in
     total (across every blocked cycle) waiting for it to clear
===  ==========================================================================

Scope (``--task-classes``)
--------------------------
``visual,sentiment,deal_verdict`` (the default, full enrichment) is the only
scope this runner accepts, because ``run_enrichment`` always runs visual +
sentiment and writes a deal verdict only on the full pass. Both narrower scopes
are refused, for the same underlying reason: ``deal_verdict`` alone would spend
cloud quota on visual+sentiment, overwrite ``ai_score`` and still never write
the verdict; ``visual,sentiment`` writes ``ai_score`` with no verdict, and since
candidate selection (``mode=missing``) keys only on ``ai_score``, every row it
touched would stop being a candidate and never get a verdict from a later full
pass. Both stay part of the task-class vocabulary for stories 1.5/1.6.

Completion is measured against the **candidate queue** — active rows with no AI
score — not ``total properties - enriched``. The runner never fetches inactive
listings (494 of them on 2026-08-05), so the old total-based arithmetic could
never reach zero: the completion branch was dead and every finished run exited
through the "no progress this cycle" message instead.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import socket
import sys
import time
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

# Bootstrap sys.path so both `import adapters...` and config's `from src....`
# resolve regardless of how the script is invoked.
_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sqlalchemy  # noqa: E402

from adapters.ai.client import _gemini_client_for, resolve_enrichment_backend  # noqa: E402
from adapters.ai.image_store import ImageStore  # noqa: E402
from adapters.queue.tasks import run_enrichment  # noqa: E402
from core.backfill_runner import (  # noqa: E402
    _STATE_REFRESH_SECONDS,
    DEFAULT_BACKFILL_SCOPE,
    AttemptLedger,
    BackfillControl,
    BackfillLease,
    BackfillResult,
    BackfillState,
    Checkpoint,
    DailyBudget,
    Heartbeat,
    MigrationGate,
    QueueCensus,
    TokenBudget,
    estimate_eta_days,
    launch_interval_for_rpm,
    parse_task_classes,
    partition_candidates,
    run_backfill,
    stages_for_task_classes,
)
from core.enrichment import EnrichmentBackend, is_cloud_backend  # noqa: E402
from core.enrichment_rerun import (  # noqa: E402
    MODE_MISSING,
    STAGES_VERDICT_ONLY,
    STAGES_VISUAL_SENTIMENT,
    EnrichmentRerunParams,
    fetch_candidate_rows,
)
from core.photo_gate import effective_min_photos, photo_gate_kwargs_from_config  # noqa: E402
from infra.config import get_config  # noqa: E402
from infra.db import SessionLocal  # noqa: E402
from infra.logging import get_logger  # noqa: E402
from infra.redis_client import get_redis  # noqa: E402

logger = get_logger(__name__)

# Exit codes — a backfill that finishes overnight has to be distinguishable from
# one that gave up, without reading the scrollback (v0.13-fu3).
EXIT_COMPLETE = 0                 # candidate queue drained cleanly
EXIT_STALLED = 3                  # work remains but no progress is being made
EXIT_COMPLETE_WITH_QUARANTINE = 4 # queue drained, but rows were retired unenriched
EXIT_LEASE_HELD = 5               # another runner already holds the lease
EXIT_STOPPED = 6                  # an operator asked this run to stop
EXIT_LEASE_LOST = 7               # the lease lapsed mid-run; someone else may own it
EXIT_MIGRATION_ACTIVE = 8         # migrate-primary.sh holds the primary DB (DW-3/DW-4)

_BANNER_WIDTH = 68

# Consecutive ``--continuous`` passes that end in a provider quota refusal with
# nothing enriched before the short (per-minute-throttle) back-off is ruled out
# and the runner waits out the whole RPD window instead. Four passes is ~1h at
# the default ``quota_backoff_seconds``: long past any per-minute throttle.
_MAX_QUOTA_BACKOFF_CYCLES = 4

# The only scope ``run_enrichment`` can serve without stranding rows (see
# ``_stages_for``). Narrower scopes stay part of the task-class vocabulary for
# stories 1.5/1.6; this *runner* refuses them.
_SUPPORTED_SCOPES_HELP = "'visual,sentiment,deal_verdict' (full enrichment)"

_LEASE_LOST_TITLE = (
    "BACKFILL LEASE LOST — another runner may have taken over; "
    "exiting to avoid two writers"
)
# Banner body for the outcomes that never measured a census: a migration-blocked
# pass deliberately skips it (its SELECTs can block on the migration's ACCESS
# EXCLUSIVE lock for the whole upgrade).
_LEASE_LOST_LINES = [
    "The checkpoint is intact: whoever holds the lease continues from it.",
    "Check `--status` before starting another run.",
]
_MIGRATION_BLOCKED_LINES = [
    "No row was launched and the checkpoint is exactly where the last pass "
    "left it.",
    "Re-run the same command once migrate-primary.sh has finished.",
]


def _counts(session) -> tuple[int, int]:
    """Return ``(total_properties, enriched_properties)``."""
    total = session.execute(
        sqlalchemy.text("SELECT COUNT(*) FROM properties")
    ).scalar()
    enriched = session.execute(
        sqlalchemy.text("SELECT COUNT(*) FROM metrics_scoring WHERE ai_score > 0")
    ).scalar()
    return int(total or 0), int(enriched or 0)


# The runner's real work queue: active rows with no AI score — exactly what
# ``fetch_candidate_rows(mode=missing, active_only=True)`` returns. ``photos``
# mirrors ``core.photo_gate.count_photos`` (non-blank strings only) so the SQL
# census and the in-process partition agree on which rows are gate-blocked.
_CANDIDATES_SUBQUERY = """
    SELECT p.id AS id,
           CASE
             WHEN p.image_urls IS NULL THEN 0
             WHEN jsonb_typeof(p.image_urls::jsonb) <> 'array' THEN 0
             ELSE (
               SELECT count(*) FROM jsonb_array_elements_text(p.image_urls::jsonb) u
               WHERE btrim(u) <> ''
             )
           END AS photos
    FROM properties p
    LEFT JOIN metrics_scoring m ON m.property_id = p.id
    WHERE p.active
      AND (m.id IS NULL OR m.ai_score IS NULL OR m.ai_score = 0)
"""


def _min_photos_required(cfg) -> int:
    """Photos a row needs to be enrichable at all.

    With the gate on this is its threshold; with the gate off it is still 1 —
    ``evaluate_candidate`` rejects a gallery-less row before the gate runs,
    because the visual stage has nothing to look at.
    """
    gate = cfg.scraping.photo_gate
    if not getattr(gate, "enabled", True):
        return 1
    override = getattr(gate, "min_photos", None)
    if override is not None:
        return max(1, int(override))
    return effective_min_photos(
        floor_min=int(getattr(gate, "floor_min", 8)),
        max_images_per_property=int(cfg.ai.max_images_per_property),
        coverage_ratio=float(getattr(gate, "coverage_ratio", 1.0)),
    )


def _count_quarantined_candidates(session, ids: list[str], min_photos: int) -> int:
    """How many retired rows are still *in* the queue (so not double-counted)."""
    if not ids:
        return 0
    stmt = sqlalchemy.text(
        f"SELECT count(*) FROM ({_CANDIDATES_SUBQUERY}) q "
        "WHERE q.photos >= :min_photos AND q.id::text = ANY(:ids)"
    ).bindparams(
        sqlalchemy.bindparam("ids", value=ids, type_=sqlalchemy.ARRAY(sqlalchemy.String)),
        sqlalchemy.bindparam("min_photos", value=min_photos),
    )
    return int(session.execute(stmt).scalar() or 0)


def _census(cfg, session, ledger: AttemptLedger) -> QueueCensus:
    """Measure the queue the runner actually works, not ``total - enriched``.

    The old arithmetic counted every property, including the inactive ones the
    runner never fetches (``active_only=True``), so "remaining" could never reach
    zero and the completion branch was unreachable.
    """
    total, enriched = _counts(session)
    min_photos = _min_photos_required(cfg)
    candidates, blocked = session.execute(
        sqlalchemy.text(
            f"SELECT count(*) AS candidates, "
            f"count(*) FILTER (WHERE q.photos < :min_photos) AS blocked "
            f"FROM ({_CANDIDATES_SUBQUERY}) q"
        ).bindparams(min_photos=min_photos)
    ).one()
    quarantined = _count_quarantined_candidates(
        session, ledger.quarantined_ids(), min_photos
    )
    return QueueCensus(
        total_properties=total,
        enriched=enriched,
        candidates=int(candidates or 0),
        blocked_no_photos=int(blocked or 0),
        quarantined=quarantined,
    )


def _quarantine_report(ledger: AttemptLedger) -> dict[str, str]:
    return ledger.quarantine_report()


def _scope_from_args(args) -> frozenset:
    """Backfill scope as ``EnrichmentTaskClass`` values (story 1.1 vocabulary)."""
    raw = getattr(args, "task_classes", None)
    if not raw:
        return DEFAULT_BACKFILL_SCOPE
    try:
        return parse_task_classes(raw)
    except ValueError as exc:
        raise SystemExit(f"--task-classes: {exc}") from exc


def _stages_for(scope) -> str:
    """Legacy ``stages`` literal for ``fetch_candidate_rows`` / ``run_enrichment``.

    ``verdict_only`` is a legitimate value of that vocabulary elsewhere (the
    ``ai_enrich`` task honors it), so ``stages_for_task_classes`` keeps
    translating it. This *runner* cannot use it: ``run_enrichment`` always runs
    visual + sentiment and writes a deal verdict only when ``stages == "all"``,
    so a ``deal_verdict``-only backfill would burn cloud quota on visual +
    sentiment, overwrite ``ai_score``, and never write the verdict. The refusal
    belongs here, at the CLI, not in the core vocabulary helper.
    """
    try:
        stages = stages_for_task_classes(scope)
    except ValueError as exc:
        raise SystemExit(f"--task-classes: {exc}") from exc
    if stages == STAGES_VERDICT_ONLY:
        raise SystemExit(
            "--task-classes: a deal_verdict-only backfill is not supported. "
            "run_enrichment always runs visual+sentiment and writes the deal "
            "verdict only on the full pass, so this scope would spend cloud "
            "quota on visual+sentiment, overwrite ai_score, and still never "
            f"write a verdict.\n  Supported scopes: {_SUPPORTED_SCOPES_HELP}."
        )
    if stages == STAGES_VISUAL_SENTIMENT:
        raise SystemExit(
            "--task-classes: a visual+sentiment backfill is not supported. It "
            "writes ai_score without a deal verdict, and candidate selection "
            "(mode=missing) keys only on ai_score — so every row it touches "
            "stops being a candidate and never gets a verdict from a later "
            "full pass. Recovering costs a --force re-run of the whole "
            "visual+sentiment spend.\n"
            f"  Supported scopes: {_SUPPORTED_SCOPES_HELP}."
        )
    return stages


def _ordered(scope) -> list:
    return sorted(scope, key=lambda tc: tc.value)


def _api_key(cfg) -> str:
    """The cloud key as ``cloud_available`` reads it — stripped.

    ``resolve_enrichment_backend`` degrades cloud routing to local on a *blank*
    key (``cloud_available`` strips before testing), so a key of whitespace has
    to count as missing here too. Testing the raw value made a whitespace key
    take the "these resolve local" branch — telling the operator to set routing
    entries they had already set — and then sent the blank bearer token to the
    provider, 401-ing every row.
    """
    return (cfg.ai.gemini_api_key or "").strip()


def _resolve_backfill_backend(cfg, scope) -> str:
    """The one cloud backend that serves this scope, per ``ai.enrichment_routing``.

    AD-13: backend selection has exactly one source of truth. The runner used to
    hardcode Gemma, which was a second, unrouted decision path. It now asks the
    routing map for every scoped task class and refuses — loudly, before taking
    the lease or spending a request — when the answer is not a single cloud
    backend, because the runner has no local execution mode (AD-4: local work
    belongs on the ``ai`` queue behind the GPU semaphore).
    """
    resolved = {
        tc: resolve_enrichment_backend(tc, cfg, for_backfill=True)
        for tc in _ordered(scope)
    }
    local = [tc for tc, backend in resolved.items() if not is_cloud_backend(backend)]
    if local:
        keys = ", ".join(f"ai.enrichment_routing.{tc.value}" for tc in local)
        # ``resolve_enrichment_backend`` degrades a cloud routing entry to local
        # when no key is present, so "these resolve local" is a misdiagnosis
        # when the map is already cloud and only GEMINI_API_KEY is missing —
        # the operator would be told to set keys they have already set.
        routed_cloud = [
            tc for tc in local if is_cloud_backend(cfg.ai.enrichment_routing[tc.value])
        ]
        if len(routed_cloud) == len(local) and not _api_key(cfg):
            raise SystemExit(
                f"The backfill needs a cloud backend for every task class in "
                f"scope. {keys} are routed to cloud, but GEMINI_API_KEY is not "
                f"set, so they degrade to the local backend "
                f"('{cfg.ai.backend}').\n"
                f"  Fix: export GEMINI_API_KEY."
            )
        raise SystemExit(
            f"The backfill needs a cloud backend for every task class in scope, "
            f"but these resolve local: {keys}.\n"
            f"  Fix: set them to '{EnrichmentBackend.GEMMA.value}' (or "
            f"'{EnrichmentBackend.GEMINI.value}') in configs/app_config.yaml and "
            f"export GEMINI_API_KEY.\n"
            f"  (Narrowing --task-classes does not help: the runner supports "
            f"only {_SUPPORTED_SCOPES_HELP}, so every class in either scope must "
            f"be cloud-routed.)\n"
            f"  (Local enrichment runs through the ai queue and the GPU "
            f"semaphore, not through this runner.)"
        )
    backends = sorted({str(b) for b in resolved.values()})
    if len(backends) > 1:
        detail = ", ".join(f"{tc.value}={b}" for tc, b in resolved.items())
        raise SystemExit(
            f"The backfill scope mixes cloud backends ({detail}). One run drives "
            f"one client, so route every scoped task class to the same backend "
            f"in ai.enrichment_routing."
        )
    return backends[0]


def _build_client(cfg, scope=DEFAULT_BACKFILL_SCOPE):
    backend = _resolve_backfill_backend(cfg, scope)
    # Key is loaded from the GEMINI_API_KEY env into cfg by infra.config — the
    # single place env is read (never os.getenv here, per repo convention).
    api_key = _api_key(cfg)
    if not api_key:
        raise SystemExit(
            "GEMINI_API_KEY is not set — the cloud backfill needs a free-tier key."
        )
    model = (
        cfg.ai.gemma_model
        if backend == EnrichmentBackend.GEMMA.value
        else cfg.ai.gemini_model
    )
    logger.info("backfill_backend_resolved", backend=backend, model=model)
    return _gemini_client_for(
        model,
        api_key=api_key,
        base_url=cfg.ai.gemini_url,
        timeout=cfg.ai.timeout,
    )


def _dry_run_backend_preflight(cfg, scope) -> None:
    """Report — without failing — what a *real* run would decide for this scope.

    ``--dry-run`` is the pre-flight operators use before committing to a
    multi-day pass, so skipping backend resolution entirely (as it did) gave
    false confidence: the plan printed fine and the real run died instantly on
    an all-local routing map or a missing key. This resolves the same routing a
    real run would, prints a loud warning when it would refuse, and never
    requires ``GEMINI_API_KEY`` or aborts the plan.
    """
    try:
        backend = _resolve_backfill_backend(cfg, scope)
    except SystemExit as exc:
        print(
            f"WARNING: this scope would refuse to start a real run:\n{exc}",
            file=sys.stderr,
        )
        return
    if not _api_key(cfg):
        print(
            "WARNING: this scope would refuse to start a real run: "
            f"routing resolves to '{backend}' but GEMINI_API_KEY is not set.",
            file=sys.stderr,
        )
        return
    print(f"Dry run: a real run would drive the '{backend}' backend for this scope.")


def _launch_interval(cfg, override: float | None) -> float:
    """Seconds between property launches (``--min-interval`` overrides the default).

    Default keeps the request rate under the free-tier RPM cap regardless of
    concurrency.
    """
    if override is not None:
        return max(0.0, override)
    return launch_interval_for_rpm(
        cfg.backfill.requests_per_property, cfg.backfill.rpm_limit
    )


def _observed_rate_per_day(session) -> float | None:
    """Enrichments in the last hour × 24 — the *actual* throughput, or None if idle.

    The request-budget ETA assumes the RPD cap is the bottleneck; in practice each
    property is ~3 sequential Gemma calls, so wall-clock latency dominates. This
    reports what's really happening so the ETA is honest.
    """
    try:
        rate = session.execute(
            sqlalchemy.text(
                "SELECT count(*) FROM metrics_scoring "
                "WHERE (meta->>'enriched_at')::timestamptz > now() - interval '60 minutes'"
            )
        ).scalar()
    except Exception:  # noqa: BLE001 - status must never crash
        return None
    return float(rate) * 24.0 if rate else None


async def _enrich_one(prop, *, client, cfg, stages: str) -> None:
    """Adapter: pull image_urls/description off the row and enrich in place.

    ``run_enrichment`` stays the single write authority (AD-10) — this runner is
    a second *driver*, never a second writer.
    """
    image_urls = prop.image_urls if isinstance(getattr(prop, "image_urls", None), list) else []
    description = getattr(prop, "description", None) or ""
    image_store = ImageStore()
    await run_enrichment(
        client,
        image_store,
        str(prop.id),
        image_urls,
        description,
        stages,
        cfg,
    )


def _print_status(cfg, session, redis) -> None:
    ledger = _build_ledger(cfg, redis)
    census = _census(cfg, session, ledger)
    budget = DailyBudget(
        redis,
        prefix=cfg.backfill.redis_prefix,
        daily_limit=cfg.backfill.daily_request_budget,
    )
    consumed = budget.consumed()
    checkpoint = Checkpoint(redis, prefix=cfg.backfill.redis_prefix)
    observed = _observed_rate_per_day(session)
    if observed:
        rate_str = f"~{observed:.0f}/day (last hour ×24)"
        eta_str = f"{estimate_eta_days(census.remaining, observed):.1f} (observed)"
    else:
        # No recent activity — fall back to the request-budget ceiling.
        budget_rate = cfg.backfill.daily_request_budget / cfg.backfill.requests_per_property
        rate_str = "idle"
        eta_str = f"{estimate_eta_days(census.remaining, budget_rate):.1f} (budget ceiling; not running)"
    cp = checkpoint.load()

    print("Gemma backfill status (BIN-248)")
    # Denominator is the *enrichable* set: quoting the raw 26k total implied work
    # that will never happen (inactive rows are never fetched).
    print(f"  enriched / enrichable: {census.enriched} / {census.enrichable}"
          f" ({census.progress_pct:.1f}%)")
    print(f"  remaining            : {census.remaining}")
    print(f"  non-enrichable       : {census.non_enrichable} of {census.total_properties} total"
          f" (inactive/unfetched {census.non_enrichable - census.blocked_total},"
          f" photo-blocked {census.blocked_no_photos}, quarantined {census.quarantined})")
    print(f"  budget today         : {consumed} / {cfg.backfill.daily_request_budget} requests")
    print(f"  observed rate        : {rate_str}")
    print(f"  processed (all-time) : {checkpoint.processed_total()}")
    print(f"  last property        : {cp.get('last_property_id', '—')}")
    print(f"  last run date        : {cp.get('last_run_date', '—')}")
    print(f"  ETA (~days)          : {eta_str}")
    control = _control_for(cfg, redis)
    print(f"  control state        : {control.state().value}")
    # "Why is the runner launching nothing?" has two answers, and this was the
    # invisible one: a migration holding the key blocks every pass, and without
    # it here the operator's only way to see that was to run migrate-primary.sh.
    gate = _migration_gate_for(cfg, redis)
    holder = gate.holder_token()
    print(f"  primary migration    : {('IN PROGRESS — ' + holder) if holder else 'none'}")
    # Pending requests, not just the published state: a request the next start
    # would discard (or one a dead run never observed) was invisible here.
    pending = _pending_requests(control)
    print(f"  pending requests     : {', '.join(pending) if pending else 'none'}")
    print(f"  lease                : {_lease_summary(_lease_for(cfg, redis).holder())}")
    _print_quarantine(_quarantine_report(ledger), indent="  ")


def _control_for(cfg, redis) -> BackfillControl:
    return BackfillControl(redis, prefix=cfg.backfill.redis_prefix)


def _lease_for(cfg, redis) -> BackfillLease:
    """Lease handle for this process (token identifies *this* run)."""
    return BackfillLease(
        redis,
        prefix=cfg.backfill.redis_prefix,
        ttl_seconds=int(cfg.backfill.lease_ttl_seconds),
        owner=f"{socket.gethostname()}:{os.getpid()}",
    )


def _migration_gate_for(cfg, redis) -> MigrationGate:
    """Read-only handle on the key ``migrate-primary.sh`` holds while migrating."""
    return MigrationGate(redis, prefix=cfg.backfill.redis_prefix)


def _lease_summary(holder: dict | None) -> str:
    if not holder:
        return "free"
    age = holder.get("seconds_since_last_seen")
    seen = "last seen unknown" if age is None else f"last seen {_format_age(age)} ago"
    return f"held by {holder.get('owner', 'unknown')} (since {holder.get('acquired_at') or '—'}, {seen})"


def _format_age(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return f"{seconds:.0f}s"
    return _format_elapsed(seconds)


def _build_ledger(cfg, redis, max_attempts: int | None = None) -> AttemptLedger:
    return AttemptLedger(
        redis,
        prefix=cfg.backfill.redis_prefix,
        max_attempts=max_attempts or cfg.backfill.max_attempts,
    )


def _run(cfg, session, redis, args, *, control=None, lease=None) -> BackfillResult:
    scope = _scope_from_args(args)
    stages = _stages_for(scope)
    # Read the gate before the first DB query. ``fetch_candidate_rows`` (and the
    # census right after it) can block for the whole upgrade on the ACCESS
    # EXCLUSIVE lock an ALTER TABLE holds, so a pass that is going to be refused
    # anyway would sit inside Postgres long enough for its own lease to lapse.
    # This is a pure optimization — it can only refuse a pass early, never let
    # one through — so the *authoritative* beat-then-check stays exactly where it
    # is, in ``_go`` after ``heartbeat.beat()``: only that ordering makes the two
    # halves mutually exclusive (DW-3/DW-4).
    if not args.dry_run:
        early_gate = _migration_gate_for(cfg, redis)
        if early_gate.is_migrating():
            print(_migration_refusal(early_gate.holder_token()), file=sys.stderr)
            return BackfillResult(migration_blocked=True)
    # A dry-run makes no API calls, so it must not require a key/client — build
    # the cloud client only for a real run. It still pre-flights the routing a
    # real run would demand, as a warning rather than a refusal.
    client = None
    if args.dry_run:
        _dry_run_backend_preflight(cfg, scope)
    else:
        client = _build_client(cfg, scope)
    ledger = _build_ledger(cfg, redis, getattr(args, "max_attempts", None))
    params = EnrichmentRerunParams(
        mode=MODE_MISSING,
        stages=stages,
        active_only=True,
        limit=args.limit,
    )
    rows = fetch_candidate_rows(session, params)
    # ``fetch_candidate_rows`` applies only the SQL filters. Drop the rows this
    # pipeline can never score — no/too-few photos, and rows the ledger retired —
    # so they neither cost budget nor inflate "remaining" (v0.13-fu3).
    partition = partition_candidates(
        rows,
        gate_kwargs=photo_gate_kwargs_from_config(cfg.scraping.photo_gate, cfg.ai),
        ledger=ledger,
        stages=stages,
    )
    if partition.blocked_total:
        logger.info(
            "backfill_candidates_excluded",
            blocked_no_photos=len(partition.blocked_no_photos),
            quarantined=len(partition.quarantined),
        )
    rows = partition.workable
    # Oldest-first: enrich the properties that have been un-scored the longest.
    rows = sorted(rows, key=lambda pm: getattr(pm[0], "first_seen", None) or datetime.min)
    logger.info("backfill_candidates_loaded", count=len(rows), limit=args.limit)

    budget = DailyBudget(
        redis,
        prefix=cfg.backfill.redis_prefix,
        daily_limit=args.daily_budget or cfg.backfill.daily_request_budget,
    )
    checkpoint = Checkpoint(redis, prefix=cfg.backfill.redis_prefix)
    heartbeat = Heartbeat(redis, prefix=cfg.backfill.redis_prefix)
    # A dry run takes no lease and writes nothing, so it takes no control keys
    # either — the migration gate follows the same rule.
    migration_gate = None if args.dry_run else _migration_gate_for(cfg, redis)
    launch_interval = _launch_interval(cfg, args.min_interval)
    concurrency = args.concurrency or cfg.backfill.concurrency
    tokens_per_property = args.tokens_per_property or cfg.backfill.tokens_per_property
    tpm_limit = args.tpm_limit or cfg.backfill.tpm_limit
    token_budget = TokenBudget(
        tpm_limit=tpm_limit,
        tokens_per_property=tokens_per_property,
        safety_margin=cfg.backfill.tpm_safety_margin,
    )
    logger.info(
        "backfill_rate_limits",
        concurrency=concurrency,
        tpm_limit=tpm_limit,
        tokens_per_property=tokens_per_property,
        max_props_per_min=round(
            tpm_limit * cfg.backfill.tpm_safety_margin / max(1, tokens_per_property), 2
        ),
    )

    # Last processed-count milestone already logged. The hook now fires on error
    # and quota rows too, so ``processed % 25`` alone would re-log the same
    # count on every failing row.
    progress_logged = {"milestone": 0}

    def _on_progress(res: BackfillResult) -> None:
        # A multi-day run must not die on a transient Redis blip: this hook is
        # bookkeeping, never the run's correctness. The lease is renewed inside
        # ``run_backfill`` (which sees failing rows and pauses too), not here.
        try:
            heartbeat.beat()
            milestone = res.processed - (res.processed % 25)
            if milestone > progress_logged["milestone"]:
                progress_logged["milestone"] = milestone
                logger.info(
                    "backfill_progress",
                    processed=res.processed,
                    requests_consumed=res.requests_consumed,
                    errors=res.errors,
                    rate_limit_hits=getattr(client, "rate_limit_hits", 0),
                    retry_count=getattr(client, "retry_count", 0),
                )
        except Exception as exc:  # noqa: BLE001 - bookkeeping never aborts a run
            logger.warning("backfill_progress_tick_failed", error=str(exc))

    async def _run_backfill() -> BackfillResult:
        return await run_backfill(
            rows,
            enrich_fn=partial(_enrich_one, client=client, cfg=cfg, stages=stages),
            budget=budget,
            checkpoint=checkpoint,
            requests_per_property=cfg.backfill.requests_per_property,
            limit=args.limit,
            force=args.force,
            dry_run=args.dry_run,
            concurrency=concurrency,
            launch_interval=launch_interval,
            token_budget=None if args.dry_run else token_budget,
            ledger=None if args.dry_run else ledger,
            on_progress=_on_progress,
            control=control,
            # The lease is renewed inside run_backfill: once per launch-loop
            # iteration and once per pause poll, so neither a storm of failing
            # rows nor a long pause can let it lapse under a second runner.
            lease=lease,
            # Re-read on every launch and every pause poll: a migration can
            # start at any point in a pass that runs for hours.
            is_migrating=None if migration_gate is None else migration_gate.is_migrating,
            pause_poll_seconds=float(cfg.backfill.control_poll_seconds),
        )

    async def _go() -> BackfillResult:
        # Beat *before* reading the migrating key, never after. migrate-primary.sh
        # takes `:migrating` before it probes `:active`, so with both sides
        # set-then-check at least one of the two always sees the other and they
        # can never both proceed (DW-3). This is also the wake-up gate: every
        # --continuous pass funnels through here, including the one resuming
        # from `_sleep_for_reset`, whose `finally` cleared the heartbeat on the
        # way in — so a sleeping runner read as idle to the guard and came back
        # writing mid-migration (DW-4).
        heartbeat.beat()
        try:
            if migration_gate is not None and migration_gate.is_migrating():
                print(_migration_refusal(migration_gate.holder_token()), file=sys.stderr)
                return BackfillResult(migration_blocked=True)
            if args.dry_run:  # no client / no HTTP session needed
                return await _run_backfill()
            async with client.session_context():
                return await _run_backfill()
        finally:
            heartbeat.clear()

    return asyncio.run(_go())


def _format_elapsed(seconds: float) -> str:
    total = int(max(0.0, seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _print_quarantine(report: dict[str, str], *, indent: str = "  ") -> None:
    """List retired rows so they are reported, never silently dropped."""
    if not report:
        return
    print(f"{indent}quarantined rows ({len(report)}) — excluded from the queue:")
    for pid, reason in list(report.items())[:20]:
        print(f"{indent}  {pid}  {reason}")
    if len(report) > 20:
        print(f"{indent}  … and {len(report) - 20} more (see backfill:gemma:attempts)")


def _print_banner(title: str, lines: list[str]) -> None:
    """Loud terminal summary — a run that ends overnight must be obvious."""
    rule = "═" * _BANNER_WIDTH
    print(f"\n{rule}")
    print(f"  {title}")
    for line in lines:
        print(f"  {line}")
    print(f"{rule}\n")


def _terminal_summary(census: QueueCensus, *, cycle: int, elapsed: float,
                      processed: int, errors: int) -> list[str]:
    return [
        f"enriched {census.enriched:,} / enrichable {census.enrichable:,}"
        f" ({census.progress_pct:.1f}%)",
        f"remaining {census.remaining:,} · non-enrichable {census.non_enrichable:,}"
        f" of {census.total_properties:,} total",
        f"  (inactive/unfetched {census.non_enrichable - census.blocked_total:,}"
        f" · photo-blocked {census.blocked_no_photos:,}"
        f" · quarantined {census.quarantined:,})",
        f"cycles {cycle} · elapsed {_format_elapsed(elapsed)}"
        f" · enriched this run {processed:,} · errors {errors:,}",
    ]


def _finish(census: QueueCensus, report: dict[str, str], *, cycle: int, elapsed: float,
            processed: int, errors: int) -> int:
    """Print the terminal banner and return the exit code for this outcome."""
    summary = _terminal_summary(
        census, cycle=cycle, elapsed=elapsed, processed=processed, errors=errors
    )
    if census.is_complete:
        retired = census.quarantined or len(report)
        title = "BACKFILL COMPLETE" + (f" (with {retired} quarantined)" if retired else "")
        code = EXIT_COMPLETE_WITH_QUARANTINE if retired else EXIT_COMPLETE
    else:
        title = "BACKFILL STALLED — work remains but the last cycle made no progress"
        code = EXIT_STALLED
    _print_banner(title, summary)
    _print_quarantine(report)
    logger.info(
        "backfill_terminal",
        outcome="complete" if census.is_complete else "stalled",
        exit_code=code,
        cycles=cycle,
        elapsed_seconds=round(elapsed),
        **census.to_dict(),
    )
    return code


def _sleep_for_reset(wait: float, *, cfg, control=None, lease=None) -> None:
    """Sleep out a budget window in small, interruptible steps.

    Three cadences, deliberately different:

    * **step** = ``control_poll_seconds`` — how quickly a stop (``--stop``, or
      SIGINT/SIGTERM, whose handler only *requests* a stop) is noticed. Sleeping
      in ``lease_ttl/3`` chunks meant up to 300s of an unresponsive Ctrl-C:
      PEP 475 makes ``time.sleep`` resume the remaining interval after the
      handler returns instead of raising.
    * **lease renew** every ``lease_ttl/3`` — a single ``time.sleep(~24h)``
      would outlive the lease and let a second runner start mid-sleep.
    * **state re-publish** every ``_STATE_REFRESH_SECONDS`` — strictly below the
      120s state-key TTL, so ``backing-off`` never decays to ``idle`` while the
      runner is in fact alive and waiting.
    """
    step = max(0.05, float(cfg.backfill.control_poll_seconds))
    renew_every = max(1.0, float(cfg.backfill.lease_ttl_seconds) / 3.0)
    state_every = float(_STATE_REFRESH_SECONDS)
    wait = max(0.0, float(wait))
    # Elapsed time is the *later* of the requested chunks and the wall clock.
    # ``time.sleep`` only guarantees a lower bound, so on a host that suspends
    # (or is heavily descheduled) an accumulator of requested chunks under-counts
    # real elapsed time and the renew cadence silently drifts past the lease TTL
    # — the lease lapses mid-wait and a second runner can start.
    started = time.monotonic()
    slept = 0.0
    next_renew = 0.0
    next_state = 0.0
    while True:
        elapsed = max(slept, time.monotonic() - started)
        if elapsed >= wait:
            return
        if control is not None and control.should_stop():
            return
        if lease is not None and elapsed >= next_renew:
            # Losing the lease mid-wait used to go unnoticed for the rest of the
            # window — potentially hours asleep on a lease someone else now
            # owns. Return so the next pass sees it and exits EXIT_LEASE_LOST.
            # Checked *before* publishing: a lapsed lease means the state key
            # already describes the successor, and stamping ``backing-off`` over
            # their ``running`` is exactly the lie the exit path guards against.
            if not lease.renew():
                return
            # Fixed cadence (``+=``), not ``elapsed + every``: the latter folds
            # each check's own offset into the next deadline and drifts.
            next_renew += renew_every
            if next_renew <= elapsed:  # a long stall skipped whole periods
                next_renew = elapsed + renew_every
        if control is not None and elapsed >= next_state:
            # A pause issued during the wait was invisible: the key kept
            # reading ``backing-off`` for the whole window, so the operator
            # (and story 1.5's API) got no acknowledgement the request had
            # been seen. The wait itself is unchanged — the launch loop is
            # what actually holds on a pause.
            control.publish_state(
                BackfillState.PAUSED
                if control.is_paused()
                else BackfillState.BACKING_OFF
            )
            next_state += state_every
            if next_state <= elapsed:
                next_state = elapsed + state_every
        chunk = min(step, wait - elapsed)
        time.sleep(chunk)
        slept += chunk


def _wait_out_migration(
    cfg, redis, *, control=None, lease=None, budget_seconds=None
) -> str:
    """Poll until ``migrate-primary.sh`` releases the key.

    A migration is minutes and a blocked pass launched nothing, so an unattended
    run waits it out and resumes rather than dying and needing an operator to
    restart it. The wait renews the lease on ``_sleep_for_reset``'s
    ``lease_ttl/3`` cadence — parking here for half an hour on an unrenewed
    lease is exactly how a second runner starts — and re-publishes the control
    state on its ``_STATE_REFRESH_SECONDS`` cadence, because the state key's TTL
    is 120s and a wait of up to ``migration_wait_seconds`` would otherwise make
    ``--status`` report a live, lease-holding runner as ``idle``.

    Returns the outcome, which the caller maps to an exit code:
    ``"cleared"`` (resume), ``"stopped"``, ``"lease_lost"``, ``"timeout"``.
    A boolean cannot express those: a lost lease reported as "resume" sends the
    next pass straight back into the gate — ``_go`` short-circuits before
    ``run_backfill`` ever renews — so the run loops on ``migration_blocked``
    forever, re-beating ``:active`` each cycle and blocking the *next* legitimate
    ``migrate-primary.sh`` along the way.

    ``budget_seconds`` is the wait left in this run's *cumulative* budget, so
    repeated blocked cycles cannot add up to an unbounded wait.

    The key is only ever read: it belongs to the migration and self-clears on
    its own TTL, so clearing it here would green-light writes mid-upgrade.
    """
    gate = _migration_gate_for(cfg, redis)
    limit = float(cfg.backfill.migration_wait_seconds)
    if budget_seconds is not None:
        limit = min(limit, float(budget_seconds))
    limit = max(0.0, limit)
    step = max(0.05, float(cfg.backfill.control_poll_seconds))
    renew_every = max(1.0, float(cfg.backfill.lease_ttl_seconds) / 3.0)
    state_every = float(_STATE_REFRESH_SECONDS)
    started = time.monotonic()
    next_renew = renew_every
    # 0.0, like ``_sleep_for_reset``: the pass that got here published ``idle``
    # (``run_backfill``'s exit) or nothing at all (the short-circuit in ``_go``),
    # so waiting a full refresh interval before the first publish is exactly the
    # "live, lease-holding runner reads back as idle" window this loop exists to
    # close — just 30s of it.
    next_state = 0.0
    announced = False
    while True:
        if not gate.is_migrating():
            return "cleared"
        elapsed = time.monotonic() - started
        # Before the timeout: a stop that arrives on the timing-out iteration
        # (or any stop at all when the budget is already spent, where the
        # timeout returns on the first pass through this loop) would otherwise
        # never be observed here — and never be cleared, leaving a pending
        # request behind for its whole TTL.
        if control is not None and control.should_stop():
            return "stopped"
        if elapsed >= limit:
            return "timeout"
        if lease is not None and elapsed >= next_renew:
            if not lease.renew():
                return "lease_lost"
            next_renew = max(next_renew + renew_every, elapsed + renew_every)
        if control is not None and elapsed >= next_state:
            # Same fix as ``_sleep_for_reset``: publish what is actually true —
            # a pause issued during the wait must still read back as ``paused``.
            # ``BLOCKED``, never ``BACKING_OFF``: no provider refused anything
            # here, and "backing-off" points the operator at the wrong system.
            control.publish_state(
                BackfillState.PAUSED
                if control.is_paused()
                else BackfillState.BLOCKED
            )
            next_state = max(next_state + state_every, elapsed + state_every)
        if not announced:
            announced = True
            logger.info("backfill_waiting_for_migration", limit_seconds=round(limit))
            print(
                f"A primary database migration holds {gate.key}; waiting up to "
                f"{limit / 60:.0f}min for it to finish, then resuming. "
                f"Ctrl-C to stop; safe to resume."
            )
        time.sleep(min(step, limit - elapsed))


def _run_continuous(cfg, redis, args, *, control=None, lease=None) -> int:
    """Run passes until the backfill completes, sleeping across RPD-window resets.

    Each pass enriches until the daily budget is exhausted (or candidates run
    out), then — if work remains — sleeps until the rolling 24h budget window
    resets and resumes. Checkpointed, so a killed process resumes.

    Completion is measured against the **candidate queue** (:func:`_census`), not
    ``total - enriched``: inactive rows are never fetched, so the old arithmetic
    never reached zero. The queue is re-censused before any sleep, so a pass that
    exhausts the budget *and* finishes the queue exits now instead of sleeping
    ~24h to discover there is nothing left (v0.13-fu3).
    """
    daily_limit = args.daily_budget or cfg.backfill.daily_request_budget
    # A cap smaller than one property's request cost can never reserve anything,
    # so every pass ends budget_exhausted with nothing processed and the loop
    # sleeps out a full 24h window — forever, without ever tripping the stall
    # detector (which only fires when the budget is *not* exhausted).
    if daily_limit < cfg.backfill.requests_per_property:
        raise SystemExit(
            f"Daily budget {daily_limit} is below backfill.requests_per_property "
            f"({cfg.backfill.requests_per_property}): no property could ever be "
            f"reserved and --continuous would sleep out a 24h window forever. "
            f"Raise --daily-budget / backfill.daily_request_budget."
        )
    budget = DailyBudget(
        redis,
        prefix=cfg.backfill.redis_prefix,
        daily_limit=daily_limit,
    )
    ledger = _build_ledger(cfg, redis, getattr(args, "max_attempts", None))
    started = time.monotonic()
    cycle = 0
    enriched_this_run = 0
    errors_this_run = 0
    quota_zero_cycles = 0
    # Cumulative across *consecutive blocked* cycles, not per call: a migration
    # that keeps the key (or a runner that keeps being blocked at pass entry)
    # must not be able to stretch ``migration_wait_seconds`` into an unbounded
    # wait one cycle at a time. It resets on any cycle that actually ran, or a
    # multi-day ``--continuous`` run would spend the whole budget on its first
    # migration and then refuse to wait a single second for the next one —
    # exiting 8 on a key that was about to clear.
    migration_waited = 0.0
    while True:
        cycle += 1
        with SessionLocal() as session:
            result = _run(cfg, session, redis, args, control=control, lease=lease)
            # A blocked pass launched nothing, so there is nothing to measure —
            # and the census SELECTs run on the same session, where an ALTER
            # TABLE's ACCESS EXCLUSIVE lock can hold them for the whole upgrade.
            # Waiting there instead of in ``_wait_out_migration`` costs this
            # runner its lease.
            census = None if result.migration_blocked else _census(cfg, session, ledger)
        enriched_this_run += result.processed
        errors_this_run += result.errors
        remaining = "unmeasured" if census is None else census.remaining
        logger.info(
            "backfill_cycle_done",
            cycle=cycle,
            processed=result.processed,
            errors=result.errors,
            skipped_quarantined=result.skipped_quarantined,
            # ``None``, not the human string: this field is an int everywhere
            # else, and a log consumer parsing it should not have to special-case
            # a word. The console line below still says "unmeasured".
            remaining=None if census is None else census.remaining,
            budget_exhausted=result.budget_exhausted,
            # Without this a blocked pass reads exactly like an ordinary empty
            # one in the logs.
            migration_blocked=result.migration_blocked,
        )
        print(
            f"[cycle {cycle}] enriched {result.processed}, errors {result.errors}, "
            f"quarantined-skips {result.skipped_quarantined}, "
            f"migration-blocked {result.migration_blocked}, remaining {remaining}"
        )

        # First, because it is the only branch that runs without a census — and
        # because the wait renews the lease and honors a stop, so a lost lease or
        # an operator stop during a blocked pass still surfaces as itself.
        if result.migration_blocked:
            if result.lease_lost:
                # Both flags set (a worker's renew failed while the pass was
                # breaking on the gate): there is nothing to wait for, a
                # successor owns the run.
                _print_banner(_LEASE_LOST_TITLE, _LEASE_LOST_LINES)
                return EXIT_LEASE_LOST
            waited_from = time.monotonic()
            outcome = _wait_out_migration(
                cfg,
                redis,
                control=control,
                lease=lease,
                budget_seconds=max(
                    0.0, float(cfg.backfill.migration_wait_seconds) - migration_waited
                ),
            )
            migration_waited += time.monotonic() - waited_from
            if outcome == "cleared":
                continue  # the migration released the key → fresh pass now
            if outcome == "lease_lost":
                _print_banner(_LEASE_LOST_TITLE, _LEASE_LOST_LINES)
                return EXIT_LEASE_LOST
            if outcome == "stopped":
                _print_banner(
                    "BACKFILL STOPPED — operator requested; resume with the "
                    "same command",
                    _MIGRATION_BLOCKED_LINES,
                )
                if control is not None:
                    # Served — see the matching note in ``main``.
                    control.clear_stop()
                return EXIT_STOPPED
            _print_banner(
                "BACKFILL BLOCKED BY A PRIMARY MIGRATION — "
                "restart once migrate-primary.sh has finished",
                _MIGRATION_BLOCKED_LINES,
            )
            return EXIT_MIGRATION_ACTIVE

        # This cycle ran, so the next migration gets the full budget again: the
        # bound is on one uninterrupted stretch of blocked cycles, not on the
        # lifetime of a runner that may stay up for days.
        migration_waited = 0.0

        def _end() -> int:
            return _finish(
                census,
                _quarantine_report(ledger),
                cycle=cycle,
                elapsed=time.monotonic() - started,
                processed=enriched_this_run,
                errors=errors_this_run,
            )

        # Losing the lease is terminal and takes precedence over everything else
        # — including a queue that now reads complete. Another runner may hold
        # the lease and have drained it; reporting *this* process as the one
        # that completed the backfill (exit 0) would hide the displacement the
        # exit code exists to surface, and let ``main`` stamp its final state
        # over the successor's.
        if result.lease_lost:
            _print_banner(
                _LEASE_LOST_TITLE,
                _terminal_summary(
                    census,
                    cycle=cycle,
                    elapsed=time.monotonic() - started,
                    processed=enriched_this_run,
                    errors=errors_this_run,
                ),
            )
            return EXIT_LEASE_LOST
        # Completion is checked *before* the budget branch: a pass that spends the
        # last of its budget on the last of the queue must exit now, not sleep out
        # the remaining ~24h only to find an empty queue.
        if census.is_complete:
            if control is not None:
                # A pause/stop aimed at this run is moot now that the queue is
                # drained, and leaving it set makes ``--status`` report a
                # pending request with no runner alive for the 7-day request
                # TTL. We still hold the lease, so these are unambiguously ours.
                control.clear_requests()
            return _end()
        # An operator stop is terminal and is *not* a stall: the checkpoint is
        # intact and the next start resumes exactly here.
        if result.stopped or (control is not None and control.should_stop()):
            _print_banner(
                "BACKFILL STOPPED — operator requested; resume with the same command",
                _terminal_summary(
                    census,
                    cycle=cycle,
                    elapsed=time.monotonic() - started,
                    processed=enriched_this_run,
                    errors=errors_this_run,
                ),
            )
            if control is not None:
                # Served — see the matching note in ``main``.
                control.clear_stop()
            return EXIT_STOPPED
        if not result.budget_exhausted:
            # Budget left, work left, yet nothing moved → a real stall (every
            # remaining row is failing). Exiting non-zero makes that visible.
            if result.processed == 0:
                return _end()
            continue  # made progress, more may be fetchable → next pass now
        # Budget spent with work remaining — including a pass that processed
        # nothing because the window was already exhausted on entry. Sleep.

        wait = budget.seconds_until_reset() + args.reset_margin
        # A provider 429 that survived the client's retries is *not* proof the
        # daily (RPD) allowance is gone — free tiers throttle per minute too.
        # When the local budget still has room for another property, cap the
        # wait at quota_backoff_seconds instead of parking for the whole rolling
        # window; only a genuinely spent local budget sleeps to the reset.
        headroom = budget.remaining()
        rpd_spent = headroom < cfg.backfill.requests_per_property
        # A quota refusal sets ``budget_exhausted`` too, which puts the pass out
        # of reach of the stall detector above. So a provider that refuses every
        # request — a spent RPD, a revoked key — produced a pass that enriched
        # nothing, slept the short back-off, and repeated: ~96 identical passes a
        # day, each re-spending the client's retry budget against an account that
        # is already refusing, with no exit and no escalation. The short back-off
        # is right for a *per-minute* throttle, which clears in minutes; after
        # this many consecutive zero-progress refusals it plainly is not one, so
        # fall back to the RPD-window wait (never shorter than the back-off).
        if result.quota_exhausted and result.processed == 0:
            quota_zero_cycles += 1
        else:
            quota_zero_cycles = 0
        throttle_ruled_out = quota_zero_cycles >= _MAX_QUOTA_BACKOFF_CYCLES
        if result.quota_exhausted and not rpd_spent and not throttle_ruled_out:
            wait = min(wait, float(cfg.backfill.quota_backoff_seconds))
            reason = (
                f"Provider refused on quota, but the local daily budget still "
                f"has {headroom} requests — treating it as a per-minute "
                f"throttle and backing off {wait / 60:.0f}min "
                f"(backfill.quota_backoff_seconds)"
            )
        elif result.quota_exhausted and not rpd_spent:
            wait = max(wait, float(cfg.backfill.quota_backoff_seconds))
            reason = (
                f"Provider has refused on quota for {quota_zero_cycles} "
                f"consecutive passes without enriching anything — this is not a "
                f"per-minute throttle. Waiting out the RPD window instead of "
                f"re-spending retries against a refusing account"
            )
        elif result.quota_exhausted:
            reason = "Provider quota exhausted and the local daily budget is spent"
        else:
            reason = "Daily budget spent"
        resume_at = datetime.now().astimezone() + timedelta(seconds=wait)
        logger.info(
            "backfill_waiting_for_reset",
            seconds=round(wait),
            resume_at=str(resume_at),
            quota_exhausted=result.quota_exhausted,
            budget_remaining=headroom,
        )
        print(
            f"{reason}; sleeping {wait / 3600:.1f}h "
            f"(resuming ~{resume_at:%Y-%m-%d %H:%M %Z}). "
            f"Ctrl-C to stop; safe to resume."
        )
        _sleep_for_reset(wait, cfg=cfg, control=control, lease=lease)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resumable Gemma enrichment backfill (BIN-248)")
    parser.add_argument("--limit", type=int, default=None, help="cap candidates this run")
    parser.add_argument("--dry-run", action="store_true", help="plan only; no API calls / writes")
    parser.add_argument("--force", action="store_true", help="re-enrich already-scored rows")
    parser.add_argument(
        "--daily-budget", type=int, default=None, help="override daily request budget"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="properties to enrich in parallel (default: config; 1 = sequential)",
    )
    parser.add_argument(
        "--tokens-per-property",
        type=int,
        default=None,
        help="estimated tokens per property for TPM pacing (default: config, 7000)",
    )
    parser.add_argument(
        "--tpm-limit",
        type=int,
        default=None,
        help="tokens-per-minute ceiling to stay under (default: config, 16000)",
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=None,
        help="min seconds between property launches (default: RPM-safe from config)",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="run until the whole backfill is done, waiting across daily-budget resets",
    )
    parser.add_argument(
        "--reset-margin",
        type=float,
        default=120.0,
        help="extra seconds to wait past the budget-window reset (default: 120)",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="attempts before a row is quarantined and excluded (default: config, 3)",
    )
    parser.add_argument(
        "--reset-quarantine",
        action="store_true",
        help="clear the attempt ledger (retries every quarantined row) and exit",
    )
    parser.add_argument(
        "--task-classes",
        default=None,
        help=(
            "backfill scope; only 'visual,sentiment,deal_verdict' (the default "
            "— full enrichment) is supported. Narrower scopes are refused: "
            "run_enrichment always runs visual+sentiment and writes a deal "
            "verdict only on the full pass, so they strand rows"
        ),
    )
    parser.add_argument(
        "--pause", action="store_true", help="ask the running backfill to pause, then exit"
    )
    parser.add_argument(
        "--resume", action="store_true", help="release a pause request, then exit"
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="ask the running backfill to stop after in-flight rows drain, then exit",
    )
    parser.add_argument("--status", action="store_true", help="print status and exit")
    args = parser.parse_args(argv)

    # Each of these takes over the whole invocation and returns; combining them
    # silently ran the first and dropped the rest, so `--stop --status` reported
    # nothing and `--reset-quarantine --pause` never paused anything.
    exclusive = [
        flag
        for flag in ("reset_quarantine", "pause", "resume", "stop", "status")
        if getattr(args, flag)
    ]
    if len(exclusive) > 1:
        names = ", ".join(f"--{flag.replace('_', '-')}" for flag in exclusive)
        parser.error(f"pick exactly one of {names} — they cannot be combined")
    if args.reset_margin < 0:
        # A negative margin can drive the post-budget wait to zero, and a
        # zero-length sleep turns --continuous into a tight loop of passes that
        # can reserve nothing.
        parser.error("--reset-margin cannot be negative")

    cfg = get_config()
    redis = get_redis()
    control = _control_for(cfg, redis)

    if args.reset_quarantine:
        # The ledger is shared state a live run consults on every row. Clearing
        # it under an active runner releases the rows that runner quarantined,
        # which it then re-fetches and re-attempts — spending cloud quota on
        # properties already proven unenrichable. Mutual exclusion has to cover
        # the one command that rewrites the same Redis state, not just the run.
        #
        # It *takes* the lease rather than reading the holder: a read is
        # check-then-act, and a run starting in the gap between the read and
        # ``reset_all()`` gets its ledger wiped underneath it anyway.
        guard = _lease_for(cfg, redis)
        if not guard.acquire():
            print(
                "Refusing to reset the attempt ledger: a backfill run holds the "
                f"lease.\n  {_lease_summary(guard.holder())}\n"
                "  Ask it to finish with --stop first, then retry.",
                file=sys.stderr,
            )
            return EXIT_LEASE_HELD
        try:
            ledger = _build_ledger(cfg, redis, args.max_attempts)
            released = ledger.quarantined_count()
            ledger.reset_all()
        finally:
            guard.release()
        print(f"Attempt ledger cleared — {released} quarantined properties released.")
        return 0

    # Control commands and read-only modes never take the lease — they must work
    # *while* a run holds it, which is the entire point of them.
    if args.pause or args.resume or args.stop:
        return _apply_control_command(control, args)

    if args.status:
        with SessionLocal() as session:
            _print_status(cfg, session, redis)
        return 0

    if args.continuous and args.dry_run:
        parser.error("--continuous cannot be combined with --dry-run")

    # Validate the scope and the routing it implies *before* taking the lease —
    # which is what `_resolve_backfill_backend` already claimed to do. Resolving
    # it inside `_run` meant a misconfigured start acquired the lease and ran
    # `clear_requests()`, silently discarding an operator's pending pause/stop,
    # only to die on the routing refusal a moment later.
    _stages_for(_scope_from_args(args))
    if not args.dry_run:
        _resolve_backfill_backend(cfg, _scope_from_args(args))

    # Refuse a single pass up front: a migration holds the primary DB, so this
    # run would launch nothing anyway, and refusing here means it never takes
    # the lease nor clears an operator's pending pause/stop. ``--continuous``
    # deliberately falls through — it takes the lease and waits the migration
    # out (see ``_wait_out_migration``) instead of dying unattended.
    if not args.dry_run and not args.continuous:
        gate = _migration_gate_for(cfg, redis)
        if gate.is_migrating():
            print(_migration_refusal(gate.holder_token()), file=sys.stderr)
            return EXIT_MIGRATION_ACTIVE

    lease = None
    if not args.dry_run:
        lease = _lease_for(cfg, redis)
        if not lease.acquire():
            print(_lease_refusal(lease.holder()), file=sys.stderr)
            return EXIT_LEASE_HELD

    # Everything from here on is inside the try: anything that raises after the
    # lease was taken must still hand it back, or the next run is refused for
    # the whole 900s TTL.
    quota_backoff = False
    lease_lost = False
    stopped = False
    try:
        if lease is not None:
            # A fresh run must not inherit a pause/stop left over from the last
            # one — but silently dropping an operator's request is its own bug,
            # so say exactly what is being discarded.
            _report_discarded_requests(control)
            control.clear_requests()
            _install_stop_signals(control)

        if args.continuous:
            # --continuous processes to completion; a per-run --limit would loop.
            args.limit = None
            rc = _run_continuous(
                cfg, redis, args, control=None if args.dry_run else control, lease=lease
            )
            # run_backfill publishes BACKING_OFF when the provider refused; the
            # finally below must not erase it.
            # A finished backfill is not backing off, whatever the last pass
            # published on its way to draining the queue — publishing
            # ``backing-off`` for a completed run misreports it to --status and
            # story 1.5's API for the whole state TTL.
            quota_backoff = (
                control.state() is BackfillState.BACKING_OFF
                and rc
                not in (
                    EXIT_COMPLETE,
                    EXIT_COMPLETE_WITH_QUARANTINE,
                    # A run that ends blocked by a migration never hit a quota
                    # ceiling; stamping ``backing-off`` on the way out reports a
                    # provider refusal that did not happen for the state TTL.
                    EXIT_MIGRATION_ACTIVE,
                )
            )
            lease_lost = rc == EXIT_LEASE_LOST
            return rc

        with SessionLocal() as session:
            result = _run(
                cfg,
                session,
                redis,
                args,
                control=None if args.dry_run else control,
                lease=lease,
            )
        quota_backoff = result.quota_exhausted
        lease_lost = result.lease_lost
        # Read the stop request while the lease is still held. Reading it after
        # the release (as this did) means a runner that started in between owns
        # these keys, so an operator's stop aimed at *that* live run was
        # reported as served by this one — and then cleared, so it never stopped.
        stopped = result.stopped or (not args.dry_run and control.should_stop())
    finally:
        if lease is not None:
            # Everything that touches the control keys happens *before* the
            # release. Releasing first opens a window in which a newly started
            # runner takes the freed lease and publishes ``running``, only for
            # this exiting process to stamp ``idle`` over it. A run that *lost*
            # its lease touches nothing at all — the keys already describe
            # whoever took it over.
            if not lease_lost:
                if stopped:
                    # The request has been served. Leaving it set made
                    # ``--status`` report a pending stop for the next 7 days and
                    # made the following start announce it as an operator
                    # request being discarded — when it had been honored.
                    control.clear_stop()
                try:
                    # A deliberate ``backing-off`` is what tells the operator
                    # (and story 1.5's API) the provider refused; overwriting it
                    # with ``idle`` on the way out hid exactly that. It decays to
                    # idle via the TTL. A failure here must not cost the release:
                    # an unreleased lease locks the next run out for the full TTL.
                    control.publish_state(
                        BackfillState.BACKING_OFF
                        if quota_backoff
                        else BackfillState.IDLE
                    )
                except Exception as exc:  # noqa: BLE001 - never skip the release
                    logger.warning("backfill_final_state_publish_failed", error=str(exc))
            lease.release()

    logger.info("backfill_done", **result.to_dict())
    if result.migration_blocked:
        # "enriched 0" is the same sentence an ordinary empty pass prints, so a
        # blocked run looked like a run with nothing left to do.
        print(
            "Backfill pass blocked by a primary database migration: no property "
            "was launched, nothing was enriched, and the checkpoint is intact. "
            "Re-run once migrate-primary.sh has finished."
        )
    else:
        verb = "would enrich" if args.dry_run else "enriched"
        n = result.would_process if args.dry_run else result.processed
        # "pass done", not "complete" — a single pass says nothing about the
        # queue. Only --continuous prints the terminal BACKFILL COMPLETE banner.
        print(
            f"Backfill pass done: {verb} {n} properties "
            f"(skipped {result.skipped_already_enriched}, "
            f"quarantined {result.skipped_quarantined}, errors {result.errors}, "
            f"budget_exhausted={result.budget_exhausted})"
        )
    if result.lease_lost:
        _print_banner(_LEASE_LOST_TITLE, _LEASE_LOST_LINES)
        return EXIT_LEASE_LOST
    # A migration took the primary DB between the startup check and pass entry:
    # nothing was launched and the checkpoint is intact, so the exit code — not
    # a silent "enriched 0" — is what tells the operator to re-run afterwards.
    if result.migration_blocked:
        return EXIT_MIGRATION_ACTIVE
    # ``stopped`` was resolved (and the served request retired) inside the try /
    # finally above, while this process still held the lease.
    return EXIT_STOPPED if stopped else 0


def _pending_requests(control: BackfillControl) -> list[str]:
    """Outstanding operator requests, as human-readable words."""
    pending = []
    if control.is_paused():
        pending.append("pause")
    if control.should_stop():
        pending.append("stop")
    return pending


def _report_discarded_requests(control: BackfillControl) -> None:
    """Announce the pause/stop requests this start-up is about to drop.

    Clearing them silently meant an operator who asked for a pause (or a stop)
    seconds before the run started saw it vanish with no trace anywhere.
    """
    pending = _pending_requests(control)
    if not pending:
        return
    for request in pending:
        print(
            f"Discarding a pending {request} request from a previous run — "
            f"re-issue it with --{request} if you still want it."
        )


def _apply_control_command(control: BackfillControl, args) -> int:
    """Handle ``--pause`` / ``--resume`` / ``--stop`` without taking the lease."""
    if sum(bool(x) for x in (args.pause, args.resume, args.stop)) > 1:
        print("Pick one of --pause / --resume / --stop.", file=sys.stderr)
        return 2
    if args.pause:
        control.request_pause()
        print("Pause requested — the running backfill will hold after the current rows.")
    elif args.resume:
        # Clearing only the pause key left an earlier --stop in force, so the
        # run ended anyway while this command claimed it would continue.
        had_stop = control.should_stop()
        # ``request_resume`` itself clears pause *and* stop — "resume" means
        # both. Going through it (rather than ``clear_requests``) keeps the CLI
        # and story 1.5's endpoints on literally the same code path.
        control.request_resume()
        print("Resume requested — the running backfill will continue launching rows.")
        if had_stop:
            print("  (also cleared a pending stop request)")
    else:
        control.request_stop()
        print("Stop requested — the running backfill will drain and exit; safe to resume later.")
    print(f"  control state: {control.state().value}")
    return 0


def _lease_refusal(holder: dict | None) -> str:
    return (
        "Refusing to start: another backfill runner holds the lease.\n"
        f"  {_lease_summary(holder)}\n"
        "  Use --status to inspect it, --stop to ask it to finish, or wait for "
        "the lease TTL to expire if that run is gone."
    )


def _migration_refusal(token: str | None) -> str:
    return (
        "Refusing to launch rows: a primary database migration is in progress "
        f"(migrate-primary.sh holds the exclusion key; token {token or 'unknown'}).\n"
        "  Enriching now would write against a schema mid-upgrade.\n"
        "  Wait for the migration to finish (the key self-clears within its TTL "
        "— never delete it manually) and re-run; the checkpoint is intact."
    )


def _install_stop_signals(control: BackfillControl) -> None:
    """SIGINT/SIGTERM → request a clean stop; a second signal aborts hard.

    The first signal drains in-flight rows so nothing is half-written; the
    handler immediately restores the default disposition, so an impatient
    operator pressing Ctrl-C twice still gets the usual hard abort.
    """
    def _handler(signum, _frame):
        signal.signal(signum, signal.SIG_DFL)
        control.request_stop()
        print(
            "\nStop requested — draining in-flight properties. "
            "Signal again to abort immediately.",
            file=sys.stderr,
        )

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):  # not the main thread / unsupported platform
            logger.debug("backfill_signal_handler_unavailable", signum=int(sig))


if __name__ == "__main__":
    raise SystemExit(main())
