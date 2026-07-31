"""add source column to queue_requests

Revision ID: 20260730_183000_add_source_to_queue_requests
Revises: 20260724_231548_add_tempo_pitch_to_queue_requests
Create Date: 2026-07-30 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260730_183000_add_source_to_queue_requests'
down_revision: Union[str, None] = '3ad7aa9fa593'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('queue_requests', sa.Column('source', sa.Text(), nullable=False, server_default='mobile'))
    op.create_check_constraint(
        'ck_queue_requests_source',
        'queue_requests',
        "source IN ('mobile', 'portal', 'host')",
    )
    op.create_index('ix_queue_requests_source', 'queue_requests', ['source'])


def downgrade() -> None:
    op.drop_index('ix_queue_requests_source', table_name='queue_requests')
    op.drop_constraint('ck_queue_requests_source', 'queue_requests', type_='check')
    op.drop_column('queue_requests', 'source')
