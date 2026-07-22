"""Watchlist CRUD API — manage watched properties for price-drop alerts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from infra.db import SessionLocal
from infra.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistCreate(BaseModel):
    property_id: str
    min_drop_pct: float = Field(5.0, ge=0.1, le=100.0)


class WatchlistItem(BaseModel):
    id: str
    property_id: str
    min_drop_pct: float
    last_notified_price: Optional[float] = None
    created_at: Optional[str] = None


@router.get("")
def list_watchlist() -> List[WatchlistItem]:
    """Return all watched properties."""
    with SessionLocal() as session:
        rows = session.execute(
            text(
                "SELECT id, property_id, min_drop_pct, last_notified_price, created_at "
                "FROM watchlist ORDER BY created_at DESC"
            )
        ).fetchall()
        return [
            WatchlistItem(
                id=str(r[0]),
                property_id=str(r[1]),
                min_drop_pct=float(r[2]),
                last_notified_price=float(r[3]) if r[3] is not None else None,
                created_at=r[4].isoformat() if r[4] else None,
            )
            for r in rows
        ]


@router.post("", status_code=201)
def add_to_watchlist(req: WatchlistCreate) -> WatchlistItem:
    """Add a property to the watchlist."""
    with SessionLocal() as session:
        try:
            # Verify property exists
            prop = session.execute(
                text("SELECT id FROM properties WHERE id = :pid"),
                {"pid": req.property_id},
            ).fetchone()
            if prop is None:
                raise HTTPException(status_code=404, detail="Property not found")

            # Check if already in watchlist
            existing = session.execute(
                text("SELECT id FROM watchlist WHERE property_id = :pid"),
                {"pid": req.property_id},
            ).fetchone()
            if existing is not None:
                raise HTTPException(status_code=409, detail="Property already in watchlist")

            import uuid
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            watchlist_id = str(uuid.uuid4())
            session.execute(
                text(
                    "INSERT INTO watchlist (id, property_id, min_drop_pct, created_at) "
                    "VALUES (:id, :pid, :min_drop, :now)"
                ),
                {"id": watchlist_id, "pid": req.property_id, "min_drop": req.min_drop_pct, "now": now},
            )
            session.commit()

            logger.info("watchlist_add", property_id=req.property_id, min_drop_pct=req.min_drop_pct)
            return WatchlistItem(
                id=watchlist_id,
                property_id=req.property_id,
                min_drop_pct=req.min_drop_pct,
                created_at=now.isoformat(),
            )
        except HTTPException:
            raise
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{property_id}")
def remove_from_watchlist(property_id: str) -> Dict[str, str]:
    """Remove a property from the watchlist."""
    with SessionLocal() as session:
        try:
            result = session.execute(
                text("DELETE FROM watchlist WHERE property_id = :pid"),
                {"pid": property_id},
            )
            session.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Property not in watchlist")
            logger.info("watchlist_remove", property_id=property_id)
            return {"status": "removed", "property_id": property_id}
        except HTTPException:
            raise
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=500, detail=str(exc))


@router.get("/check/{property_id}")
def check_watchlist(property_id: str) -> Dict[str, Any]:
    """Check if a specific property is in the watchlist."""
    with SessionLocal() as session:
        row = session.execute(
            text("SELECT id, min_drop_pct, last_notified_price FROM watchlist WHERE property_id = :pid"),
            {"pid": property_id},
        ).fetchone()
        if row is None:
            return {"watched": False}
        return {
            "watched": True,
            "id": str(row[0]),
            "min_drop_pct": float(row[1]),
            "last_notified_price": float(row[2]) if row[2] is not None else None,
        }
