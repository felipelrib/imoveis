"""align_property_listings_schema_with_model

Revision ID: 97cc5c6e9880
Revises: 649d5ab8503b
Create Date: 2026-07-09 00:59:58.123456

This migration was originally intended to rename columns and add constraints
to property_listings, but the add_property_listings_table migration (275bc5394bff)
already creates the table with the correct schema (platform_listing_id, first_seen,
last_seen, etc.).  This migration is therefore a no-op.
"""

# revision identifiers, used by Alembic.
revision = '97cc5c6e9880'
down_revision = '649d5ab8503b'
branch_labels = None
depends_on = None


def upgrade():
    # No-op: the property_listings table was already created with the correct
    # schema in the add_property_listings_table migration.  Columns
    # (platform_listing_id, first_seen, last_seen, currency, is_furnished,
    # accepts_pets, condo_fee, iptu, raw_json, active) and the
    # uq_platform_listing constraint are already in place.
    pass


def downgrade():
    pass
