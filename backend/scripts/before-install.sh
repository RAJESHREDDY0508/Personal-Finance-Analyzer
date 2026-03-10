#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# BeforeInstall hook — prepares the host before files are copied.
# Runs as root.
# ──────────────────────────────────────────────────────────────
set -euo pipefail
exec > >(tee -a /var/log/pfa-deploy.log) 2>&1

echo "[before-install] Starting at $(date -Iseconds)"

# Stop the API service gracefully before replacing files
if systemctl is-active --quiet pfa-api 2>/dev/null; then
  echo "[before-install] Stopping pfa-api service"
  systemctl stop pfa-api
fi

# Create the app user if it doesn't exist
if ! id pfa &>/dev/null; then
  echo "[before-install] Creating pfa system user"
  useradd -r -s /sbin/nologin -d /opt/pfa pfa
fi

# Ensure target directory exists and is clean
mkdir -p /opt/pfa /etc/pfa
chown pfa:pfa /opt/pfa
chmod 750 /etc/pfa

echo "[before-install] Complete"
