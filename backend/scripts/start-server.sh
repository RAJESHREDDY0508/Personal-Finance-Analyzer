#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# ApplicationStart hook — starts (or restarts) the API service.
# Runs as root.
# ──────────────────────────────────────────────────────────────
set -euo pipefail
exec > >(tee -a /var/log/pfa-deploy.log) 2>&1

echo "[start-server] Starting pfa-api and pfa-worker at $(date -Iseconds)"
systemctl restart pfa-api
systemctl restart pfa-worker
echo "[start-server] pfa-api and pfa-worker started"
