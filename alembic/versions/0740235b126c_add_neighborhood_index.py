"""Add neighborhood index

Revision ID: 0740235b126c
Revises: 3e4b18f30e04
Create Date: 2026-07-22 21:30:14.776669

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0740235b126c"
down_revision = "3e4b18f30e04"
branch_labels = None
depends_on = None


def upgrade():
    # CONCURRENTLY cannot run inside a transaction block
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_properties_neighborhood "
            "ON properties ((props_json->>'neighborhood'))"
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_properties_neighborhood")
