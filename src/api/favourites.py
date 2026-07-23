"""Favourites CRUD API — manage favourited properties for quick access."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from infra.db import SessionLocal
from infra.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/favourites", tags=["favourites"])


class FavouriteCreate(BaseModel):
    property_id: str


class FavouriteItem(BaseModel):
    id: str
    property_id: str
    created_at: Optional[str] = None


class FavouriteWithProperty(BaseModel):
    id: str
    property_id: str
    created_at: Optional[str] = None
    title: Optional[str] = None
    address: Optional[str] = None
    price: Optional[float] = None
    image_urls: Optional[List[str]] = None
    combined_score: Optional[float] = None
    neighborhood_name: Optional[str] = None
    platform: Optional[str] = None


class PaginatedFavouritesResponse(BaseModel):
    items: List[FavouriteWithProperty]
    total: int
    page: int
    page_size: int


@router.get("", response_model=PaginatedFavouritesResponse)
def list_favourites(page: int = 1, page_size: int = 50) -> PaginatedFavouritesResponse:
    """Return all favourites with property details."""
    with SessionLocal() as session:
        offset = (page - 1) * page_size

        total = session.execute(text("SELECT COUNT(*) FROM favourites")).scalar() or 0

        rows = session.execute(
            text(
                "SELECT f.id, f.property_id, f.created_at, "
                "p.title, p.address, p.price, p.image_urls, "
                "ms.combined_score, n.name AS neighborhood_name, p.platform "
                "FROM favourites f "
                "JOIN properties p ON p.id = f.property_id "
                "LEFT JOIN metrics_scoring ms ON ms.property_id = f.property_id "
                "LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id "
                "ORDER BY f.created_at DESC "
                "LIMIT :limit OFFSET :offset"
            ),
            {"limit": page_size, "offset": offset}
        ).fetchall()

        items = [
            FavouriteWithProperty(
                id=str(r[0]),
                property_id=str(r[1]),
                created_at=r[2].isoformat() if r[2] else None,
                title=r[3],
                address=r[4],
                price=float(r[5]) if r[5] is not None else None,
                image_urls=r[6] if isinstance(r[6], list) else None,
                combined_score=float(r[7]) if r[7] is not None else None,
                neighborhood_name=r[8],
                platform=r[9],
            )
            for r in rows
        ]

        return PaginatedFavouritesResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size
        )


@router.post("", status_code=201, response_model=FavouriteItem)
def add_favourite(req: FavouriteCreate) -> FavouriteItem:
    """Add a property to favourites."""
    with SessionLocal() as session:
        try:
            # Verify property exists
            prop = session.execute(
                text("SELECT id FROM properties WHERE id = :pid"),
                {"pid": req.property_id},
            ).fetchone()
            if prop is None:
                raise HTTPException(status_code=404, detail="Property not found")

            result = session.execute(
                text(
                    "INSERT INTO favourites (id, property_id, created_at) "
                    "VALUES (:id, :pid, :now) "
                    "ON CONFLICT (property_id) DO NOTHING "
                    "RETURNING id"
                ),
                {"id": fav_id, "pid": req.property_id, "now": now},
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=409, detail="Property already favourited")
            session.commit()
            logger.info("favourite_add", property_id=req.property_id)
            return FavouriteItem(
                id=fav_id,
                property_id=req.property_id,
                created_at=now.isoformat(),
            )
        except HTTPException:
            raise
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{property_id}")
def remove_favourite(property_id: str) -> Dict[str, str]:
    """Remove a property from favourites."""
    with SessionLocal() as session:
        try:
            result = session.execute(
                text("DELETE FROM favourites WHERE property_id = :pid"),
                {"pid": property_id},
            )
            session.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Property not in favourites")
            logger.info("favourite_remove", property_id=property_id)
            return {"status": "removed", "property_id": property_id}
        except HTTPException:
            raise
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=500, detail=str(exc))


@router.get("/check/{property_id}")
def check_favourite(property_id: str) -> Dict[str, Any]:
    """Check if a specific property is favourited."""
    with SessionLocal() as session:
        row = session.execute(
            text("SELECT id, created_at FROM favourites WHERE property_id = :pid"),
            {"pid": property_id},
        ).fetchone()
        if row is None:
            return {"favourited": False}
        return {
            "favourited": True,
            "id": str(row[0]),
            "created_at": row[1].isoformat() if row[1] else None,
        }
