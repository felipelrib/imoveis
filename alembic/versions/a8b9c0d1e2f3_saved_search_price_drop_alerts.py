"""Saved-search price-drop alerts (Story 1.10, FR-32, UX-DR13).

``saved_searches`` gains the moment drop alerts became active for the search
(alerts on and a minimum drop stored): the floor the drop of a Listing is
measured from. It also gains the local date of the last drop email, the daily
window of the drop pass, separate from the new-match one.

``saved_search_price_drop_alerts`` holds one row per alerted Listing of a
Property a drop email carried: the price the comparison started from, the
Listing's price when the email left and the threshold the email stated.
There is no pending state. That price is the reference of the next
comparison for that search and Listing. Rows go with their search, Property
or Listing (``CASCADE``).

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-10-08 23:30:00.000000

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "a8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None

SEARCHES = "saved_searches"
ALERTS = "saved_search_price_drop_alerts"
CK_DROP = "ck_saved_search_price_drop_alerts_drop"
IX_PROPERTY = "ix_saved_search_price_drop_alerts_property_id"
IX_LOOKUP = "ix_saved_search_price_drop_alerts_lookup"


def upgrade() -> None:
    op.add_column(SEARCHES, sa.Column("price_drop_enabled_at", sa.DateTime(), nullable=True))
    op.add_column(SEARCHES, sa.Column("price_drop_last_window_on", sa.Date(), nullable=True))
    # A search that already has the switch on and a minimum stored (possible
    # through the API since Story 1.9) is active from this migration on. Without
    # a floor it would read as alerting and never send.
    op.execute(
        "UPDATE saved_searches SET price_drop_enabled_at = (now() AT TIME ZONE 'utc') "
        "WHERE notify_new_matches AND min_price_drop IS NOT NULL"
    )

    op.create_table(
        ALERTS,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("saved_search_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_listing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("listing_type", sa.String(), nullable=False),
        sa.Column("platform", sa.String(), nullable=True),
        sa.Column("reference_price", sa.Float(), nullable=False),
        sa.Column("new_price", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("new_price < reference_price AND threshold >= 0", name=CK_DROP),
        sa.ForeignKeyConstraint(["saved_search_id"], ["saved_searches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["property_listing_id"], ["property_listings.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(IX_PROPERTY, ALERTS, ["property_id"], unique=False)
    op.create_index(
        IX_LOOKUP, ALERTS, ["saved_search_id", "property_listing_id", "sent_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(IX_LOOKUP, table_name=ALERTS)
    op.drop_index(IX_PROPERTY, table_name=ALERTS)
    op.drop_table(ALERTS)
    op.drop_column(SEARCHES, "price_drop_last_window_on")
    op.drop_column(SEARCHES, "price_drop_enabled_at")
