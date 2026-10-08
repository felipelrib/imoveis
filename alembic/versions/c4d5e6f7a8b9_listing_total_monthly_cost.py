"""Total Monthly Cost columns on property_listings (Story 1.1, FR-31, AD-3/AD-19).

Adds the typed cost components, their completeness flags and ``updated_at``.
Existing rows start as ``unknown`` (NULL components, ``cost_complete`` false);
``tasks.backfill_listing_costs`` populates them from the stored figures.

Revision ID: c4d5e6f7a8b9
Revises: f3a7c81d5e42
Create Date: 2026-10-08 09:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c4d5e6f7a8b9"
down_revision = "f3a7c81d5e42"
branch_labels = None
depends_on = None

TABLE = "property_listings"
PERIODICITY_CHECK = "ck_property_listings_iptu_periodicity_source"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("rent_monthly", sa.Float(), nullable=True))
    op.add_column(TABLE, sa.Column("condo_fee_monthly", sa.Float(), nullable=True))
    op.add_column(TABLE, sa.Column("iptu_monthly", sa.Float(), nullable=True))
    op.add_column(
        TABLE,
        sa.Column(
            "iptu_periodicity_source",
            sa.String(),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
    )
    op.add_column(
        TABLE,
        sa.Column("fees_bundled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(TABLE, sa.Column("total_monthly_cost", sa.Float(), nullable=True))
    op.add_column(
        TABLE,
        sa.Column("cost_complete", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        TABLE,
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_check_constraint(
        PERIODICITY_CHECK,
        TABLE,
        "iptu_periodicity_source IN ('monthly', 'annual', 'unknown')",
    )


def downgrade() -> None:
    op.drop_constraint(PERIODICITY_CHECK, TABLE, type_="check")
    op.drop_column(TABLE, "updated_at")
    op.drop_column(TABLE, "cost_complete")
    op.drop_column(TABLE, "total_monthly_cost")
    op.drop_column(TABLE, "fees_bundled")
    op.drop_column(TABLE, "iptu_periodicity_source")
    op.drop_column(TABLE, "iptu_monthly")
    op.drop_column(TABLE, "condo_fee_monthly")
    op.drop_column(TABLE, "rent_monthly")
