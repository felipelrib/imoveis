"""Saved-search new-match rules (v0.14-s1.9, FR-32): the pure part.

Translation of a stored search into list filters, the newness floor, the daily
window, the email text and the SQL assembly. What the SQL selects on real rows
is ``tests/integration/test_saved_search_new_matches.py``.
"""

from __future__ import annotations

import ast
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.property_list_filters import PropertyMatchFilters, build_property_where
from core.saved_search_alerts import (
    DECIDABLE_SQL,
    SAVED_SEARCH_WIRE_KEYS,
    build_record_new_matches_sql,
    cheapest_percent,
    local_window_date,
    match_filters_from_saved_search,
    newness_floor,
    record_new_matches,
    render_new_match_email,
    saved_search_is_matchable,
    window_is_due,
)

SP = "America/Sao_Paulo"  # UTC-3, no daylight saving since 2019


@pytest.mark.unit
class TestTranslation:
    def test_empty_search_matches_every_active_property(self):
        assert match_filters_from_saved_search({}) == PropertyMatchFilters()

    def test_max_price_without_price_type_leaves_the_endpoint_default(self):
        # The list builder then caps the listing type, else rent - what
        # GET /properties does for the same parameters.
        filters = match_filters_from_saved_search({"max_price": 4000, "listing_type": "sale"})
        assert filters.max_price == 4000
        assert filters.price_type is None
        _predicates, params = build_property_where(filters)
        assert params["price_type"] == "sale"
        _predicates, params = build_property_where(
            match_filters_from_saved_search({"max_price": 4000})
        )
        assert params["price_type"] == "rent"

    def test_max_price_keeps_the_stored_price_type(self):
        filters = match_filters_from_saved_search({"max_price": 900000, "price_type": "sale"})
        assert (filters.max_price, filters.price_type) == (900000, "sale")

    def test_price_type_without_max_price_is_not_sent(self):
        filters = match_filters_from_saved_search({"price_type": "sale"})
        assert filters.price_type is None
        assert filters.max_price is None

    def test_places_use_the_list_parameter_names(self):
        filters = match_filters_from_saved_search(
            {"neighborhood": "Savassi,Lourdes", "city": "Belo Horizonte"}
        )
        assert filters.neighborhood_name == "Savassi,Lourdes"
        assert filters.city_name == "Belo Horizonte"

    @pytest.mark.parametrize("listing_type", ["rent", "sale"])
    def test_listing_type_is_passed_through(self, listing_type):
        assert match_filters_from_saved_search({"listing_type": listing_type}).listing_type == listing_type

    @pytest.mark.parametrize("wire", [{}, {"listing_type": "both"}, {"listing_type": ""}])
    def test_both_or_missing_listing_type_means_no_type(self, wire):
        assert match_filters_from_saved_search(wire).listing_type is None

    def test_amenity_flags_only_when_true(self):
        on = match_filters_from_saved_search({"is_furnished": True, "accepts_pets": True})
        assert (on.is_furnished, on.accepts_pets) == (True, True)
        off = match_filters_from_saved_search({"is_furnished": False, "accepts_pets": False})
        assert (off.is_furnished, off.accepts_pets) == (None, None)

    @pytest.mark.parametrize("value", [0.25, 0.5, 1, 0.305])
    def test_percentile_inside_the_range_is_kept(self, value):
        filters = match_filters_from_saved_search({"max_price_per_m2_percentile": value})
        assert filters.max_price_per_m2_percentile == value

    @pytest.mark.parametrize("value", [0, -0.1, 1.01, None, "", "abc", True])
    def test_percentile_outside_the_range_is_dropped(self, value):
        filters = match_filters_from_saved_search({"max_price_per_m2_percentile": value})
        assert filters.max_price_per_m2_percentile is None

    def test_plain_fields_are_taken_as_stored(self):
        filters = match_filters_from_saved_search(
            {
                "min_bedrooms": 2,
                "min_parking": 1,
                "min_score": 0.6,
                "platform": "olx",
                "property_type": "apartment",
            }
        )
        assert filters == PropertyMatchFilters(
            min_bedrooms=2, min_parking=1, min_score=0.6, platform="olx", property_type="apartment"
        )

    def test_fields_the_list_endpoint_ignores_are_ignored(self):
        filters = match_filters_from_saved_search(
            {"sort_by": "price", "sort_dir": "asc", "min_price": 1000, "max_bedrooms": 3}
        )
        assert filters == PropertyMatchFilters()

    @pytest.mark.parametrize(
        "wire",
        [
            {"maxPrice": 3000, "listingType": "rent"},  # legacy camelCase blob
            {"listing_type": "rent", "neighbourhood": "Savassi"},
            {"max_total_monthly_cost": 4000},
            {"bbox": "1,2,3,4"},
        ],
    )
    def test_a_blob_with_an_unknown_key_never_fires(self, wire):
        # Reading it as "no such filter" would alert on far more than the grid lists.
        assert match_filters_from_saved_search(wire) is None
        assert saved_search_is_matchable(wire) is False

    def test_wire_keys_are_the_ones_the_api_writes(self):
        from api.saved_searches import SavedSearchFilters

        assert SAVED_SEARCH_WIRE_KEYS == set(SavedSearchFilters.model_fields)

    def test_spa_wire_keys_are_known(self):
        # frontend/src/savedSearchFilters.ts CAMEL_TO_SNAKE: what the SPA stores.
        import re
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "frontend" / "src" / "savedSearchFilters.ts"
        ).read_text(encoding="utf-8")
        table = source.split("const CAMEL_TO_SNAKE", 1)[1].split("}", 1)[0]
        spa_keys = set(re.findall(r":\s*'([a-z0-9_]+)'", table))
        assert len(spa_keys) >= 16
        assert spa_keys <= SAVED_SEARCH_WIRE_KEYS

    @pytest.mark.parametrize("q", ["varanda gourmet", "  x  "])
    def test_semantic_search_is_not_matchable(self, q):
        assert match_filters_from_saved_search({"q": q, "listing_type": "rent"}) is None
        assert saved_search_is_matchable({"q": q}) is False

    @pytest.mark.parametrize("wire", [{}, {"q": ""}, {"q": "   "}, {"q": None}])
    def test_blank_q_is_matchable(self, wire):
        assert match_filters_from_saved_search(wire) is not None
        assert saved_search_is_matchable(wire) is True

    @pytest.mark.parametrize("wire", [None, [], "{}", 3])
    def test_a_non_mapping_blob_never_fires(self, wire):
        assert match_filters_from_saved_search(wire) is None
        assert saved_search_is_matchable(wire) is False


