"""Parse and resolve property references (sequential public_id or UUID PK)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


def is_public_id_token(value: str) -> bool:
    return value.isdigit()


def parse_property_ref(raw: str) -> tuple[str, Any]:
    """Return (``public_id``|``id``, value) for a path/query/body property reference."""
    token = (raw or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Empty property id")
    if is_public_id_token(token):
        return "public_id", int(token)
    try:
        uuid.UUID(token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid property id: {token}") from exc
    return "id", token


def resolve_property_uuid(session: Session, raw: str) -> str:
    """Resolve public_id or UUID to the properties.id UUID string.

    Raises HTTPException 404 when the property does not exist.
    """
    key_kind, key_value = parse_property_ref(raw)
    if key_kind == "public_id":
        row = session.execute(
            text("SELECT id FROM properties WHERE public_id = :id"),
            {"id": key_value},
        ).fetchone()
    else:
        row = session.execute(
            text("SELECT id FROM properties WHERE id = :id"),
            {"id": key_value},
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return str(row[0])
