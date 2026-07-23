"""Add admin_audit table

Revision ID: 33f5df56dd1c
Revises: 0740235b126c
Create Date: 2026-07-22 23:43:52.407199

"""
import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = '33f5df56dd1c'
down_revision = '0740235b126c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'admin_audit',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('performed_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('admin_audit')
