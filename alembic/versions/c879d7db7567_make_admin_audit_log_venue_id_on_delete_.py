"""make admin_audit_log venue_id on delete set null

Revision ID: c879d7db7567
Revises: 20260629_170100
Create Date: 2026-07-02 16:24:44.723765

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c879d7db7567'
down_revision: Union[str, None] = '20260629_170100'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The original admin_audit_logs migration created a plain FK without
    # ON DELETE behavior. When a venue is hard-deleted we want to keep the
    # audit trail row and just clear venue_id, rather than failing with a
    # foreign-key violation or cascading the deletion into audit history.
    op.drop_constraint('admin_audit_logs_venue_id_fkey', 'admin_audit_logs', type_='foreignkey')
    op.create_foreign_key(
        'admin_audit_logs_venue_id_fkey',
        'admin_audit_logs',
        'venues',
        ['venue_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('admin_audit_logs_venue_id_fkey', 'admin_audit_logs', type_='foreignkey')
    op.create_foreign_key(
        'admin_audit_logs_venue_id_fkey',
        'admin_audit_logs',
        'venues',
        ['venue_id'],
        ['id'],
    )
