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
from api.errors import raise_api_error
from core.listing_type import normalize_listing_type, normalize_price_type
from core.property_type import normalize_property_type
from core.saved_search_alerts import saved_search_is_matchable
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
    # Cohort price/m2 percentile cap (v0.14-s1.7); same range as GET /properties.
    max_price_per_m2_percentile: Optional[float] = Field(
        None,
        gt=0,
        le=1,
        validation_alias=AliasChoices(
            "max_price_per_m2_percentile", "maxPricePerM2Percentile"
        ),
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
        "max_price_per_m2_percentile",
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
    # New-match alerts (v0.14-s1.9): off unless asked for.
    notify_new_matches: bool = False
    # Stored and returned only; the drop rule that reads it is Story 1.10.
    min_price_drop: Optional[float] = Field(None, ge=0, allow_inf_nan=False)


class SavedSearchUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    filters: Optional[SavedSearchFilters] = None
    notify_new_matches: Optional[bool] = None
    # ``null`` sent explicitly clears the threshold; an absent key leaves it.
    min_price_drop: Optional[float] = Field(None, ge=0, allow_inf_nan=False)


class SavedSearchItem(BaseModel):
    id: str
    name: str
    filters: Dict[str, Any]
    created_at: Optional[str] = None
    notify_new_matches: bool = False
    min_price_drop: Optional[float] = None
    # Naive UTC; only Properties first seen at or after it can be a new match.
    notify_enabled_at: Optional[str] = None
    # False when the filters carry a semantic query or an unknown key, or are
    # not an object: such a search never fires.
    new_match_alerts_supported: bool = True
    # Local date (alerts.new_match.window_timezone) of the last new-match email.
    last_new_match_alert_on: Optional[str] = None


# One column list for every read, in the order ``_item_from_row`` unpacks.
_ITEM_COLUMNS = (
    "id, name, filters, created_at, notify_new_matches, min_price_drop, "
    "notify_enabled_at, new_match_last_window_on"
)


def _utcnow_naive() -> datetime:
    """Naive UTC, the clock of ``properties.first_seen`` (the newness floor)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _item_from_row(row: Any) -> SavedSearchItem:
    filters = row[2] if isinstance(row[2], dict) else {}
    return SavedSearchItem(
        id=str(row[0]),
        name=row[1],
        filters=filters,
        created_at=row[3].isoformat() if row[3] else None,
        notify_new_matches=bool(row[4]),
        min_price_drop=row[5],
        notify_enabled_at=row[6].isoformat() if row[6] else None,
        # The stored value, not the ``{}`` stand-in: a blob that is not an
        # object never fires, and the API must say so.
        new_match_alerts_supported=saved_search_is_matchable(row[2]),
        last_new_match_alert_on=row[7].isoformat() if row[7] else None,
    )


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
                "SELECT " + _ITEM_COLUMNS + " "
                "FROM saved_searches WHERE owner = :owner "
                "ORDER BY created_at DESC "
                "LIMIT :limit OFFSET :offset"
            ),
            {"owner": principal.id, "limit": page_size, "offset": offset},
        ).fetchall()

        items = [_item_from_row(r) for r in rows]

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
                "SELECT " + _ITEM_COLUMNS + " "
                "FROM saved_searches WHERE id = :sid AND owner = :owner"
            ),
            {"sid": search_id, "owner": principal.id},
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=SAVED_SEARCH_NOT_FOUND)
        return _item_from_row(row)


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
            # Created with alerts on: only Properties first seen from now on count.
            enabled_at = _utcnow_naive() if req.notify_new_matches else None
            session.execute(
                text(
                    "INSERT INTO saved_searches (id, name, filters, owner, created_at, "
                    "notify_new_matches, notify_enabled_at, min_price_drop) "
                    "VALUES (:id, :name, :filters, :owner, :now, "
                    ":notify_new_matches, :notify_enabled_at, :min_price_drop)"
                ),
                {
                    "id": search_id,
                    "name": req.name,
                    "filters": json.dumps(wire),
                    "owner": principal.id,
                    "now": now,
                    "notify_new_matches": req.notify_new_matches,
                    "notify_enabled_at": enabled_at,
                    "min_price_drop": req.min_price_drop,
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
                notify_new_matches=req.notify_new_matches,
                min_price_drop=req.min_price_drop,
                notify_enabled_at=enabled_at.isoformat() if enabled_at else None,
                new_match_alerts_supported=saved_search_is_matchable(wire),
                last_new_match_alert_on=None,
            )
        except Exception as exc:
            session.rollback()
            raise_api_error(logger, "saved_search_create_failed", exc)


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
            raise_api_error(logger, "saved_search_delete_failed", exc)


@router.patch("/{search_id}", responses={**_RESP_404, **_RESP_500})
def update_saved_search(
    search_id: str, req: SavedSearchUpdate, principal: CurrentPrincipal
) -> SavedSearchItem:
    """Update a saved search owned by the principal."""
    with SessionLocal() as session:
        try:
            existing = session.execute(
                text(
                    "SELECT id, name, filters, notify_new_matches FROM saved_searches "
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

            if req.notify_new_matches is not None:
                update_fields.append("notify_new_matches = :notify_new_matches")
                params["notify_new_matches"] = req.notify_new_matches
                if req.notify_new_matches and not existing[3]:
                    # Off -> on: the newness floor starts now. Switching off
                    # keeps the old stamp; switching on again replaces it.
                    update_fields.append("notify_enabled_at = :notify_enabled_at")
                    params["notify_enabled_at"] = _utcnow_naive()

            if "min_price_drop" in req.model_fields_set:
                update_fields.append("min_price_drop = :min_price_drop")
                params["min_price_drop"] = req.min_price_drop

            if not update_fields:
                return get_saved_search(search_id, principal)

            # update_fields entries are hardcoded literals ("name = :name",
            # "filters = :filters", ...) appended above — never user-supplied
            # column names. Plain concatenation (not an f-string) per BIN-135.
            session.execute(
                text(
                    "UPDATE saved_searches SET " + ", ".join(update_fields) + " "
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
            raise_api_error(logger, "saved_search_update_failed", exc)
