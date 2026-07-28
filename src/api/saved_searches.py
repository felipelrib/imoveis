"""Saved Searches CRUD API — persist and reapply filter sets."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)
from sqlalchemy import text

from api.auth import Principal, verify_api_key
from core.listing_type import normalize_listing_type, normalize_price_type
from core.property_type import normalize_property_type
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


def _empty_str_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


class SavedSearchFilters(BaseModel):
    """Locale-stable EN filter wire for saved searches (BIN-100).

    Accepts camelCase SPA payloads and legacy ``furnished`` / ``pets`` /
    ``neighbourhood`` keys; always dumps snake_case EN canonical values.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    sort_by: Optional[str] = Field(
        None, validation_alias=AliasChoices("sort_by", "sortBy")
    )
    sort_dir: Optional[str] = Field(
        None, validation_alias=AliasChoices("sort_dir", "sortDir")
    )
    listing_type: Optional[str] = Field(
        None, validation_alias=AliasChoices("listing_type", "listingType")
    )
    property_type: Optional[str] = Field(
        None, validation_alias=AliasChoices("property_type", "propertyType")
    )
    platform: Optional[str] = Field(
        None, validation_alias=AliasChoices("platform")
    )
    min_price: Optional[float] = Field(
        None, validation_alias=AliasChoices("min_price", "minPrice")
    )
    max_price: Optional[float] = Field(
        None, validation_alias=AliasChoices("max_price", "maxPrice")
    )
    price_type: Optional[str] = Field(
        None, validation_alias=AliasChoices("price_type", "priceType")
    )
    min_bedrooms: Optional[int] = Field(
        None, validation_alias=AliasChoices("min_bedrooms", "minBedrooms")
    )
    max_bedrooms: Optional[int] = Field(
        None, validation_alias=AliasChoices("max_bedrooms", "maxBedrooms")
    )
    min_parking: Optional[int] = Field(
        None, validation_alias=AliasChoices("min_parking", "minParking")
    )
    neighborhood: Optional[str] = Field(
        None,
        validation_alias=AliasChoices(
            "neighborhood", "neighbourhood", "neighborhood_name"
        ),
    )
    city: Optional[str] = Field(
        None, validation_alias=AliasChoices("city", "city_name", "cityName")
    )
    is_furnished: Optional[bool] = Field(
        None,
        validation_alias=AliasChoices("is_furnished", "isFurnished", "furnished"),
    )
    accepts_pets: Optional[bool] = Field(
        None,
        validation_alias=AliasChoices("accepts_pets", "acceptsPets", "pets"),
    )
    min_score: Optional[float] = Field(
        None, validation_alias=AliasChoices("min_score", "minScore")
    )
    q: Optional[str] = Field(None, validation_alias=AliasChoices("q"))

    @field_validator(
        "sort_by",
        "sort_dir",
        "listing_type",
        "property_type",
        "platform",
        "price_type",
        "q",
        mode="before",
    )
    @classmethod
    def _blank_strings(cls, value: Any) -> Any:
        return _empty_str_to_none(value)

    @field_validator("neighborhood", "city", mode="before")
    @classmethod
    def _join_place_lists(cls, value: Any) -> Any:
        if isinstance(value, list):
            parts = [str(x).strip() for x in value if str(x).strip()]
            return ",".join(parts) if parts else None
        return _empty_str_to_none(value)

    @field_validator(
        "min_price",
        "max_price",
        "min_score",
        "min_bedrooms",
        "max_bedrooms",
        "min_parking",
        mode="before",
    )
    @classmethod
    def _blank_numbers(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("listing_type", mode="before")
    @classmethod
    def _normalize_listing_type(cls, value: Any) -> Any:
        value = _empty_str_to_none(value)
        if value is None:
            return None
        return normalize_listing_type(str(value)) or value

    @field_validator("price_type", mode="before")
    @classmethod
    def _normalize_price_type(cls, value: Any) -> Any:
        value = _empty_str_to_none(value)
        if value is None:
            return None
        return normalize_price_type(str(value)) or value

    @field_validator("property_type", mode="before")
    @classmethod
    def _normalize_property_type(cls, value: Any) -> Any:
        value = _empty_str_to_none(value)
        if value is None:
            return None
        return normalize_property_type(str(value)) or value

    def to_wire(self) -> Dict[str, Any]:
        """Snake_case EN JSON suitable for JSONB persistence."""
        data = self.model_dump(by_alias=False, exclude_none=True)
        # Omit false amenity flags — SPA defaults are unchecked.
        if data.get("is_furnished") is False:
            data.pop("is_furnished")
        if data.get("accepts_pets") is False:
            data.pop("accepts_pets")
        return data


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
            wire = req.filters.to_wire()
            session.execute(
                text(
                    "INSERT INTO saved_searches (id, name, filters, owner, created_at) "
                    "VALUES (:id, :name, :filters, :owner, :now)"
                ),
                {
                    "id": search_id,
                    "name": req.name,
                    "filters": json.dumps(wire),
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
                filters=wire,
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
                params["filters"] = json.dumps(req.filters.to_wire())

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
