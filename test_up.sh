#!/bin/bash
set -e
cd /home/garenthino/.hermes/kanban/workspaces/t_d7af7975

echo "=== Bringing up stack ==="
docker compose up -d

echo "=== Container status ==="
docker compose ps

echo "=== Health checks ==="
sleep 5

curl -s http://localhost:8000/health || echo "Backend not responding"
curl -s http://localhost:3001/health || echo "Gateway not responding"
