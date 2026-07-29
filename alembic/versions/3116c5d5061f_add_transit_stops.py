"""Add transit_stops table for durable GTFS/OSM stop geometry (BIN-118).

Revision ID: 3116c5d5061f
Revises: f4eea36d6f80
Create Date: 2026-07-29 05:50:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "3116c5d5061f"
down_revision = "f4eea36d6f80"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transit_stops",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column(
            "location",
            Geometry(geometry_type="POINT", srid=4326),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "source",
            "external_id",
            name="uq_transit_stops_source_external_id",
        ),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transit_stops_location_gist "
        "ON transit_stops USING GIST (location)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_transit_stops_location_gist")
    op.drop_table("transit_stops")
