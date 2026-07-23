"""Unit tests for owner-scoped favourites, saved searches, and watchlist (BIN-45)."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app
from infra.config import AuthConfig, get_config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _auth_config(
    *,
    api_key: str = "test-valid-key",
    principal_id: str = "tenant-a",
) -> AuthConfig:
    return AuthConfig(
        api_key=api_key,
        jwt_secret="test-jwt-secret",
        principal_id=principal_id,
        admin_user="admin",
        admin_pass="admin",
    )


def _patch_auth(monkeypatch: pytest.MonkeyPatch, auth: AuthConfig) -> None:
    cfg = MagicMock()
    cfg.auth = auth
    monkeypatch.setattr("api.auth.get_config", lambda: cfg)
    monkeypatch.setattr("infra.config.get_config", lambda: cfg)


PROTECTED_GETS = (
    "/favourites",
    "/saved-searches",
    "/watchlist",
    f"/favourites/check/{uuid4()}",
    f"/watchlist/check/{uuid4()}",
)


@pytest.mark.unit
@pytest.mark.parametrize("path", PROTECTED_GETS)
def test_personalization_rejects_missing_credential(
    monkeypatch: pytest.MonkeyPatch, path: str
):
    _patch_auth(monkeypatch, _auth_config())
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(path)
    assert response.status_code == 401


@pytest.mark.unit
@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("post", "/favourites", {"json": {}}),
        ("post", "/saved-searches", {"json": {}}),
        ("post", "/watchlist", {"json": {}}),
        ("delete", f"/favourites/{uuid4()}", {}),
        ("delete", f"/saved-searches/{uuid4()}", {}),
        ("delete", f"/watchlist/{uuid4()}", {}),
    ],
)
def test_personalization_mutations_reject_missing_credential(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str, kwargs: dict
):
    _patch_auth(monkeypatch, _auth_config())
    client = TestClient(app, raise_server_exceptions=False)
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 401


class _FakeResult:
    def __init__(self, *, rows=None, scalar=None, rowcount=1):
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._scalar


class _OwnerScopedSession:
    """In-memory session that enforces owner filters like the real SQL."""

    def __init__(self):
        self.favourites: list[dict] = []
        self.saved_searches: list[dict] = []
        self.watchlist: list[dict] = []
        self.properties: set[str] = set()
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def execute(self, statement, params=None):
        params = params or {}
        sql = str(statement).lower()

        if "from properties" in sql and "select id" in sql:
            pid = params.get("pid")
            if pid in self.properties:
                return _FakeResult(rows=[(pid,)])
            return _FakeResult(rows=[])

        if "count(*) from favourites" in sql:
            owner = params["owner"]
            n = sum(1 for r in self.favourites if r["owner"] == owner)
            return _FakeResult(scalar=n)

        if "from favourites f" in sql and "where f.owner" in sql:
            owner = params["owner"]
            rows = [
                (
                    r["id"],
                    r["property_id"],
                    r["created_at"],
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
                for r in self.favourites
                if r["owner"] == owner
            ]
            return _FakeResult(rows=rows)

        if "insert into favourites" in sql:
            owner = params["owner"]
            pid = params["pid"]
            if any(
                r["owner"] == owner and r["property_id"] == pid
                for r in self.favourites
            ):
                return _FakeResult(rowcount=0)
            self.favourites.append(
                {
                    "id": params["id"],
                    "property_id": pid,
                    "owner": owner,
                    "created_at": params["now"],
                }
            )
            return _FakeResult(rowcount=1)

        if "delete from favourites" in sql:
            before = len(self.favourites)
            self.favourites = [
                r
                for r in self.favourites
                if not (
                    r["property_id"] == params["pid"]
                    and r["owner"] == params["owner"]
                )
            ]
            return _FakeResult(rowcount=before - len(self.favourites))

        if "from favourites" in sql and "where property_id" in sql:
            match = next(
                (
                    r
                    for r in self.favourites
                    if r["property_id"] == params["pid"]
                    and r["owner"] == params["owner"]
                ),
                None,
            )
            if match is None:
                return _FakeResult(rows=[])
            return _FakeResult(rows=[(match["id"], match["created_at"])])

        if "delete from saved_searches" in sql:
            before = len(self.saved_searches)
            self.saved_searches = [
                r
                for r in self.saved_searches
                if not (
                    r["id"] == params["sid"] and r["owner"] == params["owner"]
                )
            ]
            return _FakeResult(rowcount=before - len(self.saved_searches))

        if "insert into saved_searches" in sql:
            self.saved_searches.append(
                {
                    "id": params["id"],
                    "name": params["name"],
                    "filters": {},
                    "owner": params["owner"],
                    "created_at": params["now"],
                }
            )
            return _FakeResult(rowcount=1)

        if "count(*) from saved_searches" in sql:
            owner = params["owner"]
            n = sum(1 for r in self.saved_searches if r["owner"] == owner)
            return _FakeResult(scalar=n)

        if "from saved_searches where owner" in sql and "order by" in sql:
            owner = params["owner"]
            rows = [
                (r["id"], r["name"], r["filters"], r["created_at"])
                for r in self.saved_searches
                if r["owner"] == owner
            ]
            return _FakeResult(rows=rows)

        if "select id, name, filters" in sql and "from saved_searches" in sql:
            match = next(
                (
                    r
                    for r in self.saved_searches
                    if r["id"] == params["sid"] and r["owner"] == params["owner"]
                ),
                None,
            )
            if match is None:
                return _FakeResult(rows=[])
            return _FakeResult(
                rows=[
                    (
                        match["id"],
                        match["name"],
                        match["filters"],
                        match.get("created_at"),
                    )
                ]
            )

        if "update saved_searches" in sql:
            match = next(
                (
                    r
                    for r in self.saved_searches
                    if r["id"] == params["sid"] and r["owner"] == params["owner"]
                ),
                None,
            )
            if match is None:
                return _FakeResult(rowcount=0)
            if "name" in params:
                match["name"] = params["name"]
            if "filters" in params:
                match["filters"] = {}
            return _FakeResult(rowcount=1)

        if "from watchlist where owner" in sql and "order by" in sql:
            owner = params["owner"]
            rows = [
                (
                    r["id"],
                    r["property_id"],
                    r["min_drop_pct"],
                    r.get("last_notified_price"),
                    r["created_at"],
                )
                for r in self.watchlist
                if r["owner"] == owner
            ]
            return _FakeResult(rows=rows)

        if "insert into watchlist" in sql:
            owner = params["owner"]
            pid = params["pid"]
            if any(
                r["owner"] == owner and r["property_id"] == pid
                for r in self.watchlist
            ):
                return _FakeResult(rowcount=0)
            self.watchlist.append(
                {
                    "id": params["id"],
                    "property_id": pid,
                    "owner": owner,
                    "min_drop_pct": params["min_drop"],
                    "created_at": params["now"],
                }
            )
            return _FakeResult(rowcount=1)

        if "delete from watchlist" in sql:
            before = len(self.watchlist)
            self.watchlist = [
                r
                for r in self.watchlist
                if not (
                    r["property_id"] == params["pid"]
                    and r["owner"] == params["owner"]
                )
            ]
            return _FakeResult(rowcount=before - len(self.watchlist))

        if "from watchlist where property_id" in sql:
            match = next(
                (
                    r
                    for r in self.watchlist
                    if r["property_id"] == params["pid"]
                    and r["owner"] == params["owner"]
                ),
                None,
            )
            if match is None:
                return _FakeResult(rows=[])
            return _FakeResult(
                rows=[
                    (
                        match["id"],
                        match["min_drop_pct"],
                        match.get("last_notified_price"),
                    )
                ]
            )

        raise AssertionError(f"Unhandled SQL in fake session: {sql}")


@pytest.fixture
def owner_db(monkeypatch: pytest.MonkeyPatch):
    store = _OwnerScopedSession()
    monkeypatch.setattr("api.favourites.SessionLocal", lambda: store)
    monkeypatch.setattr("api.saved_searches.SessionLocal", lambda: store)
    monkeypatch.setattr("api.watchlist.SessionLocal", lambda: store)
    return store


def _client_for(monkeypatch: pytest.MonkeyPatch, principal_id: str, api_key: str):
    _patch_auth(monkeypatch, _auth_config(api_key=api_key, principal_id=principal_id))
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.unit
def test_favourite_scoped_to_principal(monkeypatch: pytest.MonkeyPatch, owner_db):
    prop_id = str(uuid4())
    owner_db.properties.add(prop_id)

    client_a = _client_for(monkeypatch, "alice", "key-a")
    add = client_a.post(
        "/favourites",
        headers={"X-API-Key": "key-a"},
        json={"property_id": prop_id},
    )
    assert add.status_code == 201, add.text
    assert owner_db.favourites[0]["owner"] == "alice"

    listed = client_a.get("/favourites", headers={"X-API-Key": "key-a"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    client_b = _client_for(monkeypatch, "bob", "key-b")
    other = client_b.get("/favourites", headers={"X-API-Key": "key-b"})
    assert other.status_code == 200
    assert other.json()["total"] == 0

    denied = client_b.delete(
        f"/favourites/{prop_id}", headers={"X-API-Key": "key-b"}
    )
    assert denied.status_code == 404
    assert len(owner_db.favourites) == 1


@pytest.mark.unit
def test_saved_search_scoped_to_principal(monkeypatch: pytest.MonkeyPatch, owner_db):
    client_a = _client_for(monkeypatch, "alice", "key-a")
    created = client_a.post(
        "/saved-searches",
        headers={"X-API-Key": "key-a"},
        json={"name": "BH rentals", "filters": {"min_price": 1000}},
    )
    assert created.status_code == 201, created.text
    search_id = created.json()["id"]
    assert owner_db.saved_searches[0]["owner"] == "alice"

    client_b = _client_for(monkeypatch, "bob", "key-b")
    assert (
        client_b.get(
            f"/saved-searches/{search_id}", headers={"X-API-Key": "key-b"}
        ).status_code
        == 404
    )
    assert (
        client_b.delete(
            f"/saved-searches/{search_id}", headers={"X-API-Key": "key-b"}
        ).status_code
        == 404
    )
    assert len(owner_db.saved_searches) == 1


@pytest.mark.unit
def test_watchlist_scoped_to_principal(monkeypatch: pytest.MonkeyPatch, owner_db):
    prop_id = str(uuid4())
    owner_db.properties.add(prop_id)

    client_a = _client_for(monkeypatch, "alice", "key-a")
    add = client_a.post(
        "/watchlist",
        headers={"X-API-Key": "key-a"},
        json={"property_id": prop_id, "min_drop_pct": 7.5},
    )
    assert add.status_code == 201, add.text
    assert "user_id" not in add.json()
    assert owner_db.watchlist[0]["owner"] == "alice"

    check = client_a.get(
        f"/watchlist/check/{prop_id}", headers={"X-API-Key": "key-a"}
    )
    assert check.status_code == 200
    assert check.json()["watched"] is True

    client_b = _client_for(monkeypatch, "bob", "key-b")
    assert (
        client_b.get("/watchlist", headers={"X-API-Key": "key-b"}).json() == []
    )
    assert (
        client_b.get(
            f"/watchlist/check/{prop_id}", headers={"X-API-Key": "key-b"}
        ).json()["watched"]
        is False
    )
    assert (
        client_b.delete(
            f"/watchlist/{prop_id}", headers={"X-API-Key": "key-b"}
        ).status_code
        == 404
    )
