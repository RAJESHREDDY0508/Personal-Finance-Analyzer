#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# ValidateService hook — confirms the API is healthy after start.
# Runs as root.
# ──────────────────────────────────────────────────────────────
set -euo pipefail
exec > >(tee -a /var/log/pfa-deploy.log) 2>&1

echo "[validate] Validating pfa-api service at $(date -Iseconds)"

# Give uvicorn time to bind and accept connections
sleep 5

# 1. systemd health check
STATUS=$(systemctl is-active pfa-api)
if [ "${STATUS}" != "active" ]; then
  echo "[validate] FAIL — pfa-api is not active: ${STATUS}"
  systemctl status pfa-api --no-pager || true
  journalctl -u pfa-api -n 50 --no-pager || true
  exit 1
fi
echo "[validate] systemd status: ${STATUS}"

# 2. HTTP health check
MAX_RETRIES=6
RETRY_INTERVAL=5
for i in $(seq 1 "${MAX_RETRIES}"); do
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null || echo "000")
  if [ "${HTTP_STATUS}" = "200" ]; then
    echo "[validate] Health check passed (attempt ${i}/${MAX_RETRIES})"
    break
  fi
  echo "[validate] Health check attempt ${i}/${MAX_RETRIES}: HTTP ${HTTP_STATUS} — retrying in ${RETRY_INTERVAL}s"
  if [ "${i}" -eq "${MAX_RETRIES}" ]; then
    echo "[validate] FAIL — health endpoint did not return 200 after ${MAX_RETRIES} attempts"
    journalctl -u pfa-api -n 100 --no-pager || true
    exit 1
  fi
  sleep "${RETRY_INTERVAL}"
done

echo "[validate] Service validation passed at $(date -Iseconds)"
