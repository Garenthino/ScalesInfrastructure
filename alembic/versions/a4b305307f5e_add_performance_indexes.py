"""add_performance_indexes

Revision ID: a4b305307f5e
Revises: 0b9bc5095c32
Create Date: 2026-05-31 20:34:17.906074

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4b305307f5e'
down_revision: Union[str, None] = '0b9bc5095c32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure deactivated_at exists (model added it but prior migration didn't)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='singers' AND column_name='deactivated_at'
            ) THEN
                ALTER TABLE singers ADD COLUMN deactivated_at TEXT;
            END IF;
        END $$;
        """
    )
    op.create_index('singer_venue_idx', 'singers', ['venue_id', 'deactivated_at'], unique=False)
    op.create_index('queue_position_idx', 'queue_requests', ['venue_id', 'rotation_position'], unique=False)
    op.create_index('checkin_session_singer_idx', 'check_in_sessions', ['singer_id'], unique=False)


def downgrade() -> None:
    op.drop_index('checkin_session_singer_idx', table_name='check_in_sessions')
    op.drop_index('queue_position_idx', table_name='queue_requests')
    op.drop_index('singer_venue_idx', table_name='singers')
