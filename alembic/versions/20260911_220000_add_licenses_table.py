"""Add licenses table for offline desktop activation.

Revision ID: 20260911_220000
Revises: 20260905_005257_add_venue_file_path_index
Create Date: 2026-09-11 22:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260911_220000"
down_revision: Union[str, None] = "20260905_005257"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "licenses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("venue_id", sa.String(36), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("license_key_hash", sa.Text(), nullable=False),
        sa.Column("license_key_prefix", sa.Text(), nullable=False),
        sa.Column("fingerprint_hash", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="unactivated"),
        sa.Column("plan", sa.Text(), nullable=False, server_default="basic"),
        sa.Column("seat_limit", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.Text(), nullable=True),
        sa.Column("grace_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("activated_at", sa.Text(), nullable=True),
        sa.Column("last_check_in_at", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("venue_id", "license_key_hash", name="uq_license_venue_key"),
        sa.Index("ix_licenses_venue", "venue_id", "status"),
        sa.Index("ix_licenses_key_prefix", "license_key_prefix"),
    )


def downgrade() -> None:
    op.drop_table("licenses")
