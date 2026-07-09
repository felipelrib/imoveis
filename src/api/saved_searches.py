"""Saved Searches CRUD API — persist and reapply filter sets."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from infra.db import SessionLocal
from infra.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/saved-searches", tags=["saved-searches"])


class SavedSearchCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    filters: Dict[str, Any]


class SavedSearchUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    filters: Optional[Dict[str, Any]] = None


class SavedSearchItem(BaseModel):
    id: str
    name: str
    filters: Dict[str, Any]
    created_at: Optional[str] = None


@router.get("", response_model=List[SavedSearchItem])
def list_saved_searches() -> List[SavedSearchItem]:
    """Return all saved searches ordered by most recent."""
    session = SessionLocal()
    try:
        rows = session.execute(
            text(
                "SELECT id, name, filters, created_at "
                "FROM saved_searches ORDER BY created_at DESC"
            )
        ).fetchall()
        return [
            SavedSearchItem(
                id=str(r[0]),
                name=r[1],
                filters=r[2] if isinstance(r[2], dict) else {},
                created_at=r[3].isoformat() if r[3] else None,
            )
            for r in rows
        ]
    finally:
        session.close()


@router.get("/{search_id}", response_model=SavedSearchItem)
def get_saved_search(search_id: str) -> SavedSearchItem:
    """Return a single saved search by ID."""
    session = SessionLocal()
    try:
        row = session.execute(
            text(
                "SELECT id, name, filters, created_at "
                "FROM saved_searches WHERE id = :sid"
            ),
            {"sid": search_id},
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Saved search not found")
        return SavedSearchItem(
            id=str(row[0]),
            name=row[1],
            filters=row[2] if isinstance(row[2], dict) else {},
            created_at=row[3].isoformat() if row[3] else None,
        )
    except HTTPException:
        raise
    finally:
        session.close()


@router.post("", status_code=201, response_model=SavedSearchItem)
def create_saved_search(req: SavedSearchCreate) -> SavedSearchItem:
    """Create a new saved search."""
    session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        search_id = str(uuid.uuid4())
        session.execute(
            text(
                "INSERT INTO saved_searches (id, name, filters, created_at) "
                "VALUES (:id, :name, :filters, :now)"
            ),
            {"id": search_id, "name": req.name, "filters": req.filters, "now": now},
        )
        session.commit()
        logger.info("saved_search_create", search_id=search_id, name=req.name)
        return SavedSearchItem(
            id=search_id,
            name=req.name,
            filters=req.filters,
            created_at=now.isoformat(),
        )
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        session.close()


@router.delete("/{search_id}")
def delete_saved_search(search_id: str) -> Dict[str, str]:
    """Delete a saved search."""
    session = SessionLocal()
    try:
        result = session.execute(
            text("DELETE FROM saved_searches WHERE id = :sid"),
            {"sid": search_id},
        )
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Saved search not found")
        logger.info("saved_search_delete", search_id=search_id)
        return {"status": "deleted", "id": search_id}
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        session.close()
