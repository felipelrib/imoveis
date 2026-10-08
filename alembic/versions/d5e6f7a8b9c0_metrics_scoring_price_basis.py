"""metrics_scoring.price_basis — which price produced the rent price/m² (Story 1.3, AD-3).

``rent_monthly`` when the row's rent price/m² came from a Listing's
fee-exclusive rent, ``headline`` otherwise. Existing rows start as
``headline``, which is true of them: they were scored from the published
headline price. They move only when the scoring stage recalculates them.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-10-08 15:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None

TABLE = "metrics_scoring"
PRICE_BASIS_CHECK = "ck_metrics_scoring_price_basis"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "price_basis",
            sa.String(),
            nullable=False,
            server_default=sa.text("'headline'"),
        ),
    )
    op.create_check_constraint(
        PRICE_BASIS_CHECK,
        TABLE,
        "price_basis IN ('rent_monthly', 'headline')",
    )


def downgrade() -> None:
    op.drop_constraint(PRICE_BASIS_CHECK, TABLE, type_="check")
    op.drop_column(TABLE, "price_basis")
