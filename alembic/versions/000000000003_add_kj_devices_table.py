"""add kj_devices table

Revision ID: 000000000003
Revises: 3018e1b57c5d
Create Date: 2026-07-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '000000000003'
down_revision: Union[str, None] = '3018e1b57c5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kj_devices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("venue_id", sa.String(36), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("api_key_hash", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("last_seen", sa.Text, nullable=True),
        sa.Column("revoked_at", sa.Text, nullable=True),
    )
    op.create_index("ix_kj_devices_venue_id", "kj_devices", ["venue_id"])


def downgrade() -> None:
    op.drop_index("ix_kj_devices_venue_id", table_name="kj_devices")
    op.drop_table("kj_devices")
