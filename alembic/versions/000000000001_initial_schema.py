"""Initial schema — all 27 Scales tables.

Revision ID: 000000000001
Revises: 
Create Date: 2026-05-19 21:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '000000000001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # venues (root tenant table)
    op.create_table(
        'venues',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('slug', sa.Text, nullable=False, unique=True),
        sa.Column('address', sa.Text),
        sa.Column('contact_json', sa.Text),
        sa.Column('timezone', sa.Text, server_default='UTC'),
        sa.Column('locale', sa.Text, server_default='en'),
        sa.Column('branding_json', sa.Text),
        sa.Column('subscription_tier', sa.Text, server_default='basic'),
        sa.Column('is_active', sa.Integer, server_default='1'),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
        sa.Column('deleted_at', sa.Text),
    )

    # venue_configs
    op.create_table(
        'venue_configs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('config_key', sa.Text, nullable=False),
        sa.Column('config_value', sa.Text),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
        sa.UniqueConstraint('venue_id', 'config_key'),
    )

    # songs
    op.create_table(
        'songs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('catalog_id', sa.Text),
        sa.Column('title', sa.Text, nullable=False),
        sa.Column('artist', sa.Text, nullable=False),
        sa.Column('album', sa.Text),
        sa.Column('genre', sa.Text),
        sa.Column('language', sa.Text),
        sa.Column('duration_ms', sa.Integer),
        sa.Column('lyrics_url', sa.Text),
        sa.Column('cover_art_url', sa.Text),
        sa.Column('is_available', sa.Integer, server_default='1'),
        sa.Column('is_active', sa.Integer, server_default='1'),
        sa.Column('meta_json', sa.Text),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
        sa.Column('deleted_at', sa.Text),
    )
    op.create_index('ix_songs_venue_id', 'songs', ['venue_id'])
    op.create_index('ix_songs_venue_title', 'songs', ['venue_id', 'title'])

    # song_categories
    op.create_table(
        'song_categories',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('sort_order', sa.Integer, server_default='0'),
        sa.Column('color', sa.Text),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
        sa.Column('deleted_at', sa.Text),
    )

    # song_category_mappings
    op.create_table(
        'song_category_mappings',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('song_id', sa.String(36), sa.ForeignKey('songs.id'), nullable=False),
        sa.Column('category_id', sa.String(36), sa.ForeignKey('song_categories.id'), nullable=False),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('created_at', sa.Text, nullable=False),
    )

    # singers
    op.create_table(
        'singers',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('auth_provider', sa.Text),
        sa.Column('auth_provider_id', sa.Text),
        sa.Column('stage_name', sa.Text, nullable=False),
        sa.Column('real_name', sa.Text),
        sa.Column('pronouns', sa.Text),
        sa.Column('email', sa.Text),
        sa.Column('phone', sa.Text),
        sa.Column('notes', sa.Text),
        sa.Column('loyalty_tier_id', sa.String(36), sa.ForeignKey('loyalty_tiers.id')),
        sa.Column('total_points', sa.Integer, server_default='0'),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
        sa.Column('deleted_at', sa.Text),
    )
    op.create_index('ix_singers_venue_id', 'singers', ['venue_id'])

    # singer_favorites
    op.create_table(
        'singer_favorites',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('singer_id', sa.String(36), sa.ForeignKey('singers.id'), nullable=False),
        sa.Column('song_id', sa.String(36), sa.ForeignKey('songs.id'), nullable=False),
        sa.Column('created_at', sa.Text, nullable=False),
    )

    # queue_requests
    op.create_table(
        'queue_requests',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('singer_id', sa.String(36), sa.ForeignKey('singers.id'), nullable=False),
        sa.Column('song_id', sa.String(36), sa.ForeignKey('songs.id'), nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('notes', sa.Text),
        sa.Column('rotation_position', sa.Integer),
        sa.Column('kj_id', sa.Text),
        sa.Column('requested_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
        sa.Column('played_at', sa.Text),
        sa.Column('deleted_at', sa.Text),
        sa.CheckConstraint("status IN ('pending','approved','now_playing','completed','skipped')"),
    )
    op.create_index('ix_queue_venue_status', 'queue_requests', ['venue_id', 'status'])

    # rotation_sessions
    op.create_table(
        'rotation_sessions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('name', sa.Text),
        sa.Column('mode', sa.Text, nullable=False),
        sa.Column('started_at', sa.Text),
        sa.Column('ended_at', sa.Text),
        sa.Column('is_active', sa.Integer, server_default='1'),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
        sa.Column('deleted_at', sa.Text),
        sa.CheckConstraint("mode IN ('fifo','weighted','vip_priority')"),
    )

    # rotation_entries
    op.create_table(
        'rotation_entries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('rotation_session_id', sa.String(36), sa.ForeignKey('rotation_sessions.id'), nullable=False),
        sa.Column('singer_id', sa.String(36), sa.ForeignKey('singers.id'), nullable=False),
        sa.Column('queue_request_id', sa.String(36), sa.ForeignKey('queue_requests.id')),
        sa.Column('position', sa.Integer, nullable=False),
        sa.Column('weight', sa.REAL, server_default='1.0'),
        sa.Column('sang_at', sa.Text),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
        sa.Column('deleted_at', sa.Text),
    )

    # loyalty_tiers
    op.create_table(
        'loyalty_tiers',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('min_points', sa.Integer, server_default='0'),
        sa.Column('multiplier', sa.REAL, server_default='1.0'),
        sa.Column('color', sa.Text),
        sa.Column('icon', sa.Text),
        sa.Column('is_active', sa.Integer, server_default='1'),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
        sa.Column('deleted_at', sa.Text),
    )

    # loyalty_points
    op.create_table(
        'loyalty_points',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('singer_id', sa.String(36), sa.ForeignKey('singers.id'), nullable=False),
        sa.Column('amount', sa.Integer, nullable=False),
        sa.Column('reason', sa.Text),
        sa.Column('reference_type', sa.Text),
        sa.Column('reference_id', sa.Text),
        sa.Column('created_at', sa.Text, nullable=False),
    )

    # loyalty_quests
    op.create_table(
        'loyalty_quests',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('criteria_json', sa.Text),
        sa.Column('reward_points', sa.Integer, server_default='0'),
        sa.Column('is_active', sa.Integer, server_default='1'),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
        sa.Column('deleted_at', sa.Text),
    )

    # loyalty_quest_completions
    op.create_table(
        'loyalty_quest_completions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('singer_id', sa.String(36), sa.ForeignKey('singers.id'), nullable=False),
        sa.Column('quest_id', sa.String(36), sa.ForeignKey('loyalty_quests.id'), nullable=False),
        sa.Column('completed_at', sa.Text),
        sa.Column('created_at', sa.Text, nullable=False),
    )

    # products
    op.create_table(
        'products',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('sku', sa.Text),
        sa.Column('price_cents', sa.Integer, nullable=False),
        sa.Column('currency', sa.Text, server_default='USD'),
        sa.Column('image_url', sa.Text),
        sa.Column('is_active', sa.Integer, server_default='1'),
        sa.Column('stock_quantity', sa.Integer, server_default='0'),
        sa.Column('dropshipper_id', sa.String(36), sa.ForeignKey('dropshippers.id')),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
        sa.Column('deleted_at', sa.Text),
    )

    # orders
    op.create_table(
        'orders',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('singer_id', sa.String(36), sa.ForeignKey('singers.id'), nullable=False),
        sa.Column('stripe_payment_intent_id', sa.Text, unique=True),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('total_cents', sa.Integer, nullable=False),
        sa.Column('currency', sa.Text, server_default='USD'),
        sa.Column('shipping_address_json', sa.Text),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
        sa.Column('deleted_at', sa.Text),
    )

    # order_items
    op.create_table(
        'order_items',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('orders.id'), nullable=False),
        sa.Column('product_id', sa.String(36), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('quantity', sa.Integer, nullable=False),
        sa.Column('unit_price_cents', sa.Integer, nullable=False),
        sa.Column('created_at', sa.Text, nullable=False),
    )

    # dropshippers
    op.create_table(
        'dropshippers',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('api_endpoint', sa.Text),
        sa.Column('auth_config_json', sa.Text),
        sa.Column('is_active', sa.Integer, server_default='1'),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
        sa.Column('deleted_at', sa.Text),
    )

    # leaderboards
    op.create_table(
        'leaderboards',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('metric_type', sa.Text, nullable=False),
        sa.Column('period_start', sa.Text),
        sa.Column('period_end', sa.Text),
        sa.Column('is_active', sa.Integer, server_default='1'),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
        sa.Column('deleted_at', sa.Text),
    )

    # leaderboard_entries
    op.create_table(
        'leaderboard_entries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('leaderboard_id', sa.String(36), sa.ForeignKey('leaderboards.id'), nullable=False),
        sa.Column('singer_id', sa.String(36), sa.ForeignKey('singers.id'), nullable=False),
        sa.Column('score', sa.REAL, server_default='0.0'),
        sa.Column('rank', sa.Integer),
        sa.Column('updated_at', sa.Text, nullable=False),
    )

    # consents
    op.create_table(
        'consents',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('singer_id', sa.String(36), sa.ForeignKey('singers.id'), nullable=False),
        sa.Column('consent_type', sa.Text, nullable=False),
        sa.Column('granted', sa.Integer, server_default='0'),
        sa.Column('granted_at', sa.Text),
        sa.Column('ip_address', sa.Text),
        sa.Column('metadata_json', sa.Text),
        sa.Column('created_at', sa.Text, nullable=False),
    )

    # share_events
    op.create_table(
        'share_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('singer_id', sa.String(36), sa.ForeignKey('singers.id')),
        sa.Column('platform', sa.Text),
        sa.Column('url', sa.Text),
        sa.Column('content_type', sa.Text),
        sa.Column('created_at', sa.Text, nullable=False),
    )

    # analytics_events
    op.create_table(
        'analytics_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('event_type', sa.Text, nullable=False),
        sa.Column('singer_id', sa.String(36), sa.ForeignKey('singers.id')),
        sa.Column('song_id', sa.String(36), sa.ForeignKey('songs.id')),
        sa.Column('session_id', sa.Text),
        sa.Column('payload_json', sa.Text),
        sa.Column('created_at', sa.Text, nullable=False),
    )

    # analytics_metrics
    op.create_table(
        'analytics_metrics',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('metric_name', sa.Text, nullable=False),
        sa.Column('dimensions_json', sa.Text),
        sa.Column('value', sa.REAL, server_default='0.0'),
        sa.Column('bucket_start', sa.Text),
        sa.Column('bucket_end', sa.Text),
        sa.Column('granularity', sa.Text),
        sa.Column('created_at', sa.Text, nullable=False),
    )

    # exports
    op.create_table(
        'exports',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('export_type', sa.Text, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('filter_params_json', sa.Text),
        sa.Column('file_url', sa.Text),
        sa.Column('file_size', sa.Integer),
        sa.Column('created_by', sa.Text),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('completed_at', sa.Text),
        sa.Column('deleted_at', sa.Text),
    )

    # kj_sessions
    op.create_table(
        'kj_sessions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('device_id', sa.Text, nullable=False, unique=True),
        sa.Column('device_name', sa.Text),
        sa.Column('started_at', sa.Text),
        sa.Column('last_heartbeat_at', sa.Text),
        sa.Column('current_rotation_session_id', sa.String(36), sa.ForeignKey('rotation_sessions.id')),
        sa.Column('state_snapshot_json', sa.Text),
        sa.Column('sync_checkpoint_at', sa.Text),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
    )

    # sync_checkpoints
    op.create_table(
        'sync_checkpoints',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venue_id', sa.String(36), sa.ForeignKey('venues.id'), nullable=False),
        sa.Column('kj_session_id', sa.String(36), sa.ForeignKey('kj_sessions.id'), nullable=False),
        sa.Column('table_name', sa.Text, nullable=False),
        sa.Column('last_synced_at', sa.Text),
        sa.Column('last_record_id', sa.Text),
        sa.Column('checksum', sa.Text),
        sa.Column('direction', sa.Text, nullable=False),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('updated_at', sa.Text, nullable=False),
    )


def downgrade() -> None:
    tables = [
        'sync_checkpoints', 'kj_sessions', 'exports', 'analytics_metrics',
        'analytics_events', 'share_events', 'consents', 'leaderboard_entries',
        'leaderboards', 'dropshippers', 'order_items', 'orders', 'products',
        'loyalty_quest_completions', 'loyalty_quests', 'loyalty_points',
        'loyalty_tiers', 'rotation_entries', 'rotation_sessions',
        'queue_requests', 'song_category_mappings', 'song_categories',
        'songs', 'singer_favorites', 'singers', 'venue_configs', 'venues',
    ]
    for t in tables:
        op.drop_table(t)
