"""Merge heads

Revision ID: c5e5613ec0fa
Revises: a114265eed3f, fix_singers_rls
Create Date: 2026-06-04 20:18:32.778797

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5e5613ec0fa'
down_revision: Union[str, None] = ('a114265eed3f', 'fix_singers_rls')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
