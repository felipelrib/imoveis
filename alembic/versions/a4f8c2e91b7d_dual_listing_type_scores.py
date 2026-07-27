"""Add rent/sale stat/z/percentile/combined scores (BIN-83).

Revision ID: a4f8c2e91b7d
Revises: 7b8c9d0e1f2a
Create Date: 2026-07-27 06:10:00.000000

Schema-only: nullable columns filled by compute_neighborhood_stats / Recalculate.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "a4f8c2e91b7d"
down_revision = "7b8c9d0e1f2a"
branch_labels = None
depends_on = None

_COLUMNS = (
    "stat_score_rent",
    "stat_score_sale",
    "z_score_rent",
    "z_score_sale",
    "percentile_rank_rent",
    "percentile_rank_sale",
    "combined_score_rent",
    "combined_score_sale",
)


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column("metrics_scoring", sa.Column(name, sa.Float(), nullable=True))


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("metrics_scoring", name)
