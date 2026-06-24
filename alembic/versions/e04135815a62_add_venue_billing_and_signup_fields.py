"""add venue billing and signup fields

Revision ID: e04135815a62
Revises: 60a30fbeb261
Create Date: 2026-06-23 17:58:38.939905

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e04135815a62'
down_revision: Union[str, None] = '60a30fbeb261'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Billing / signup fields for venue management and Stripe integration.
    op.add_column('venues', sa.Column('billing_email', sa.Text(), nullable=True))
    op.add_column('venues', sa.Column('subscription_status', sa.Text(), nullable=True))
    op.add_column('venues', sa.Column('billing_status', sa.Text(), nullable=True))
    op.add_column('venues', sa.Column('plan_expires_at', sa.Text(), nullable=True))
    op.add_column('venues', sa.Column('trial_ends_at', sa.Text(), nullable=True))
    op.add_column('venues', sa.Column('stripe_customer_id', sa.Text(), nullable=True))
    op.add_column('venues', sa.Column('stripe_subscription_id', sa.Text(), nullable=True))
    op.add_column('venues', sa.Column('signup_source', sa.Text(), nullable=True))
    op.add_column('venues', sa.Column('sales_rep_email', sa.Text(), nullable=True))
    op.add_column('venues', sa.Column('plan_features_json', sa.Text(), nullable=True))

    # Constraints matching the SQLAlchemy model CHECK constraints.
    op.create_check_constraint(
        'ck_venues_subscription_status',
        'venues',
        sa.text("subscription_status IS NULL OR subscription_status IN ('trialing', 'active', 'past_due', 'cancelled', 'comped')")
    )
    op.create_check_constraint(
        'ck_venues_billing_status',
        'venues',
        sa.text("billing_status IS NULL OR billing_status IN ('trial', 'active', 'past_due', 'cancelled')")
    )
    op.create_check_constraint(
        'ck_venues_signup_source',
        'venues',
        sa.text("signup_source IS NULL OR signup_source IN ('self_serve', 'sales_assisted')")
    )

    # Existing rows start as trialing/manual so nothing breaks before Stripe is wired.
    op.execute("UPDATE venues SET subscription_status = 'trialing' WHERE subscription_status IS NULL")
    op.execute("UPDATE venues SET billing_status = 'trial' WHERE billing_status IS NULL")
    op.execute("UPDATE venues SET signup_source = 'self_serve' WHERE signup_source IS NULL")


def downgrade() -> None:
    op.drop_constraint('ck_venues_signup_source', 'venues', type_='check')
    op.drop_constraint('ck_venues_billing_status', 'venues', type_='check')
    op.drop_constraint('ck_venues_subscription_status', 'venues', type_='check')

    op.drop_column('venues', 'plan_features_json')
    op.drop_column('venues', 'sales_rep_email')
    op.drop_column('venues', 'signup_source')
    op.drop_column('venues', 'stripe_subscription_id')
    op.drop_column('venues', 'stripe_customer_id')
    op.drop_column('venues', 'trial_ends_at')
    op.drop_column('venues', 'plan_expires_at')
    op.drop_column('venues', 'billing_status')
    op.drop_column('venues', 'subscription_status')
    op.drop_column('venues', 'billing_email')
