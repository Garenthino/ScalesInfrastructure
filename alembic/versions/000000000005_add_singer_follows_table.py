"""add singer_follows table

Revision ID: 000000000005
Revises: 000000000004
Create Date: 2026-05-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '000000000005'
down_revision: Union[str, None] = '000000000004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "singer_follows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("venue_id", sa.String(36), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("follower_id", sa.String(36), sa.ForeignKey("singers.id"), nullable=False),
        sa.Column("followee_id", sa.String(36), sa.ForeignKey("singers.id"), nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("deleted_at", sa.Text),
    )
    op.create_index("ix_singer_follows_venue", "singer_follows", ["venue_id"])
    op.create_index("ix_singer_follows_follower", "singer_follows", ["follower_id"])
    op.create_index("ix_singer_follows_followee", "singer_follows", ["followee_id"])
    op.create_unique_constraint("uq_follow", "singer_follows", ["venue_id", "follower_id", "followee_id"])


def downgrade() -> None:
    op.drop_index("ix_singer_follows_followee", table_name="singer_follows")
    op.drop_index("ix_singer_follows_follower", table_name="singer_follows")
    op.drop_index("ix_singer_follows_venue", table_name="singer_follows")
    op.drop_table("singer_follows")
