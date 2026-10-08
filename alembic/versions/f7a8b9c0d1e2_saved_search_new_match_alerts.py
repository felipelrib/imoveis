"""Saved-search new-match alerts (Story 1.9, FR-32).

``saved_searches`` gains the per-search switch (off for every existing row),
the moment it was last switched on (the newness floor), the stored minimum
price drop (round-tripped only; the drop rule is Story 1.10) and the local
date of the last new-match email.

``saved_search_new_matches`` holds one row per search x Property that was
found to be a new match: ``pending`` until the daily window emails it,
``sent`` afterwards, ``withdrawn`` when it must not be emailed any more. The
unique constraint is what makes "at most once per search x Property" true.
Deleting a search keeps its rows (``SET NULL``) so the weekly digest still
knows the Property was already alerted.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-10-08 23:00:00.000000

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None

SEARCHES = "saved_searches"
MATCHES = "saved_search_new_matches"
CK_MIN_PRICE_DROP = "ck_saved_searches_min_price_drop"
CK_STATUS = "ck_saved_search_new_matches_status"
UQ_MATCH = "uq_saved_search_new_match"
IX_PROPERTY = "ix_saved_search_new_matches_property_id"


def upgrade() -> None:
    op.add_column(
        SEARCHES,
        sa.Column(
            "notify_new_matches", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(SEARCHES, sa.Column("notify_enabled_at", sa.DateTime(), nullable=True))
    op.add_column(SEARCHES, sa.Column("min_price_drop", sa.Float(), nullable=True))
    op.add_column(SEARCHES, sa.Column("new_match_last_window_on", sa.Date(), nullable=True))
    op.create_check_constraint(
        CK_MIN_PRICE_DROP, SEARCHES, "min_price_drop IS NULL OR min_price_drop >= 0"
    )

    op.create_table(
        MATCHES,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("saved_search_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("matched_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'sent', 'withdrawn')", name=CK_STATUS),
        sa.ForeignKeyConstraint(["saved_search_id"], ["saved_searches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("saved_search_id", "property_id", name=UQ_MATCH),
    )
    op.create_index(IX_PROPERTY, MATCHES, ["property_id"], unique=False)


def downgrade() -> None:
    op.drop_index(IX_PROPERTY, table_name=MATCHES)
    op.drop_table(MATCHES)
    op.drop_constraint(CK_MIN_PRICE_DROP, SEARCHES, type_="check")
    op.drop_column(SEARCHES, "new_match_last_window_on")
    op.drop_column(SEARCHES, "min_price_drop")
    op.drop_column(SEARCHES, "notify_enabled_at")
    op.drop_column(SEARCHES, "notify_new_matches")
