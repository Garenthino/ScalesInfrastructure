# MS-10B Security Hardening Checklist
**Project:** ScalesInfrastructure
**Date:** 2026-06-01
**Status:** IN PROGRESS

---

## 1. Dependency Audit & Remediation
- [x] Run `pip-audit` on `requirements.txt`
- [x] Fix `python-multipart` (CVE-2026-24486, CVE-2026-40347, CVE-2026-42561)
- [x] Fix `starlette` (PYSEC-2026-161, CVE-2025-54121, CVE-2025-62727)
- [x] Fix `pytest` (CVE-2025-71176)
- [x] Fix `pyasn1` (CVE-2026-30922) — transitive via `python-jose`
- [x] Fix `python-jose` (version bump to 3.5.0, compatible with pyasn1 0.6.3)
- [x] Verify `pip-audit` clean after changes:
  ```
  pip install pip-audit
  pip-audit -r requirements.txt
  ```
- [x] Add `pip-audit` step to CI pipeline
- [x] Add CI security gate that fails on `pip-audit` findings

## 2. Docker / Supply-Chain Hardening
- [x] Pin Python base image to SHA256 digest (`python@sha256:...`)
- [x] Pin Postgres base image to SHA256 digest
- [x] Pin Redis base image to SHA256 digest
- [ ] Enable Docker Content Trust / sign images (optional)
- [ ] Scan built image with Trivy / Snyk before push
- [x] Multi-stage build: separate builder & runner stages
- [x] Run container as non-root user (`scales`)
- [x] Drop build-time tools from final image (gcc, libc6-dev)
- [ ] Add `.dockerignore` exclusions for secrets

## 3. Secrets & Key Rotation
- [x] Ensure `JWT_SECRET_KEY` is required at container startup (not defaulted)
- [ ] Rotate `JWT_SECRET_KEY` in production vault (re-auth all users)
- [ ] Rotate `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`
- [ ] Move secrets from `.env` files to HashiCorp Vault / AWS SSM / 1Password
- [ ] Implement `/auth/rotate-keys` admin endpoint for zero-downtime JWT rotation
- [ ] Store DB credentials in secrets manager, inject via initContainer/envFrom
- [ ] Audit all API keys in repository history (`git-filter-repo` scrub if leaked)

## 4. Nginx / Reverse Proxy Hardening
- [x] `server_tokens off;`
- [x] HSTS header (`max-age=31536000; includeSubDomains; preload`)
- [x] `X-Frame-Options SAMEORIGIN`
- [x] `X-Content-Type-Options nosniff`
- [x] `Referrer-Policy strict-origin-when-cross-origin`
- [x] Content-Security-Policy (CSP) header
- [x] Cache-control for static chunks (`immutable`, 1 year)
- [x] Cache-control for HTML pages (`no-cache, no-store, must-revalidate`)
- [x] Cache-control for API responses (`no-store`)
- [ ] Rate limit at nginx layer (`limit_req_zone`) for high-abuse endpoints
- [ ] Enable `ssl_ocsp` and `ssl_stapling`

## 5. Backup & Disaster Recovery
- [x] `scripts/backup_db.sh` — nightly DB dump to S3-compatible storage
- [x] 14-day local retention policy
- [ ] Schedule via cron (`crontab -e` or systemd timer on VPS)
- [ ] Verify restore procedure monthly
- [ ] Enable WAL archiving for point-in-time recovery (optional)
- [ ] Backup encryption at rest (client-side with GPG)
- [ ] Offsite backup to separate S3 bucket / region

## 6. CI/CD Pipeline
- [x] GitHub Actions workflow (`ci.yml`)
- [x] Phase 1: Security (`pip-audit`)
- [x] Phase 2: Test suite with Postgres & Redis services
- [x] Phase 3: Build Docker image (no push on PR)
- [ ] Phase 4: Deploy to production VPS via SSH (needs secret config)
- [ ] Add `docker compose up -d --build` deploy step
- [ ] Add smoke-test after deploy (`curl /health`)
- [ ] Auto-rollback on smoke-test failure

## 7. Rollback & SSL Automation
- [x] `scripts/rollback.sh` — stop, reset, restart previous build
- [ ] SSL renewal automation (`certbot renew` + nginx reload cron)
- [ ] SRE runbook: incident response steps, rollback decision tree
- [ ] Automated canary deploy: send 10% traffic to new build before full rollout

## 8. Monitoring & Alerting
- [ ] Sentry DSN added to backend (`sentry-sdk[fastapi]` integration)
- [ ] Sentry release tracking linked to GitHub commits
- [ ] Uptime check via UptimeRobot / Pingdom / Statuspage
- [ ] Prometheus metrics already exposed (`/metrics`)
- [ ] Grafana dashboard for API latency, error rate, DB pool usage
- [ ] PagerDuty / Opsgenie alert on health-check failure
- [ ] Log aggregation (Loki / CloudWatch / Datadog)

## 9. Documentation & Runbooks
- [x] `docs/SECURITY.md` — threat model, data classification, incident response
- [x] `docs/DEPLOYMENT.md` — step-by-step deploy + rollback instructions
- [x] `docs/MONITORING.md` — metric definitions, alert thresholds, escalation
- [ ] `docs/SECRETS.md` — vault architecture, key rotation procedure
- [ ] Annual security review scheduled

## 10. Outstanding Questions / Decisions
- **Secrets Store:** Which vault product? (HashiCorp Vault, AWS SSM, 1Password)
- **S3 Endpoint:** Backblaze B2, MinIO, or AWS S3? Needs access keys in vault.
- **SSL**: Is certbot auto-renew already configured on VPS nginx?
- **Sentry:** DSN not yet configured — needs project creation.
- **Uptime Monitor:** UptimeRobot vs Pingdom? Free tier sufficient?

**Next Actions:**
1. Configure VPS `.env` with rotated `JWT_SECRET_KEY`
2. Set up S3-compatible bucket + cron for `scripts/backup_db.sh`
3. Add `sentry-sdk` to `requirements.txt` & configure `SENTRY_DSN`
4. Complete GitHub Actions deploy step with VPS secrets
5. Verify nginx config reload + HSTS headers in production
