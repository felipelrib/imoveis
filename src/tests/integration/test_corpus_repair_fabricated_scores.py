"""Characterization lock for the v0.13-s2.7 corpus repair predicate.

Story 2.7 nulls ``metrics_scoring.ai_score`` on rows poisoned before story 3.2
landed, where every AI-client exception fallback persisted a fabricated ``0.5``
with ``analysis="Error"``. ``mode_is_missing_ai`` is ``not score``, so those
rows left the enrichment candidate set permanently.

These tests seed the story's full I/O matrix against a real Postgres and lock
the predicate's include/exclude boundary **before** the surgery is applied to
the primary corpus — in particular that the honest ``0.5`` written by
``neutral_sentiment_no_description()`` (BIN-243) survives untouched, and that
JSON scalars in ``meta`` are excluded rather than raising *"cannot extract
element from a scalar"*.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from adapters.ai.client import SentimentResult, VisualResult
from adapters.ai.enrich_pipeline import neutral_sentiment_no_description
from adapters.db.models import MetricsScoring, Neighborhood, Property
from core.enrichment_rerun import mode_is_missing_ai

# The repair lives in an alembic version file, which is not importable as a
# module path (``alembic/versions`` is not a package and its filenames start
# with a revision hash). Loading it by path is what lets the forensic predicate
# keep exactly ONE definition: story 2.7 forbids the ``analysis == 'Error'``
# test from entering ``src/``, so this test reads it out of the migration
# instead of carrying a second copy that could drift.
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "f3a7c81d5e42_repair_fabricated_ai_scores.py"
)


def _load_repair_migration():
    spec = importlib.util.spec_from_file_location(
        "corpus_repair_f3a7c81d5e42", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_repair_migration()

BLEND = migration.DOUBLY_FABRICATED_BLEND

# The pre-3.2 fallback blobs, as ``model_dump()`` persisted them at the time:
# ``VisualResult(condition_score=0.5, analysis="Error")`` /
# ``SentimentResult(sentiment_score=0.5, analysis="Error")``, every other field
# defaulted. Hand-built rather than dumped from the current models because
# ``degraded`` did not exist yet — a genuinely poisoned corpus row carries no
# such key, and surviving that absence is part of the contract.
POISONED_VISUAL = {
    "condition_score": 0.5,
    "analysis": "Error",
    "category": "average",
    "reasoning": "",
    "features_detected": [],
    "issues_detected": [],
}
POISONED_SENTIMENT = {
    "sentiment_score": 0.5,
    "analysis": "Error",
    "category": "average",
    "reasoning": "",
    "green_flags": [],
    "red_flags": [],
}


def _honest_visual(score: float) -> dict:
    return VisualResult(
        condition_score=score,
        analysis="Cozinha reformada, piso laminado em bom estado.",
        category="good",
        reasoning="Acabamentos recentes e sem sinais de infiltracao.",
        features_detected=["armarios planejados"],
        issues_detected=[],
    ).model_dump()


def _honest_sentiment(score: float) -> dict:
    return SentimentResult(
        sentiment_score=score,
        analysis="Anuncio detalhado, com planta e condominio informado.",
        category="good",
        reasoning="Descricao consistente com as fotos.",
        green_flags=["condominio informado"],
        red_flags=[],
    ).model_dump()


def _drop_degraded(blob: dict) -> dict:
    """A pre-3.2 honest blob: same shape, minus the field story 3.2 added."""
    return {key: value for key, value in blob.items() if key != "degraded"}


def _as_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# The story's I/O & edge-case matrix, one entry per seeded row.
#
# ``marker``   — does ``FABRICATION_PREDICATE_SQL`` alone match the row?
# ``repaired`` — does the repair null it (marker AND ``ai_score IS NOT NULL``)?
# ``on_blend`` — is it counted in the doubly-fabricated sub-count?
# ``meta``     — the literal JSON text stored in the ``json`` column, or None
#                for a SQL NULL. Text, so the scalar cases (``"broken"``,
#                ``null``) stay distinguishable from a missing value.
# ---------------------------------------------------------------------------
SCENARIOS: list[dict] = [
    {
        "name": "canonical_poison",
        "meta": _as_json({"visual": POISONED_VISUAL, "sentiment": POISONED_SENTIMENT}),
        "ai_score": BLEND,
        "marker": True,
        "repaired": True,
        "on_blend": True,
    },
    {
        "name": "visual_only_poison_on_blend",
        "meta": _as_json(
            {"visual": POISONED_VISUAL, "sentiment": _honest_sentiment(0.5)}
        ),
        "ai_score": BLEND,
        "marker": True,
        "repaired": True,
        "on_blend": True,
    },
    {
        "name": "sentiment_only_poison_on_blend",
        "meta": _as_json(
            {"visual": _honest_visual(0.5), "sentiment": POISONED_SENTIMENT}
        ),
        "ai_score": BLEND,
        "marker": True,
        "repaired": True,
        "on_blend": True,
    },
    {
        # Half-fabricated but *off* the blend: 0.5*0.7 + 0.8*0.3 = 0.59. This
        # row is the whole reason the marker, not the 0.5 value, is the
        # predicate — keying on the blend would leave it poisoned forever.
        "name": "half_poisoned_off_blend",
        "meta": _as_json(
            {"visual": POISONED_VISUAL, "sentiment": _honest_sentiment(0.8)}
        ),
        "ai_score": 0.59,
        "marker": True,
        "repaired": True,
        "on_blend": False,
    },
    {
        # BIN-243's honest neutral: analysis="" plus the sentinel reasoning.
        # The exclusion this suite exists to protect.
        "name": "honest_neutral_sentiment",
        "meta": _as_json(
            {
                "visual": _honest_visual(0.5),
                "sentiment": neutral_sentiment_no_description().model_dump(),
            }
        ),
        "ai_score": BLEND,
        "marker": False,
        "repaired": False,
        "on_blend": False,
    },
    {
        "name": "fully_honest_coincidental_blend",
        "meta": _as_json(
            {
                "visual": _drop_degraded(_honest_visual(0.5)),
                "sentiment": _drop_degraded(_honest_sentiment(0.5)),
            }
        ),
        "ai_score": BLEND,
        "marker": False,
        "repaired": False,
        "on_blend": False,
    },
    {
        "name": "post_32_shaped_honest_row",
        "meta": _as_json(
            {"visual": _honest_visual(0.72), "sentiment": _honest_sentiment(0.64)}
        ),
        "ai_score": 0.696,
        "marker": False,
        "repaired": False,
        "on_blend": False,
    },
    {
        # Already repaired (or never scored): the marker is there but there is
        # nothing to null. Excluded, so the reported count stays honest.
        "name": "already_repaired_marker_null_score",
        "meta": _as_json({"visual": POISONED_VISUAL, "sentiment": POISONED_SENTIMENT}),
        "ai_score": None,
        "marker": True,
        "repaired": False,
        "on_blend": False,
    },
    {
        "name": "meta_is_sql_null",
        "meta": None,
        "ai_score": BLEND,
        "marker": False,
        "repaired": False,
        "on_blend": False,
    },
    {
        # JSON scalars: ``json -> text`` is undefined for these, so without the
        # ``json_typeof`` guard the statement dies with "cannot extract element
        # from a scalar" and the whole repair does nothing at all.
        "name": "meta_is_json_string_scalar",
        "meta": '"broken"',
        "ai_score": BLEND,
        "marker": False,
        "repaired": False,
        "on_blend": False,
    },
    {
        "name": "meta_is_json_null_scalar",
        "meta": "null",
        "ai_score": BLEND,
        "marker": False,
        "repaired": False,
        "on_blend": False,
    },
    {
        "name": "meta_visual_is_json_scalar",
        "meta": '{"visual": 3}',
        "ai_score": BLEND,
        "marker": False,
        "repaired": False,
        "on_blend": False,
    },
    {
        "name": "meta_object_without_ai_keys",
        "meta": '{"stat_analysis": "x"}',
        "ai_score": BLEND,
        "marker": False,
        "repaired": False,
        "on_blend": False,
    },
    {
        # A blob that is an object but carries no ``analysis`` key — the shape
        # ``test_properties_ai_scores.py`` already seeds, and a plausible
        # half-written row in the very corpus this repair cleans.
        # ``NULL = 'Error'`` is NULL, so without the predicate's COALESCE this
        # row makes the whole expression three-valued rather than false.
        "name": "meta_visual_object_without_analysis_key",
        "meta": _as_json({"visual": {"condition_score": 0.5}}),
        "ai_score": BLEND,
        "marker": False,
        "repaired": False,
        "on_blend": False,
    },
    {
        "name": "meta_both_objects_without_analysis_key",
        "meta": _as_json(
            {"visual": {"condition_score": 0.5}, "sentiment": {"sentiment_score": 0.5}}
        ),
        "ai_score": BLEND,
        "marker": False,
        "repaired": False,
        "on_blend": False,
    },
]

EXPECTED_REPAIRED = sum(1 for scenario in SCENARIOS if scenario["repaired"])
EXPECTED_ON_BLEND = sum(1 for scenario in SCENARIOS if scenario["on_blend"])


# --- seeding helpers (mirroring test_scoring_sql_assembly.py) ---------------


def _neighborhood(session) -> Neighborhood:
    n = Neighborhood(
        name=f"Cohort-{uuid4().hex[:8]}",
        city="Belo Horizonte",
        state="MG",
    )
    session.add(n)
    session.flush()
    return n


def _property(session, *, neighborhood_id) -> Property:
    p = Property(
        platform="test",
        platform_id=f"p-{uuid4().hex[:12]}",
        title="Corpus repair fixture",
        price=2500.0,
        area_m2=60.0,
        neighborhood_id=neighborhood_id,
        active=True,
    )
    session.add(p)
    session.flush()
    return p


def _seed_metrics(session, *, property_id, ai_score, meta_text) -> str:
    """Insert one metrics row with byte-exact control over the ``json`` value.

    Raw parameterized SQL rather than the ORM: the matrix needs a JSON scalar
    (``"broken"``, ``null``) and a SQL NULL as *distinct* stored states, which
    the ``JSON`` column type conflates on the way in. UUIDs travel as text with
    an explicit cast so the test never depends on psycopg2's uuid adapter.
    """
    return session.execute(
        sa.text(
            "INSERT INTO metrics_scoring (property_id, ai_score, meta)"
            " VALUES (CAST(:pid AS uuid), :score, CAST(:meta AS json))"
            " RETURNING CAST(id AS text)"
        ),
        {"pid": str(property_id), "score": ai_score, "meta": meta_text},
    ).scalar_one()


def _snapshot(session, metrics_id: str):
    """``(ai_score, raw meta text)``.

    Postgres stores ``json`` verbatim, so comparing the text before and after
    is an exact untouched check rather than a semantic one.
    """
    return session.execute(
        sa.text(
            "SELECT ai_score, CAST(meta AS text) AS meta_text"
            " FROM metrics_scoring WHERE id = CAST(:id AS uuid)"
        ),
        {"id": metrics_id},
    ).one()


def _marker_verdicts(session) -> dict:
    """Project FABRICATION_PREDICATE_SQL over every seeded row.

    Plain concatenation, never an f-string (BIN-135); the only interpolated
    fragment is the migration module's own constant.
    """
    rows = session.execute(
        sa.text(
            "SELECT CAST(id AS text) AS metrics_id, ("
            + migration.FABRICATION_PREDICATE_SQL
            + ") AS marker FROM metrics_scoring"
        )
    ).all()
    return {row.metrics_id: row.marker for row in rows}


@pytest.fixture(scope="function")
def seeded_matrix(wipe_safe_db_session):
    """Seed one property + one metrics row per matrix scenario.

    Empties ``metrics_scoring`` first. ``wipe_safe_db_session`` wipes on
    *teardown* only, and both the marker projection and ``apply_repair`` scan
    the whole table — so a row left behind by an interrupted or errored earlier
    test would turn the exact-equality count assertions below into a failure
    blaming this suite. ``test_enrichment_coverage_sql.py`` documents the same
    hazard and empties for the same reason.
    """
    session = wipe_safe_db_session
    session.execute(sa.text("DELETE FROM metrics_scoring"))
    session.flush()
    nhood = _neighborhood(session)
    ids = {}
    for scenario in SCENARIOS:
        prop = _property(session, neighborhood_id=nhood.id)
        ids[scenario["name"]] = _seed_metrics(
            session,
            property_id=prop.id,
            ai_score=scenario["ai_score"],
            meta_text=scenario["meta"],
        )
    session.commit()
    return session, ids


@pytest.mark.integration
class TestFabricationPredicateBoundary:
    def test_blend_constant_is_pinned_history_not_live_config(self):
        """The doubly-fabricated blend is frozen, not read from live config.

        Poisoned rows were blended with the weights in force before story 3.2
        (0.5 * 0.7 + 0.5 * 0.3). Deriving the constant from ``get_config()``
        would move it the moment the weights are retuned, silently reporting
        ``on_blend = 0`` — and would make every assertion below tautological,
        since they seed ``ai_score = BLEND`` from the same source.
        """
        assert migration.DOUBLY_FABRICATED_BLEND == 0.5

    def test_marker_verdict_matches_matrix_and_never_raises_on_scalars(self, seeded_matrix):
        """Every matrix row gets the include/exclude verdict story 2.7 fixed.

        The JSON-scalar rows are the point of the ``json_typeof`` guard: this
        query returning at all — rather than dying with "cannot extract element
        from a scalar" — is the assertion for them.
        """
        session, ids = seeded_matrix

        verdicts = _marker_verdicts(session)

        for scenario in SCENARIOS:
            name = scenario["name"]
            assert verdicts[ids[name]] is scenario["marker"], name

    def test_repair_nulls_only_marked_rows_and_reports_honest_counts(self, seeded_matrix):
        session, ids = seeded_matrix
        before = {name: _snapshot(session, metrics_id) for name, metrics_id in ids.items()}

        counts = migration.apply_repair(session.connection())
        session.commit()

        assert counts == {"repaired": EXPECTED_REPAIRED, "on_blend": EXPECTED_ON_BLEND}

        for scenario in SCENARIOS:
            name = scenario["name"]
            after = _snapshot(session, ids[name])
            if scenario["repaired"]:
                assert after.ai_score is None, name
            elif before[name].ai_score is None:
                assert after.ai_score is None, name
            else:
                assert after.ai_score == pytest.approx(before[name].ai_score), name
            # ``meta`` is never rewritten: the forensic evidence stays on the
            # row for both populations.
            assert after.meta_text == before[name].meta_text, name

    def test_empty_corpus_reports_zero_and_does_not_fail(self, wipe_safe_db_session):
        # Explicit rather than assumed: the fixture wipes on teardown, so an
        # earlier module that skipped it must not turn this into a flake.
        wipe_safe_db_session.execute(sa.text("DELETE FROM metrics_scoring"))
        wipe_safe_db_session.flush()

        counts = migration.apply_repair(wipe_safe_db_session.connection())

        assert counts == {"repaired": 0, "on_blend": 0}


@pytest.mark.integration
class TestCandidateSetReadmission:
    def test_characterization_poisoned_row_rejoins_missing_ai_candidates(self, seeded_matrix):
        """Characterization lock (story v0.13-s2.7).

        Locks the include/exclude boundary of the corpus surgery *before* it is
        applied to the primary DB, stated in the ``mode_is_missing_ai`` terms
        that actually decide re-enrichment. A canonically poisoned row is
        invisible to ``mode=missing`` before the repair (its fabricated blend is
        truthy and ``mode_is_missing_ai`` is literally ``not score``) and is a
        candidate after it. The honest neutral-sentiment row — a legitimate
        ``0.5`` from ``neutral_sentiment_no_description()`` — is not a candidate
        on either side, which is what proves the predicate keys on the
        fabrication marker rather than on the value.
        """
        session, ids = seeded_matrix
        poisoned_id = UUID(ids["canonical_poison"])
        honest_id = UUID(ids["honest_neutral_sentiment"])

        def _metrics(metrics_id):
            return session.query(MetricsScoring).filter_by(id=metrics_id).one()

        assert mode_is_missing_ai(_metrics(poisoned_id)) is False
        assert mode_is_missing_ai(_metrics(honest_id)) is False

        migration.apply_repair(session.connection())
        session.commit()
        session.expire_all()

        assert mode_is_missing_ai(_metrics(poisoned_id)) is True
        assert mode_is_missing_ai(_metrics(honest_id)) is False
