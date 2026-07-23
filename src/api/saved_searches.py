"""Saved Searches CRUD API — persist and reapply filter sets."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from api.auth import Principal, verify_api_key
from infra.db import SessionLocal
from infra.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(
    prefix="/saved-searches",
    tags=["saved-searches"],
    dependencies=[Depends(verify_api_key)],
)

CurrentPrincipal = Annotated[Principal, Depends(verify_api_key)]

SAVED_SEARCH_NOT_FOUND = "Saved search not found"
_RESP_404 = {404: {"description": SAVED_SEARCH_NOT_FOUND}}
_RESP_500 = {500: {"description": "Internal server error"}}


class SavedSearchFilters(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sort_by: Optional[str] = None
    sort_dir: Optional[str] = None
    listing_type: Optional[str] = None
    property_type: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_bedrooms: Optional[int] = None
    max_bedrooms: Optional[int] = None
    neighbourhood: List[str] = Field(default_factory=list)
    furnished: Optional[bool] = None
    pets: Optional[bool] = None
    min_score: Optional[float] = None


class SavedSearchCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    filters: SavedSearchFilters


class SavedSearchUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    filters: Optional[SavedSearchFilters] = None


class SavedSearchItem(BaseModel):
    id: str
    name: str
    filters: Dict[str, Any]
    created_at: Optional[str] = None


class PaginatedSavedSearchesResponse(BaseModel):
    items: List[SavedSearchItem]
    total: int
    page: int
    page_size: int


@router.get("")
def list_saved_searches(
    principal: CurrentPrincipal,
    page: int = 1,
    page_size: int = 50,
) -> PaginatedSavedSearchesResponse:
    """Return saved searches for the authenticated principal."""
    with SessionLocal() as session:
        offset = (page - 1) * page_size

        total = session.execute(
            text("SELECT COUNT(*) FROM saved_searches WHERE owner = :owner"),
            {"owner": principal.id},
        ).scalar() or 0

        rows = session.execute(
            text(
                "SELECT id, name, filters, created_at "
                "FROM saved_searches WHERE owner = :owner "
                "ORDER BY created_at DESC "
                "LIMIT :limit OFFSET :offset"
            ),
            {"owner": principal.id, "limit": page_size, "offset": offset},
        ).fetchall()

        items = [
            SavedSearchItem(
                id=str(r[0]),
                name=r[1],
                filters=r[2] if isinstance(r[2], dict) else {},
                created_at=r[3].isoformat() if r[3] else None,
            )
            for r in rows
        ]

        return PaginatedSavedSearchesResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )


@router.get("/{search_id}", responses=_RESP_404)
def get_saved_search(search_id: str, principal: CurrentPrincipal) -> SavedSearchItem:
    """Return a single saved search owned by the principal."""
    with SessionLocal() as session:
        row = session.execute(
            text(
                "SELECT id, name, filters, created_at "
                "FROM saved_searches WHERE id = :sid AND owner = :owner"
            ),
            {"sid": search_id, "owner": principal.id},
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=SAVED_SEARCH_NOT_FOUND)
        return SavedSearchItem(
            id=str(row[0]),
            name=row[1],
            filters=row[2] if isinstance(row[2], dict) else {},
            created_at=row[3].isoformat() if row[3] else None,
        )


@router.post("", status_code=201, responses=_RESP_500)
def create_saved_search(
    req: SavedSearchCreate, principal: CurrentPrincipal
) -> SavedSearchItem:
    """Create a new saved search for the authenticated principal."""
    with SessionLocal() as session:
        try:
            now = datetime.now(timezone.utc)
            search_id = str(uuid.uuid4())
            session.execute(
                text(
                    "INSERT INTO saved_searches (id, name, filters, owner, created_at) "
                    "VALUES (:id, :name, :filters, :owner, :now)"
                ),
                {
                    "id": search_id,
                    "name": req.name,
                    "filters": json.dumps(req.filters.model_dump(exclude_none=True)),
                    "owner": principal.id,
                    "now": now,
                },
            )
            session.commit()
            logger.info(
                "saved_search_create",
                search_id=search_id,
                search_name=req.name,
                owner=principal.id,
            )
            return SavedSearchItem(
                id=search_id,
                name=req.name,
                filters=req.filters.model_dump(exclude_none=True),
                created_at=now.isoformat(),
            )
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{search_id}", responses={**_RESP_404, **_RESP_500})
def delete_saved_search(
    search_id: str, principal: CurrentPrincipal
) -> Dict[str, str]:
    """Delete a saved search owned by the principal."""
    with SessionLocal() as session:
        try:
            result = session.execute(
                text(
                    "DELETE FROM saved_searches WHERE id = :sid AND owner = :owner"
                ),
                {"sid": search_id, "owner": principal.id},
            )
            session.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail=SAVED_SEARCH_NOT_FOUND)
            logger.info(
                "saved_search_delete",
                search_id=search_id,
                owner=principal.id,
            )
            return {"status": "deleted", "id": search_id}
        except HTTPException:
            raise
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=500, detail=str(exc))


@router.patch("/{search_id}", responses={**_RESP_404, **_RESP_500})
def update_saved_search(
    search_id: str, req: SavedSearchUpdate, principal: CurrentPrincipal
) -> SavedSearchItem:
    """Update a saved search owned by the principal."""
    with SessionLocal() as session:
        try:
            existing = session.execute(
                text(
                    "SELECT id, name, filters FROM saved_searches "
                    "WHERE id = :sid AND owner = :owner"
                ),
                {"sid": search_id, "owner": principal.id},
            ).fetchone()

            if not existing:
                raise HTTPException(status_code=404, detail=SAVED_SEARCH_NOT_FOUND)

            update_fields = []
            params: Dict[str, Any] = {"sid": search_id, "owner": principal.id}

            if req.name is not None:
                update_fields.append("name = :name")
                params["name"] = req.name

            if req.filters is not None:
                update_fields.append("filters = :filters")
                params["filters"] = json.dumps(req.filters.model_dump(exclude_none=True))

            if not update_fields:
                return get_saved_search(search_id, principal)

            session.execute(
                text(
                    f"UPDATE saved_searches SET {', '.join(update_fields)} "
                    "WHERE id = :sid AND owner = :owner"
                ),
                params,
            )
            session.commit()

            logger.info(
                "saved_search_update",
                search_id=search_id,
                owner=principal.id,
            )
            return get_saved_search(search_id, principal)
        except HTTPException:
            raise
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=500, detail=str(exc))
