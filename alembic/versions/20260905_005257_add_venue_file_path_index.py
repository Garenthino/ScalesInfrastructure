"""add venue_file_path index

Revision ID: 20260905_005257
Revises: 
Create Date: 2026-09-05T00:52:57.169367+00:00

"""
from typing import Sequence, Union
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '20260905_005257'
down_revision: Union[str, None] = '20260808210827'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CONCURRENTLY is safe on production and avoids locking the songs table while
    # KJ desktop syncs may be running. The index is critical for the
    # /v1/kj/sync/songs batch upsert path.
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_songs_venue_file_path ON songs (venue_id, file_path)")


def downgrade() -> None:
    op.drop_index('ix_songs_venue_file_path', table_name='songs')
