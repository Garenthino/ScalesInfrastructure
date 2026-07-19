"""add_allow_priority_bump_to_venues

Revision ID: 09554556e9a0
Revises: 5776b1e9eb1e
Create Date: 2026-07-19 16:48:25.237045

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '09554556e9a0'
down_revision: Union[str, None] = '5776b1e9eb1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Priority-bump feature flag for Android singer queue.
    # Stored as integer 0/1 for SQLite/PostgreSQL portability, default false (0).
    op.add_column('venues', sa.Column('allow_priority_bump', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('venues', 'allow_priority_bump')
