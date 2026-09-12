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
    # The index is critical for the /v1/kj/sync/songs batch upsert path.
    # CREATE INDEX CONCURRENTLY cannot run inside the Alembic transaction, so we
    # use a plain CREATE INDEX with IF NOT EXISTS to stay idempotent in case a
    # previous failed attempt left the index behind.
    op.execute("CREATE INDEX IF NOT EXISTS ix_songs_venue_file_path ON songs (venue_id, file_path)")


def downgrade() -> None:
    op.drop_index('ix_songs_venue_file_path', table_name='songs')
