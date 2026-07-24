"""Add base_price to property_listings (BIN-67).

Revision ID: a1b2c3d4e5f6
Revises: f9a0b1c2d3e4
Create Date: 2026-07-24 08:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "property_listings",
        sa.Column("base_price", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("property_listings", "base_price")
