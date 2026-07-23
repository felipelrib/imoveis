"""Add properties.embedding (pgvector) for semantic search

Revision ID: e8a1b2c3d4e5
Revises: 33f5df56dd1c
Create Date: 2026-07-23 05:20:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "e8a1b2c3d4e5"
down_revision = "33f5df56dd1c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE properties ADD COLUMN embedding vector(768)")
    op.execute(
        "CREATE INDEX ix_properties_embedding_hnsw ON properties "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_properties_embedding_hnsw")
    op.execute("ALTER TABLE properties DROP COLUMN IF EXISTS embedding")
    op.execute("DROP EXTENSION IF EXISTS vector")
