#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Scales API Entrypoint — Production Boot Script
# Waits for DB connectivity, runs migrations, validates secrets, then starts
# the app.
# ---------------------------------------------------------------------------

# Environment defaults
: "${APP_NAME:=ScalesAPI}"
: "${ENVIRONMENT:=development}"
: "${DATABASE_URL:=postgresql+asyncpg://scales:scales@postgres:5432/scales}"
: "${REDIS_URL:=redis://redis:6379/0}"

# ---------------------------------------------------------------------------
# Helper: extract host/port/db from DATABASE_URL (asyncpg syntax)
# e.g. postgresql+asyncpg://user:pass@host:5432/dbname
# ---------------------------------------------------------------------------
parse_db_url() {
    local url="$1"
    # handle postgresql+asyncpg:// prefix
    url="${url#postgresql+asyncpg://}"
    echo "$url"
}

get_db_host() {
    local parsed
    parsed="${1#*@}"
    parsed="${parsed%:*}"
    parsed="${parsed%/*}"
    echo "$parsed"
}

get_db_port() {
    local url="$1"
    local host_port_db
    host_port_db="${url#*@}"
    # extract port before /dbname
    local port_and_db="${host_port_db##*:}"
    echo "${port_and_db%%/*}"
}

# ---------------------------------------------------------------------------
wait_for_db() {
    local db_url
    db_url="${DATABASE_URL}"
    local host port parsed
    parsed=$(parse_db_url "$db_url")
    host=$(get_db_host "$db_url")
    port=$(get_db_port "$db_url")
    : "${port:=5432}"

    echo "[entrypoint] Waiting for database at ${host}:${port} ..."
    for i in $(seq 1 60); do
        if timeout 2 bash -c "cat < /dev/null > /dev/tcp/${host}/${port}" 2>/dev/null; then
            echo "[entrypoint] Database is reachable."
            return 0
        fi
        echo "[entrypoint] DB not ready (attempt ${i}/60); sleeping 1s ..."
        sleep 1
    done
    echo "[entrypoint] ERROR: Could not reach database after 60s."
    exit 1
}

# ---------------------------------------------------------------------------
validate_jwt() {
    : "${JWT_SECRET_KEY:=change-me}"
    if [ "$ENVIRONMENT" = "production" ]; then
        if [ "$JWT_SECRET_KEY" = "change-me" ] || [ "${#JWT_SECRET_KEY}" -lt 32 ]; then
            echo "[entrypoint] FATAL: JWT_SECRET_KEY must be at least 32 characters and not the default 'change-me' in production." >&2
            echo "[entrypoint] Generate one with: openssl rand -hex 32" >&2
            exit 1
        fi
    fi
}

# ---------------------------------------------------------------------------
warn_redis() {
    if [ -z "${REDIS_URL:-}" ]; then
        echo "[entrypoint] WARNING: REDIS_URL is not set. Application will use in-memory fallback for rate limiting and queue pub/sub."
    fi
}

# ---------------------------------------------------------------------------
run_migrations() {
    if [ -d "alembic" ] && [ -f "alembic.ini" ]; then
        echo "[entrypoint] Running alembic upgrade head ..."
        alembic upgrade head
        echo "[entrypoint] Migrations complete."
    else
        echo "[entrypoint] No alembic config found; skipping migrations."
    fi
}

# ---------------------------------------------------------------------------
start_app() {
    echo "[entrypoint] Starting uvicorn ..."
    # --timeout-keep-alive 120: KJ desktop bulk song-sync uploads one batch every
    # ~60-70s while the server is inserting 2000 rows. Uvicorn's default 5s
    # keep-alive timeout closes idle connections mid-request, which nginx then
    # reports to the client as a read timeout. 120s keeps the control connection
    # open for the full batch duration.
    exec uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" --timeout-keep-alive 120 "$@"
}

# ---------------------------------------------------------------------------
main() {
    wait_for_db
    validate_jwt
    warn_redis
    run_migrations
    start_app "$@"
}

main "$@"
