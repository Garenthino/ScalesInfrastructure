#!/usr/bin/env bash
#===============================================================================
#  UBUNTU SSH HARDEN — Safe one-liner for Ubuntu VPS
#  Paste into your SSH session:
#    curl -s https://raw.githubusercontent.com/Garenthino/ScalesInfrastructure/main/scripts/vps_harden_ssh.sh | bash
#  Or if you already have the repo:
#    bash ~/ScalesInfrastructure/scripts/vps_harden_ssh.sh
#===============================================================================
set -euo pipefail

SSH_SERVICE="ssh"
if ! systemctl list-unit-files 2>/dev/null | grep -q "^ssh.service"; then
    echo "ERROR: ssh.service not found — this script is for Ubuntu"
    exit 1
fi

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# 1. fail2ban
log "Installing fail2ban..."
sudo apt-get update -qq
sudo apt-get install -y -qq fail2ban

sudo tee /etc/fail2ban/jail.local > /dev/null <<EOF
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 6
backend = systemd

[ssh]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 6
bantime = 7200
EOF

sudo systemctl enable fail2ban
sudo systemctl restart fail2ban

# 2. sshd hardening
log "Hardening sshd_config..."
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak.$(date +%Y%m%d_%H%M%S)

sudo tee /etc/ssh/sshd_config.d/scales-hardening.conf > /dev/null <<'EOF'
#--- Scales SSH Hardening ---
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 6
MaxSessions 5
LoginGraceTime 120
ClientAliveInterval 300
ClientAliveCountMax 2
AllowUsers scales
Protocol 2
X11Forwarding no
AllowTcpForwarding no
EOF

sudo sshd -t || { log "SSHD config test FAILED!"; exit 1; }
sudo systemctl restart ssh

# 3. Rate limit
sudo iptables -I INPUT -p tcp --dport 22 -m state --state NEW -m recent --set --name SSH_ATTEMPTS
sudo iptables -I INPUT -p tcp --dport 22 -m state --state NEW -m recent --update --seconds 60 --hitcount 4 --name SSH_ATTEMPTS -j DROP
sudo iptables-save | sudo tee /etc/iptables/rules.v4 > /dev/null 2>&1 || true

# 4. Deploy key
sudo mkdir -p /home/scales/.ssh
sudo touch /home/scales/.ssh/authorized_keys
sudo chmod 700 /home/scales/.ssh
sudo chmod 600 /home/scales/.ssh/authorized_keys
sudo chown -R scales:scales /home/scales/.ssh

DEPLOY_KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB0UbQLuOrJ+iirD5Kn3wAr3nN5WjmyeyEliI9Rif2Tg scales-deploy-20260601"
if ! grep -q "$DEPLOY_KEY" /home/scales/.ssh/authorized_keys; then
    echo "$DEPLOY_KEY" | sudo tee -a /home/scales/.ssh/authorized_keys > /dev/null
    sudo chown scales:scales /home/scales/.ssh/authorized_keys
fi

# 5. Verify
log ""
log "=== Banned IPs ==="
sudo fail2ban-client status ssh 2>/dev/null || true
sudo iptables -L -n | grep -i ssh || true
log ""
log "=== SSH Status ==="
sudo systemctl status ssh --no-pager | head -5

log ""
log "✅ DONE. fail2ban active, password=off, key-only, rate-limited."
