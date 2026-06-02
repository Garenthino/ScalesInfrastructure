# VPS Deploy Guide — KJ Device Registration + Health Checks + Webhook Auto-Deploy

## Prerequisites
- SSH access to VPS as `scales` user
- Docker and docker-compose installed
- Git repo cloned at `/home/scales/ScalesInfrastructure`
- Git configured with pull access

---

## Step 1: Manual Deploy (right now)

```bash
ssh scales@dancingdragonservices.com

cd ~/ScalesInfrastructure
git pull origin main

# Restart backend + web
docker compose up -d --build

# Verify
curl -s http://localhost:8000/health
curl -s http://localhost:4000/api/health  # if web exposes health
```

---

## Step 2: Install Health Check Script

```bash
ssh scales@dancingdragonservices.com

# Copy script to system location
sudo cp ~/ScalesInfrastructure/scripts/vps_health_check.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/vps_health_check.sh

# Create log directory
sudo mkdir -p /var/log
sudo touch /var/log/scales-health.log
sudo chown scales:scales /var/log/scales-health.log

# Test run
/usr/local/bin/vps_health_check.sh

# Add to crontab (check every 5 minutes)
crontab -e
# Add this line:
*/5 * * * * /usr/local/bin/vps_health_check.sh >/dev/null 2>&1
```

**What it checks:**
| Check | Action on failure |
|-------|------------------|
| SSH service | Restart sshd |
| Docker containers | `docker compose up -d --build` |
| API /health endpoint | Restart scales-api container |
| SSL cert expiry | Auto-renew if < 7 days |
| Disk space | Docker prune |
| Memory usage | Alert only |

---

## Step 3: Install Webhook Auto-Deploy

```bash
ssh scales@dancingdragonservices.com

# Install dependencies
pip3 install flask waitress

# Generate a webhook secret
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Save this value — you'll need it for GitHub

# Copy systemd service
sudo cp ~/ScalesInfrastructure/infra/scales-webhook.service /etc/systemd/system/

# Edit the service file to set your secret
sudo nano /etc/systemd/system/scales-webhook.service
# Replace REPLACE_ME_WITH_SECRET with the value from above

# Start the webhook server
sudo systemctl daemon-reload
sudo systemctl enable scales-webhook
sudo systemctl start scales-webhook

# Verify it's running
sudo systemctl status scales-webhook
sudo ss -tlnp | grep 9000
```

### Configure GitHub Webhook

1. Go to https://github.com/Garenthino/ScalesInfrastructure/settings/hooks
2. Click **Add webhook**
3. Fill in:
   - **Payload URL:** `http://207.180.216.76:9000/webhook`
   - **Content type:** `application/json`
   - **Secret:** (the value you generated above)
   - **Events:** Just the push event
4. Click **Add webhook**

Now every `git push` to `main` will auto-deploy!

---

## Step 4: Allow Port 9000 Through Firewall

```bash
sudo ufw allow 9000/tcp comment 'GitHub webhook deploy'
sudo ufw reload
```

---

## Files Added in This Commit

| File | Purpose |
|------|---------|
| `scripts/vps_health_check.sh` | SSH/Docker/API/SSL/Disk/Memory monitoring |
| `scripts/webhook_deploy.py` | GitHub webhook receiver → auto `git pull` + `docker compose up -d --build` |
| `infra/scales-webhook.service` | systemd service for webhook server |
| `docs/VPS_SETUP.md` | This guide |

---

## Troubleshooting

**Webhook returns 401:** Check `GITHUB_WEBHOOK_SECRET` matches GitHub settings  
**Webhook returns 500:** Check `/var/log/scales-webhook.log` on VPS  
**Health check emails not sending:** Set `ALERT_WEBHOOK` env var to Discord/Slack webhook URL  
**Port 9000 blocked:** Verify `ufw` or cloud provider security group allows inbound TCP 9000
