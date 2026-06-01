#!/usr/bin/env bash
# SSL Renewal Automation for Scales (Let's Encrypt via certbot + nginx)
# Usage: scripts/renew_ssl.sh [--force]
set -euo pipefail

FORCE=""
if [[ "${1:-}" == "--force" ]]; then
  FORCE="--force-renewal"
fi

DOMAIN="dancingdragonservices.com"
EMAIL="admin@${DOMAIN}"

echo "[+] Checking certbot renewal..."
if ! command -v certbot >/dev/null 2>&1; then
  echo "[!] certbot not found. Install via: sudo snap install certbot --classic"
  exit 1
fi

certbot renew --quiet $FORCE

# Verify certificate validity
EXPIRY=$(openssl x509 -in /etc/letsencrypt/live/${DOMAIN}/fullchain.pem -noout -enddate | cut -d= -f2)
echo "[+] Certificate expires: ${EXPIRY}"

echo "[+] Reloading nginx..."
nginx -t && systemctl reload nginx || service nginx reload

echo "[+] Done."
