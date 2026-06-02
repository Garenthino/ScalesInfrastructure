#!/usr/bin/env bash
#===============================================================================
#  SSH RESCUE — Run this via Contabo VNC/console only
#  Removes broken hardening, restarts SSH safely
#===============================================================================
set -euo pipefail

echo "=== SSH Rescue ==="
echo ""

# 1. Stop fail2ban temporarily (so it doesn't interfere)
echo "Stopping fail2ban..."
sudo systemctl stop fail2ban 2>/dev/null || true

# 2. Disable password auth hardening (common cause: duplicate/conflicting directives)
if [[ -f /etc/ssh/sshd_config.d/scales-hardening.conf ]]; then
    echo "Disabling hardening config..."
    sudo mv /etc/ssh/sshd_config.d/scales-hardening.conf /etc/ssh/sshd_config.d/scales-hardening.conf.bak
fi

# 3. Test sshd config
echo "Testing sshd config..."
if sudo sshd -t; then
    echo "sshd config: OK"
else
    echo "sshd config: FAILED"
    echo "Reverting to default..."
    sudo cp /etc/ssh/sshd_config.bak.* /etc/ssh/sshd_config 2>/dev/null || true
    sudo sshd -t || { echo "CRITICAL: Even default config fails!"; exit 1; }
fi

# 4. Restart SSH service (Ubuntu vs RHEL safe)
SSH_SERVICE="ssh"
if systemctl list-unit-files 2>/dev/null | grep -q "^sshd.service"; then
    SSH_SERVICE="sshd"
fi

echo "Restarting ${SSH_SERVICE}..."
sudo systemctl restart ${SSH_SERVICE}
sleep 2

if systemctl is-active --quiet ${SSH_SERVICE}; then
    echo "${SSH_SERVICE}: RUNNING ✓"
else
    echo "${SSH_SERVICE}: FAILED to start"
    echo "Logs:"
    sudo journalctl -u ${SSH_SERVICE} --no-pager -n 20
    exit 1
fi

# 5. Verify port 22 is listening
echo ""
echo "Checking port 22..."
if ss -tlnp | grep -q ':22 '; then
    echo "Port 22: LISTENING ✓"
else
    echo "Port 22: NOT LISTENING ✗"
    echo "=== All listening ports ==="
    ss -tlnp
    echo ""
    echo "=== sshd config Port line ==="
    grep "^Port" /etc/ssh/sshd_config /etc/ssh/sshd_config.d/* 2>/dev/null || echo "(none found — defaulting to 22)"
fi

# 6. Ensure root can still log in with key (emergency access)
echo ""
echo "Ensuring root login (emergency only)..."
sudo sed -i '/^#PermitRootLogin/d' /etc/ssh/sshd_config
sudo sed -i '/^PermitRootLogin/d' /etc/ssh/sshd_config
sudo bash -c 'echo "PermitRootLogin prohibit-password" >> /etc/ssh/sshd_config'

echo "Ensuring pubkey auth..."
sudo sed -i '/^#PubkeyAuthentication/d' /etc/ssh/sshd_config
sudo sed -i '/^PubkeyAuthentication/d' /etc/ssh/sshd_config
sudo bash -c 'echo "PubkeyAuthentication yes" >> /etc/ssh/sshd_config'

sudo systemctl restart ${SSH_SERVICE}

# 7. Check firewall
echo ""
echo "Firewall status:"
sudo ufw status 2>/dev/null || sudo iptables -L -n 2>/dev/null | head -10 || echo "(No firewall info)"

# 8. Enable SSH in firewall
sudo ufw allow 22/tcp 2>/dev/null || true

# 9. Start fail2ban (but disable the ssh jail if it causes issues)
echo ""
read -p "Start fail2ban? [Y/n] " yn
if [[ -z "$yn" || "$yn" =~ ^[Yy]$ ]]; then
    sudo systemctl start fail2ban
    sudo fail2ban-client status 2>/dev/null | head -5 || echo "fail2ban: not responding"
else
    echo "Skipping fail2ban. Run 'sudo systemctl start fail2ban' later if desired."
fi

echo ""
echo "=== Rescue complete ==="
echo ""
echo "Try SSH again: ssh scales@dancingdragonservices.com"
echo "If still failing, check: sudo journalctl -u ${SSH_SERVICE} -f"
