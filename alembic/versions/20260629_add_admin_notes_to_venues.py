"""Add admin_notes column to venues.

Revision ID: 20260629_add_admin_notes_to_venues
Revises: e04135815a62
Create Date: 2026-06-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '20260629_add_admin_notes_to_venues'
down_revision: Union[str, None] = 'e04135815a62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('venues', sa.Column('admin_notes', sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column('venues', 'admin_notes')
