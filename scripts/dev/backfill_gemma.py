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

    # Status: enriched vs total, budget consumed today, ETA:
    PYTHONPATH=src python scripts/dev/backfill_gemma.py --status

A real run calls the live Gemma endpoint (free tier) and mutates DB scores.
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
    BackfillResult,
    Checkpoint,
    DailyBudget,
    Heartbeat,
    TokenBudget,
    estimate_eta_days,
    launch_interval_for_rpm,
    run_backfill,
)
from core.enrichment_rerun import (  # noqa: E402
    MODE_MISSING,
    STAGES_ALL,
    EnrichmentRerunParams,
    fetch_candidate_rows,
)
from infra.config import get_config  # noqa: E402
from infra.db import SessionLocal  # noqa: E402
from infra.logging import get_logger  # noqa: E402
from infra.redis_client import get_redis  # noqa: E402

logger = get_logger(__name__)


def _counts(session) -> tuple[int, int]:
    """Return ``(total_properties, enriched_properties)``."""
    total = session.execute(
        sqlalchemy.text("SELECT COUNT(*) FROM properties")
    ).scalar()
    enriched = session.execute(
        sqlalchemy.text("SELECT COUNT(*) FROM metrics_scoring WHERE ai_score > 0")
    ).scalar()
    return int(total or 0), int(enriched or 0)


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
    total, enriched = _counts(session)
    remaining_props = max(0, total - enriched)
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
        eta_str = f"{estimate_eta_days(remaining_props, observed):.1f} (observed)"
    else:
        # No recent activity — fall back to the request-budget ceiling.
        budget_rate = cfg.backfill.daily_request_budget / cfg.backfill.requests_per_property
        rate_str = "idle"
        eta_str = f"{estimate_eta_days(remaining_props, budget_rate):.1f} (budget ceiling; not running)"
    cp = checkpoint.load()

    print("Gemma backfill status (BIN-248)")
    print(f"  enriched / total     : {enriched} / {total}")
    print(f"  remaining            : {remaining_props}")
    print(f"  budget today         : {consumed} / {cfg.backfill.daily_request_budget} requests")
    print(f"  observed rate        : {rate_str}")
    print(f"  processed (all-time) : {checkpoint.processed_total()}")
    print(f"  last property        : {cp.get('last_property_id', '—')}")
    print(f"  last run date        : {cp.get('last_run_date', '—')}")
    print(f"  ETA (~days)          : {eta_str}")


def _run(cfg, session, redis, args) -> BackfillResult:
    # A dry-run makes no API calls, so it must not require a key/client — build
    # the Gemma client only for a real run.
    client = None if args.dry_run else _build_client(cfg)
    params = EnrichmentRerunParams(
        mode=MODE_MISSING,
        stages=STAGES_ALL,
        active_only=True,
        limit=args.limit,
    )
    rows = fetch_candidate_rows(session, params)
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


def _remaining(cfg, redis, session) -> int:
    total, enriched = _counts(session)
    return max(0, total - enriched)


def _run_continuous(cfg, redis, args) -> int:
    """Run passes until the backfill completes, sleeping across RPD-window resets.

    Each pass enriches until the daily budget is exhausted (or candidates run
    out), then — if properties remain — sleeps until the rolling 24h budget
    window resets and resumes. Checkpointed, so a killed process resumes.
    """
    budget = DailyBudget(
        redis,
        prefix=cfg.backfill.redis_prefix,
        daily_limit=args.daily_budget or cfg.backfill.daily_request_budget,
    )
    cycle = 0
    while True:
        cycle += 1
        with SessionLocal() as session:
            result = _run(cfg, session, redis, args)
            remaining = _remaining(cfg, redis, session)
        logger.info(
            "backfill_cycle_done",
            cycle=cycle,
            processed=result.processed,
            errors=result.errors,
            remaining=remaining,
            budget_exhausted=result.budget_exhausted,
        )
        print(
            f"[cycle {cycle}] enriched {result.processed}, "
            f"errors {result.errors}, remaining {remaining}"
        )

        if remaining == 0:
            print("Backfill complete — all properties enriched.")
            return 0
        if not result.budget_exhausted:
            # Budget left but nothing more processed this pass → no further
            # progress is possible right now (e.g. remaining rows un-enrichable);
            # stop rather than spin.
            if result.processed == 0:
                print(
                    f"Stopping: {remaining} remaining but no progress this cycle "
                    "(re-run later or inspect those rows)."
                )
                return 0
            continue  # made progress, more may be fetchable → next pass now

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
    parser.add_argument("--status", action="store_true", help="print status and exit")
    args = parser.parse_args(argv)

    cfg = get_config()
    redis = get_redis()

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
    print(
        f"Backfill complete: {verb} {n} properties "
        f"(skipped {result.skipped_already_enriched}, errors {result.errors}, "
        f"budget_exhausted={result.budget_exhausted})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
