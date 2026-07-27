"""Add rent/sale price_per_m2 and neighbourhood stats (BIN-84).

Revision ID: d1e2f3a4b5c6
Revises: c8d9e0f1a2b3
Create Date: 2026-07-27 05:00:00.000000

Schema-only: nullable columns filled by compute_neighborhood_stats / Recalculate.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "d1e2f3a4b5c6"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None

_COLUMNS = (
    "price_per_m2_rent",
    "price_per_m2_sale",
    "neighborhood_mean_rent",
    "neighborhood_mean_sale",
    "neighborhood_median_rent",
    "neighborhood_median_sale",
)


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column("metrics_scoring", sa.Column(name, sa.Float(), nullable=True))


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("metrics_scoring", name)
