"""Add gdpr_erased_at to singers

Revision ID: a114265eed3f
Revises: 40de330b5263
Create Date: 2026-06-04 12:02:34.562397

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a114265eed3f'
down_revision: Union[str, None] = '40de330b5263'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('singers', sa.Column('gdpr_erased_at', sa.Text(), nullable=True))
    op.create_index('ix_singers_gdpr_erased', 'singers', ['venue_id', 'gdpr_erased_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_singers_gdpr_erased', table_name='singers')
    op.drop_column('singers', 'gdpr_erased_at')
