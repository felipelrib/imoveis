"""Resize properties.embedding to 1024-d for bge-m3 (BIN-73).

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-07-24 19:00:00.000000
"""

from alembic import op

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector cannot ALTER dimension in place; recreate column (clears old 768-d rows).
    op.execute("DROP INDEX IF EXISTS ix_properties_embedding_hnsw")
    op.execute("ALTER TABLE properties DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE properties ADD COLUMN embedding vector(1024)")
    op.execute(
        "CREATE INDEX ix_properties_embedding_hnsw ON properties "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_properties_embedding_hnsw")
    op.execute("ALTER TABLE properties DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE properties ADD COLUMN embedding vector(768)")
    op.execute(
        "CREATE INDEX ix_properties_embedding_hnsw ON properties "
        "USING hnsw (embedding vector_cosine_ops)"
    )
