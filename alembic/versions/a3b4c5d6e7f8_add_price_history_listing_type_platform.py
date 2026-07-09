"""add_price_history_listing_type_platform

Revision ID: a3b4c5d6e7f8
Revises: 97cc5c6e9880
Create Date: 2026-07-09 00:12:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3b4c5d6e7f8'
down_revision = '97cc5c6e9880'
branch_labels = None
depends_on = None


def upgrade():
    # Add listing_type column — default 'sale' for existing rows
    op.add_column(
        'price_history',
        sa.Column('listing_type', sa.String(), nullable=False, server_default='sale'),
    )
    # Drop server_default after migration — the app will set it explicitly
    op.alter_column('price_history', 'listing_type', server_default=None)

    # Add platform column
    op.add_column(
        'price_history',
        sa.Column('platform', sa.String(), nullable=True),
    )

    # Add property_listing_id FK
    op.add_column(
        'price_history',
        sa.Column(
            'property_listing_id',
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey('property_listings.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )

    # Composite index for efficient per-listing-type queries
    op.create_index(
        'ix_price_history_prop_type_platform',
        'price_history',
        ['property_id', 'listing_type', 'platform'],
    )


def downgrade():
    op.drop_index('ix_price_history_prop_type_platform', table_name='price_history')
    op.drop_column('price_history', 'property_listing_id')
    op.drop_column('price_history', 'platform')
    op.drop_column('price_history', 'listing_type')