#!/usr/bin/env bash
#===============================================================================
#  VPS Health Check & Recovery Script for ScalesInfrastructure
#  Run manually or via cron every 5 minutes
#===============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/var/log/scales-health.log"
ALERT_WEBHOOK="${ALERT_WEBHOOK:-}"      # Set in .env for Slack/Discord alerts
VPS_IP="$(curl -s -4 ifconfig.me 2>/dev/null || echo 'unknown')"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
alert() {
    log "ALERT: $*"
    if [[ -n "$ALERT_WEBHOOK" ]]; then
        curl -s -X POST -H "Content-Type: application/json" \
            -d "{\"text\":\"🚨 Scales VPS [$VPS_IP]: $*\"}" \
            "$ALERT_WEBHOOK" >/dev/null 2>&1 || true
    fi
}

#===============================================================================
#  1. SSH Service Check
#===============================================================================
check_ssh() {
    if ! systemctl is-active --quiet sshd 2>/dev/null; then
        alert "sshd is DOWN — restarting..."
        systemctl restart sshd
        sleep 2
        if systemctl is-active --quiet sshd; then
            log "sshd restarted successfully"
        else
            alert "CRITICAL: sshd failed to restart!"
            exit 1
        fi
    else
        log "sshd: OK"
    fi
    
    # Verify port 22 is actually listening
    if ! ss -tlnp | grep -q ':22 '; then
        alert "sshd running but NOT listening on port 22!"
        grep "^Port" /etc/ssh/sshd_config 2>/dev/null || alert "No Port directive in sshd_config"
    fi
}

#===============================================================================
#  2. Docker Containers Check
#===============================================================================
check_docker() {
    local required_containers=("scales-api" "scales-postgres" "scales-redis")
    local down=()
    
    for c in "${required_containers[@]}"; do
        if ! docker ps --format '{{.Names}}' | grep -qx "$c"; then
            down+=("$c")
        fi
    done
    
    if [[ ${#down[@]} -gt 0 ]]; then
        alert "Containers DOWN: ${down[*]} — restarting stack..."
        cd /home/scales/ScalesInfrastructure || exit 1
        docker compose up -d --build
        sleep 10
        
        # Verify
        for c in "${down[@]}"; do
            if docker ps --format '{{.Names}}' | grep -qx "$c"; then
                log "$c: restarted OK"
            else
                alert "CRITICAL: $c failed to restart!"
            fi
        done
    else
        log "Docker: all containers OK"
    fi
}

#===============================================================================
#  3. API Health Check
#===============================================================================
check_api() {
    local api_url="http://localhost:8000/health"
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$api_url" 2>/dev/null || echo "000")
    
    if [[ "$http_code" != "200" ]]; then
        alert "API health check FAILED (HTTP $http_code) — restarting api container..."
        docker restart scales-api
        sleep 5
        
        # Recheck
        http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$api_url" 2>/dev/null || echo "000")
        if [[ "$http_code" == "200" ]]; then
            log "API: recovered after restart"
        else
            alert "CRITICAL: API still down after restart (HTTP $http_code)"
        fi
    else
        log "API: OK (HTTP 200)"
    fi
}

#===============================================================================
#  4. SSL Certificate Expiry Check
#===============================================================================
check_ssl() {
    local domain="dancingdragonservices.com"
    local cert_file="/etc/letsencrypt/live/$domain/fullchain.pem"
    
    if [[ ! -f "$cert_file" ]]; then
        alert "SSL cert not found at $cert_file"
        return
    fi
    
    local expiry_days
    expiry_days=$(openssl x509 -in "$cert_file" -noout -dates 2>/dev/null | \
        grep notAfter | cut -d= -f2 | xargs -I {} date -d "{}" +%s 2>/dev/null || echo "0")
    local now
    now=$(date +%s)
    local days_left=$(( (expiry_days - now) / 86400 ))
    
    if [[ $days_left -lt 7 ]]; then
        alert "SSL cert expires in $days_left days — renewing..."
        certbot renew --quiet || alert "Certbot renew failed!"
    elif [[ $days_left -lt 30 ]]; then
        log "SSL: WARNING — expires in $days_left days"
    else
        log "SSL: OK ($days_left days left)"
    fi
}

#===============================================================================
#  5. Disk Space Check
#===============================================================================
check_disk() {
    local usage
    usage=$(df / | tail -1 | awk '{print $5}' | tr -d '%')
    if [[ $usage -gt 90 ]]; then
        alert "DISK CRITICAL: ${usage}% full — running docker prune..."
        docker system prune -f --volumes || true
        usage=$(df / | tail -1 | awk '{print $5}' | tr -d '%')
        log "Disk: now ${usage}% after cleanup"
    elif [[ $usage -gt 80 ]]; then
        log "Disk: WARNING — ${usage}% full"
    else
        log "Disk: OK (${usage}%)"
    fi
}

#===============================================================================
#  6. Memory Check
#===============================================================================
check_memory() {
    local mem_pct
    mem_pct=$(free | grep Mem | awk '{printf("%.0f", ($3/$2)*100)}')
    if [[ $mem_pct -gt 90 ]]; then
        alert "MEMORY CRITICAL: ${mem_pct}% used"
    elif [[ $mem_pct -gt 80 ]]; then
        log "Memory: WARNING — ${mem_pct}% used"
    else
        log "Memory: OK (${mem_pct}%)"
    fi
}

#===============================================================================
#  Main
#===============================================================================
main() {
    log "=== Scales VPS Health Check ==="
    check_ssh
    check_docker
    check_api
    check_ssl
    check_disk
    check_memory
    log "=== Check complete ==="
}

main "$@"
