"""add up_next to queue_request status check constraint

Revision ID: 60a30fbeb261
Revises: 20260607
Create Date: 2026-06-23 16:35:22.665620

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '60a30fbeb261'
down_revision: Union[str, None] = '20260607'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STATUSES = ["pending", "approved", "up_next", "now_playing", "completed", "skipped", "rejected"]


def upgrade() -> None:
    op.execute("ALTER TABLE queue_requests DROP CONSTRAINT IF EXISTS queue_requests_status_check")
    op.execute(
        "ALTER TABLE queue_requests ADD CONSTRAINT queue_requests_status_check "
        "CHECK (status = ANY (ARRAY{}))".format(
            "[" + ",".join(f"'{s}'::text" for s in STATUSES) + "]"
        )
    )


def downgrade() -> None:
    op.execute("ALTER TABLE queue_requests DROP CONSTRAINT IF EXISTS queue_requests_status_check")
    op.execute(
        "ALTER TABLE queue_requests ADD CONSTRAINT queue_requests_status_check "
        "CHECK (status = ANY (ARRAY['pending'::text, 'approved'::text, 'now_playing'::text, "
        "'completed'::text, 'skipped'::text, 'rejected'::text]))"
    )