@pytest.mark.unit
class TestNewnessFloor:
    NOW = datetime(2026, 10, 8, 12, 0, 0)

    def test_recently_enabled_search_floors_at_the_enable_moment(self):
        enabled = self.NOW - timedelta(hours=5)
        assert newness_floor(enabled) == enabled

    def test_long_enabled_search_still_floors_at_the_enable_moment(self):
        # No maximum age: a match is held until decidable, never dropped.
        enabled = self.NOW - timedelta(days=300)
        assert newness_floor(enabled) == enabled

    def test_aware_inputs_are_read_as_utc_and_returned_naive(self):
        from datetime import timezone

        enabled = datetime(2026, 10, 8, 9, 0, tzinfo=timezone(timedelta(hours=-3)))  # 12:00 UTC
        floor = newness_floor(enabled)
        assert floor == datetime(2026, 10, 8, 12, 0)
        assert floor.tzinfo is None


@pytest.mark.unit
class TestWindow:
    def test_local_date_is_the_timezone_date(self):
        # 02:00 UTC on the 9th is 23:00 on the 8th in Sao Paulo.
        assert local_window_date(datetime(2026, 10, 9, 2, 0), SP) == date(2026, 10, 8)
        assert local_window_date(datetime(2026, 10, 9, 3, 0), SP) == date(2026, 10, 9)

    def test_before_the_hour_is_not_due(self):
        # 09:59 UTC = 06:59 local.
        assert not window_is_due(
            datetime(2026, 10, 8, 9, 59), tz_name=SP, window_hour=7, last_window_on=None
        )

    def test_at_the_hour_is_due(self):
        assert window_is_due(
            datetime(2026, 10, 8, 10, 0), tz_name=SP, window_hour=7, last_window_on=None
        )

    def test_after_the_hour_is_due_so_a_late_worker_still_sends(self):
        assert window_is_due(
            datetime(2026, 10, 8, 20, 0),
            tz_name=SP,
            window_hour=7,
            last_window_on=date(2026, 10, 7),
        )

    def test_second_run_the_same_local_day_is_not_due(self):
        assert not window_is_due(
            datetime(2026, 10, 8, 11, 0),
            tz_name=SP,
            window_hour=7,
            last_window_on=date(2026, 10, 8),
        )

    def test_utc_date_change_is_not_a_new_local_day(self):
        # Sent on the 8th (local). 01:00 UTC on the 9th is still 22:00 on the 8th.
        assert not window_is_due(
            datetime(2026, 10, 9, 1, 0),
            tz_name=SP,
            window_hour=7,
            last_window_on=date(2026, 10, 8),
        )

    def test_next_local_day_waits_for_the_hour_again(self):
        last = date(2026, 10, 8)
        assert not window_is_due(
            datetime(2026, 10, 9, 5, 0), tz_name=SP, window_hour=7, last_window_on=last
        )
        assert window_is_due(
            datetime(2026, 10, 9, 10, 0), tz_name=SP, window_hour=7, last_window_on=last
        )

    def test_hour_zero_is_due_all_day(self):
        assert window_is_due(
            datetime(2026, 10, 8, 3, 0), tz_name=SP, window_hour=0, last_window_on=None
        )


