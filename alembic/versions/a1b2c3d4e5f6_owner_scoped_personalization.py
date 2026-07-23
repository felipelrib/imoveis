"""Align owner columns with Principal.id; scope watchlist by owner.

Revision ID: a1b2c3d4e5f6
Revises: f9a0b1c2d3e4
Create Date: 2026-07-23 19:30:00.000000

Single-tenant attribution: existing null/legacy rows get owner = 'default'
(matching AuthConfig.principal_id default).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None

DEFAULT_OWNER = "default"


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return rows is not None


def upgrade() -> None:
    # --- favourites: UUID owner → VARCHAR ---
    op.execute(
        "ALTER TABLE favourites ALTER COLUMN owner TYPE VARCHAR "
        "USING owner::text"
    )
    op.execute(f"UPDATE favourites SET owner = '{DEFAULT_OWNER}' WHERE owner IS NULL")
    op.drop_constraint("uq_favourite_property", "favourites", type_="unique")
    op.create_unique_constraint(
        "uq_favourite_owner_property",
        "favourites",
        ["owner", "property_id"],
    )

    # --- saved_searches: UUID owner → VARCHAR ---
    op.execute(
        "ALTER TABLE saved_searches ALTER COLUMN owner TYPE VARCHAR "
        "USING owner::text"
    )
    op.execute(
        f"UPDATE saved_searches SET owner = '{DEFAULT_OWNER}' WHERE owner IS NULL"
    )

    # --- watchlist: add owner, drop drifted user_id if present ---
    if not _has_column("watchlist", "owner"):
        op.add_column("watchlist", sa.Column("owner", sa.String(), nullable=True))

    if _has_column("watchlist", "user_id"):
        op.execute(
            f"UPDATE watchlist SET owner = COALESCE(user_id, '{DEFAULT_OWNER}') "
            "WHERE owner IS NULL"
        )
        op.drop_column("watchlist", "user_id")
    else:
        op.execute(
            f"UPDATE watchlist SET owner = '{DEFAULT_OWNER}' WHERE owner IS NULL"
        )

    op.drop_constraint("uq_watchlist_property", "watchlist", type_="unique")
    op.create_unique_constraint(
        "uq_watchlist_owner_property",
        "watchlist",
        ["owner", "property_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_watchlist_owner_property", "watchlist", type_="unique")
    op.create_unique_constraint(
        "uq_watchlist_property", "watchlist", ["property_id"]
    )
    op.add_column("watchlist", sa.Column("user_id", sa.String(), nullable=True))
    op.execute("UPDATE watchlist SET user_id = owner")
    op.drop_column("watchlist", "owner")

    op.execute(
        "ALTER TABLE saved_searches ALTER COLUMN owner TYPE UUID "
        "USING CASE WHEN owner ~ "
        "'^[0-9a-fA-F-]{36}$' THEN owner::uuid ELSE NULL END"
    )

    op.drop_constraint("uq_favourite_owner_property", "favourites", type_="unique")
    op.create_unique_constraint(
        "uq_favourite_property", "favourites", ["property_id"]
    )
    op.execute(
        "ALTER TABLE favourites ALTER COLUMN owner TYPE UUID "
        "USING CASE WHEN owner ~ "
        "'^[0-9a-fA-F-]{36}$' THEN owner::uuid ELSE NULL END"
    )
