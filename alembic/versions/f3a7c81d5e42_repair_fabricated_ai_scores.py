"""Repair metrics_scoring rows poisoned with fabricated AI scores (v0.13-s2.7)

Revision ID: f3a7c81d5e42
Revises: b65411932ef9
Create Date: 2026-08-13 00:00:00.000000

WHAT THE POISON IS
------------------
Before story 3.2 landed, every exception fallback inside the AI client
persisted a *fabricated* result rather than failing: ``condition_score`` /
``sentiment_score`` were set to ``0.5`` and ``analysis`` to the literal string
``"Error"`` (``src/adapters/ai/client.py`` pre-3.2 fallbacks). The enrichment
task then blended those invented halves into ``metrics_scoring.ai_score`` and
committed, storing the fabrication under ``meta['visual']`` /
``meta['sentiment']``.

That is not merely a wrong number. ``core.enrichment_rerun.mode_is_missing_ai``
is literally ``not score``, and the SQL candidate push-down is
``ai_score IS NULL OR ai_score = 0`` — so a truthy fabricated score removes the
row from the enrichment candidate set **permanently**. No later census, no
re-run, no restart ever looks at it again. Story 3.2 stopped new fabrication
(``tasks.py`` now raises ``AIResultDegradedError`` *before* opening a session,
so no honest row written after 3.2 can carry the marker) but repaired nothing
retroactively. This migration is the missing half of that gate: it nulls
``ai_score`` on exactly the marker-carrying rows so ``mode=missing`` re-admits
them and the running backfill re-enriches them on its next census.

WHY THE MARKER, NOT THE 0.5 BLEND, IS THE PREDICATE
---------------------------------------------------
With the shipped weights (``ai.visual_weight`` 0.7 / ``ai.text_weight`` 0.3) a
*doubly* fabricated row lands on exactly ``0.5`` (``0.35 + 0.15``). But a row
whose visual half was fabricated beside an honest sentiment of ``0.8`` lands on
``0.59`` — still half-invented, still permanently uncandidatable. Keying on the
blend value alone would knowingly leave that population poisoned forever.
Keying on the marker cannot produce a false positive: no honest path writes
``analysis = 'Error'`` (``neutral_sentiment_no_description()`` writes ``""``
with an explicit sentinel ``reasoning``), and post-3.2 no degraded result is
persisted at all — so the marker describes a closed, pre-3.2-only population.
The asymmetry decides it: over-repair self-heals through one re-enrichment,
under-repair is permanent. The on-blend sub-count is still reported separately
so the operator can see both populations.

WHY A MIGRATION (AND NOT A SCRIPT, AND NOT AN ADMIN ENDPOINT)
-------------------------------------------------------------
* **Migration (chosen).** ``alembic_version`` makes it run exactly once by
  construction, so this can never become a recurring path. The forensic
  predicate sits in a versioned one-off artifact, outside ``src/``. And
  ``scripts/agent/migrate-primary.sh`` is already the sanctioned guarded path
  to the primary corpus: it takes ``backfill:gemma:migrating`` and refuses on a
  live ``backfill:gemma:active`` heartbeat, so the repair inherits the
  backfill mutual exclusion (v0.13-fu6) for free — no new guard code.
* **``scripts/dev/`` script (rejected).** It would have to re-implement that
  same migration/backfill handshake to be safe against a live backfill — a
  divergent second copy of exactly the machinery fu6 centralized.
* **Admin endpoint (rejected).** That puts the ``analysis == "Error"`` string
  inside feature code, on a re-runnable route. Story 3.2's contract forbids it:
  ``degraded: bool`` is the runtime marker and stays the only one.

THIS PREDICATE IS WIDER THAN THE STORY'S WRITTEN "GIVEN"
--------------------------------------------------------
The epic AC (``epics.md`` story 2.7) describes the signature as the marker
*"with ``ai_score`` sitting on the configured blend of 0.5"*. This migration
deliberately drops the value half and repairs on the marker alone, which is a
**wider** population than the AC literally names — the half-fabricated rows in
the paragraph above. Recorded as a deliberate widening, with the rationale
above, rather than presented as a literal reading of the AC.

WHAT THIS DOES *NOT* GUARD AGAINST
----------------------------------
``migrate-primary.sh`` is the sanctioned path and does hold
``backfill:gemma:migrating`` for the whole upgrade — but it is not the only way
``alembic upgrade head`` reaches the primary DB. ``scripts/start.sh`` and
``scripts/agent/run-services.sh`` both run it in the ``api`` container with no
lock and no heartbeat probe (that gap is **DW-32**, open/high, scheduled in
this same wave). Until DW-32 lands, a ``./scripts/start.sh`` on the primary
checkout can apply this repair unguarded — and ``start.sh`` captures the
migration output and prints it only on failure, so the ``N``/``M`` line below
would be swallowed. The feature doc carries a read-only recovery query for
exactly that case.

THIS FILE IS A ONE-OFF FORENSIC ARTIFACT. Nothing under ``src/`` may import it.
The ``'Error'`` string test is a statement about pre-3.2 history, not a runtime
signal; the only consumer is
``src/tests/integration/test_corpus_repair_fabricated_scores.py``, which
imports this module *by path* so the predicate keeps exactly one definition.

Applying it to the primary ``realestate`` DB is the operator's guarded step
(``bash scripts/agent/migrate-primary.sh``), never an agent action.
"""
from __future__ import annotations

