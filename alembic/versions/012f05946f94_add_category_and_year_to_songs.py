"""add_category_and_year_to_songs

Revision ID: 012f05946f94
Revises: a4b305307f5e
Create Date: 2026-06-01 00:46:06.750191

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '012f05946f94'
down_revision: Union[str, None] = 'a4b305307f5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add category and year columns (nullable — matches model)
    op.add_column('songs', sa.Column('category', sa.Text(), nullable=True))
    op.add_column('songs', sa.Column('year', sa.Integer(), nullable=True))

    # Create composite indexes declared in the Song model __table_args__
    op.create_index('ix_songs_venue_genre', 'songs', ['venue_id', 'genre'], unique=False)
    op.create_index('ix_songs_venue_year', 'songs', ['venue_id', 'year'], unique=False)
    op.create_index('ix_songs_venue_category', 'songs', ['venue_id', 'category'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_songs_venue_category', table_name='songs')
    op.drop_index('ix_songs_venue_year', table_name='songs')
    op.drop_index('ix_songs_venue_genre', table_name='songs')
    op.drop_column('songs', 'year')
    op.drop_column('songs', 'category')
