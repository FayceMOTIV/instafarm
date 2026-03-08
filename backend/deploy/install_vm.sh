#!/usr/bin/env bash
# install_vm.sh — Setup complet d'une VM Oracle ARM fresh
# Usage: ssh ubuntu@oracle-vm 'bash -s' < install_vm.sh
set -euo pipefail

echo "=========================================="
echo "  InstaFarm — Installation VM Fresh"
echo "=========================================="

# ============================================================
# 1. System packages
# ============================================================
echo ""
echo "[1/7] Mise a jour systeme..."
sudo apt-get update -qq
sudo apt-get upgrade -y -qq

echo "[1/7] Installation packages systeme..."
sudo apt-get install -y -qq \
    python3.11 python3.11-venv python3-pip \
    nginx certbot python3-certbot-nginx \
    redis-server \
    sqlite3 \
    curl wget git htop \
    supervisor

# ============================================================
# 2. Python environment
# ============================================================
echo ""
echo "[2/7] Configuration Python..."
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 2>/dev/null || true
sudo update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 2>/dev/null || true

# pip global
python3 -m pip install --upgrade pip --quiet

# ============================================================
# 3. Projet directory
# ============================================================
echo ""
echo "[3/7] Creation repertoire projet..."
sudo mkdir -p /opt/instafarm
sudo chown "$(whoami):$(whoami)" /opt/instafarm

# ============================================================
# 4. Redis config
# ============================================================
echo ""
echo "[4/7] Configuration Redis..."
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Verifier Redis
redis-cli ping | grep -q "PONG" && echo "   Redis OK" || echo "   ERREUR Redis!"

# ============================================================
# 5. Playwright browsers
# ============================================================
echo ""
echo "[5/7] Installation Playwright..."
pip install playwright --quiet
playwright install chromium
playwright install-deps chromium

# ============================================================
# 6. Systemd services
# ============================================================
echo ""
echo "[6/7] Installation services systemd..."

# Copier les fichiers service si presents
if [ -f /opt/instafarm/backend/deploy/instafarm-api.service ]; then
    sudo cp /opt/instafarm/backend/deploy/instafarm-api.service /etc/systemd/system/
    sudo cp /opt/instafarm/backend/deploy/instafarm-scheduler.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable instafarm-api
    sudo systemctl enable instafarm-scheduler
    echo "   Services systemd installes et actives"
else
    echo "   SKIP: fichiers service non trouves (deployer le code d'abord)"
fi

# ============================================================
# 7. Nginx config
# ============================================================
echo ""
echo "[7/7] Configuration Nginx..."

if [ -f /opt/instafarm/backend/deploy/nginx.conf ]; then
    sudo cp /opt/instafarm/backend/deploy/nginx.conf /etc/nginx/sites-available/instafarm
    sudo ln -sf /etc/nginx/sites-available/instafarm /etc/nginx/sites-enabled/instafarm
    sudo rm -f /etc/nginx/sites-enabled/default
    sudo nginx -t && sudo systemctl reload nginx
    echo "   Nginx OK"
else
    echo "   SKIP: nginx.conf non trouve"
fi

# ============================================================
# Firewall
# ============================================================
echo ""
echo "Configuration firewall..."
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || true
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || true
sudo iptables -I INPUT -p tcp --dport 8000 -j ACCEPT 2>/dev/null || true

echo ""
echo "=========================================="
echo "  Installation TERMINEE"
echo ""
echo "  Prochaines etapes :"
echo "  1. Copier .env dans /opt/instafarm/"
echo "  2. Deployer le code : ./deploy.sh"
echo "  3. Verifier : ./preflight_vm.sh"
echo "=========================================="
