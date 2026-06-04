"""fix_rls_null_handling

Revision ID: a7d6319_fix_rls
Revises: 40de330b5263
Create Date: 2026-06-04 00:00:00.000000

Fix RLS policies so that NULL (setting not yet set) is treated the same as
empty string, allowing queries to proceed before the app sets a venue_id.
"""
from __future__ import annotations

from alembic import op

revision: str = "a7d6319_fix_rls"
down_revision: str = "40de330b5263"

# All tables that had RLS enabled by bce9f1a12d34
RLS_TABLES = [
    "analytics_events",
    "analytics_metrics",
    "check_in_sessions",
    "consents",
    "device_tokens",
    "dropshippers",
    "exports",
    "kj_devices",
    "kj_sessions",
    "leaderboard_entries",
    "leaderboards",
    "loyalty_points",
    "loyalty_quest_completions",
    "loyalty_quests",
    "order_items",
    "points_ledger",
    "products",
    "queues",
    "rotation_entries",
    "rotation_sessions",
    "settings",
    "shipments",
    "singer_achievements",
    "singer_checkins",
    "singer_favorites",
    "singer_follows",
    "singer_loyalty_events",
    "singers",
    "singers_history",
    "song_categories",
    "song_category_mappings",
    "songs",
    "sync_checkpoints",
    "venue_configs",
]


def upgrade() -> None:
    for table in RLS_TABLES:
        # Drop the old policy that uses bare current_setting (fails on NULL)
        op.execute(f"DROP POLICY IF EXISTS app_tenant_isolation_{table} ON {table}")

        # Create new policy that coalesces NULL -> '' so unset session = allow all
        op.execute(
            f"""
            CREATE POLICY app_tenant_isolation_{table}
                ON {table}
                FOR ALL
                TO PUBLIC
                USING (
                    COALESCE(current_setting('app.current_venue_id', true), '') = ''
                    OR (venue_id IS NOT NULL
                        AND venue_id = current_setting('app.current_venue_id', true))
                )
                WITH CHECK (
                    COALESCE(current_setting('app.current_venue_id', true), '') = ''
                    OR (venue_id IS NOT NULL
                        AND venue_id = current_setting('app.current_venue_id', true))
                )
            """
        )


def downgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS app_tenant_isolation_{table} ON {table}")
        op.execute(
            f"""
            CREATE POLICY app_tenant_isolation_{table}
                ON {table}
                FOR ALL
                TO PUBLIC
                USING (
                    (current_setting('app.current_venue_id', true) = '')
                    OR (venue_id IS NOT NULL
                        AND venue_id = current_setting('app.current_venue_id', true))
                )
                WITH CHECK (
                    (current_setting('app.current_venue_id', true) = '')
                    OR (venue_id IS NOT NULL
                        AND venue_id = current_setting('app.current_venue_id', true))
                )
            """
        )
