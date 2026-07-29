"""GIST index on properties.location for spatial filters

Revision ID: f4eea36d6f80
Revises: a4f8c2e91b7d
Create Date: 2026-07-29 05:50:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "f4eea36d6f80"
down_revision = "a4f8c2e91b7d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Initial create_table used Geometry(spatial_index=True), so fresh installs
    # already have GeoAlchemy2's idx_properties_location GIST. Rename that to
    # the project-canonical name (parity with ix_neighborhoods_geometry_gist);
    # create only when neither name exists. Drop the legacy name if both exist
    # so we never keep two identical GISTs on location (BIN-121).
    op.execute(
        """
        DO $mig$
        BEGIN
          IF to_regclass('public.idx_properties_location') IS NOT NULL
             AND to_regclass('public.ix_properties_location_gist') IS NULL THEN
            ALTER INDEX idx_properties_location
              RENAME TO ix_properties_location_gist;
          ELSIF to_regclass('public.ix_properties_location_gist') IS NULL THEN
            CREATE INDEX ix_properties_location_gist
              ON properties USING GIST (location);
          END IF;
          IF to_regclass('public.idx_properties_location') IS NOT NULL
             AND to_regclass('public.ix_properties_location_gist') IS NOT NULL THEN
            DROP INDEX idx_properties_location;
          END IF;
        END
        $mig$;
        """
    )


def downgrade() -> None:
    # Restore GeoAlchemy2's default name so a re-upgrade can rename again.
    op.execute(
        """
        DO $mig$
        BEGIN
          IF to_regclass('public.ix_properties_location_gist') IS NOT NULL
             AND to_regclass('public.idx_properties_location') IS NULL THEN
            ALTER INDEX ix_properties_location_gist
              RENAME TO idx_properties_location;
          ELSIF to_regclass('public.ix_properties_location_gist') IS NOT NULL THEN
            DROP INDEX ix_properties_location_gist;
          END IF;
        END
        $mig$;
        """
    )
