#!/usr/bin/env bash
# preflight_vm.sh — Verification complete de la VM en production
# Usage: ssh ubuntu@oracle-vm 'cd /opt/instafarm && bash backend/deploy/preflight_vm.sh'
set -uo pipefail

PASS=0
FAIL=0
WARN=0

check_pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
check_fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }
check_warn() { echo "  [WARN] $1"; WARN=$((WARN + 1)); }

echo "=========================================="
echo "  InstaFarm — Preflight VM Check"
echo "=========================================="
echo ""

# ============================================================
# 1. Fichiers critiques
# ============================================================
echo "[1/8] Fichiers critiques..."

[ -f /opt/instafarm/.env ] && check_pass ".env present" || check_fail ".env MANQUANT"
[ -f /opt/instafarm/backend/main.py ] && check_pass "backend/main.py" || check_fail "backend/main.py MANQUANT"
[ -f /opt/instafarm/backend/database.py ] && check_pass "backend/database.py" || check_fail "backend/database.py MANQUANT"
[ -f /opt/instafarm/pwa/index.html ] && check_pass "pwa/index.html" || check_fail "pwa/index.html MANQUANT"
[ -f /opt/instafarm/requirements.txt ] && check_pass "requirements.txt" || check_fail "requirements.txt MANQUANT"

# ============================================================
# 2. Python
# ============================================================
echo ""
echo "[2/8] Python..."

python3 --version >/dev/null 2>&1 && check_pass "Python3 installe ($(python3 --version 2>&1))" || check_fail "Python3 non installe"

python3 -c "import fastapi" 2>/dev/null && check_pass "FastAPI installe" || check_fail "FastAPI non installe"
python3 -c "import sqlalchemy" 2>/dev/null && check_pass "SQLAlchemy installe" || check_fail "SQLAlchemy non installe"
python3 -c "import playwright" 2>/dev/null && check_pass "Playwright installe" || check_warn "Playwright non installe (optionnel local)"

# ============================================================
# 3. Redis
# ============================================================
echo ""
echo "[3/8] Redis..."

systemctl is-active redis-server >/dev/null 2>&1 && check_pass "Redis actif" || check_warn "Redis inactif"
redis-cli ping 2>/dev/null | grep -q "PONG" && check_pass "Redis repond PONG" || check_warn "Redis ne repond pas"

# ============================================================
# 4. Services systemd
# ============================================================
echo ""
echo "[4/8] Services systemd..."

systemctl is-active instafarm-api >/dev/null 2>&1 && check_pass "instafarm-api actif" || check_fail "instafarm-api inactif"
systemctl is-active instafarm-scheduler >/dev/null 2>&1 && check_pass "instafarm-scheduler actif" || check_fail "instafarm-scheduler inactif"

# ============================================================
# 5. API health
# ============================================================
echo ""
echo "[5/8] API health..."

HEALTH=$(curl -sf http://127.0.0.1:8000/health 2>/dev/null || echo "FAIL")
echo "$HEALTH" | grep -q "ok" && check_pass "Health endpoint OK" || check_fail "Health endpoint ECHOUE"

# ============================================================
# 6. Nginx
# ============================================================
echo ""
echo "[6/8] Nginx..."

systemctl is-active nginx >/dev/null 2>&1 && check_pass "Nginx actif" || check_warn "Nginx inactif"
nginx -t 2>/dev/null && check_pass "Nginx config valide" || check_warn "Nginx config invalide"

# ============================================================
# 7. Database
# ============================================================
echo ""
echo "[7/8] Base de donnees..."

DB_FILE="/opt/instafarm/instafarm.db"
if [ -f "$DB_FILE" ]; then
    check_pass "instafarm.db existe"
    SIZE=$(du -h "$DB_FILE" | cut -f1)
    echo "         Taille: $SIZE"

    # Verifier WAL mode
    WAL=$(sqlite3 "$DB_FILE" "PRAGMA journal_mode;" 2>/dev/null || echo "error")
    [ "$WAL" = "wal" ] && check_pass "Mode WAL actif" || check_warn "Mode WAL inactif ($WAL)"

    # Compter les tables
    TABLES=$(sqlite3 "$DB_FILE" "SELECT count(*) FROM sqlite_master WHERE type='table';" 2>/dev/null || echo "0")
    check_pass "$TABLES tables en base"

    # Compter les donnees
    TENANTS=$(sqlite3 "$DB_FILE" "SELECT count(*) FROM tenants;" 2>/dev/null || echo "0")
    NICHES=$(sqlite3 "$DB_FILE" "SELECT count(*) FROM niches;" 2>/dev/null || echo "0")
    ACCOUNTS=$(sqlite3 "$DB_FILE" "SELECT count(*) FROM ig_accounts;" 2>/dev/null || echo "0")
    PROSPECTS=$(sqlite3 "$DB_FILE" "SELECT count(*) FROM prospects;" 2>/dev/null || echo "0")
    echo "         Tenants: $TENANTS | Niches: $NICHES | Comptes: $ACCOUNTS | Prospects: $PROSPECTS"
else
    check_warn "instafarm.db n'existe pas encore (sera cree au premier demarrage)"
fi

# ============================================================
# 8. Variables d'environnement
# ============================================================
echo ""
echo "[8/8] Variables d'environnement..."

if [ -f /opt/instafarm/.env ]; then
    source /opt/instafarm/.env 2>/dev/null || true

    [ -n "${GROQ_API_KEY:-}" ] && [ "${GROQ_API_KEY}" != "gsk_..." ] && check_pass "GROQ_API_KEY defini" || check_warn "GROQ_API_KEY non defini"
    [ -n "${APIFY_TOKEN:-}" ] && [ "${APIFY_TOKEN}" != "apify_api_..." ] && check_pass "APIFY_TOKEN defini" || check_warn "APIFY_TOKEN non defini"
    [ -n "${SMS_ACTIVATE_KEY:-}" ] && check_pass "SMS_ACTIVATE_KEY defini" || check_warn "SMS_ACTIVATE_KEY non defini"
    [ -n "${SECRET_KEY:-}" ] && [ "${SECRET_KEY}" != "change_me_ultra_secure_key" ] && check_pass "SECRET_KEY change" || check_fail "SECRET_KEY encore par defaut!"
fi

# ============================================================
# RESULTAT
# ============================================================
echo ""
echo "=========================================="
TOTAL=$((PASS + FAIL + WARN))
echo "  Resultat: ${PASS}/${TOTAL} PASS | ${FAIL} FAIL | ${WARN} WARN"

if [ "$FAIL" -eq 0 ]; then
    echo "  STATUS: PRET POUR LA PRODUCTION"
else
    echo "  STATUS: CORRECTIONS NECESSAIRES"
fi
echo "=========================================="

exit "$FAIL"
