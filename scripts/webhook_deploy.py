#!/usr/bin/env python3
"""
GitHub Webhook Auto-Deploy Server for ScalesInfrastructure
Listens on port 9000 for GitHub push webhooks, verifies signature, deploys.

Setup:
1. Install: pip install flask waitress
2. Set secret: export GITHUB_WEBHOOK_SECRET="your-secret"
3. Run: python scripts/webhook_deploy.py
4. Configure GitHub repo → Settings → Webhooks:
   - Payload URL: http://207.180.216.76:9000/webhook
   - Content type: application/json
   - Secret: same as GITHUB_WEBHOOK_SECRET
   - Events: Just the push event
"""
import os
import sys
import hmac
import hashlib
import subprocess
import json
import logging
from flask import Flask, request, abort

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/var/log/scales-webhook.log"),
    ],
)
logger = logging.getLogger("scales-webhook")

app = Flask(__name__)

# Configuration
REPO_PATH = "/home/scales/ScalesInfrastructure"
GITHUB_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
DEPLOY_BRANCH = "main"
DEPLOY_TIMEOUT = 300  # seconds


def verify_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook HMAC signature."""
    if not GITHUB_SECRET:
        logger.warning("GITHUB_WEBHOOK_SECRET not set — accepting ALL webhooks (INSECURE)")
        return True
    if not signature:
        return False
    
    expected = "sha256=" + hmac.new(
        GITHUB_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def run_deploy() -> dict:
    """Pull latest code and rebuild docker stack."""
    results = {}
    
    try:
        # Pull latest
        logger.info("[DEPLOY] git pull origin main...")
        result = subprocess.run(
            ["git", "pull", "origin", DEPLOY_BRANCH],
            cwd=REPO_PATH,
            capture_output=True,
            text=True,
            timeout=60,
        )
        results["git_pull"] = {"rc": result.returncode, "out": result.stdout, "err": result.stderr}
        logger.info(f"[DEPLOY] git pull: rc={result.returncode}")
        
        # Rebuild and restart
        logger.info("[DEPLOY] docker compose up -d --build...")
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "--build"],
            cwd=REPO_PATH,
            capture_output=True,
            text=True,
            timeout=DEPLOY_TIMEOUT,
        )
        results["docker"] = {"rc": result.returncode, "out": result.stdout, "err": result.stderr}
        logger.info(f"[DEPLOY] docker compose: rc={result.returncode}")
        
        # Prune old images (optional, keeps disk clean)
        subprocess.run(
            ["docker", "system", "prune", "-f"],
            capture_output=True,
            timeout=30,
        )
        
        return {"success": True, "steps": results}
        
    except subprocess.TimeoutExpired as e:
        logger.error(f"[DEPLOY] Timeout: {e}")
        return {"success": False, "error": f"Timeout after {DEPLOY_TIMEOUT}s", "steps": results}
    except Exception as e:
        logger.error(f"[DEPLOY] Exception: {e}")
        return {"success": False, "error": str(e), "steps": results}


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Hub-Signature-256", "")
    event = request.headers.get("X-GitHub-Event", "")
    
    if not verify_signature(request.data, signature):
        logger.warning("Webhook signature verification FAILED")
        abort(401, "Invalid signature")
    
    if event != "push":
        logger.info(f"Ignoring non-push event: {event}")
        return {"status": "ignored", "event": event}, 200
    
    payload = request.get_json()
    ref = payload.get("ref", "")
    branch = ref.replace("refs/heads/", "")
    
    if branch != DEPLOY_BRANCH:
        logger.info(f"Ignoring push to {branch} (only deploys {DEPLOY_BRANCH})")
        return {"status": "ignored", "branch": branch}, 200
    
    commit = payload.get("head_commit", {})
    commit_msg = commit.get("message", "unknown")
    committer = commit.get("committer", {}).get("name", "unknown")
    
    logger.info(f"[WEBHOOK] Deploy triggered by {committer}: {commit_msg}")
    
    result = run_deploy()
    
    if result["success"]:
        logger.info("[WEBHOOK] Deploy completed successfully")
        return {"status": "deployed", "branch": branch, "commit": commit_msg}, 200
    else:
        logger.error(f"[WEBHOOK] Deploy failed: {result.get('error')}")
        return {"status": "failed", "error": result.get("error")}, 500


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "service": "scales-webhook"}, 200


if __name__ == "__main__":
    if not os.path.exists(REPO_PATH):
        logger.error(f"Repo path does not exist: {REPO_PATH}")
        sys.exit(1)
    
    logger.info(f"Starting webhook server on 0.0.0.0:9000")
    logger.info(f"Deploy branch: {DEPLOY_BRANCH}")
    logger.info(f"Repo path: {REPO_PATH}")
    logger.info(f"Secret configured: {'yes' if GITHUB_SECRET else 'NO (INSECURE)'}")
    
    # Use waitress in production (pip install waitress)
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=9000)
    except ImportError:
        logger.warning("waitress not installed — using Flask dev server (NOT for production)")
        app.run(host="0.0.0.0", port=9000, debug=False)
