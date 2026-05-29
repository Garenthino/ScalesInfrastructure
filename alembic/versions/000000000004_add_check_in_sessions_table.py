"""add check_in_sessions table

Revision ID: 000000000004
Revises: 000000000003
Create Date: 2026-05-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '000000000004'
down_revision: Union[str, None] = '000000000003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "check_in_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("singer_id", sa.String(36), sa.ForeignKey("singers.id"), nullable=False),
        sa.Column("venue_id", sa.String(36), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("checked_in_at", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text),
        sa.Column("table_number", sa.Text),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("ix_checkin_venue_expires", "check_in_sessions", ["venue_id", "expires_at"])
    op.create_index("ix_checkin_singer_expires", "check_in_sessions", ["singer_id", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_checkin_singer_expires", table_name="check_in_sessions")
    op.drop_index("ix_checkin_venue_expires", table_name="check_in_sessions")
    op.drop_table("check_in_sessions")