import logging

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "f3a7c81d5e42"
down_revision = "b65411932ef9"
branch_labels = None
depends_on = None

# ``alembic.ini``'s ``[logger_alembic]`` sets ``level = INFO`` on the ``alembic``
# qualname, so anything logged under it reaches ``migrate-primary.sh``'s output
# where the operator can read the repaired count. ``alembic.runtime.migration``
# is the same channel alembic's own "Running upgrade …" lines use.
logger = logging.getLogger("alembic.runtime.migration")

# The fabricated half-score every pre-3.2 exception fallback invented.
_FABRICATED_HALF_SCORE = 0.5

# Floats are compared with a tolerance, never ``=`` (Sonar S1244 — the same
# reason ``core.enrichment_rerun.mode_is_missing_ai`` uses ``not score``
# instead of ``score == 0``). This only classifies the reported sub-count; it
# never decides what gets repaired.
_BLEND_TOLERANCE = 1e-9

# The ``ai_score`` a *doubly* fabricated row landed on, with the weights that
# were in force before story 3.2: 0.5 * 0.7 + 0.5 * 0.3, which is exactly 0.5
# in IEEE754 (no float dust).
#
# PINNED, deliberately NOT read from ``get_config()``. The poisoned rows are
# frozen history: they were blended with the weights of the day, so a later
# retune of ``ai.visual_weight`` / ``ai.text_weight`` describes *new* rows and
# says nothing about these. Deriving this from live config would silently move
# the constant off every poisoned row's value and report ``on_blend = 0`` with
# no signal — and would make the test that seeds ``ai_score = BLEND`` pass for
# any weights, so nothing could catch the drift. Pinning also keeps this module
# import-free of ``src/``: alembic imports every version script to build its
# revision map, and ``alembic history`` / ``heads`` / ``branches`` do NOT run
# ``env.py`` first, so an ``infra.config`` import here breaks those commands
# outright whenever ``src/`` is not already on ``PYTHONPATH`` — and a bad
# ``IMOVEIS_*`` override would abort ``upgrade head`` before *any* migration in
# the chain ran. No other file in ``alembic/versions/`` imports from ``src/``.
DOUBLY_FABRICATED_BLEND = 0.5

# ``metrics_scoring.meta`` is a Postgres ``json`` column, **not** ``jsonb``.
# Never cast it: ``json -> jsonb`` rejects NUL unicode escapes, which the
# scraped free text inside the AI meta blobs can legitimately carry, and that
# would turn this repair into a hard failure on a handful of rows. ``->`` and
# ``->>`` are defined for ``json`` directly, so no cast is needed.
#
# Every extraction is wrapped in ``CASE WHEN json_typeof(...) = 'object'``, and
# that guard is not decoration: ``json -> text`` is only defined for objects
# (a scalar raises *"cannot extract element from a scalar"*), and SQL ``AND``
# is not guaranteed to short-circuit, so a row whose ``meta`` is ``'"broken"'``
# or ``'null'`` — or whose ``meta->'visual'`` is a bare number — has to be
# excluded *before* the extraction is attempted, not beside it. Same shape as
# ``src/adapters/db/enrichment_coverage_queries.py``'s signal-count guards.
#
# Either half being fabricated poisons the blend, hence ``OR``.
#
# ``COALESCE(..., false)`` makes the predicate **total**. A ``meta -> 'visual'``
# object that carries no ``analysis`` key at all — a plausible shape in exactly
# the half-written corpus this repair is cleaning, and the shape
# ``src/tests/integration/test_properties_ai_scores.py`` already seeds — yields
# ``NULL = 'Error'`` → ``NULL``, so the whole expression would be three-valued.
# ``WHERE`` treats that as false (the right outcome), but projecting it as a
# boolean or reusing it under ``NOT (...)`` would not. Collapsing it here means
# the constant means the same thing everywhere it is used.
FABRICATION_PREDICATE_SQL = """
    CASE WHEN json_typeof(meta) = 'object' THEN
           COALESCE(
             CASE WHEN json_typeof(meta -> 'visual') = 'object'
                  THEN meta -> 'visual' ->> 'analysis' = 'Error'
                  ELSE false END, false)
        OR COALESCE(
             CASE WHEN json_typeof(meta -> 'sentiment') = 'object'
                  THEN meta -> 'sentiment' ->> 'analysis' = 'Error'
                  ELSE false END, false)
         ELSE false END
"""

