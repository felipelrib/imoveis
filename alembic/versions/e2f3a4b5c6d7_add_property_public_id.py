"""Add sequential public_id for shareable property URLs (BIN-82).

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-07-27 05:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("properties")}
    if "public_id" in cols:
        # Recover from an earlier revision-id collision where this column
        # was applied under d1e2f3a4b5c6 before BIN-84 claimed that id.
        op.execute(sa.text("CREATE SEQUENCE IF NOT EXISTS properties_public_id_seq"))
        op.execute(
            sa.text(
                """
                SELECT setval(
                    'properties_public_id_seq',
                    GREATEST(COALESCE((SELECT MAX(public_id) FROM properties), 0), 1),
                    (SELECT COUNT(*) > 0 FROM properties)
                )
                """
            )
        )
        op.execute(
            sa.text(
                "ALTER SEQUENCE properties_public_id_seq OWNED BY properties.public_id"
            )
        )
        existing = {
            cons["name"]
            for cons in inspect(bind).get_unique_constraints("properties")
        }
        if "uq_properties_public_id" not in existing:
            op.create_unique_constraint(
                "uq_properties_public_id", "properties", ["public_id"]
            )
        return

    op.execute(sa.text("CREATE SEQUENCE IF NOT EXISTS properties_public_id_seq"))
    op.add_column(
        "properties",
        sa.Column("public_id", sa.BigInteger(), nullable=True),
    )
    # Stable assignment: oldest first so early scrapes get low numbers.
    op.execute(
        sa.text(
            """
            WITH numbered AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           ORDER BY first_seen NULLS LAST, id
                       ) AS rn
                FROM properties
            )
            UPDATE properties AS p
            SET public_id = numbered.rn
            FROM numbered
            WHERE p.id = numbered.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            SELECT setval(
                'properties_public_id_seq',
                GREATEST(COALESCE((SELECT MAX(public_id) FROM properties), 0), 1),
                (SELECT COUNT(*) > 0 FROM properties)
            )
            """
        )
    )
    op.alter_column(
        "properties",
        "public_id",
        existing_type=sa.BigInteger(),
        nullable=False,
        server_default=sa.text("nextval('properties_public_id_seq')"),
    )
    op.execute(
        sa.text(
            "ALTER SEQUENCE properties_public_id_seq OWNED BY properties.public_id"
        )
    )
    op.create_unique_constraint("uq_properties_public_id", "properties", ["public_id"])


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("properties")}
    if "public_id" not in cols:
        return
    existing = {
        cons["name"] for cons in inspect(bind).get_unique_constraints("properties")
    }
    if "uq_properties_public_id" in existing:
        op.drop_constraint("uq_properties_public_id", "properties", type_="unique")
    op.drop_column("properties", "public_id")
    op.execute(sa.text("DROP SEQUENCE IF EXISTS properties_public_id_seq"))
