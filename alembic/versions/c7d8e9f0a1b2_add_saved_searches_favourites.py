"""Add saved_searches and favourites tables.

Revision ID: c7d8e9f0a1b2
Revises: b1c2d3e4f5a6
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers
revision = "c7d8e9f0a1b2"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_searches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("filters", JSONB, nullable=False),
        sa.Column("owner", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("now()")),
    )

    op.create_table(
        "favourites",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "property_id",
            UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("now()")),
        sa.UniqueConstraint("property_id", name="uq_favourite_property"),
    )
    op.create_index("ix_favourites_property_id", "favourites", ["property_id"])


def downgrade() -> None:
    op.drop_index("ix_favourites_property_id", table_name="favourites")
    op.drop_table("favourites")
    op.drop_table("saved_searches")
