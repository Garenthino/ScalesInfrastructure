"""add points_ledger and singer_achievements tables

Revision ID: 000000000007
Revises: 000000000006
Create Date: 2026-06-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '000000000007'
down_revision: Union[str, None] = '000000000006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "points_ledger",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("venue_id", sa.String(36), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("singer_id", sa.String(36), sa.ForeignKey("singers.id"), nullable=False),
        sa.Column("amount", sa.Integer, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("reference_type", sa.Text, nullable=True),
        sa.Column("reference_id", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Index("ix_points_venue_singer", "venue_id", "singer_id"),
        sa.Index("ix_points_venue_created", "venue_id", "created_at"),
        sa.Index("ix_points_singer_type", "singer_id", "reference_type"),
    )

    op.create_table(
        "singer_achievements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("venue_id", sa.String(36), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("singer_id", sa.String(36), sa.ForeignKey("singers.id"), nullable=False),
        sa.Column("achievement_key", sa.Text, nullable=False),
        sa.Column("unlocked_at", sa.Text, nullable=True),
        sa.Column("progress", sa.Integer, default=0),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.UniqueConstraint("venue_id", "singer_id", "achievement_key", name="uq_singer_achievement"),
        sa.Index("ix_singer_achievements_singer", "singer_id"),
    )


def downgrade() -> None:
    op.drop_table("singer_achievements")
    op.drop_table("points_ledger")