def _prop(**over):
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "public_id": 42,
        "title": "Apartamento na Savassi",
        "price": 3500.0,
        "area_m2": 80.0,
        "bedrooms": 2,
        "neighborhood_name": "Savassi",
        "city": "Belo Horizonte",
        "deal_summary": "Bom preço para a região.",
        "price_per_m2_percentile_rent": 0.2001,
        "price_per_m2_percentile_sale": None,
        "available_for_rent": True,
        "available_for_sale": False,
        "primary_listing": {"listing_type": "rent", "price": 3500.0},
        "listings": [{"listing_type": "rent", "price": 3500.0}],
    }
    base.update(over)
    return base


@pytest.mark.unit
class TestCheapestPercent:
    @pytest.mark.parametrize(
        "value, expected", [(0.25, 25), (0.2001, 21), (0.07, 7), (0.0001, 1), (1.0, 100)]
    )
    def test_rounds_up_to_a_whole_percent(self, value, expected):
        assert cheapest_percent(value) == expected

    @pytest.mark.parametrize("value", [None, 0, -1, 1.5, "x"])
    def test_no_value_no_percent(self, value):
        assert cheapest_percent(value) is None


@pytest.mark.unit
class TestEmailText:
    def test_pt_br_is_the_default(self):
        subject, body = render_new_match_email(
            search_name="Savassi 2q", properties=[_prop()], app_base_url="http://localhost:5173"
        )
        assert subject == "1 imóvel novo na busca “Savassi 2q”"
        assert "Savassi 2q" in body
        assert "Apartamento na Savassi" in body
        assert "Savassi" in body
        assert "R$ 3.500/mês" in body
        assert "80 m²" in body
        assert "2 quartos" in body
        assert "Bom preço para a região." in body
        assert "entre os 21% mais baratos do bairro" in body
        assert "http://localhost:5173/properties/42" in body
        assert "Buscas salvas" in body

    def test_english(self):
        subject, body = render_new_match_email(
            search_name="Savassi 2q", properties=[_prop(), _prop(public_id=43)], locale="en"
        )
        assert subject == "2 new homes for “Savassi 2q”"
        assert "R$ 3,500/month" in body
        assert "2 bedrooms" in body
        assert "among the 21% cheapest in the neighbourhood" in body
        assert "Buscas salvas" in body
        assert "mais baratos" not in body

    def test_percentile_line_is_absent_when_the_percentile_is_null(self):
        _subject, body = render_new_match_email(
            search_name="x", properties=[_prop(price_per_m2_percentile_rent=None)]
        )
        assert "mais baratos" not in body
        assert "%" not in body

    def test_percentile_of_the_searched_type_is_the_one_read(self):
        dual = _prop(
            price_per_m2_percentile_rent=0.9,
            price_per_m2_percentile_sale=0.1,
            available_for_sale=True,
            listings=[
                {"listing_type": "rent", "price": 3500.0},
                {"listing_type": "sale", "price": 650000.0},
            ],
        )
        _subject, body = render_new_match_email(
            search_name="x", properties=[dual], listing_type="sale"
        )
        assert "entre os 10% mais baratos do bairro" in body
        assert "R$ 650.000" in body
        assert "/mês" not in body

    def test_sale_price_has_no_monthly_suffix(self):
        sale = _prop(
            primary_listing={"listing_type": "sale", "price": 500000.0},
            listings=[{"listing_type": "sale", "price": 500000.0}],
            available_for_rent=False,
            available_for_sale=True,
            price=500000.0,
            price_per_m2_percentile_rent=None,
        )
        _subject, body = render_new_match_email(search_name="x", properties=[sale])
        assert "R$ 500.000" in body
        assert "/mês" not in body

    def test_subject_is_one_line_whatever_the_name(self):
        subject, _body = render_new_match_email(
            search_name="Savassi\r\n2q\tbarato", properties=[_prop()]
        )
        assert subject == "1 imóvel novo na busca “Savassi 2q barato”"

    def test_no_link_without_a_base_url(self):
        _subject, body = render_new_match_email(search_name="x", properties=[_prop()])
        assert "/properties/" not in body
        assert "http" not in body

    def test_base_url_trailing_slash_is_not_doubled(self):
        _subject, body = render_new_match_email(
            search_name="x", properties=[_prop()], app_base_url="https://imoveis.test/"
        )
        assert "https://imoveis.test/properties/42" in body

    def test_remaining_matches_get_a_line_that_says_they_come_next(self):
        props = [_prop(public_id=i, title="Imóvel " + str(i)) for i in range(1, 4)]
        subject, body = render_new_match_email(search_name="x", properties=props, remaining=2)
        # The subject counts what this email carries.
        assert subject.startswith("3 imóveis novos")
        assert "Imóvel 3" in body
        assert "+2 nesta busca chegam no próximo aviso." in body
        _s, english = render_new_match_email(
            search_name="x", properties=props, remaining=2, locale="en"
        )
        assert "+2 more in this search arrive in the next email." in english

    def test_nothing_remaining_means_no_plus_line(self):
        props = [_prop(public_id=i) for i in range(1, 4)]
        _subject, body = render_new_match_email(search_name="x", properties=props)
        assert "+0" not in body
        assert "\n+" not in body

    def test_held_line_only_when_something_is_held(self):
        _s, none_held = render_new_match_email(search_name="x", properties=[_prop()], held=0)
        _s, some_held = render_new_match_email(search_name="x", properties=[_prop()], held=4)
        assert "em análise" not in none_held
        assert "4" in some_held and "em análise" in some_held

    def test_untitled_property_falls_back_to_its_type(self):
        _s, body = render_new_match_email(
            search_name="x", properties=[_prop(title=None, property_type="apartamento")]
        )
        assert "Apartamento" in body

    def test_missing_optional_facts_are_left_out_not_invented(self):
        bare = _prop(area_m2=None, bedrooms=None, deal_summary=None, neighborhood_name=None)
        _s, body = render_new_match_email(search_name="x", properties=[bare])
        assert "m²" not in body
        assert "quarto" not in body
        assert "None" not in body

    def test_no_threshold_wording(self):
        _s, body = render_new_match_email(search_name="x", properties=[_prop()], held=2)
        for word in ("queda", "limite", "threshold", "drop"):
            assert word not in body.lower()


