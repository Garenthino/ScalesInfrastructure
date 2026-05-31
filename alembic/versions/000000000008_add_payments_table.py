"""add payments table

Revision ID: 000000000008
Revises: 3018e1b57c5d
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '000000000008'
down_revision: Union[str, None] = '3018e1b57c5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("venue_id", sa.String(36), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("singer_id", sa.String(36), sa.ForeignKey("singers.id"), nullable=False),
        sa.Column("recipient_id", sa.String(36), sa.ForeignKey("singers.id"), nullable=True),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.Text, default="USD"),
        sa.Column("payment_type", sa.Text, nullable=False),
        sa.Column("stripe_payment_intent_id", sa.Text, unique=True),
        sa.Column("status", sa.Text, nullable=False, default="pending"),
        sa.Column("metadata_json", sa.Text),
        sa.Column("reference_type", sa.Text),
        sa.Column("reference_id", sa.Text),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.Column("deleted_at", sa.Text),
    )
    op.create_index("ix_payments_venue_singer", "payments", ["venue_id", "singer_id"])
    op.create_index("ix_payments_stripe_pi", "payments", ["stripe_payment_intent_id"])
    op.create_check_constraint(
        "ck_payment_type",
        "payments",
        "payment_type IN ('tip','priority_bump')",
    )
    op.create_check_constraint(
        "ck_payment_status",
        "payments",
        "status IN ('pending','succeeded','failed','canceled')",
    )


def downgrade() -> None:
    op.drop_index("ix_payments_stripe_pi", table_name="payments")
    op.drop_index("ix_payments_venue_singer", table_name="payments")
    op.drop_table("payments")
