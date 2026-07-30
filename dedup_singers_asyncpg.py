"""Deduplicate venue singers sharing the same account_id.

Connects directly to Postgres and bypasses row-level security for this
maintenance operation. For each (venue_id, account_id) group with more than
one live Singer row:
- Pick the canonical row (most related records, then matching stage name).
- Reassign records from duplicates to the canonical.
- Soft-delete the duplicate rows.
"""
import asyncio
import os
import asyncpg

TABLES_AND_COLUMNS = [
    ("queue_requests", "singer_id"),
    ("rotation_entries", "singer_id"),
    ("check_in_sessions", "singer_id"),
    ("payments", "singer_id"),
    ("orders", "singer_id"),
    ("loyalty_points", "singer_id"),
    ("loyalty_quest_completions", "singer_id"),
    ("points_ledger", "singer_id"),
    ("singer_achievements", "singer_id"),
    ("leaderboard_entries", "singer_id"),
    ("device_tokens", "singer_id"),
    ("notification_settings", "singer_id"),
    ("notifications", "singer_id"),
    ("share_events", "singer_id"),
    ("singer_favorites", "singer_id"),
    ("singer_follows", "singer_id"),
    ("singer_follows", "followed_singer_id"),
    ("audit_log", "user_id"),
]

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://scales:scales@postgres:5432/scales",
).replace("postgresql+asyncpg://", "postgresql://")


async def deduplicate():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("SET row_security = off")

        groups = await conn.fetch(
            """
            SELECT venue_id, account_id, COUNT(*) AS cnt
            FROM singers
            WHERE account_id IS NOT NULL AND account_id <> '' AND deleted_at IS NULL
            GROUP BY venue_id, account_id
            HAVING COUNT(*) > 1
            """
        )
        if not groups:
            return {"message": "No duplicate (venue_id, account_id) groups found.", "groups": 0, "deleted": 0}

        log = []
        total_deleted = 0

        for row in groups:
            venue_id = row["venue_id"]
            account_id = row["account_id"]
            singers = await conn.fetch(
                """
                SELECT s.id, s.stage_name, s.created_at,
                       a.stage_name AS account_stage_name, a.email AS account_email
                FROM singers s
                LEFT JOIN accounts a ON s.account_id = a.id
                WHERE s.venue_id = $1 AND s.account_id = $2 AND s.deleted_at IS NULL
                """,
                venue_id, account_id,
            )
            if len(singers) < 2:
                continue

            async def score(s):
                recs = 0
                for table, col in TABLES_AND_COLUMNS:
                    query = f"SELECT COUNT(*) FROM {table} WHERE {col} = $1"
                    params = [s["id"]]
                    # Only add venue filter if column exists in that table
                    venue_col = await conn.fetch(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name=$1 AND column_name='venue_id'",
                        table,
                    )
                    if venue_col:
                        query += " AND venue_id = $2"
                        params.append(venue_id)
                    recs += await conn.fetchval(query, *params) or 0

                name_match = 0
                names = {s["account_stage_name"] or "", (s["account_email"] or "").split("@")[0]}
                if s["stage_name"] and s["stage_name"].strip() in names:
                    name_match = 1
                return (recs, name_match, s["created_at"] or "")

            scored = [(await score(s), s) for s in singers]
            scored.sort(key=lambda x: x[0], reverse=True)
            canonical = scored[0][1]
            duplicates = [s for _, s in scored[1:]]

            moved_total = 0
            async with conn.transaction():
                for dup in duplicates:
                    for table, col in TABLES_AND_COLUMNS:
                        query = f"UPDATE {table} SET {col} = $1 WHERE {col} = $2"
                        params = [canonical["id"], dup["id"]]
                        venue_col = await conn.fetch(
                            "SELECT 1 FROM information_schema.columns "
                            "WHERE table_name=$1 AND column_name='venue_id'",
                            table,
                        )
                        if venue_col:
                            query += " AND venue_id = $3"
                            params.append(venue_id)
                        moved_total += int((await conn.execute(query, *params)).split()[-1])

                    await conn.execute(
                        "UPDATE singers SET deleted_at = NOW() WHERE id = $1",
                        dup["id"],
                    )
                    total_deleted += 1

            log.append({
                "venue_id": str(venue_id),
                "account_id": str(account_id),
                "canonical_singer_id": str(canonical["id"]),
                "canonical_stage_name": canonical["stage_name"],
                "duplicate_ids": [str(s["id"]) for s in duplicates],
                "moved_records": moved_total,
            })

        return {"groups": len(groups), "duplicates_deleted": total_deleted, "details": log}
    finally:
        await conn.close()


if __name__ == "__main__":
    outcome = asyncio.run(deduplicate())
    print(outcome)
