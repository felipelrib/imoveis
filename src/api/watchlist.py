"""Watchlist CRUD API — manage watched properties for price-drop alerts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from api.auth import verify_jwt
from infra.db import SessionLocal
from infra.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistCreate(BaseModel):
    property_id: str
    min_drop_pct: float = Field(5.0, ge=0.1, le=100.0)
    user_id: Optional[str] = None


class WatchlistItem(BaseModel):
    id: str
    property_id: str
    min_drop_pct: float
    user_id: Optional[str] = None
    last_notified_price: Optional[float] = None
    created_at: Optional[str] = None


@router.get("")
def list_watchlist(user_id: str = Depends(verify_jwt)) -> List[WatchlistItem]:
    """Return all watched properties."""
    with SessionLocal() as session:
        rows = session.execute(
            text(
                "SELECT id, property_id, min_drop_pct, user_id, last_notified_price, created_at "
                "FROM watchlist WHERE user_id = :uid ORDER BY created_at DESC"
            ),
            {"uid": user_id}
        ).fetchall()
        return [
            WatchlistItem(
                id=str(r[0]),
                property_id=str(r[1]),
                min_drop_pct=float(r[2]),
                user_id=str(r[3]) if r[3] else None,
                last_notified_price=float(r[4]) if r[4] is not None else None,
                created_at=r[5].isoformat() if r[5] else None,
            )
            for r in rows
        ]


@router.post("", status_code=201)
def add_to_watchlist(req: WatchlistCreate, user_id: str = Depends(verify_jwt)) -> WatchlistItem:
    """Add a property to the watchlist."""
    req.user_id = user_id
    with SessionLocal() as session:
        try:
            # Verify property exists
            prop = session.execute(
                text("SELECT id FROM properties WHERE id = :pid"),
                {"pid": req.property_id},
            ).fetchone()
            if prop is None:
                raise HTTPException(status_code=404, detail="Property not found")

            # Try to insert (ON CONFLICT DO NOTHING relies on unique property_id)
            import uuid
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            watchlist_id = str(uuid.uuid4())
            result = session.execute(
                text(
                    "INSERT INTO watchlist (id, property_id, min_drop_pct, user_id, created_at) "
                    "VALUES (:id, :pid, :min_drop, :uid, :now) "
                    "ON CONFLICT (property_id) DO NOTHING "
                    "RETURNING id"
                ),
                {"id": watchlist_id, "pid": req.property_id, "min_drop": req.min_drop_pct, "uid": req.user_id, "now": now},
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=409, detail="Property already in watchlist")
            session.commit()

            logger.info("watchlist_add", property_id=req.property_id, min_drop_pct=req.min_drop_pct)
            return WatchlistItem(
                id=watchlist_id,
                property_id=req.property_id,
                min_drop_pct=req.min_drop_pct,
                user_id=req.user_id,
                created_at=now.isoformat(),
            )
        except HTTPException:
            raise
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{property_id}")
def remove_from_watchlist(property_id: str, user_id: str = Depends(verify_jwt)) -> Dict[str, str]:
    """Remove a property from the watchlist."""
    with SessionLocal() as session:
        try:
            result = session.execute(
                text("DELETE FROM watchlist WHERE property_id = :pid AND user_id = :uid"),
                {"pid": property_id, "uid": user_id},
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
def check_watchlist(property_id: str, user_id: str = Depends(verify_jwt)) -> Dict[str, Any]:
    """Check if a specific property is in the watchlist."""
    with SessionLocal() as session:
        row = session.execute(
            text(
                "SELECT id, min_drop_pct, user_id, last_notified_price "
                "FROM watchlist WHERE property_id = :pid AND user_id = :uid"
            ),
            {"pid": property_id, "uid": user_id},
        ).fetchone()
        if row is None:
            return {"watched": False}
        return {
            "watched": True,
            "id": str(row[0]),
            "min_drop_pct": float(row[1]),
            "user_id": str(row[2]) if row[2] else None,
            "last_notified_price": float(row[3]) if row[3] is not None else None,
        }
