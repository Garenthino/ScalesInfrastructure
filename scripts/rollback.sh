#!/usr/bin/env bash
# Scales Production Rollback Script
# Usage: scripts/rollback.sh [--hard]
# --hard: git reset --hard to last known good commit (DANGEROUS)
set -euo pipefail

HARD=""
if [[ "${1:-}" == "--hard" ]]; then
  HARD="true"
fi

SCALES_ROOT="${SCALES_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
echo "[+] Working from ${SCALES_ROOT}"
cd "${SCALES_ROOT}" || exit 1

# Find and kill old next-server (web) if running
pgrep -a -f "npm start" 2>/dev/null | while read pid cmd; do
  echo "    Killing npm start (PID $pid)"
  kill -TERM "$pid" 2>/dev/null || true
done
sleep 3
pgrep -f "next-server" 2>/dev/null | xargs kill -KILL 2>/dev/null || true

# Stop Docker services
docker compose down api postgres redis 2>/dev/null || true

if [[ -n "$HARD" ]]; then
  echo "[!] HARD rollback requested — resetting git to last known good..."
  git reset --hard HEAD~1
fi

echo "[+] Rebuilding API image..."
docker compose build --no-cache api

echo "[+] Starting services..."
docker compose up -d postgres redis
sleep 5
docker compose up -d api

echo "[+] Restarting web server..."
cd web || exit 1
rm -rf .next node_modules/.cache
npm run build 2>&1 | tail -5
export PATH="/home/scales/.nvm/versions/node/v20.20.2/bin:$PATH"
nohup npm start > /tmp/web-server.log 2>&1 &
sleep 4

echo "[+] Health checks..."
for _ in {1..6}; do
  if curl -sf http://localhost:8000/health > /dev/null; then
    echo "    API OK"
    break
  fi
  sleep 2
done

curl -sf http://localhost:4000 > /dev/null && echo "    Web OK" || echo "    Web check failed (might need login page check)"

echo "[+] Rollback complete."
