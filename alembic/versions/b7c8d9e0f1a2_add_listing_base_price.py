"""Add base_price to property_listings (BIN-67).

Revision ID: b7c8d9e0f1a2
Revises: a2b3c4d5e6f7
Create Date: 2026-07-24 08:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b7c8d9e0f1a2"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "property_listings",
        sa.Column("base_price", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("property_listings", "base_price")
