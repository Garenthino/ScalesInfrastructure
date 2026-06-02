#!/usr/bin/env bash
#===============================================================================
#  EMERGENCY SSH HARDENING for Scales VPS
#  Run once via your working SSH session — it will NOT disconnect you
#===============================================================================
set -euo pipefail

# Auto-detect SSH service name (Ubuntu=ssh, RHEL/CentOS=sshd)
SSH_SERVICE="sshd"
if systemctl list-unit-files 2>/dev/null | grep -q "^ssh.service"; then
    SSH_SERVICE="ssh"
fi

log() { echo "[$(date '+%H:%M:%S')] $*"; }

#===============================================================================
#  1. Install + Configure fail2ban (blocks brute-force IPs)
#===============================================================================
log "Installing fail2ban..."
if command -v apt-get &> /dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq fail2ban
elif command -v dnf &> /dev/null; then
    sudo dnf install -y fail2ban
elif command -v yum &> /dev/null; then
    sudo yum install -y fail2ban
fi

sudo tee /etc/fail2ban/jail.local > /dev/null <<EOF
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3
backend = systemd

[${SSH_SERVICE}]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 7200
EOF

sudo systemctl enable fail2ban
sudo systemctl restart fail2ban
log "fail2ban active — blocking IPs after 3 failed attempts"

#===============================================================================
#  2. Harden sshd_config
#===============================================================================
log "Hardening sshd_config..."

sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak.$(date +%Y%m%d_%H%M%S)

sudo tee /etc/ssh/sshd_config.d/scales-hardening.conf > /dev/null <<'EOF'
#--- Scales SSH Hardening ---
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
MaxSessions 2
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
AllowUsers scales
Protocol 2
X11Forwarding no
AllowTcpForwarding no
EOF

sudo sshd -t || { log "SSHD config test FAILED! Reverting..."; sudo mv /etc/ssh/sshd_config.bak.* /etc/ssh/sshd_config; exit 1; }

sudo systemctl restart ${SSH_SERVICE}
log "${SSH_SERVICE} restarted with hardening applied"

#===============================================================================
#  3. Rate limit SSH via UFW / iptables (connection throttling)
#===============================================================================
log "Adding SSH rate limits..."

# Using iptables to rate-limit new SSH connections
sudo iptables -I INPUT -p tcp --dport 22 -m state --state NEW -m recent --set --name SSH_ATTEMPTS
sudo iptables -I INPUT -p tcp --dport 22 -m state --state NEW -m recent --update --seconds 60 --hitcount 4 --name SSH_ATTEMPTS -j DROP

# Make persistent (install iptables-persistent if needed)
if command -v netfilter-persistent &> /dev/null; then
    sudo netfilter-persistent save
elif command -v iptables-save &> /dev/null; then
    sudo mkdir -p /etc/iptables
    sudo iptables-save | sudo tee /etc/iptables/rules.v4 > /dev/null
fi

log "SSH rate limited: max 3 new connections per 60 seconds per IP"

#===============================================================================
#  4. Verify deploy key is authorized
#===============================================================================
log "Checking authorized_keys..."
sudo mkdir -p /home/scales/.ssh
sudo touch /home/scales/.ssh/authorized_keys
sudo chmod 700 /home/scales/.ssh
sudo chmod 600 /home/scales/.ssh/authorized_keys
sudo chown -R scales:scales /home/scales/.ssh

# Ensure the deploy key is present
DEPLOY_KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB0UbQLuOrJ+iirD5Kn3wAr3nN5WjmyeyEliI9Rif2Tg scales-deploy-20260601"
if ! grep -q "$DEPLOY_KEY" /home/scales/.ssh/authorized_keys; then
    echo "$DEPLOY_KEY" | sudo tee -a /home/scales/.ssh/authorized_keys > /dev/null
    sudo chown scales:scales /home/scales/.ssh/authorized_keys
    log "Deploy key added to authorized_keys"
else
    log "Deploy key already present"
fi

#===============================================================================
#  5. Show active bans (immediate relief)
#===============================================================================
log ""
log "=== Currently banned IPs ==="
sudo fail2ban-client status ${SSH_SERVICE} 2>/dev/null || log "fail2ban status not available yet"
sudo iptables -L -n | grep -i ssh || true

log ""
log "=== SSH Status ==="
sudo systemctl status ${SSH_SERVICE} --no-pager | head -5

log ""
log "HARDENING COMPLETE. Your SSH session is still active."
log "New settings: root=no, password=no, key-only, fail2ban active, rate-limited."
