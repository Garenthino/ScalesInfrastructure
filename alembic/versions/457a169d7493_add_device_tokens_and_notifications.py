"""add_device_tokens_and_notifications

Revision ID: 457a169d7493
Revises: 93d70d3324db
Create Date: 2026-05-31 19:23:21.407672

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '457a169d7493'
down_revision: Union[str, None] = '93d70d3324db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('device_tokens',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('singer_id', sa.String(length=36), nullable=False),
    sa.Column('venue_id', sa.String(length=36), nullable=False),
    sa.Column('platform', sa.Text(), nullable=False),
    sa.Column('token', sa.Text(), nullable=False),
    sa.Column('device_name', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Integer(), nullable=True, server_default='1'),
    sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column('updated_at', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['singer_id'], ['singers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('singer_id', 'platform', 'token', name='uq_device_token')
    )
    op.create_index('ix_device_tokens_singer', 'device_tokens', ['singer_id'], unique=False)
    op.create_index('ix_device_tokens_venue', 'device_tokens', ['venue_id'], unique=False)

    op.create_table('notifications',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('singer_id', sa.String(length=36), nullable=False),
    sa.Column('venue_id', sa.String(length=36), nullable=False),
    sa.Column('notification_type', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('data_json', sa.Text(), nullable=True),
    sa.Column('is_read', sa.Integer(), nullable=True, server_default='0'),
    sa.Column('sent_at', sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column('read_at', sa.Text(), nullable=True),
    sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.ForeignKeyConstraint(['singer_id'], ['singers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_notifications_singer', 'notifications', ['singer_id', 'created_at'], unique=False)
    op.create_index('ix_notifications_unread', 'notifications', ['singer_id', 'is_read'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_notifications_unread', table_name='notifications')
    op.drop_index('ix_notifications_singer', table_name='notifications')
    op.drop_table('notifications')
    op.drop_index('ix_device_tokens_venue', table_name='device_tokens')
    op.drop_index('ix_device_tokens_singer', table_name='device_tokens')
    op.drop_table('device_tokens')
