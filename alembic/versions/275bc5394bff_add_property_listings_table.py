"""add_property_listings_table

Revision ID: 275bc5394bff
Revises: b64c262168da
Create Date: 2026-07-07 03:38:08.169791

"""
from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision = '275bc5394bff'
down_revision = 'b64c262168da'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('property_listings',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('property_id', sa.UUID(), nullable=False),
        sa.Column('platform', sa.String(), nullable=False),
        sa.Column('platform_listing_id', sa.String(), nullable=False),
        sa.Column('listing_type', sa.String(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=True),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('is_furnished', sa.Boolean(), nullable=True),
        sa.Column('accepts_pets', sa.Boolean(), nullable=True),
        sa.Column('condo_fee', sa.Float(), nullable=True),
        sa.Column('iptu', sa.Float(), nullable=True),
        sa.Column('raw_json', sa.JSON(), nullable=True),
        sa.Column('first_seen', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('last_seen', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=True),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('platform', 'platform_listing_id', 'listing_type', name='uq_platform_listing'),
    )
    op.create_index(op.f('ix_property_listings_property_id'), 'property_listings', ['property_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_property_listings_property_id'), table_name='property_listings')
    op.drop_table('property_listings')