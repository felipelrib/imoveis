"""align_property_listings_schema_with_model

Revision ID: 97cc5c6e9880
Revises: 649d5ab8503b
Create Date: 2026-07-09 00:59:58.123456

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '97cc5c6e9880'
down_revision = '649d5ab8503b'
branch_labels = None
depends_on = None


def upgrade():
    # Drop old unique constraint before renaming columns
    op.drop_constraint('uq_platform_id_type', 'property_listings', type_='unique')

    # Rename columns to match the model
    op.alter_column('property_listings', 'platform_id',
                     new_column_name='platform_listing_id',
                     existing_type=sa.String(),
                     existing_nullable=False)
    op.alter_column('property_listings', 'discovered_at',
                     new_column_name='first_seen',
                     existing_type=sa.DateTime(),
                     existing_nullable=True,
                     server_default=sa.text('now()'))
    op.alter_column('property_listings', 'last_seen_at',
                     new_column_name='last_seen',
                     existing_type=sa.DateTime(),
                     existing_nullable=True,
                     server_default=sa.text('now()'))

    # Add missing nullable columns
    op.add_column('property_listings', sa.Column('currency', sa.String(3), nullable=True))
    op.add_column('property_listings', sa.Column('is_furnished', sa.Boolean(), nullable=True))
    op.add_column('property_listings', sa.Column('accepts_pets', sa.Boolean(), nullable=True))
    op.add_column('property_listings', sa.Column('condo_fee', sa.Float(), nullable=True))
    op.add_column('property_listings', sa.Column('iptu', sa.Float(), nullable=True))
    op.add_column('property_listings', sa.Column('raw_json', sa.JSON(), nullable=True))
    op.add_column('property_listings', sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=True))

    # Recreate unique constraint with correct column name
    op.create_unique_constraint(
        'uq_platform_listing', 'property_listings',
        ['platform', 'platform_listing_id', 'listing_type'],
    )


def downgrade():
    op.drop_constraint('uq_platform_listing', 'property_listings', type_='unique')

    # Drop added columns
    op.drop_column('property_listings', 'active')
    op.drop_column('property_listings', 'raw_json')
    op.drop_column('property_listings', 'iptu')
    op.drop_column('property_listings', 'condo_fee')
    op.drop_column('property_listings', 'accepts_pets')
    op.drop_column('property_listings', 'is_furnished')
    op.drop_column('property_listings', 'currency')

    # Rename columns back to original names
    op.alter_column('property_listings', 'first_seen',
                     new_column_name='discovered_at',
                     existing_type=sa.DateTime(),
                     existing_nullable=True)
    op.alter_column('property_listings', 'last_seen',
                     new_column_name='last_seen_at',
                     existing_type=sa.DateTime(),
                     existing_nullable=True)
    op.alter_column('property_listings', 'platform_listing_id',
                     new_column_name='platform_id',
                     existing_type=sa.String(),
                     existing_nullable=False)

    # Restore old unique constraint
    op.create_unique_constraint(
        'uq_platform_id_type', 'property_listings',
        ['platform', 'platform_id', 'listing_type'],
    )