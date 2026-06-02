#!/usr/bin/env bash
#===============================================================================
#  FIX: Relax SSH thresholds for legitimate key-auth users
#  Run on VPS as root or scales with sudo
#===============================================================================
set -euo pipefail

echo "=== Tuning SSH + fail2ban for legitimate users ==="

# 1. Increase MaxAuthTries — key-auth clients often try multiple keys from agent
sudo sed -i 's/^MaxAuthTries 3/MaxAuthTries 6/' /etc/ssh/sshd_config.d/scales-hardening.conf 2>/dev/null || true
echo "MaxAuthTries → 6 (was 3)"

# 2. Increase LoginGraceTime — slow connections or key-agent negotiation needs more time
sudo sed -i 's/^LoginGraceTime 30/LoginGraceTime 120/' /etc/ssh/sshd_config.d/scales-hardening.conf 2>/dev/null || true
echo "LoginGraceTime → 120s (was 30s)"

# 3. Increase MaxSessions — allow more concurrent sessions for the same IP
sudo sed -i 's/^MaxSessions 2/MaxSessions 5/' /etc/ssh/sshd_config.d/scales-hardening.conf 2>/dev/null || true
echo "MaxSessions → 5 (was 2)"

# 4. Restart SSH
SSH_SERVICE="ssh"
if systemctl list-unit-files 2>/dev/null | grep -q "^sshd.service"; then
    SSH_SERVICE="sshd"
fi
sudo sshd -t && sudo systemctl restart ${SSH_SERVICE}
echo "SSH restarted with relaxed thresholds"

# 5. Unban your current IP from fail2ban (if already banned)
MY_IP=$(who am i | awk '{print $5}' | tr -d '()')
if [[ -n "$MY_IP" && "$MY_IP" != "" ]]; then
    echo "Unbanning your IP ($MY_IP) from fail2ban..."
    sudo fail2ban-client set ssh unbanip "$MY_IP" 2>/dev/null || true
fi

# 6. Increase fail2ban maxretry to 6 (match relaxed MaxAuthTries)
if [[ -f /etc/fail2ban/jail.local ]]; then
    sudo sed -i 's/^maxretry = 3/maxretry = 6/' /etc/fail2ban/jail.local
    sudo systemctl restart fail2ban
    echo "fail2ban maxretry → 6, restarted"
fi

# 7. Add your IP to fail2ban whitelist (permanent exclusion)
# Detect your public IP
if command -v curl >/dev/null 2>&1; then
    MY_PUB_IP=$(curl -s -4 ifconfig.me 2>/dev/null || echo "")
    if [[ -n "$MY_PUB_IP" ]]; then
        echo "Whitelisting your public IP ($MY_PUB_IP) in fail2ban..."
        if ! grep -q "ignoreip.*$MY_PUB_IP" /etc/fail2ban/jail.local 2>/dev/null; then
            sudo sed -i "s/\[DEFAULT\]/[DEFAULT]\nignoreip = 127.0.0.1\/8 ::1 $MY_PUB_IP/" /etc/fail2ban/jail.local 2>/dev/null || \
            sudo sed -i "/\[DEFAULT\]/a ignoreip = 127.0.0.1\/8 ::1 $MY_PUB_IP" /etc/fail2ban/jail.local
            sudo systemctl restart fail2ban
            echo "Whitelisted $MY_PUB_IP"
        fi
    fi
fi

# 8. Show final config
echo ""
echo "=== Final SSH Settings ==="
grep -E "^(MaxAuthTries|LoginGraceTime|MaxSessions|PermitRootLogin|PasswordAuthentication|AllowUsers)" /etc/ssh/sshd_config.d/scales-hardening.conf 2>/dev/null || true

echo ""
echo "=== fail2ban SSH Jail ==="
sudo fail2ban-client status ssh 2>/dev/null || sudo fail2ban-client status sshd 2>/dev/null || true

echo ""
echo "=== Whitelisted IPs ==="
grep "^ignoreip" /etc/fail2ban/jail.local 2>/dev/null || echo "(no explicit whitelist)"

echo ""
echo "✅ DONE. You should now be able to SSH without being banned."
echo "   If still banned: sudo fail2ban-client set ssh unbanip YOUR_IP"
