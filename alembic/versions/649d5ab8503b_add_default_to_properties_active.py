"""add_default_to_properties_active

Revision ID: 649d5ab8503b
Revises: 275bc5394bff
Create Date: 2026-07-08 14:08:40.032468

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = '649d5ab8503b'
down_revision = '275bc5394bff'
branch_labels = None
depends_on = None


def upgrade():
    # Backfill existing NULL active values to true
    op.execute("UPDATE properties SET active = true WHERE active IS NULL")
    # Add server_default for future inserts
    op.alter_column(
        'properties', 'active',
        server_default=sa.text('true'),
        existing_type=sa.Boolean(),
        existing_nullable=True,
    )


def downgrade():
    # Remove the server default (keep column as nullable)
    op.alter_column(
        'properties', 'active',
        server_default=None,
        existing_type=sa.Boolean(),
        existing_nullable=True,
    )
