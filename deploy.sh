#!/bin/bash
# deploy.sh — Deploie InstaFarm sur Oracle ARM Ubuntu 22.04
# Usage : ./deploy.sh [first_time | update]

set -euo pipefail

APP_DIR="/home/ubuntu/instafarm"
VENV_DIR="/home/ubuntu/.venv"
SYSTEMD_DIR="/etc/systemd/system"
SERVICES=("instafarm-api" "instafarm-bot" "instafarm-watchdog")

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "Ce script doit etre lance en root (sudo ./deploy.sh ...)"
        exit 1
    fi
}

# =============================================
# FIRST TIME — Installation complete
# =============================================
first_time_install() {
    log_info "=== INSTALLATION PREMIERE FOIS ==="

    # 1. Mise a jour systeme + paquets essentiels
    log_info "1/9 — Mise a jour systeme + installation paquets..."
    apt update && apt upgrade -y
    apt install -y \
        software-properties-common \
        build-essential \
        python3.11 python3.11-venv python3.11-dev \
        redis-server \
        nginx \
        certbot python3-certbot-nginx \
        git curl wget unzip \
        libnss3 libatk-bridge2.0-0 libdrm2 libxcomposite1 \
        libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
        libcairo2 libasound2

    # 2. Python venv + pip
    log_info "2/9 — Creation venv Python 3.11..."
    sudo -u ubuntu python3.11 -m venv "$VENV_DIR"
    sudo -u ubuntu "$VENV_DIR/bin/pip" install --upgrade pip wheel setuptools

    # 3. Dependencies Python
    log_info "3/9 — Installation dependances Python..."
    sudo -u ubuntu "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

    # 4. Playwright Chromium
    log_info "4/9 — Installation Playwright Chromium..."
    sudo -u ubuntu "$VENV_DIR/bin/playwright" install chromium
    "$VENV_DIR/bin/playwright" install-deps chromium

    # 5. Configuration Redis
    log_info "5/9 — Configuration Redis..."
    cat > /etc/redis/redis.conf.d/instafarm.conf << 'REDIS_CONF'
bind 127.0.0.1
maxmemory 512mb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000
REDIS_CONF
    systemctl restart redis-server
    systemctl enable redis-server

    # 6. Configuration Nginx reverse proxy
    log_info "6/9 — Configuration Nginx..."
    cat > /etc/nginx/sites-available/instafarm << 'NGINX_CONF'
server {
    listen 80;
    server_name _;

    # API + PWA
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Static PWA assets (cache 1 an)
    location /pwa/ {
        proxy_pass http://127.0.0.1:8000/pwa/;
        proxy_cache_valid 200 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }
}
NGINX_CONF
    ln -sf /etc/nginx/sites-available/instafarm /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    nginx -t && systemctl restart nginx
    systemctl enable nginx

    # 7. Cloudflare Tunnel (cloudflared)
    log_info "7/9 — Installation Cloudflare Tunnel..."
    if ! command -v cloudflared &> /dev/null; then
        curl -L --output /tmp/cloudflared.deb \
            https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
        dpkg -i /tmp/cloudflared.deb
        rm /tmp/cloudflared.deb
    fi
    log_warn "Cloudflared installe. Configurer manuellement : cloudflared tunnel login && cloudflared tunnel create instafarm"

    # 8. Services systemd
    log_info "8/9 — Installation services systemd..."
    for svc in "${SERVICES[@]}"; do
        cp "$APP_DIR/systemd/${svc}.service" "$SYSTEMD_DIR/"
    done
    systemctl daemon-reload
    for svc in "${SERVICES[@]}"; do
        systemctl enable "$svc"
    done

    # 9. Init DB + Seeds
    log_info "9/9 — Initialisation DB + seeds..."
    if [ -f "$APP_DIR/.env" ]; then
        cd "$APP_DIR"
        sudo -u ubuntu "$VENV_DIR/bin/python" -c "
import asyncio
from backend.database import init_db
asyncio.run(init_db())
print('DB initialisee.')
"
        sudo -u ubuntu "$VENV_DIR/bin/python" -m backend.seeds.seed_niches
        sudo -u ubuntu "$VENV_DIR/bin/python" -m backend.seeds.seed_tenant
    else
        log_error ".env non trouve ! Copier .env.example vers .env et remplir les valeurs."
        exit 1
    fi

    # Demarrer tous les services
    log_info "Demarrage des services..."
    for svc in "${SERVICES[@]}"; do
        systemctl start "$svc"
        log_info "$svc → $(systemctl is-active "$svc")"
    done

    log_info "=== INSTALLATION TERMINEE ==="
    echo ""
    log_info "Prochaines etapes :"
    echo "  1. Configurer Cloudflare Tunnel : cloudflared tunnel route dns instafarm votre-domaine.com"
    echo "  2. Verifier : curl http://localhost:8000/health"
    echo "  3. Verifier PWA : https://votre-domaine.com/pwa/"
    echo "  4. Ajouter proxies 4G en DB via /admin"
}

