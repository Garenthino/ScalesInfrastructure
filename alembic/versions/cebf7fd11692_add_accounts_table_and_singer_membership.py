"""add accounts table and singer membership

Revision ID: cebf7fd11692
Revises: 000000000011
Create Date: 2026-07-04 20:16:12.736227

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cebf7fd11692'
down_revision: Union[str, None] = '000000000011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Global accounts table
    op.create_table(
        'accounts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email', sa.Text(), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=True),
        sa.Column('auth_provider', sa.Text(), nullable=True),
        sa.Column('auth_provider_id', sa.Text(), nullable=True),
        sa.Column('real_name', sa.Text(), nullable=True),
        sa.Column('pronouns', sa.Text(), nullable=True),
        sa.Column('phone', sa.Text(), nullable=True),
        sa.Column('bio', sa.Text(), nullable=True),
        sa.Column('avatar_url', sa.Text(), nullable=True),
        sa.Column('social_links', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.Text(), nullable=True),
        sa.Column('deleted_at', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    op.create_index('ix_accounts_email', 'accounts', ['email'], unique=False)

    # Link singers to accounts
    op.add_column('singers', sa.Column('account_id', sa.String(length=36), nullable=True))
    op.create_foreign_key(
        'fk_singers_account_id',
        'singers',
        'accounts',
        ['account_id'],
        ['id']
    )
    op.create_unique_constraint(
        'uq_singer_account_venue',
        'singers',
        ['account_id', 'venue_id']
    )

    # Backfill accounts for existing singers with email
    op.execute("""
        INSERT INTO accounts (id, email, password_hash, auth_provider, auth_provider_id,
                              real_name, pronouns, phone, bio, avatar_url, social_links,
                              is_active, created_at, updated_at)
        SELECT DISTINCT ON (email)
               gen_random_uuid(),
               email,
               password_hash,
               auth_provider,
               auth_provider_id,
               real_name,
               pronouns,
               phone,
               bio,
               avatar_url,
               social_links,
               1,
               created_at,
               updated_at
        FROM singers
        WHERE email IS NOT NULL AND email != ''
        ORDER BY email, created_at ASC
    """)

    # Link singers to the backfilled accounts
    op.execute("""
        UPDATE singers
        SET account_id = accounts.id
        FROM accounts
        WHERE singers.email = accounts.email
          AND singers.email IS NOT NULL
          AND singers.email != ''
    """)

    # Self-referential link for merge history
    op.add_column('singers', sa.Column('linked_singer_id', sa.String(length=36), nullable=True))
    op.create_foreign_key(
        'fk_singers_linked_singer_id',
        'singers',
        'singers',
        ['linked_singer_id'],
        ['id']
    )

    # Merge audit log
    op.create_table(
        'singer_link_merge_logs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('venue_id', sa.String(length=36), nullable=False),
        sa.Column('source_singer_id', sa.String(length=36), nullable=False),
        sa.Column('target_singer_id', sa.String(length=36), nullable=False),
        sa.Column('merged_by_account_id', sa.String(length=36), nullable=True),
        sa.Column('merged_by_kj_device_id', sa.String(length=36), nullable=True),
        sa.Column('queue_requests_moved', sa.Integer(), nullable=True),
        sa.Column('payments_moved', sa.Integer(), nullable=True),
        sa.Column('favorites_moved', sa.Integer(), nullable=True),
        sa.Column('achievements_moved', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['merged_by_account_id'], ['accounts.id']),
        sa.ForeignKeyConstraint(['merged_by_kj_device_id'], ['kj_devices.id']),
        sa.ForeignKeyConstraint(['source_singer_id'], ['singers.id']),
        sa.ForeignKeyConstraint(['target_singer_id'], ['singers.id']),
        sa.ForeignKeyConstraint(['venue_id'], ['venues.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_singer_link_merge_logs_venue', 'singer_link_merge_logs', ['venue_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('singer_link_merge_logs')
    op.drop_constraint('fk_singers_linked_singer_id', 'singers', type_='foreignkey')
    op.drop_column('singers', 'linked_singer_id')
    op.drop_constraint('uq_singer_account_venue', 'singers', type_='unique')
    op.drop_constraint('fk_singers_account_id', 'singers', type_='foreignkey')
    op.drop_column('singers', 'account_id')
    op.drop_table('accounts')
