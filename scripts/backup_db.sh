#!/usr/bin/env bash
# Scales nightly database backup to S3-compatible (e.g. Backblaze B2, MinIO, AWS S3)
# Usage: scripts/backup_db.sh <endpoint> <bucket> <access-key> <secret-key>
# Or set env: S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY
set -euo pipefail

S3_ENDPOINT="${1:-${S3_ENDPOINT:-}}"
S3_BUCKET="${2:-${S3_BUCKET:-}}"
S3_ACCESS_KEY="${3:-${S3_ACCESS_KEY:-}}"
S3_SECRET_KEY="${4:-${S3_SECRET_KEY:-}}"

if [[ -z "$S3_ENDPOINT" || -z "$S3_BUCKET" || -z "$S3_ACCESS_KEY" || -z "$S3_SECRET_KEY" ]]; then
  echo "Usage: $0 <endpoint> <bucket> <access-key> <secret-key>" >&2
  echo "Or set env vars S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY" >&2
  exit 1
fi

DATE=$(date +%Y%m%d_%H%M%S)
DUMP_FILE="scales_backup_${DATE}.sql.gz"
BACKUP_DIR="/tmp/scales_backups"
mkdir -p "$BACKUP_DIR"

echo "[+] Starting DB dump..."
docker exec -t scales-postgres pg_dump -U scales -d scales | gzip >"${BACKUP_DIR}/${DUMP_FILE}"

echo "[+] Uploading to S3-compatible storage..."
if command -v s3cmd &>/dev/null; then
  s3cmd --host="$S3_ENDPOINT" --host-bucket="%(bucket)s.$S3_ENDPOINT" \
        --access_key="$S3_ACCESS_KEY" --secret_key="$S3_SECRET_KEY" \
        put "${BACKUP_DIR}/${DUMP_FILE}" "s3://${S3_BUCKET}/backups/${DUMP_FILE}"
elif command -v rclone &>/dev/null; then
  rclone copy "${BACKUP_DIR}/${DUMP_FILE}" ":s3,access_key_id=$S3_ACCESS_KEY,secret_access_key=$S3_SECRET_KEY,endpoint=$S3_ENDPOINT:${S3_BUCKET}"
elif command -v aws &>/dev/null; then
  AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" \
    aws s3 cp "${BACKUP_DIR}/${DUMP_FILE}" "s3://${S3_BUCKET}/backups/${DUMP_FILE}" --endpoint-url "$S3_ENDPOINT"
else
  echo "[!] No S3 CLI tool found (s3cmd, rclone, aws). Install one or manually upload ${BACKUP_DIR}/${DUMP_FILE}" >&2
  exit 2
fi

echo "[+] Backup uploaded: s3://${S3_BUCKET}/backups/${DUMP_FILE}"

# Retention: keep last 14 days
find "$BACKUP_DIR" -name 'scales_backup_*.sql.gz' -mtime +14 -delete

echo "[+] Done."
