"""add singer_removals table

Revision ID: 5776b1e9eb1e
Revises: 000000000011
Create Date: 2026-07-18 17:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "5776b1e9eb1e"
down_revision: Union[str, None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "singer_removals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("venue_id", sa.String(36), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("singer_id", sa.String(36), sa.ForeignKey("singers.id"), nullable=False),
        sa.Column("removed_by_device_id", sa.String(36), sa.ForeignKey("kj_devices.id"), nullable=True),
        sa.Column("removed_by_account_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("removed_at", sa.Text, nullable=False),
        sa.Column("acknowledged_at", sa.Text, nullable=True),
    )
    op.create_index("ix_singer_removals_venue_singer", "singer_removals", ["venue_id", "singer_id"])
    op.create_index("ix_singer_removals_venue_ack", "singer_removals", ["venue_id", "acknowledged_at"])


def downgrade() -> None:
    op.drop_index("ix_singer_removals_venue_ack", table_name="singer_removals")
    op.drop_index("ix_singer_removals_venue_singer", table_name="singer_removals")
    op.drop_table("singer_removals")
