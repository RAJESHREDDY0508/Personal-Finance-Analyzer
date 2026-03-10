#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# ApplicationStart hook — starts (or restarts) the API service.
# Runs as root.
# ──────────────────────────────────────────────────────────────
set -euo pipefail
exec > >(tee -a /var/log/pfa-deploy.log) 2>&1

echo "[start-server] Starting pfa-api at $(date -Iseconds)"
systemctl restart pfa-api
echo "[start-server] pfa-api started"
