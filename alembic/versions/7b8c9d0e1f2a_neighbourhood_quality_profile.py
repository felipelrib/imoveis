"""Add neighbourhood quality profile columns (BIN-86).

Revision ID: 7b8c9d0e1f2a
Revises: e2f3a4b5c6d7
Create Date: 2026-07-27 05:40:00.000000

Nullable score columns (floats in [0,1] at the app layer); empty risk_flags;
JSONB quality_meta for provider / refreshed_at. Storage + read only — no
scoring blend in this revision.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from alembic import op

revision = "7b8c9d0e1f2a"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None

_SCORE_COLUMNS = (
    "amenity_score",
    "transit_score",
    "access_score",
    "safety_score",
)


def upgrade() -> None:
    for name in _SCORE_COLUMNS:
        op.add_column("neighborhoods", sa.Column(name, sa.Float(), nullable=True))
    op.add_column(
        "neighborhoods",
        sa.Column(
            "risk_flags",
            ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column("neighborhoods", sa.Column("quality_meta", JSONB(), nullable=True))
    op.add_column("neighborhoods", sa.Column("quality_notes", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("neighborhoods", "quality_notes")
    op.drop_column("neighborhoods", "quality_meta")
    op.drop_column("neighborhoods", "risk_flags")
    for name in reversed(_SCORE_COLUMNS):
        op.drop_column("neighborhoods", name)
