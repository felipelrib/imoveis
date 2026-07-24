"""Collect and persist pipeline metric snapshots (BIN-61)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from adapters.db.models import PipelineMetricSnapshot
from infra.logging import get_logger

logger = get_logger(__name__)


def collect_snapshot_fields() -> Dict[str, Any]:
    """Sample the same sources as GET /system/pipeline + property counts."""
    from api.system import (
        _ai_pipeline_metrics,
        _check_db_and_counts,
        _pipeline_queue_lengths,
    )
    from infra.redis_client import get_redis

    redis = get_redis()
    queues = _pipeline_queue_lengths(redis)
    ai_metrics = _ai_pipeline_metrics(redis.lrange("pipeline:ai:telemetry", 0, -1))
    _db_status, total, enriched = _check_db_and_counts()
    return {
        "ts": datetime.now(timezone.utc),
        "total_properties": total,
        "enriched_properties": enriched,
        "scraper_queue": int(queues.get("scrapers") or 0),
        "ai_queue": int(queues.get("ai") or 0),
        "throughput_per_min": float(ai_metrics.get("throughput_per_min") or 0.0),
    }


def write_snapshot(session, fields: Optional[Dict[str, Any]] = None) -> PipelineMetricSnapshot:
    """Insert one snapshot row. Caller owns commit."""
    data = fields or collect_snapshot_fields()
    row = PipelineMetricSnapshot(
        id=data.get("id") or uuid.uuid4(),
        ts=data["ts"],
        total_properties=data.get("total_properties"),
        enriched_properties=data.get("enriched_properties"),
        scraper_queue=data.get("scraper_queue", 0),
        ai_queue=data.get("ai_queue", 0),
        throughput_per_min=data.get("throughput_per_min", 0.0),
    )
    session.add(row)
    return row


def prune_old_snapshots(session, retention_days: int = 7) -> int:
    """Delete snapshots older than retention_days. Returns rows deleted."""
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = (
        session.query(PipelineMetricSnapshot)
        .filter(PipelineMetricSnapshot.ts < cutoff)
        .delete(synchronize_session=False)
    )
    return int(deleted or 0)


def list_snapshots_since(session, since: datetime) -> List[PipelineMetricSnapshot]:
    """Return snapshots with ts >= since, oldest first."""
    return (
        session.query(PipelineMetricSnapshot)
        .filter(PipelineMetricSnapshot.ts >= since)
        .order_by(PipelineMetricSnapshot.ts.asc())
        .all()
    )


def snapshot_and_prune(session, retention_days: int = 7) -> Dict[str, Any]:
    """Write a snapshot and prune old rows in one transaction."""
    fields = collect_snapshot_fields()
    write_snapshot(session, fields)
    pruned = prune_old_snapshots(session, retention_days=retention_days)
    session.commit()
    logger.info(
        "pipeline_metric_snapshot_written",
        total_properties=fields.get("total_properties"),
        ai_queue=fields.get("ai_queue"),
        throughput_per_min=fields.get("throughput_per_min"),
        pruned=pruned,
    )
    return {"written": 1, "pruned": pruned, **{k: fields[k] for k in (
        "total_properties", "enriched_properties", "scraper_queue", "ai_queue", "throughput_per_min"
    )}}
