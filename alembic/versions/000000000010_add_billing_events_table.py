"""add billing_events table for Stripe webhook idempotency

Revision ID: 000000000010
Revises: 000000000009
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '000000000010'
down_revision: Union[str, None] = '000000000009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'billing_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('stripe_event_id', sa.Text(), nullable=False),
        sa.Column('event_type', sa.Text(), nullable=False),
        sa.Column('stripe_subscription_id', sa.Text(), nullable=True),
        sa.Column('payload_json', sa.Text(), nullable=True),
        sa.Column('processed', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.Text(), nullable=True),
    )
    op.create_index('ix_billing_events_stripe_event_id', 'billing_events', ['stripe_event_id'])
    op.create_index('ix_billing_events_venue', 'billing_events', ['venue_id', 'created_at'])
    op.create_unique_constraint(
        'uq_billing_event',
        'billing_events',
        ['venue_id', 'stripe_event_id'],
    )


def downgrade() -> None:
    op.drop_table('billing_events')
