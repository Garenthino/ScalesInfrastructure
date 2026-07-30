"""add rejected_at rejected_by retention to queue_requests

Revision ID: 3ad7aa9fa593
Revises: 20260724_231548_add_tempo_pitch_to_queue_requests
Create Date: 2026-07-30 20:09:42.451411

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3ad7aa9fa593'
down_revision: Union[str, None] = '20260724_231548_add_tempo_pitch_to_queue_requests'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('queue_requests', sa.Column('rejected_at', sa.Text(), nullable=True))
    op.add_column('queue_requests', sa.Column('rejected_by', sa.Text(), nullable=True))
    op.add_column('queue_requests', sa.Column('rejection_retention_until', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('queue_requests', 'rejection_retention_until')
    op.drop_column('queue_requests', 'rejected_by')
    op.drop_column('queue_requests', 'rejected_at')
