"""add_admin_audit_logs_table

Revision ID: 20260629_170100
Revises: 20260629_add_admin_notes_to_venues
Create Date: 2026-06-29 17:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260629_170100'
down_revision: Union[str, None] = '20260629_add_admin_notes_to_venues'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('admin_audit_logs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('admin_email', sa.Text(), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('venue_id', sa.String(length=36), nullable=True),
        sa.Column('venue_name', sa.Text(), nullable=True),
        sa.Column('details_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_admin_audit_logs_venue', 'admin_audit_logs', ['venue_id', 'created_at'], unique=False)
    op.create_index('ix_admin_audit_logs_action', 'admin_audit_logs', ['action', 'created_at'], unique=False)
    op.create_index('ix_admin_audit_logs_admin', 'admin_audit_logs', ['admin_email', 'created_at'], unique=False)
    op.execute("ALTER TABLE admin_audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE admin_audit_logs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY app_tenant_isolation_admin_audit_logs
            ON admin_audit_logs
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
    op.execute("DROP POLICY IF EXISTS app_tenant_isolation_admin_audit_logs ON admin_audit_logs")
    op.execute("ALTER TABLE admin_audit_logs NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE admin_audit_logs DISABLE ROW LEVEL SECURITY")
    op.drop_index('ix_admin_audit_logs_admin', table_name='admin_audit_logs')
    op.drop_index('ix_admin_audit_logs_action', table_name='admin_audit_logs')
    op.drop_index('ix_admin_audit_logs_venue', table_name='admin_audit_logs')
    op.drop_table('admin_audit_logs')
