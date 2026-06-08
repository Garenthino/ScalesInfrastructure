"""add song sync fields

Revision ID: 20260607
Revises: c5e5613ec0fa
Create Date: 2026-06-07 04:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260607'
down_revision: Union[str, None] = 'c5e5613ec0fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('songs', sa.Column('file_path', sa.Text(), nullable=True))
    op.add_column('songs', sa.Column('file_hash', sa.Text(), nullable=True))
    op.add_column('songs', sa.Column('file_size', sa.BigInteger(), nullable=True))
    op.add_column('songs', sa.Column('unavailable_reason', sa.Text(), nullable=True))
    op.add_column('songs', sa.Column('last_scanned_at', sa.Text(), nullable=True))
    op.add_column('songs', sa.Column('metadata_locked', sa.Integer(), nullable=True, server_default='0'))


def downgrade() -> None:
    op.drop_column('songs', 'metadata_locked')
    op.drop_column('songs', 'last_scanned_at')
    op.drop_column('songs', 'unavailable_reason')
    op.drop_column('songs', 'file_size')
    op.drop_column('songs', 'file_hash')
    op.drop_column('songs', 'file_path')
