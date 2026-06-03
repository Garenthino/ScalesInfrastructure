"""add_rls_to_audit_logs

Revision ID: 40de330b5263
Revises: bce9f1a12d34
Create Date: 2026-06-01 15:38:18.000000

Enable Row-Level Security on audit_logs.  Unlike other venue-scoped tables,
audit_logs has a nullable venue_id (platform-level audit entries).  The
policy allows admin bypass (empty string) and matches rows where venue_id
equals the current session venue_id.  Rows with NULL venue_id are hidden
from non-admin users.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "40de330b5263"
down_revision: Union[str, None] = "bce9f1a12d34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY app_tenant_isolation_audit_logs
            ON audit_logs
            FOR ALL
            TO PUBLIC
            USING (
                (current_setting('app.current_venue_id', true) = '')
                OR (
                    venue_id IS NOT NULL
                    AND venue_id = current_setting('app.current_venue_id', true)
                )
            )
            WITH CHECK (
                (current_setting('app.current_venue_id', true) = '')
                OR (
                    venue_id IS NOT NULL
                    AND venue_id = current_setting('app.current_venue_id', true)
                )
            )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS app_tenant_isolation_audit_logs ON audit_logs")
    op.execute("ALTER TABLE audit_logs NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY")
