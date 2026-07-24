"""Add pipeline_metric_snapshots for durable Dashboard history (BIN-61).

Revision ID: a2b3c4d5e6f7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-24 07:10:00.000000

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "a2b3c4d5e6f7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_metric_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("total_properties", sa.Integer(), nullable=True),
        sa.Column("enriched_properties", sa.Integer(), nullable=True),
        sa.Column("scraper_queue", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ai_queue", sa.Integer(), server_default="0", nullable=False),
        sa.Column("throughput_per_min", sa.Float(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pipeline_metric_snapshots_ts",
        "pipeline_metric_snapshots",
        ["ts"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_metric_snapshots_ts", table_name="pipeline_metric_snapshots")
    op.drop_table("pipeline_metric_snapshots")
