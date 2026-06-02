#!/usr/bin/env bash
#===============================================================================
#  ONE-SHOT DEPLOY + HARDEN
#  Paste this entire file into your VPS SSH session and run it:
#    bash /tmp/deploy_and_harden.sh
#===============================================================================
set -euo pipefail

echo "=== Scales Deploy + SSH Harden ==="

# 1. Pull latest code
cd ~/ScalesInfrastructure || exit 1
git pull origin main

# 2. Deploy
docker compose up -d --build

# 3. Run SSH hardening
bash ~/ScalesInfrastructure/scripts/vps_harden_ssh.sh

# 4. Install health check
sudo cp ~/ScalesInfrastructure/scripts/vps_health_check.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/vps_health_check.sh

# 5. Quick verification
echo ""
echo "=== Verification ==="
curl -s -o /dev/null -w "API Health: %{http_code}\n" http://localhost:8000/health
docker ps --format 'table {{.Names}}\t{{.Status}}' | head -5
sudo fail2ban-client status sshd 2>/dev/null | head -3 || true

echo ""
echo "✅ DONE. SSH hardened, app deployed, health check installed."
echo "   The deploy key should now work: ssh -i ~/.ssh/id_ed25519_scales_deploy scales@dancingdragonservices.com"
