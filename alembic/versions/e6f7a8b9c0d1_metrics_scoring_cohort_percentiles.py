"""metrics_scoring cohort price/m² percentiles (Story 1.6, FR-30).

Per listing type: the share of the Property's city x neighbourhood x
listing-type cohort priced at or below it (in (0, 1], lower is cheaper), the
size of that cohort, and one timestamp for the last evaluation. All nullable
and NULL on existing rows: a row has no percentile until the scoring stage
evaluates it, and none when its cohort is below the configured minimum size
or the Property is not a cohort member. The legacy ``percentile_rank*``
columns are untouched.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-10-08 20:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None

TABLE = "metrics_scoring"

PERCENTILE_COLUMNS = ("price_per_m2_percentile_rent", "price_per_m2_percentile_sale")
COHORT_SIZE_COLUMNS = ("percentile_cohort_size_rent", "percentile_cohort_size_sale")
EVALUATED_AT_COLUMN = "percentile_evaluated_at"


def _check_name(column: str) -> str:
    return "ck_metrics_scoring_" + column


def upgrade() -> None:
    for column in PERCENTILE_COLUMNS:
        op.add_column(TABLE, sa.Column(column, sa.Float(), nullable=True))
    for column in COHORT_SIZE_COLUMNS:
        op.add_column(TABLE, sa.Column(column, sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column(EVALUATED_AT_COLUMN, sa.DateTime(), nullable=True))

    for column in PERCENTILE_COLUMNS:
        op.create_check_constraint(
            _check_name(column),
            TABLE,
            column + " IS NULL OR (" + column + " > 0 AND " + column + " <= 1)",
        )
    for column in COHORT_SIZE_COLUMNS:
        op.create_check_constraint(
            _check_name(column),
            TABLE,
            column + " IS NULL OR " + column + " >= 1",
        )


def downgrade() -> None:
    for column in (*PERCENTILE_COLUMNS, *COHORT_SIZE_COLUMNS):
        op.drop_constraint(_check_name(column), TABLE, type_="check")
    op.drop_column(TABLE, EVALUATED_AT_COLUMN)
    for column in (*COHORT_SIZE_COLUMNS, *PERCENTILE_COLUMNS):
        op.drop_column(TABLE, column)
