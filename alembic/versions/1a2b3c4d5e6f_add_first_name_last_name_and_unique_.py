"""add first_name last_name and unique venue stage_name

Revision ID: 1a2b3c4d5e6f
Revises: cebf7fd11692
Create Date: 2026-07-09 18:07:15.781593

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, None] = 'cebf7fd11692'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add first_name/last_name and stage_name to accounts
    op.add_column('accounts', sa.Column('first_name', sa.Text(), nullable=True))
    op.add_column('accounts', sa.Column('last_name', sa.Text(), nullable=True))
    op.add_column('accounts', sa.Column('stage_name', sa.Text(), nullable=True))

    # Add first_name/last_name to singers
    op.add_column('singers', sa.Column('first_name', sa.Text(), nullable=True))
    op.add_column('singers', sa.Column('last_name', sa.Text(), nullable=True))

    # Backfill first_name/last_name from existing real_name for accounts and singers
    op.execute("""
        UPDATE accounts
        SET first_name = split_part(real_name, ' ', 1),
            last_name = nullif(substring(real_name from position(' ' in real_name) + 1), '')
        WHERE real_name IS NOT NULL AND real_name != ''
          AND first_name IS NULL AND last_name IS NULL
    """)
    op.execute("""
        UPDATE singers
        SET first_name = split_part(real_name, ' ', 1),
            last_name = nullif(substring(real_name from position(' ' in real_name) + 1), '')
        WHERE real_name IS NOT NULL AND real_name != ''
          AND first_name IS NULL AND last_name IS NULL
    """)

    # Enforce unique stage names within a venue
    op.create_unique_constraint(
        'uq_singer_venue_stage_name',
        'singers',
        ['venue_id', 'stage_name']
    )


def downgrade() -> None:
    op.drop_constraint('uq_singer_venue_stage_name', 'singers', type_='unique')
    op.drop_column('singers', 'last_name')
    op.drop_column('singers', 'first_name')
    op.drop_column('accounts', 'stage_name')
    op.drop_column('accounts', 'last_name')
    op.drop_column('accounts', 'first_name')
