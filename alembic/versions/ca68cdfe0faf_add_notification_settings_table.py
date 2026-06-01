"""add_notification_settings_table

Revision ID: ca68cdfe0faf
Revises: 457a169d7493
Create Date: 2026-05-31 20:30:55.281987

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ca68cdfe0faf'
down_revision: Union[str, None] = '457a169d7493'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notification_settings',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('singer_id', sa.String(length=36), nullable=False),
        sa.Column('venue_id', sa.String(length=36), nullable=False),
        sa.Column('up_soon', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('on_stage', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('bumped', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('queue_update', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('announcement', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('social', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('payment', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column('updated_at', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['singer_id'], ['singers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('singer_id', 'venue_id', name='uq_notification_setting')
    )
    op.create_index('ix_notification_settings_singer', 'notification_settings', ['singer_id'], unique=False)
    op.create_index('ix_notification_settings_venue', 'notification_settings', ['venue_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_notification_settings_venue', table_name='notification_settings')
    op.drop_index('ix_notification_settings_singer', table_name='notification_settings')
    op.drop_table('notification_settings')