@pytest.mark.unit
class TestRecordSql:
    FILTERS = PropertyMatchFilters(
        listing_type="rent",
        max_price=4000.0,
        price_type="rent",
        min_score=0.5,
        neighborhood_name="Savassi",
        max_price_per_m2_percentile=0.25,
        accepts_pets=True,
    )

    def test_sql_carries_exactly_the_shared_predicates(self):
        sql, params = build_record_new_matches_sql(self.FILTERS)
        predicates, where_params = build_property_where(self.FILTERS)
        assert "WHERE " + " AND ".join(predicates) + " AND p.first_seen >= :nm_floor" in sql
        for key, value in where_params.items():
            assert params[key] == value

    def test_sql_shape(self):
        sql, _params = build_record_new_matches_sql(self.FILTERS)
        assert sql.startswith("INSERT INTO saved_search_new_matches ")
        assert (
            "FROM properties p "
            "LEFT JOIN metrics_scoring ms ON ms.property_id = p.id "
            "LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id "
        ) in sql
        assert "AND " + DECIDABLE_SQL in sql
        assert sql.endswith("ON CONFLICT (saved_search_id, property_id) DO NOTHING")

    def test_decidable_needs_the_stamp_and_a_non_blank_verdict(self):
        assert DECIDABLE_SQL == (
            "ms.percentile_evaluated_at IS NOT NULL "
            "AND NULLIF(btrim(ms.meta->'deal_verdict'->>'verdict'), '') IS NOT NULL"
        )

    def test_matcher_parameters_cannot_collide_with_filter_parameters(self):
        _sql, where_params = build_property_where(self.FILTERS)
        assert not [k for k in where_params if k.startswith("nm_")]

    def test_record_binds_search_owner_floor_and_returns_the_inserted_count(self):
        session = MagicMock()
        session.execute.return_value.rowcount = 3
        now = datetime(2026, 10, 8, 12, 0)
        enabled = now - timedelta(hours=2)
        inserted = record_new_matches(
            session,
            search_id="5b0f6a0e-0000-0000-0000-000000000001",
            owner="default",
            filters=self.FILTERS,
            enabled_at=enabled,
            now=now,
        )
        assert inserted == 3
        statement, params = session.execute.call_args[0]
        assert "ON CONFLICT (saved_search_id, property_id) DO NOTHING" in str(statement)
        assert params["nm_search_id"] == "5b0f6a0e-0000-0000-0000-000000000001"
        assert params["nm_owner"] == "default"
        assert params["nm_floor"] == enabled
        assert params["nm_now"] == now
        assert params["max_price"] == 4000.0

    def test_record_never_reports_a_negative_count(self):
        session = MagicMock()
        session.execute.return_value.rowcount = -1
        now = datetime(2026, 10, 8, 12, 0)
        assert (
            record_new_matches(
                session,
                search_id="s",
                owner="default",
                filters=PropertyMatchFilters(),
                enabled_at=now,
                now=now,
            )
            == 0
        )


