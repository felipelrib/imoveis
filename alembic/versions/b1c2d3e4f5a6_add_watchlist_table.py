"""add_watchlist_table

Revision ID: b1c2d3e4f5a6
Revises: a3b4c5d6e7f8
Create Date: 2026-07-09 03:44:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1c2d3e4f5a6'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'watchlist',
        sa.Column(
            'id',
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            'property_id',
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey('properties.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('min_drop_pct', sa.Float(), nullable=False, server_default='5.0'),
        sa.Column('last_notified_price', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_index('ix_watchlist_property_id', 'watchlist', ['property_id'])
    op.create_unique_constraint('uq_watchlist_property', 'watchlist', ['property_id'])


def downgrade():
    op.drop_constraint('uq_watchlist_property', 'watchlist', type_='unique')
    op.drop_index('ix_watchlist_property_id', table_name='watchlist')
    op.drop_table('watchlist')