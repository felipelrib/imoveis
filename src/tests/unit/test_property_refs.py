"""Unit tests for property ref parsing (public_id vs UUID)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.property_refs import is_public_id_token, parse_property_ref


@pytest.mark.unit
def test_parse_public_id_digits():
    assert is_public_id_token("316") is True
    kind, value = parse_property_ref("316")
    assert kind == "public_id"
    assert value == 316


@pytest.mark.unit
def test_parse_uuid():
    uid = str(uuid4())
    kind, value = parse_property_ref(uid)
    assert kind == "id"
    assert value == uid


@pytest.mark.unit
def test_parse_rejects_garbage():
    with pytest.raises(HTTPException) as exc:
        parse_property_ref("not-a-ref")
    assert exc.value.status_code == 400
