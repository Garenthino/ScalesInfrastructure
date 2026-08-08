"""Add host_rotation table

Revision ID: 20260808193649
Revises: 20260731_012420_unique_now_playing_per_venue
Create Date: 2026-08-08T19:36:49.567675+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260808193649"
down_revision: Union[str, None] = "20260731_012420_unique_now_playing_per_venue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "host_rotation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("venue_id", sa.String(36), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("singer_id", sa.String(36), sa.ForeignKey("singers.id"), nullable=False),
        sa.Column("song_id", sa.String(36), sa.ForeignKey("songs.id"), nullable=True),
        sa.Column("rotation_session_id", sa.String(36), sa.ForeignKey("rotation_sessions.id"), nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("rotation_position", sa.Integer, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("reject_reason", sa.Text, nullable=True),
        sa.Column("tempo", sa.Integer, server_default="0"),
        sa.Column("pitch", sa.Integer, server_default="0"),
        sa.Column("source", sa.Text, nullable=False, server_default="host"),
        sa.Column("kj_id", sa.Text, nullable=True),
        sa.Column("requested_at", sa.Text, nullable=True),
        sa.Column("scheduled_at", sa.Text, nullable=True),
        sa.Column("completed_at", sa.Text, nullable=True),
        sa.Column("updated_at", sa.Text, nullable=True),
        sa.Column("deleted_at", sa.Text, nullable=True),
    )
    op.create_index("ix_host_rotation_venue_status", "host_rotation", ["venue_id", "status"])
    op.create_index("ix_host_rotation_venue_sort", "host_rotation", ["venue_id", "sort_order"])
    op.create_index("ix_host_rotation_singer_status", "host_rotation", ["singer_id", "status"])
    op.create_index("ix_host_rotation_session", "host_rotation", ["rotation_session_id"])
    op.create_check_constraint(
        "ck_host_rotation_status",
        "host_rotation",
        sa.text("status IN ('pending','up_next','now_playing','completed','skipped','rejected')"),
    )


def downgrade() -> None:
    op.drop_table("host_rotation")
