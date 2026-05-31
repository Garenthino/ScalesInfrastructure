"""add refund fields and message to payments table

Revision ID: 000000000009
Revises: 000000000008
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '000000000009'
down_revision: Union[str, None] = '000000000008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("payments") as batch_op:
        batch_op.add_column(sa.Column("message", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("refunded_at", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("refund_amount_cents", sa.Integer, server_default="0"))
        # Update check constraint to include 'refunded'
        batch_op.drop_constraint("ck_payment_status", type_="check")
        batch_op.create_check_constraint(
            "ck_payment_status",
            "status IN ('pending','succeeded','failed','canceled','refunded','partially_refunded')",
        )


def downgrade() -> None:
    with op.batch_alter_table("payments") as batch_op:
        batch_op.drop_constraint("ck_payment_status", type_="check")
        batch_op.create_check_constraint(
            "ck_payment_status",
            "status IN ('pending','succeeded','failed','canceled')",
        )
        batch_op.drop_column("refund_amount_cents")
        batch_op.drop_column("refunded_at")
        batch_op.drop_column("message")
