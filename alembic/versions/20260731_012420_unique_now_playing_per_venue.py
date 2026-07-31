"""unique_now_playing_per_venue

Revision ID: 20260731_012420_unique_now_playing_per_venue
Revises: 20260730_183000_add_source_to_queue_requests
Create Date: 2026-07-31T01:24:20.622840

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260731_012420_unique_now_playing_per_venue'
down_revision: Union[str, None] = '20260730_183000_add_source_to_queue_requests'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Deduplicate existing now_playing rows, keeping the most recently updated.
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY venue_id
                       ORDER BY updated_at DESC NULLS LAST, requested_at DESC NULLS LAST
                   ) AS rn
            FROM queue_requests
            WHERE status = 'now_playing'
              AND deleted_at IS NULL
        )
        UPDATE queue_requests
        SET status = 'pending',
            updated_at = CURRENT_TIMESTAMP
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
    """)

    # Create a unique partial index so a venue can only have one active now_playing row.
    op.create_index(
        'ix_queue_requests_venue_now_playing_unique',
        'queue_requests',
        ['venue_id'],
        unique=True,
        postgresql_where=sa.text("status = 'now_playing' AND deleted_at IS NULL"),
        postgresql_using='btree',
    )


def downgrade() -> None:
    op.drop_index('ix_queue_requests_venue_now_playing_unique', table_name='queue_requests')