@pytest.mark.unit
class TestCorePurity:
    def test_no_adapter_api_or_lazy_imports(self):
        path = Path(__file__).resolve().parents[2] / "core" / "saved_search_alerts.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        top_level = {id(node) for node in tree.body}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            assert id(node) in top_level, "lazy import at line " + str(node.lineno)
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
            )
            for name in names:
                assert not name.startswith(("adapters", "api", "infra")), name


@pytest.mark.unit
class TestWindowClaim:
    def test_claim_stamps_the_date_and_release_restores_only_a_claimed_one(self):
        from unittest.mock import MagicMock

        from core.saved_search_alerts import claim_window, release_window

        session = MagicMock()
        claim_window(session, "s1", date(2026, 10, 8))
        release_window(session, "s1", date(2026, 10, 8), None)

        claim, release = session.execute.call_args_list
        assert "SET new_match_last_window_on = :nm_window_date" in str(claim.args[0])
        assert claim.args[1] == {"nm_search_id": "s1", "nm_window_date": date(2026, 10, 8)}
        # Only a date that is still the claimed one is given back.
        assert "AND new_match_last_window_on = :nm_window_date" in str(release.args[0])
        assert release.args[1] == {
            "nm_search_id": "s1",
            "nm_window_date": date(2026, 10, 8),
            "nm_previous": None,
        }
