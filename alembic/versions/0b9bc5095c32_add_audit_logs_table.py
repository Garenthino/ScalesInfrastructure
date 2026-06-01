"""add_audit_logs_table

Revision ID: 0b9bc5095c32
Revises: ca68cdfe0faf
Create Date: 2026-05-31 20:32:35.403310

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0b9bc5095c32'
down_revision: Union[str, None] = 'ca68cdfe0faf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('audit_logs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('venue_id', sa.String(length=36), nullable=True),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('resource_type', sa.Text(), nullable=True),
        sa.Column('resource_id', sa.Text(), nullable=True),
        sa.Column('result', sa.Text(), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.Text(), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('request_id', sa.Text(), nullable=True),
        sa.Column('details_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['singers.id'], ),
        sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action', 'created_at'], unique=False)
    op.create_index('ix_audit_logs_user', 'audit_logs', ['user_id', 'created_at'], unique=False)
    op.create_index('ix_audit_logs_venue', 'audit_logs', ['venue_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_audit_logs_venue', table_name='audit_logs')
    op.drop_index('ix_audit_logs_user', table_name='audit_logs')
    op.drop_index('ix_audit_logs_action', table_name='audit_logs')
    op.drop_table('audit_logs')
