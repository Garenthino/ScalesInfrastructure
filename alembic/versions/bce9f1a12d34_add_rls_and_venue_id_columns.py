"""add_rls_and_venue_id_columns

Revision ID: bce9f1a12d34
Revises: 012f05946f94
Create Date: 2026-06-01 14:25:00.000000

Add venue_id to rotation_entries, leaderboard_entries, and order_items,
then enable Row-Level Security (RLS) on all venue-scoped tables.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "bce9f1a12d34"
down_revision: Union[str, None] = "012f05946f94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Tables that need RLS (every table with a venue_id FK or venue-scoped data)
# ---------------------------------------------------------------------------
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
    "loyalty_tiers",
    "notification_settings",
    "notifications",
    "order_items",
    "orders",
    "payments",
    "points_ledger",
    "products",
    "queue_requests",
    "rotation_entries",
    "rotation_sessions",
    "share_events",
    "singer_achievements",
    "singer_favorites",
    "singer_follows",
    "singers",
    "song_categories",
    "song_category_mappings",
    "songs",
    "sync_checkpoints",
    "venue_configs",
]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Add venue_id columns (nullable first so backfill can run)
    # ------------------------------------------------------------------
    op.add_column("rotation_entries", sa.Column("venue_id", sa.String(length=36), nullable=True))
    op.add_column("leaderboard_entries", sa.Column("venue_id", sa.String(length=36), nullable=True))
    op.add_column("order_items", sa.Column("venue_id", sa.String(length=36), nullable=True))

    op.create_foreign_key(
        "fk_rotation_entries_venue", "rotation_entries", "venues",
        ["venue_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_leaderboard_entries_venue", "leaderboard_entries", "venues",
        ["venue_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_order_items_venue", "order_items", "venues",
        ["venue_id"], ["id"], ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # 2. Backfill venue_id from parent tables
    # ------------------------------------------------------------------
    # rotation_entries -> rotation_sessions
    op.execute(
        """
        UPDATE rotation_entries
        SET venue_id = rotation_sessions.venue_id
        FROM rotation_sessions
        WHERE rotation_entries.rotation_session_id = rotation_sessions.id
        """
    )
    # leaderboard_entries -> leaderboards
    op.execute(
        """
        UPDATE leaderboard_entries
        SET venue_id = leaderboards.venue_id
        FROM leaderboards
        WHERE leaderboard_entries.leaderboard_id = leaderboards.id
        """
    )
    # order_items -> orders
    op.execute(
        """
        UPDATE order_items
        SET venue_id = orders.venue_id
        FROM orders
        WHERE order_items.order_id = orders.id
        """
    )

    # Set NOT NULL now that every row has a venue_id
    op.alter_column("rotation_entries", "venue_id", nullable=False)
    op.alter_column("leaderboard_entries", "venue_id", nullable=False)
    op.alter_column("order_items", "venue_id", nullable=False)

    # ------------------------------------------------------------------
    # 3. Enable RLS on every venue-scoped table
    # ------------------------------------------------------------------
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    # ------------------------------------------------------------------
    # 4. Create application-level RLS policy for each table
    # ------------------------------------------------------------------
    # This policy is permissive: it allows SELECT / INSERT / UPDATE / DELETE
    # when app.current_venue_id matches the row's venue_id OR the venue_id
    # column is NULL (admin tables like audit_logs).
    for table in RLS_TABLES:
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

    # ------------------------------------------------------------------
    # 5. Force RLS for table owners (bypassing owner privilege)
    # ------------------------------------------------------------------
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # ------------------------------------------------------------------
    # 6. Helper function for setting session variable (idempotent)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_app_venue_id(vid TEXT)
        RETURNS void AS $$
        BEGIN
            PERFORM set_config('app.current_venue_id', vid, true);
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    # Remove policies
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS app_tenant_isolation_{table} ON {table}")

    # Disable RLS
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Drop helper
    op.execute("DROP FUNCTION IF EXISTS set_app_venue_id(TEXT)")

    # Drop venue_id columns
    op.drop_constraint("fk_order_items_venue", "order_items", type_="foreignkey")
    op.drop_constraint("fk_leaderboard_entries_venue", "leaderboard_entries", type_="foreignkey")
    op.drop_constraint("fk_rotation_entries_venue", "rotation_entries", type_="foreignkey")

    op.drop_column("order_items", "venue_id")
    op.drop_column("leaderboard_entries", "venue_id")
    op.drop_column("rotation_entries", "venue_id")
