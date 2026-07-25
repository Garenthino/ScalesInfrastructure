"""add tempo and pitch to queue_requests

Revision ID: 20260724_231548_add_tempo_pitch_to_queue_requests
Revises: None
Create Date: 2026-07-24 23:15:48.833154

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260724_231548_add_tempo_pitch_to_queue_requests'
down_revision: Union[str, None] = '09554556e9a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('queue_requests', sa.Column('tempo', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('queue_requests', sa.Column('pitch', sa.Integer(), nullable=True, server_default='0'))


def downgrade() -> None:
    op.drop_column('queue_requests', 'pitch')
    op.drop_column('queue_requests', 'tempo')
