"""fix_singers_rls_coalesce

Revision ID: fix_singers_rls
Revises: 40de330b5263
Create Date: 2026-06-04 20:00:00.000000

Fix the RLS policy on the singers table so that NULL (setting not yet set)
is treated the same as empty string, allowing the login endpoint to find the
singer by email before it knows the venue_id.
"""
from __future__ import annotations

from alembic import op

revision: str = "fix_singers_rls"
down_revision: str = "40de330b5263"


def upgrade() -> None:
    # Drop the old policy if it exists (uses bare current_setting which fails on NULL)
    op.execute("DROP POLICY IF EXISTS app_tenant_isolation_singers ON singers")

    # Create corrected policy that coalesces NULL to ''
    op.execute(
        """
        CREATE POLICY app_tenant_isolation_singers
            ON singers
            FOR ALL
            TO PUBLIC
            USING (
                COALESCE(current_setting('app.current_venue_id', true), '') = ''
                OR (venue_id IS NOT NULL
                    AND venue_id = current_setting('app.current_venue_id', true))
            )
            WITH CHECK (
                COALESCE(current_setting('app.current_venue_id', true), '') = ''
                OR (venue_id IS NOT NULL
                    AND venue_id = current_setting('app.current_venue_id', true))
            )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS app_tenant_isolation_singers ON singers")
    op.execute(
        """
        CREATE POLICY app_tenant_isolation_singers
            ON singers
            FOR ALL
            TO PUBLIC
            USING (
                (current_setting('app.current_venue_id', true) = '')
                OR (venue_id IS NOT NULL
                    AND venue_id = current_setting('app.current_venue_id', true))
            )
            WITH CHECK (
                (current_setting('app.current_venue_id', true) = '')
                OR (venue_id IS NOT NULL
                    AND venue_id = current_setting('app.current_venue_id', true))
            )
        """
    )
