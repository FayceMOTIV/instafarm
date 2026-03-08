#!/usr/bin/env bash
# deploy.sh — Deploie InstaFarm sur Oracle VM
# Usage: ./deploy.sh [--skip-install] [--skip-migrate]
set -euo pipefail

# ============================================================
# CONFIG
# ============================================================
REMOTE_USER="${ORACLE_USER:-ubuntu}"
REMOTE_HOST="${ORACLE_HOST:?ORACLE_HOST non defini dans .env}"
REMOTE_DIR="/opt/instafarm"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

SKIP_INSTALL=false
SKIP_MIGRATE=false

for arg in "$@"; do
    case "$arg" in
        --skip-install) SKIP_INSTALL=true ;;
        --skip-migrate) SKIP_MIGRATE=true ;;
    esac
done

echo "=========================================="
echo "  InstaFarm Deploy → ${REMOTE_HOST}"
echo "=========================================="

# ============================================================
# STEP 1 : Rsync du code
# ============================================================
echo ""
echo "[1/5] Rsync du code..."

rsync -avz --delete \
    --exclude '.env' \
    --exclude '*.db' \
    --exclude '*.db-wal' \
    --exclude '*.db-shm' \
    --exclude '__pycache__' \
    --exclude '.git' \
    --exclude 'node_modules' \
    --exclude '*.pyc' \
    --exclude 'debug_*.png' \
    --exclude 'screenshot_*.png' \
    --exclude 'ss_*.png' \
    --exclude 'dm*.png' \
    --exclude 'familys*.png' \
    --exclude 'consent_*.png' \
    --exclude '.venv' \
    -e "ssh ${SSH_OPTS}" \
    ./ "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"

echo "   Rsync OK"

# ============================================================
# STEP 2 : Install dependencies (sauf --skip-install)
# ============================================================
if [ "$SKIP_INSTALL" = false ]; then
    echo ""
    echo "[2/5] Installation dependances..."
    ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" \
        "cd ${REMOTE_DIR} && pip install -r requirements.txt --quiet"
    echo "   Dependances OK"
else
    echo ""
    echo "[2/5] Skip install (--skip-install)"
fi

# ============================================================
# STEP 3 : Migration DB (sauf --skip-migrate)
# ============================================================
if [ "$SKIP_MIGRATE" = false ]; then
    echo ""
    echo "[3/5] Migration base de donnees..."
    ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" \
        "cd ${REMOTE_DIR} && python -c 'import asyncio; from backend.database import init_db; asyncio.run(init_db())'"
    echo "   Migration OK"
else
    echo ""
    echo "[3/5] Skip migration (--skip-migrate)"
fi

# ============================================================
# STEP 4 : Restart services systemd
# ============================================================
echo ""
echo "[4/5] Restart services..."

ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" << 'RESTART'
sudo systemctl daemon-reload
sudo systemctl restart instafarm-api
sudo systemctl restart instafarm-scheduler
sleep 2
echo "   instafarm-api     : $(systemctl is-active instafarm-api)"
echo "   instafarm-scheduler: $(systemctl is-active instafarm-scheduler)"
RESTART

# ============================================================
# STEP 5 : Health check
# ============================================================
echo ""
echo "[5/5] Health check..."

HEALTH=$(ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" \
    "curl -sf http://127.0.0.1:8000/health || echo 'FAIL'")

if echo "$HEALTH" | grep -q "ok"; then
    echo "   Health check OK"
else
    echo "   ERREUR: Health check echoue!"
    echo "   Response: ${HEALTH}"
    exit 1
fi

echo ""
echo "=========================================="
echo "  Deploy TERMINE avec succes"
echo "=========================================="
