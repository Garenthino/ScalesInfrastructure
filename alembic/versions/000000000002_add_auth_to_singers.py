"""Add role and password_hash to singers

Revision ID: 000000000002
Revises: 000000000001
Create Date: 2026-05-20 14:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '000000000002'
down_revision: Union[str, None] = '000000000001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("singers") as batch_op:
        batch_op.add_column(
            sa.Column("role", sa.Text, server_default="singer", nullable=False)
        )
        batch_op.add_column(
            sa.Column("password_hash", sa.Text, nullable=True)
        )
    op.create_index("ix_singers_role", "singers", ["role"])


def downgrade() -> None:
    op.drop_index("ix_singers_role", table_name="singers")
    with op.batch_alter_table("singers") as batch_op:
        batch_op.drop_column("password_hash")
        batch_op.drop_column("role")
