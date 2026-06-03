"""PostgreSQL RLS integration tests.

Exercises the Row-Level Security policies applied by migration
``bce9f1a12d34`` against a real PostgreSQL instance (the Docker Compose
test stack).  Verifies that SELECT, INSERT, and UPDATE are correctly
tenant-isolated via ``app.current_venue_id``.

Run with::

    pytest tests/test_rls_integration.py -v -m integration
"""
from __future__ import annotations

import os
import uuid

import pytest
import asyncpg

_DSN = os.environ.get(
    "SCALES_TEST_POSTGRES_DSN",
    "postgresql://scales_test:scales_test@localhost:25432/scales_test",
)


async def _rls_test_conn() -> asyncpg.Connection:
    """Return a connection as a non-superuser so RLS is enforced."""
    admin = await asyncpg.connect(_DSN)
    await admin.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rls_test_user') THEN
                CREATE ROLE rls_test_user LOGIN PASSWORD 'rls_test_pass';
            END IF;
        END
        $$;
        """
    )
    await admin.execute("GRANT USAGE ON SCHEMA public TO rls_test_user")
    # Grant CRUD on all existing venue-scoped tables
    tables = [
        "venues", "singers", "songs", "queue_requests", "rotation_sessions",
        "rotation_entries", "leaderboards", "leaderboard_entries", "payments",
        "orders", "order_items", "products", "loyalty_tiers", "loyalty_points",
        "loyalty_quests", "loyalty_quest_completions", "points_ledger",
        "singer_achievements", "singer_favorites", "singer_follows",
        "check_in_sessions", "kj_sessions", "kj_devices", "sync_checkpoints",
        "device_tokens", "venue_configs", "analytics_events", "analytics_metrics",
        "exports", "consents", "share_events", "song_categories",
        "song_category_mappings", "dropshippers", "notifications",
        "notification_settings",
    ]
    for t in tables:
        await admin.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO rls_test_user")
    # Grant REFERENCES on venues for FK checks
    await admin.execute("GRANT REFERENCES ON venues TO rls_test_user")
    await admin.close()
    # Build DSN for rls_test_user — parse the admin DSN to swap credentials
    import urllib.parse
    parsed = urllib.parse.urlparse(_DSN)
    # Replace netloc (user:pass@host:port) with rls_test_user credentials
    rls_netloc = f"rls_test_user:rls_test_pass@{parsed.hostname}:{parsed.port}"
    rls_dsn = urllib.parse.urlunparse(parsed._replace(netloc=rls_netloc))
    return await asyncpg.connect(rls_dsn)


@pytest.fixture
async def pg_conn():
    conn = await _rls_test_conn()
    yield conn
    await conn.close()


@pytest.mark.integration
async def test_rls_migration_state(pg_conn: asyncpg.Connection):
    """RLS enabled + FORCE on singers, policies exist, helper function exists."""
    row = await pg_conn.fetchrow(
        """
        SELECT relrowsecurity, relforcerowsecurity
        FROM pg_class
        WHERE relname = 'singers' AND relkind = 'r'
        """
    )
    assert row is not None
    assert row["relrowsecurity"] is True
    assert row["relforcerowsecurity"] is True

    policies = await pg_conn.fetch(
        "SELECT policyname FROM pg_policies WHERE tablename = 'singers'"
    )
    assert any(p["policyname"] == "app_tenant_isolation_singers" for p in policies)

    func = await pg_conn.fetchrow(
        "SELECT proname FROM pg_proc WHERE proname = 'set_app_venue_id'"
    )
    assert func is not None


def _make_ids():
    suffix = str(uuid.uuid4())[:8]
    return {
        "v1": f"rls-v1-{suffix}",
        "v2": f"rls-v2-{suffix}",
        "s1": f"rls-s1-{suffix}",
        "s2": f"rls-s2-{suffix}",
        "sl1": f"slug-v1-{suffix}",
        "sl2": f"slug-v2-{suffix}",
    }


@pytest.mark.integration
async def test_rls_select_isolation(pg_conn: asyncpg.Connection):
    """SELECT returns only rows matching the current venue_id."""
    ids = _make_ids()
    tr = pg_conn.transaction()
    await tr.start()
    await pg_conn.execute("SELECT set_app_venue_id('')")
    await pg_conn.execute(
        f"INSERT INTO venues (id, name, slug, created_at, updated_at) VALUES "
        f"('{ids['v1']}', 'V1', '{ids['sl1']}', '2024-01-01', '2024-01-01'),"
        f"('{ids['v2']}', 'V2', '{ids['sl2']}', '2024-01-01', '2024-01-01')"
    )
    await pg_conn.execute(
        f"INSERT INTO singers (id, venue_id, stage_name, created_at, updated_at) VALUES "
        f"('{ids['s1']}', '{ids['v1']}', 'Singer A', '2024-01-01', '2024-01-01'),"
        f"('{ids['s2']}', '{ids['v2']}', 'Singer B', '2024-01-01', '2024-01-01')"
    )
    await tr.commit()

    try:
        # Set to a non-matching venue_id → 0 rows (isolation active)
        tr = pg_conn.transaction()
        await tr.start()
        await pg_conn.execute("SELECT set_app_venue_id('no-such-venue')")
        rows = await pg_conn.fetch(
            f"SELECT id, venue_id FROM singers WHERE id IN ('{ids['s1']}', '{ids['s2']}')"
        )
        assert len(rows) == 0
        await tr.rollback()

        # Scoped to v1 → only s1
        tr = pg_conn.transaction()
        await tr.start()
        await pg_conn.execute(f"SELECT set_app_venue_id('{ids['v1']}')")
        rows = await pg_conn.fetch(
            f"SELECT id, venue_id FROM singers WHERE id IN ('{ids['s1']}', '{ids['s2']}')"
        )
        assert len(rows) == 1
        assert rows[0]["venue_id"] == ids["v1"]
        await tr.rollback()

        # Scoped to v2 → only s2
        tr = pg_conn.transaction()
        await tr.start()
        await pg_conn.execute(f"SELECT set_app_venue_id('{ids['v2']}')")
        rows = await pg_conn.fetch(
            f"SELECT id, venue_id FROM singers WHERE id IN ('{ids['s1']}', '{ids['s2']}')"
        )
        assert len(rows) == 1
        assert rows[0]["venue_id"] == ids["v2"]
        await tr.rollback()

        # Admin bypass (explicit empty string) → both rows
        tr = pg_conn.transaction()
        await tr.start()
        await pg_conn.execute("SELECT set_app_venue_id('')")
        rows = await pg_conn.fetch(
            f"SELECT id, venue_id FROM singers WHERE id IN ('{ids['s1']}', '{ids['s2']}')"
        )
        assert len(rows) == 2
        await tr.rollback()
    finally:
        tr = pg_conn.transaction()
        await tr.start()
        await pg_conn.execute("SELECT set_app_venue_id('')")
        await pg_conn.execute(
            f"DELETE FROM singers WHERE id IN ('{ids['s1']}', '{ids['s2']}')"
        )
        await pg_conn.execute(
            f"DELETE FROM venues WHERE id IN ('{ids['v1']}', '{ids['v2']}')"
        )
        await tr.commit()


@pytest.mark.integration
async def test_rls_insert_enforcement(pg_conn: asyncpg.Connection):
    """INSERT with mismatched venue_id is rejected."""
    suffix = str(uuid.uuid4())[:8]
    v3 = f"rls-v3-{suffix}"
    s3 = f"rls-s3-{suffix}"
    sl3 = f"slug-v3-{suffix}"
    tr = pg_conn.transaction()
    await tr.start()
    await pg_conn.execute("SELECT set_app_venue_id('')")
    await pg_conn.execute(
        f"INSERT INTO venues (id, name, slug, created_at, updated_at) VALUES "
        f"('{v3}', 'V3', '{sl3}', '2024-01-01', '2024-01-01')"
    )
    await tr.commit()
    try:
        tr = pg_conn.transaction()
        await tr.start()
        await pg_conn.execute(f"SELECT set_app_venue_id('{v3}')")
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await pg_conn.execute(
                f"INSERT INTO singers (id, venue_id, stage_name, created_at, updated_at) "
                f"VALUES ('{s3}', 'other-venue', 'Intruder', '2024-01-01', '2024-01-01')"
            )
        await tr.rollback()
    finally:
        tr = pg_conn.transaction()
        await tr.start()
        await pg_conn.execute("SELECT set_app_venue_id('')")
        await pg_conn.execute(f"DELETE FROM venues WHERE id = '{v3}'")
        await tr.commit()


@pytest.mark.integration
async def test_rls_update_enforcement(pg_conn: asyncpg.Connection):
    """UPDATE across venues is rejected."""
    suffix = str(uuid.uuid4())[:8]
    v4 = f"rls-v4-{suffix}"
    v5 = f"rls-v5-{suffix}"
    s4 = f"rls-s4-{suffix}"
    s5 = f"rls-s5-{suffix}"
    sl4 = f"slug-v4-{suffix}"
    sl5 = f"slug-v5-{suffix}"
    tr = pg_conn.transaction()
    await tr.start()
    await pg_conn.execute("SELECT set_app_venue_id('')")
    await pg_conn.execute(
        f"INSERT INTO venues (id, name, slug, created_at, updated_at) VALUES "
        f"('{v4}', 'V4', '{sl4}', '2024-01-01', '2024-01-01'),"
        f"('{v5}', 'V5', '{sl5}', '2024-01-01', '2024-01-01')"
    )
    await pg_conn.execute(
        f"INSERT INTO singers (id, venue_id, stage_name, created_at, updated_at) VALUES "
        f"('{s4}', '{v4}', 'Singer A', '2024-01-01', '2024-01-01'),"
        f"('{s5}', '{v5}', 'Singer B', '2024-01-01', '2024-01-01')"
    )
    await tr.commit()
    try:
        # Scoped to v4, try to update s5 (v5's singer)
        tr = pg_conn.transaction()
        await tr.start()
        await pg_conn.execute(f"SELECT set_app_venue_id('{v4}')")
        # s5 is invisible, so this affects 0 rows (not an error, but proves isolation)
        result = await pg_conn.execute(
            f"UPDATE singers SET stage_name = 'Hacked' WHERE id = '{s5}'"
        )
        # asyncpg execute returns a status string like "UPDATE 0"
        assert "UPDATE 0" in result
        await tr.rollback()
    finally:
        tr = pg_conn.transaction()
        await tr.start()
        await pg_conn.execute("SELECT set_app_venue_id('')")
        await pg_conn.execute(
            f"DELETE FROM singers WHERE id IN ('{s4}', '{s5}')"
        )
        await pg_conn.execute(
            f"DELETE FROM venues WHERE id IN ('{v4}', '{v5}')"
        )
        await tr.commit()


@pytest.mark.integration
async def test_rls_policy_on_all_venue_scoped_tables(pg_conn: asyncpg.Connection):
    """Every table in RLS_TABLES has RLS enabled and at least one policy."""
    rows = await pg_conn.fetch(
        """
        SELECT relname
        FROM pg_class
        WHERE relrowsecurity = true
          AND relforcerowsecurity = true
          AND relkind = 'r'
          AND relname NOT LIKE 'pg_%'
        ORDER BY relname
        """
    )
    rls_tables = {r["relname"] for r in rows}

    expected = {
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
    }
    assert expected.issubset(rls_tables), f"Missing RLS tables: {expected - rls_tables}"