# ONE statement, so both numbers are read from ONE snapshot.
#
# Plain concatenation, never an f-string (BIN-135): the only interpolated part
# is the module-level predicate constant above; the blend and its tolerance
# travel as bind parameters.
#
# ``targets`` and the data-modifying ``repaired`` CTE are evaluated against the
# same snapshot, so ``on_blend <= repaired`` holds *by construction*. Counting
# the blend population in a separate earlier statement could not promise that:
# a row re-enriched between the two statements would be counted and then not
# repaired, and the operator would read a self-contradictory report. Joining
# back to ``targets`` is also the only way to see the *pre*-update ``ai_score``
# — ``UPDATE ... RETURNING`` hands back the new value, which is always NULL.
#
# Still set-based and still never read-then-write: no id list makes a round trip
# through Python, so a row honestly re-scored before the statement runs simply
# stops matching instead of being clobbered.
_REPAIR_SQL = (
    "WITH targets AS ("
    "  SELECT id, ai_score FROM metrics_scoring"
    "   WHERE ai_score IS NOT NULL AND (" + FABRICATION_PREDICATE_SQL + ")"
    "), repaired AS ("
    "  UPDATE metrics_scoring m SET ai_score = NULL"
    "    FROM targets t WHERE m.id = t.id"
    "  RETURNING m.id"
    ")"
    " SELECT count(*) AS repaired,"
    "        count(*) FILTER (WHERE abs(t.ai_score - :blend) <= :tolerance)"
    "          AS on_blend"
    "   FROM repaired r JOIN targets t ON t.id = r.id"
)


def apply_repair(connection) -> dict[str, int]:
    """Null ``ai_score`` on every row carrying the pre-3.2 fabrication marker.

    Returns ``{"repaired": n, "on_blend": m}`` where ``n`` is the number of
    ``metrics_scoring`` rows repaired and ``m`` is how many of those sat within
    tolerance of the doubly-fabricated blend. Both are **metrics-row** counts,
    not property counts: ``metrics_scoring.property_id`` carries no unique
    constraint (see ``src/adapters/db/enrichment_coverage_queries.py``), so a
    property with a duplicated metrics row contributes twice.
    """
    row = connection.execute(
        sa.text(_REPAIR_SQL),
        {"blend": DOUBLY_FABRICATED_BLEND, "tolerance": _BLEND_TOLERANCE},
    ).one()

    logger.info(
        "v0.13-s2.7 corpus repair: nulled %s fabricated ai_score metrics rows "
        "(%s of them sat on the %s doubly-fabricated blend)",
        row.repaired,
        row.on_blend,
        DOUBLY_FABRICATED_BLEND,
    )
    return {"repaired": int(row.repaired), "on_blend": int(row.on_blend)}


def upgrade() -> None:
    apply_repair(op.get_bind())


def downgrade() -> None:
    # Deliberate no-op, logged rather than silent.
    #
    # The pre-image is not faithfully recoverable. Doubly fabricated rows sat
    # on the blend constant, but half-fabricated rows sat on an arbitrary value
    # derived from their honest half (0.59, 0.65, …) which this migration did
    # not preserve — restoring the constant to all of them would *invent* data,
    # the exact failure this migration exists to repair. Downgrading therefore
    # leaves the rows as honest NULLs, which every consumer already handles:
    # ``mode_is_missing_ai`` treats them as candidates and
    # ``blend_combined_score`` reads ``float(ai_score or 0.0)``.
    logger.info(
        "v0.13-s2.7 corpus repair: downgrade is a no-op — the fabricated "
        "ai_score pre-image is not recoverable, and the repaired rows are "
        "left as honest NULLs"
    )
