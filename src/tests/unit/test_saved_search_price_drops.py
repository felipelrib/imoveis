"""The per-search price-drop rule (v0.14-s1.10, FR-32, UX-DR13): pure parts.

The rule (``drop_amount``), the per-Property selection (``select_drops``), the
shape of the candidate statement and the email text. What the statement
returns on Postgres is ``tests/integration/test_saved_search_price_drops.py``.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from core.property_list_filters import PropertyMatchFilters, build_property_where
from core.saved_search_alerts import DECIDABLE_SQL, PROPERTIES_FROM_JOIN
from core.saved_search_price_drops import (
    MIN_DROP,
    build_drop_candidates_sql,
    claim_drop_window,
    collect_drop_candidates,
    drop_amount,
    load_drop_properties,
    record_drop_alerts,
    release_drop_window,
    render_price_drop_email,
    select_drops,
)

pytestmark = pytest.mark.unit

P1 = "11111111-0000-0000-0000-000000000001"
P2 = "22222222-0000-0000-0000-000000000002"
P3 = "33333333-0000-0000-0000-000000000003"
L1 = "aaaaaaaa-0000-0000-0000-000000000001"
L2 = "bbbbbbbb-0000-0000-0000-000000000002"
L3 = "cccccccc-0000-0000-0000-000000000003"
SEARCH = "dddddddd-0000-0000-0000-000000000004"
FLOOR = datetime(2026, 10, 1, 12, 0)
NOW = datetime(2026, 10, 8, 15, 0)


# ---------------------------------------------------------------------------
# drop_amount
# ---------------------------------------------------------------------------


class TestDropAmount:
    def test_at_the_threshold_is_a_drop(self):
        assert drop_amount(3240, 3140, 100) == 100.0

    def test_above_the_threshold(self):
        assert drop_amount(3240, 3000, 100) == 240.0

    def test_below_the_threshold_is_not(self):
        assert drop_amount(3240, 3200, 100) is None
        assert drop_amount(3240, 3140.01, 100) is None

    def test_threshold_zero_means_any_drop_but_more_than_nothing(self):
        assert drop_amount(3240, 3239, 0) == 1.0
        assert drop_amount(3240, 3239.99, 0) == MIN_DROP
        assert drop_amount(3240, 3240, 0) is None

    def test_centavo_noise_is_not_a_drop(self):
        # Float residue below one centavo is the same price.
        assert drop_amount(3240.0, 3239.996, 0) is None
        assert drop_amount(0.1 + 0.2, 0.3, 0) is None

    def test_the_amount_is_rounded_to_centavos(self):
        assert drop_amount(1000.10, 899.90, 100) == 100.2
        # 100.1 - 0.1 is 99.99999999999999 as floats: still a drop of 100.
        assert drop_amount(100.1, 0.1, 100) == 100.0

    def test_a_price_rise_is_not_a_drop(self):
        assert drop_amount(3000, 3240, 0) is None

    @pytest.mark.parametrize(
        ("reference", "current", "threshold"),
        [
            (0, 100, 0),
            (-5, 100, 0),
            (3240, 0, 0),
            (3240, -1, 0),
            (3240, 3000, -1),
        ],
    )
    def test_non_positive_prices_and_negative_thresholds(self, reference, current, threshold):
        assert drop_amount(reference, current, threshold) is None

    @pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), "3240", True])
    def test_anything_that_is_not_a_finite_number(self, bad):
        assert drop_amount(bad, 3000, 100) is None
        assert drop_amount(3240, bad, 100) is None
        assert drop_amount(3240, 3000, bad) is None


# ---------------------------------------------------------------------------
# select_drops
# ---------------------------------------------------------------------------


def _candidate(property_id, listing_id, reference, current, *, listing_type="rent", platform="olx"):
    return {
        "property_id": property_id,
        "listing_id": listing_id,
        "listing_type": listing_type,
        "platform": platform,
        "current_price": current,
        "reference_price": reference,
    }


class TestSelectDrops:
    def test_keeps_only_what_the_rule_accepts_and_adds_the_drop(self):
        rows = [
            _candidate(P1, L1, 3240, 3000),
            _candidate(P2, L2, 3240, 3200),  # below the threshold
            _candidate(P3, L3, None, 3000),  # no earlier price known
        ]

        drops = select_drops(rows, 100)

        assert [d["property_id"] for d in drops] == [P1]
        assert drops[0]["drop"] == 240.0
        assert drops[0]["listing_id"] == L1
        assert drops[0]["reference_price"] == 3240
        assert drops[0]["current_price"] == 3000
        assert drops[0]["platform"] == "olx"
        assert drops[0]["listing_type"] == "rent"

    def test_one_per_property_the_largest_drop(self):
        rows = [
            _candidate(P1, L1, 3240, 3100),  # 140
            _candidate(P1, L2, 3500, 3200),  # 300
        ]

        drops = select_drops(rows, 100)

        assert len(drops) == 1
        assert drops[0]["listing_id"] == L2
        assert drops[0]["drop"] == 300.0

    def test_equal_drops_prefer_the_lower_current_price_then_the_listing_id(self):
        lower_price = select_drops(
            [_candidate(P1, L1, 3300, 3100), _candidate(P1, L2, 3200, 3000)], 100
        )
        assert lower_price[0]["listing_id"] == L2

        same_price = select_drops(
            [_candidate(P1, L2, 3200, 3000), _candidate(P1, L1, 3200, 3000)], 100
        )
        assert same_price[0]["listing_id"] == L1

    def test_ordered_by_drop_descending_then_property_id(self):
        rows = [
            _candidate(P2, L2, 3000, 2800),  # 200
            _candidate(P3, L3, 3000, 2500),  # 500
            _candidate(P1, L1, 3000, 2800),  # 200
        ]

        drops = select_drops(rows, 100)

        assert [d["property_id"] for d in drops] == [P3, P1, P2]

    def test_ids_are_returned_as_strings_and_the_input_is_left_alone(self):
        import uuid

        row = _candidate(uuid.UUID(P1), uuid.UUID(L1), 3240, 3000)
        before = dict(row)

        drops = select_drops([row], 100)

        assert drops[0]["property_id"] == P1
        assert drops[0]["listing_id"] == L1
        assert row == before

    def test_nothing_in_nothing_out(self):
        assert select_drops([], 100) == []


# ---------------------------------------------------------------------------
# Candidate statement
# ---------------------------------------------------------------------------

_FILTERS = PropertyMatchFilters(
    platform="olx",
    min_score=0.4,
    max_price=4000,
    price_type="rent",
    min_bedrooms=2,
    min_parking=1,
    neighborhood_name="Savassi,Lourdes",
    city_name="Belo Horizonte",
    listing_type="rent",
    property_type="apartment",
    is_furnished=True,
    accepts_pets=True,
    max_price_per_m2_percentile=0.5,
)


def _flat(sql: str) -> str:
    return " ".join(sql.split())


class TestCandidateSql:
    def test_carries_every_predicate_of_the_list_where(self):
        predicates, params = build_property_where(_FILTERS)
        sql, bound = build_drop_candidates_sql(_FILTERS, listing_type="rent")

        assert predicates[0] == "p.active = true"
        for predicate in predicates:
            assert predicate in sql, predicate
        for key, value in params.items():
            assert bound[key] == value

    def test_reads_the_list_tables_joined_to_the_listing(self):
        sql, _bound = build_drop_candidates_sql(PropertyMatchFilters(), listing_type=None)

        assert PROPERTIES_FROM_JOIN in sql
        assert "JOIN property_listings dl ON dl.property_id = p.id" in sql
        # ``pl`` is the alias of the shared WHERE's own subqueries.
        assert " pl ON " not in sql

    def test_only_decidable_properties_and_active_priced_listings(self):
        sql, _bound = build_drop_candidates_sql(PropertyMatchFilters(), listing_type=None)

        assert DECIDABLE_SQL in sql
        assert "dl.active = true" in sql
        assert "dl.price > 0" in sql

    def test_candidates_are_bounded_by_price_changes_after_the_floor(self):
        sql, _bound = build_drop_candidates_sql(PropertyMatchFilters(), listing_type=None)
        flat = _flat(sql)

        assert (
            "dl.id IN (SELECT ph.property_listing_id FROM price_history ph "
            "WHERE ph.end_ts > :pd_floor AND ph.property_listing_id IS NOT NULL)"
        ) in flat

    def test_the_watchlist_is_not_read(self):
        """A price the watchlist path once stamped never hides a drop.

        ``watchlist.last_notified_price`` is written when that path enqueues
        an alert (before its debounce and its delivery) and is kept through a
        later rise, so a Listing falling back to a stamped price would be
        announced by neither path.
        """
        for filters, listing_type in (
            (PropertyMatchFilters(), None),
            (_FILTERS, "rent"),
        ):
            sql, bound = build_drop_candidates_sql(filters, listing_type=listing_type)
            assert "watchlist" not in sql
            assert "last_notified_price" not in sql
            assert "pd_owner" not in bound

    def test_reference_is_last_alert_then_price_at_the_floor_then_first_after(self):
        sql, _bound = build_drop_candidates_sql(PropertyMatchFilters(), listing_type=None)
        flat = _flat(sql)

        last_alert = flat.index("FROM saved_search_price_drop_alerts a")
        at_floor = flat.index("ph.start_ts <= :pd_floor")
        first_after = flat.index("ph.start_ts > :pd_floor")
        assert flat.index("COALESCE(") < last_alert < at_floor < first_after
        assert "a.saved_search_id = CAST(:pd_search_id AS uuid)" in flat
        assert "a.property_listing_id = dl.id" in flat
        assert "a.sent_at >= :pd_floor" in flat
        assert "(ph.end_ts IS NULL OR ph.end_ts > :pd_floor)" in flat
        # A Listing is compared with its own history only.
        assert flat.count("ph.property_listing_id = dl.id") == 2
        assert flat.count("ph.property_id = dl.property_id") == 2
        # The threshold is applied by select_drops, not in SQL.
        assert "threshold" not in flat
        assert "min_price_drop" not in flat

    @pytest.mark.parametrize("listing_type", ["rent", "sale"])
    def test_listing_type_predicate_for_a_typed_search(self, listing_type):
        sql, bound = build_drop_candidates_sql(PropertyMatchFilters(), listing_type=listing_type)

        assert "dl.listing_type = :pd_listing_type" in sql
        assert bound["pd_listing_type"] == listing_type

    @pytest.mark.parametrize("listing_type", [None, "both", "", "RENT"])
    def test_no_listing_type_predicate_otherwise(self, listing_type):
        sql, bound = build_drop_candidates_sql(PropertyMatchFilters(), listing_type=listing_type)

        assert ":pd_listing_type" not in sql
        assert "pd_listing_type" not in bound

    def test_a_price_cap_also_holds_for_the_listing_that_is_announced(self):
        capped = PropertyMatchFilters(max_price=3000, price_type="rent")
        sql, bound = build_drop_candidates_sql(capped, listing_type=None)

        assert "dl.listing_type = :price_type AND dl.price <= :max_price" in sql
        assert bound["max_price"] == 3000
        assert bound["price_type"] == "rent"

        sql, _bound = build_drop_candidates_sql(PropertyMatchFilters(), listing_type="rent")
        assert "dl.price <= :max_price" not in sql

    @pytest.mark.parametrize("listing_type", ["rent", None])
    def test_the_cap_holds_for_the_listing_when_the_search_type_agrees_or_is_absent(
        self, listing_type
    ):
        capped = PropertyMatchFilters(listing_type=listing_type, max_price=3000, price_type="rent")
        sql, _bound = build_drop_candidates_sql(capped, listing_type=listing_type)

        assert "dl.listing_type = :price_type AND dl.price <= :max_price" in sql

    def test_a_search_for_one_type_capped_on_the_other_announces_its_own_type(self):
        """Sale Listings of homes that also rent for at most R$ 3.000.

        The cap is about the rent Listing and stays in the shared WHERE. Held
        against the announced Listing too, it would ask for a Listing that is
        sale and rent at once: the search would never alert.
        """
        crossed = PropertyMatchFilters(listing_type="sale", max_price=3000, price_type="rent")
        sql, bound = build_drop_candidates_sql(crossed, listing_type="sale")

        assert "dl.listing_type = :pd_listing_type" in sql
        assert bound["pd_listing_type"] == "sale"
        assert "dl.listing_type = :price_type" not in sql
        assert "dl.price <= :max_price" not in sql
        # The Property-level cap of the grid is still there.
        assert "pl.listing_type = :price_type" in sql
        assert bound["price_type"] == "rent"
        assert bound["max_price"] == 3000

    def test_a_platform_filter_also_holds_for_the_listing_that_is_announced(self):
        sql, bound = build_drop_candidates_sql(
            PropertyMatchFilters(platform="olx"), listing_type=None
        )
        assert "dl.platform = :platform" in sql
        assert bound["platform"] == "olx"

        sql, _bound = build_drop_candidates_sql(PropertyMatchFilters(), listing_type=None)
        assert "dl.platform = :platform" not in sql

    def test_no_new_parameter_collides_with_the_shared_where(self):
        _predicates, shared = build_property_where(_FILTERS)
        sql, _bound = build_drop_candidates_sql(_FILTERS, listing_type="rent")

        names = set(re.findall(r"(?<![:\w]):([a-z_][a-z0-9_]*)", sql))
        own = names - set(shared)
        assert own == {"pd_floor", "pd_search_id", "pd_listing_type"}
        assert not any(name.startswith("pd_") for name in shared)

    def test_collect_binds_the_search_and_a_naive_floor(self):
        from datetime import timezone

        session = MagicMock()
        session.execute.return_value.mappings.return_value.fetchall.return_value = [
            {"property_id": P1, "listing_id": L1}
        ]

        rows = collect_drop_candidates(
            session,
            search_id=SEARCH,
            filters=PropertyMatchFilters(min_bedrooms=2),
            listing_type="sale",
            floor=FLOOR.replace(tzinfo=timezone.utc),
        )

        assert rows == [{"property_id": P1, "listing_id": L1}]
        statement, bound = session.execute.call_args.args
        assert "dl.listing_type = :pd_listing_type" in str(statement)
        assert bound == {
            "min_bedrooms": 2,
            "pd_search_id": SEARCH,
            "pd_floor": FLOOR,
            "pd_listing_type": "sale",
        }


# ---------------------------------------------------------------------------
# Writes: window and alert rows
# ---------------------------------------------------------------------------


class TestWrites:
    def test_claim_and_release_use_the_drop_window_column_only(self):
        session = MagicMock()
        day = date(2026, 10, 8)

        claim_drop_window(session, SEARCH, day)
        statement, bound = session.execute.call_args.args
        assert "SET price_drop_last_window_on = :pd_window_date" in str(statement)
        assert "new_match_last_window_on" not in str(statement)
        assert bound == {"pd_search_id": SEARCH, "pd_window_date": day}

        release_drop_window(session, SEARCH, day, date(2026, 10, 7))
        statement, bound = session.execute.call_args.args
        # A no-op when the date is no longer the claimed one.
        assert "AND price_drop_last_window_on = :pd_window_date" in str(statement)
        assert bound == {
            "pd_search_id": SEARCH,
            "pd_window_date": day,
            "pd_previous": date(2026, 10, 7),
        }

    def test_record_inserts_one_row_per_drop_through_the_search_and_the_listing(self):
        session = MagicMock()
        session.execute.return_value.rowcount = 1
        drops = select_drops(
            [_candidate(P1, L1, 3240, 3000), _candidate(P2, L2, 5000, 4500)], 100
        )

        recorded = record_drop_alerts(
            session, search_id=SEARCH, owner="default", drops=drops, threshold=100, now=NOW
        )

        assert recorded == 2
        assert session.execute.call_count == 2
        statement, bound = session.execute.call_args_list[0].args
        flat = _flat(str(statement))
        assert flat.startswith("INSERT INTO saved_search_price_drop_alerts")
        # A search or Listing deleted during the send inserts nothing.
        assert "FROM saved_searches s JOIN property_listings dl ON dl.id = CAST(:pd_listing_id AS uuid)" in flat
        assert "WHERE s.id = CAST(:pd_search_id AS uuid)" in flat
        assert bound == {
            "pd_search_id": SEARCH,
            "pd_listing_id": L2,
            "pd_owner": "default",
            "pd_listing_type": "rent",
            "pd_platform": "olx",
            "pd_reference_price": 5000.0,
            "pd_new_price": 4500.0,
            "pd_threshold": 100.0,
            "pd_now": NOW,
        }

    def test_record_counts_only_what_was_inserted(self):
        session = MagicMock()
        session.execute.return_value.rowcount = 0
        drops = select_drops([_candidate(P1, L1, 3240, 3000)], 100)

        assert (
            record_drop_alerts(
                session, search_id=SEARCH, owner="default", drops=drops, threshold=100, now=NOW
            )
            == 0
        )

    def test_load_properties_maps_rows_by_id_and_adds_the_stored_type(self):
        session = MagicMock()
        session.execute.return_value.mappings.return_value.fetchall.return_value = []

        assert load_drop_properties(session, [P1, P2]) == {}
        statement, bound = session.execute.call_args.args
        assert "p.id = ANY(CAST(:pd_property_ids AS uuid[]))" in str(statement)
        assert bound == {"pd_property_ids": [P1, P2]}

        session.execute.reset_mock()
        assert load_drop_properties(session, []) == {}
        session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Email text
# ---------------------------------------------------------------------------


def _drop(property_id, reference, current, drop, *, listing_type="rent", platform="quintoandar"):
    return {
        "property_id": property_id,
        "listing_id": L1,
        "listing_type": listing_type,
        "platform": platform,
        "current_price": current,
        "reference_price": reference,
        "drop": drop,
    }


_PROPS = {
    P1: {
        "id": P1,
        "public_id": 42,
        "title": "Apartamento Savassi",
        "neighborhood_name": "Savassi",
        "city": "Belo Horizonte",
        "property_type": "apartamento",
    },
    P2: {
        "id": P2,
        "public_id": 43,
        "title": "  ",
        "neighborhood_name": None,
        "city": None,
        "property_type": "casa",
    },
    P3: {"id": P3, "public_id": None, "title": None, "property_type": None},
}


class TestEmail:
    def test_pt_br_block_states_the_drop_and_the_threshold(self):
        subject, body = render_price_drop_email(
            search_name="Savassi 2q",
            drops=[_drop(P1, 3240, 3000, 240)],
            properties=_PROPS,
            threshold=100,
        )

        assert subject == "1 queda de preço na busca “Savassi 2q”"
        lines = body.split("\n")
        assert "1 imóvel desta busca baixou de preço." in lines
        start = lines.index("1. Apartamento Savassi")
        assert lines[start + 1 : start + 4] == [
            "   Savassi, Belo Horizonte",
            "   R$ 3.240/mês → R$ 3.000/mês · QuintoAndar",
            "   queda de R$ 240 — seu mínimo: R$ 100",
        ]
        assert lines[-1] == (
            "Você recebe este e-mail porque os avisos estão ligados para esta busca, "
            "com queda mínima de R$ 100. Para mudar, abra Buscas salvas."
        )
        assert "http" not in body
        assert "+" not in body

    def test_plural_subject_and_intro(self):
        subject, body = render_price_drop_email(
            search_name="Savassi 2q",
            drops=[_drop(P1, 3240, 3000, 240), _drop(P2, 500000, 480000, 20000, listing_type="sale")],
            properties=_PROPS,
            threshold=100,
        )

        assert subject == "2 quedas de preço na busca “Savassi 2q”"
        assert "2 imóveis desta busca baixaram de preço." in body

    def test_per_month_only_for_rent(self):
        _subject, body = render_price_drop_email(
            search_name="Casas",
            drops=[_drop(P2, 500000, 480000, 20000, listing_type="sale", platform=None)],
            properties=_PROPS,
            threshold=5000,
        )

        assert "   R$ 500.000 → R$ 480.000" in body.split("\n")
        assert "/mês" not in body
        assert "queda de R$ 20.000 — seu mínimo: R$ 5.000" in body

    def test_title_falls_back_to_the_stored_type_then_to_a_word(self):
        _subject, body = render_price_drop_email(
            search_name="x",
            drops=[_drop(P2, 3240, 3000, 240), _drop(P3, 3240, 3000, 240)],
            properties=_PROPS,
            threshold=100,
        )

        lines = body.split("\n")
        assert "1. Casa" in lines
        assert "2. Imóvel" in lines
        # No place stored: the price line follows the title.
        assert lines[lines.index("1. Casa") + 1].startswith("   R$ 3.240/mês")

    def test_decimals_only_when_the_value_has_centavos(self):
        _subject, body = render_price_drop_email(
            search_name="x",
            drops=[_drop(P1, 1500.5, 1234.5, 266)],
            properties=_PROPS,
            threshold=100.5,
        )

        assert "R$ 1.500,50/mês → R$ 1.234,50/mês" in body
        assert "queda de R$ 266 — seu mínimo: R$ 100,50" in body

    def test_threshold_zero_is_stated_as_zero(self):
        _subject, body = render_price_drop_email(
            search_name="x",
            drops=[_drop(P1, 3240, 3239, 1)],
            properties=_PROPS,
            threshold=0,
        )

        assert "queda de R$ 1 — seu mínimo: R$ 0" in body
        assert "com queda mínima de R$ 0." in body

    def test_english(self):
        subject, body = render_price_drop_email(
            search_name="Savassi 2q",
            drops=[_drop(P1, 3240.5, 3000, 240.5), _drop(P3, 1234567, 1200000, 34567, listing_type="sale")],
            properties=_PROPS,
            threshold=100,
            remaining=2,
            locale="en",
        )

        assert subject == "2 price drops in “Savassi 2q”"
        assert "2 homes in this search dropped in price." in body
        assert "R$ 3,240.50/month → R$ 3,000/month · QuintoAndar" in body
        assert "drop of R$ 240.50 — your minimum: R$ 100" in body
        assert "R$ 1,234,567 → R$ 1,200,000" in body
        assert "2. Home" in body.split("\n")
        assert "+2 more in this search arrive in the next email." in body
        assert "with a minimum drop of R$ 100" in body

        single, _body = render_price_drop_email(
            search_name="Savassi 2q",
            drops=[_drop(P1, 3240, 3000, 240)],
            properties=_PROPS,
            threshold=100,
            locale="en",
        )
        assert single == "1 price drop in “Savassi 2q”"

    def test_remaining_line(self):
        _subject, body = render_price_drop_email(
            search_name="x",
            drops=[_drop(P1, 3240, 3000, 240)],
            properties=_PROPS,
            threshold=100,
            remaining=5,
        )

        assert "+5 nesta busca chegam no próximo aviso." in body.split("\n")

    def test_link_only_with_a_base_url_and_a_public_id(self):
        _subject, body = render_price_drop_email(
            search_name="x",
            drops=[_drop(P1, 3240, 3000, 240), _drop(P3, 3240, 3000, 240)],
            properties=_PROPS,
            threshold=100,
            app_base_url="http://imoveis.test/",
        )

        assert "   http://imoveis.test/properties/42" in body.split("\n")
        assert body.count("http://") == 1

    def test_subject_stays_on_one_line(self):
        subject, body = render_price_drop_email(
            search_name="Savassi\r\n  2q\tBcc: x@example.test",
            drops=[_drop(P1, 3240, 3000, 240)],
            properties=_PROPS,
            threshold=100,
        )

        assert subject == "1 queda de preço na busca “Savassi 2q Bcc: x@example.test”"
        assert "\n" not in subject and "\r" not in subject
        assert body

    def test_unknown_locale_falls_back_to_pt_br(self):
        subject, _body = render_price_drop_email(
            search_name="x",
            drops=[_drop(P1, 3240, 3000, 240)],
            properties=_PROPS,
            threshold=100,
            locale="fr",
        )

        assert subject == "1 queda de preço na busca “x”"

    def test_a_drop_whose_property_was_not_loaded_is_left_out(self):
        subject, body = render_price_drop_email(
            search_name="x",
            drops=[_drop("99999999-0000-0000-0000-000000000009", 3240, 3000, 240), _drop(P1, 3240, 3000, 240)],
            properties=_PROPS,
            threshold=100,
        )

        assert subject == "1 queda de preço na busca “x”"
        assert "1. Apartamento Savassi" in body.split("\n")


class TestDropsToRecord:
    """Every Listing of an emailed Property that fell is recorded with it."""

    @staticmethod
    def _row(property_id, listing_id, reference, current):
        return {
            "property_id": property_id,
            "listing_id": listing_id,
            "listing_type": "rent",
            "platform": "olx",
            "current_price": current,
            "reference_price": reference,
        }

    def test_the_other_listing_that_fell_is_recorded_too(self):
        from core.saved_search_price_drops import drops_to_record

        candidates = [
            self._row("p1", "l1", 3240, 3100),  # 140
            self._row("p1", "l2", 3500, 3200),  # 300, the one shown
            self._row("p1", "l3", 3000, 2950),  # 50: below the threshold
            self._row("p2", "l4", 4000, 3500),  # not emailed (over the limit)
        ]
        shown = [item for item in select_drops(candidates, 100) if item["property_id"] == "p1"]

        rows = drops_to_record(candidates, 100, shown)

        assert [(row["listing_id"], row["drop"]) for row in rows] == [("l2", 300.0), ("l1", 140.0)]

    def test_nothing_shown_nothing_recorded(self):
        from core.saved_search_price_drops import drops_to_record

        assert drops_to_record([self._row("p1", "l1", 3240, 3000)], 100, []) == []
