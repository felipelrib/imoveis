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

A real run calls the live Gemma endpoint (free tier) and mutates DB scores.

Exit codes (``--continuous``)
----------------------------
An unattended run ends while nobody is watching, so the outcome is in the exit
code as well as the closing banner (v0.13-fu3):

===  ==========================================================================
0    complete — the candidate queue drained, nothing was retired
3    stalled — work remains but a full cycle made no progress; needs a look
4    complete, but N rows were quarantined unenriched (see the banner listing)
===  ==========================================================================

Completion is measured against the **candidate queue** — active rows with no AI
score — not ``total properties - enriched``. The runner never fetches inactive
listings (494 of them on 2026-08-05), so the old total-based arithmetic could
never reach zero: the completion branch was dead and every finished run exited
through the "no progress this cycle" message instead.
"""

from __future__ import annotations

import argparse
import asyncio
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

from adapters.ai.client import _gemini_client_for  # noqa: E402
from adapters.ai.image_store import ImageStore  # noqa: E402
from adapters.queue.tasks import run_enrichment  # noqa: E402
from core.backfill_runner import (  # noqa: E402
    AttemptLedger,
    BackfillResult,
    Checkpoint,
    DailyBudget,
    Heartbeat,
    QueueCensus,
    TokenBudget,
    estimate_eta_days,
    launch_interval_for_rpm,
    partition_candidates,
    run_backfill,
)
from core.enrichment_rerun import (  # noqa: E402
    MODE_MISSING,
    STAGES_ALL,
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

_BANNER_WIDTH = 68


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


def _build_client(cfg):
    # Key is loaded from the GEMINI_API_KEY env into cfg by infra.config — the
    # single place env is read (never os.getenv here, per repo convention).
    api_key = cfg.ai.gemini_api_key
    if not api_key:
        raise SystemExit(
            "GEMINI_API_KEY is not set — the Gemma backfill needs a free-tier key."
        )
    return _gemini_client_for(
        cfg.ai.gemma_model,
        api_key=api_key,
        base_url=cfg.ai.gemini_url,
        timeout=cfg.ai.timeout,
    )


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


async def _enrich_one(prop, *, client, cfg) -> None:
    """Adapter: pull image_urls/description off the row and enrich in place."""
    image_urls = prop.image_urls if isinstance(getattr(prop, "image_urls", None), list) else []
    description = getattr(prop, "description", None) or ""
    image_store = ImageStore()
    await run_enrichment(
        client,
        image_store,
        str(prop.id),
        image_urls,
        description,
        STAGES_ALL,
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
    _print_quarantine(_quarantine_report(ledger), indent="  ")


def _build_ledger(cfg, redis, max_attempts: int | None = None) -> AttemptLedger:
    return AttemptLedger(
        redis,
        prefix=cfg.backfill.redis_prefix,
        max_attempts=max_attempts or cfg.backfill.max_attempts,
    )


def _run(cfg, session, redis, args) -> BackfillResult:
    # A dry-run makes no API calls, so it must not require a key/client — build
    # the Gemma client only for a real run.
    client = None if args.dry_run else _build_client(cfg)
    ledger = _build_ledger(cfg, redis, getattr(args, "max_attempts", None))
    params = EnrichmentRerunParams(
        mode=MODE_MISSING,
        stages=STAGES_ALL,
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
        stages=STAGES_ALL,
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

    def _on_progress(res: BackfillResult) -> None:
        heartbeat.beat()
        if res.processed % 25 == 0:
            logger.info(
                "backfill_progress",
                processed=res.processed,
                requests_consumed=res.requests_consumed,
                errors=res.errors,
                rate_limit_hits=getattr(client, "rate_limit_hits", 0),
                retry_count=getattr(client, "retry_count", 0),
            )

    async def _run_backfill() -> BackfillResult:
        return await run_backfill(
            rows,
            enrich_fn=partial(_enrich_one, client=client, cfg=cfg),
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
        )

    async def _go() -> BackfillResult:
        heartbeat.beat()
        try:
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


def _run_continuous(cfg, redis, args) -> int:
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
    budget = DailyBudget(
        redis,
        prefix=cfg.backfill.redis_prefix,
        daily_limit=args.daily_budget or cfg.backfill.daily_request_budget,
    )
    ledger = _build_ledger(cfg, redis, getattr(args, "max_attempts", None))
    started = time.monotonic()
    cycle = 0
    enriched_this_run = 0
    errors_this_run = 0
    while True:
        cycle += 1
        with SessionLocal() as session:
            result = _run(cfg, session, redis, args)
            census = _census(cfg, session, ledger)
        enriched_this_run += result.processed
        errors_this_run += result.errors
        logger.info(
            "backfill_cycle_done",
            cycle=cycle,
            processed=result.processed,
            errors=result.errors,
            skipped_quarantined=result.skipped_quarantined,
            remaining=census.remaining,
            budget_exhausted=result.budget_exhausted,
        )
        print(
            f"[cycle {cycle}] enriched {result.processed}, errors {result.errors}, "
            f"quarantined-skips {result.skipped_quarantined}, remaining {census.remaining}"
        )

        def _end() -> int:
            return _finish(
                census,
                _quarantine_report(ledger),
                cycle=cycle,
                elapsed=time.monotonic() - started,
                processed=enriched_this_run,
                errors=errors_this_run,
            )

        # Completion is checked *before* the budget branch: a pass that spends the
        # last of its budget on the last of the queue must exit now, not sleep out
        # the remaining ~24h only to find an empty queue.
        if census.is_complete:
            return _end()
        if not result.budget_exhausted:
            # Budget left, work left, yet nothing moved → a real stall (every
            # remaining row is failing). Exiting non-zero makes that visible.
            if result.processed == 0:
                return _end()
            continue  # made progress, more may be fetchable → next pass now
        # Budget spent with work remaining — including a pass that processed
        # nothing because the window was already exhausted on entry. Sleep.

        wait = budget.seconds_until_reset() + args.reset_margin
        resume_at = datetime.now().astimezone() + timedelta(seconds=wait)
        logger.info("backfill_waiting_for_reset", seconds=round(wait), resume_at=str(resume_at))
        print(
            f"Daily budget spent; sleeping {wait / 3600:.1f}h until the window "
            f"resets (~{resume_at:%Y-%m-%d %H:%M %Z}). Ctrl-C to stop; safe to resume."
        )
        time.sleep(wait)


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
    parser.add_argument("--status", action="store_true", help="print status and exit")
    args = parser.parse_args(argv)

    cfg = get_config()
    redis = get_redis()

    if args.reset_quarantine:
        ledger = _build_ledger(cfg, redis, args.max_attempts)
        released = ledger.quarantined_count()
        ledger.reset_all()
        print(f"Attempt ledger cleared — {released} quarantined properties released.")
        return 0

    if args.status:
        with SessionLocal() as session:
            _print_status(cfg, session, redis)
        return 0

    if args.continuous:
        if args.dry_run:
            parser.error("--continuous cannot be combined with --dry-run")
        # --continuous processes to completion; a per-run --limit would loop.
        args.limit = None
        return _run_continuous(cfg, redis, args)

    with SessionLocal() as session:
        result = _run(cfg, session, redis, args)

    logger.info("backfill_done", **result.to_dict())
    verb = "would enrich" if args.dry_run else "enriched"
    n = result.would_process if args.dry_run else result.processed
    # "pass done", not "complete" — a single pass says nothing about the queue.
    # Only --continuous prints the terminal BACKFILL COMPLETE banner.
    print(
        f"Backfill pass done: {verb} {n} properties "
        f"(skipped {result.skipped_already_enriched}, "
        f"quarantined {result.skipped_quarantined}, errors {result.errors}, "
        f"budget_exhausted={result.budget_exhausted})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
