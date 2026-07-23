"""Add uq_property_platform_id constraint

Revision ID: 3e4b18f30e04
Revises: c7d8e9f0a1b2
Create Date: 2026-07-22 19:55:04.066034

"""
import geoalchemy2  # noqa: F401
import sqlalchemy as sa  # noqa: F401

from alembic import op

# revision identifiers, used by Alembic.
revision = '3e4b18f30e04'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint('uq_property_platform_id', 'properties', ['platform', 'platform_id'])


def downgrade():
    op.drop_constraint('uq_property_platform_id', 'properties', type_='unique')
