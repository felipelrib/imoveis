"""Add indexes on properties.active and metrics_scoring.property_id

Revision ID: b65411932ef9
Revises: 3116c5d5061f
Create Date: 2026-07-30 00:41:53.959585

BIN-152: `WHERE p.active = true` appears in nearly every hot-path query
(list_properties, export_properties, count queries, neighbourhoods/cities
aggregates) and `metrics_scoring.property_id` is joined in every properties
list/detail/export query. Neither column has an index today.

Distribution check (production data, 2026-07-30, `docker compose exec postgres
psql`): `properties.active` is 25,371 true / 817 false (~96.9% / ~3.1%) out of
26,188 rows. Because the hot-path predicate (`active = true`) matches the
overwhelming majority of rows, a partial index scoped to `WHERE active` would
still cover ~97% of the table — negligible size/selectivity benefit over a
plain index, so we use a full (non-partial) index here rather than a partial
one. `metrics_scoring.property_id` is a plain FK/join column (one row per
property, no skew) — indexed unconditionally, matching the existing
`ForeignKey` pattern used elsewhere in this table's neighbors
(`properties.platform_id`, `properties.neighborhood_id`).

Uses `CREATE INDEX CONCURRENTLY` (autocommit block) so index creation doesn't
hold a table-locking transaction on `properties` / `metrics_scoring` at
current or future volume; downgrade drops both, also concurrently.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "b65411932ef9"
down_revision = "3116c5d5061f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_properties_active",
            "properties",
            ["active"],
            unique=False,
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_metrics_scoring_property_id",
            "metrics_scoring",
            ["property_id"],
            unique=False,
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_metrics_scoring_property_id",
            table_name="metrics_scoring",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            "ix_properties_active",
            table_name="properties",
            postgresql_concurrently=True,
            if_exists=True,
        )
