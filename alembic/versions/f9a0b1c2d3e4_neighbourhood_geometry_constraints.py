"""Unique (name,city,state) + GIST on neighborhoods.geometry

Revision ID: f9a0b1c2d3e4
Revises: e8a1b2c3d4e5
Create Date: 2026-07-23 15:30:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "f9a0b1c2d3e4"
down_revision = "e8a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_neighborhoods_name_city_state",
        "neighborhoods",
        ["name", "city", "state"],
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_neighborhoods_geometry_gist "
        "ON neighborhoods USING GIST (geometry)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_neighborhoods_geometry_gist")
    op.drop_constraint(
        "uq_neighborhoods_name_city_state",
        "neighborhoods",
        type_="unique",
    )