# =============================================
# UPDATE — Mise a jour zero downtime
# =============================================
update_deploy() {
    log_info "=== MISE A JOUR ==="

    # 1. Git pull
    log_info "1/3 — Git pull..."
    cd "$APP_DIR"
    sudo -u ubuntu git pull origin main

    # 2. Dependencies
    log_info "2/3 — Mise a jour dependances..."
    sudo -u ubuntu "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" --quiet

    # 3. Restart services (un par un pour zero downtime)
    log_info "3/3 — Restart services..."
    for svc in "${SERVICES[@]}"; do
        systemctl restart "$svc"
        sleep 2
        status=$(systemctl is-active "$svc")
        if [ "$status" = "active" ]; then
            log_info "$svc → $status"
        else
            log_error "$svc → $status (ECHEC)"
            systemctl status "$svc" --no-pager -l
        fi
    done

    log_info "=== MISE A JOUR TERMINEE ==="
    echo ""
    curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || log_warn "API pas encore prete"
}

# =============================================
# STATUS — Etat des services
# =============================================
status_check() {
    echo "=== ETAT SERVICES INSTAFARM ==="
    echo ""
    for svc in "${SERVICES[@]}"; do
        status=$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")
        if [ "$status" = "active" ]; then
            echo -e "  ${GREEN}●${NC} $svc → $status"
        else
            echo -e "  ${RED}●${NC} $svc → $status"
        fi
    done
    echo ""

    # Redis
    redis_status=$(systemctl is-active redis-server 2>/dev/null || echo "not-found")
    echo -e "  Redis → $redis_status"

    # Nginx
    nginx_status=$(systemctl is-active nginx 2>/dev/null || echo "not-found")
    echo -e "  Nginx → $nginx_status"

    echo ""
    # API health
    health=$(curl -s http://localhost:8000/health 2>/dev/null || echo '{"status":"unreachable"}')
    echo "  API Health: $health"

    # DB size
    if [ -f "$APP_DIR/instafarm.db" ]; then
        db_size=$(du -h "$APP_DIR/instafarm.db" | cut -f1)
        echo "  DB Size: $db_size"
    fi
}

# =============================================
# BACKUP — Sauvegarde manuelle
# =============================================
backup_now() {
    log_info "Backup SQLite..."
    cd "$APP_DIR"
    sudo -u ubuntu "$VENV_DIR/bin/python" -m backend.services.backup_service
    log_info "Backup termine."
}

# =============================================
# LOGS — Voir les logs en temps reel
# =============================================
show_logs() {
    service_name="${2:-instafarm-api}"
    journalctl -u "$service_name" -f --no-pager
}

# =============================================
# MAIN
# =============================================
case "${1:-help}" in
    first_time)
        check_root
        first_time_install
        ;;
    update)
        check_root
        update_deploy
        ;;
    status)
        status_check
        ;;
    backup)
        backup_now
        ;;
    logs)
        show_logs "$@"
        ;;
    *)
        echo "Usage : sudo ./deploy.sh [first_time | update | status | backup | logs [service]]"
        echo ""
        echo "  first_time  — Installation complete (premiere fois)"
        echo "  update      — Mise a jour zero downtime"
        echo "  status      — Etat de tous les services"
        echo "  backup      — Backup manuel SQLite → OCI"
        echo "  logs        — Logs temps reel (defaut: instafarm-api)"
        exit 1
        ;;
esac
