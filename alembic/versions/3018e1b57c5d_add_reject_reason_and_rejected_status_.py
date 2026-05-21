"""add reject_reason and rejected status to queue_requests

Revision ID: 3018e1b57c5d
Revises: 000000000002
Create Date: 2026-05-21 10:16:55.762283

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3018e1b57c5d'
down_revision: Union[str, None] = '000000000002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite requires table recreation to alter CHECK constraints.
    with op.batch_alter_table('queue_requests', recreate='always') as batch_op:
        batch_op.add_column(sa.Column('reject_reason', sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            'ck_queue_requests_status',
            "status IN ('pending','approved','now_playing','completed','skipped','rejected')",
        )


def downgrade() -> None:
    with op.batch_alter_table('queue_requests', recreate='always') as batch_op:
        batch_op.drop_column('reject_reason')
        batch_op.create_check_constraint(
            'ck_queue_requests_status',
            "status IN ('pending','approved','now_playing','completed','skipped')",
        )
