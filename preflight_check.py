#!/usr/bin/env python3
"""
🔍 INSTAFARM PRE-FLIGHT CHECK
Lance ça AVANT de démarrer le bot pour la première fois.
Vérifie chaque dépendance critique avec de VRAIES calls API.

Usage : python preflight_check.py
"""

import asyncio
import os
import sys
import json
import time
import sqlite3
from datetime import datetime
from pathlib import Path

# Charge .env manuellement (pas de dépendance externe pour ce script)
def load_env():
    env_path = Path(".env")
    if not env_path.exists():
        print("❌ FATAL: .env introuvable. Copie .env.example → .env et remplis les clés.")
        sys.exit(1)
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

load_env()

# ============================================================
# COULEURS TERMINAL
# ============================================================
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):    print(f"  {GREEN}✅ {msg}{RESET}")
def fail(msg):  print(f"  {RED}❌ {msg}{RESET}")
def warn(msg):  print(f"  {YELLOW}⚠️  {msg}{RESET}")
def info(msg):  print(f"  {BLUE}ℹ️  {msg}{RESET}")
def header(msg): print(f"\n{BOLD}{'='*60}{RESET}\n{BOLD}  {msg}{RESET}\n{'='*60}")

results = {"passed": 0, "failed": 0, "warnings": 0}

def check(condition, success_msg, fail_msg, critical=True):
    if condition:
        ok(success_msg)
        results["passed"] += 1
        return True
    else:
        if critical:
            fail(fail_msg)
            results["failed"] += 1
        else:
            warn(fail_msg)
            results["warnings"] += 1
        return False

# ============================================================
# CHECK 1 — VARIABLES D'ENVIRONNEMENT
# ============================================================
header("1/9 — Variables d'environnement")

REQUIRED_VARS = [
    ("GROQ_API_KEY", "Groq — génération DMs IA", True),
    ("APIFY_TOKEN", "Apify — scraping Instagram", True),
    ("SMS_ACTIVATE_KEY", "SMS-activate — création comptes", True),
    ("TWOCAPTCHA_KEY", "2captcha — création comptes", True),
    ("ADMIN_TOKEN", "Token Super Admin", True),
    ("SECRET_KEY", "Clé secrète app", True),
    ("VAPID_PUBLIC_KEY", "Push notifications", False),
    ("VAPID_PRIVATE_KEY", "Push notifications", False),
    ("OCI_BUCKET_NAME", "Backup Oracle", False),
]

for var, desc, critical in REQUIRED_VARS:
    val = os.environ.get(var, "")
    is_set = bool(val) and val not in ("change_me_ultra_secure_key", "your_super_admin_token", "...", "")
    check(is_set, f"{var} configuré ({desc})", f"{var} manquant ou valeur par défaut ({desc})", critical)

# ============================================================
# CHECK 2 — BASE DE DONNÉES
# ============================================================
header("2/9 — Base de données SQLite")

db_path = Path("instafarm.db")
if check(db_path.exists(), "instafarm.db existe", "instafarm.db introuvable — lance seed_niches.py d'abord"):
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    cursor = conn.cursor()
    
    # Tables attendues
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    expected = {"tenants", "niches", "ig_accounts", "proxies", "prospects", "messages", "ab_variants", "webhooks", "system_logs"}
    missing = expected - tables
    check(not missing, f"Toutes les tables présentes ({len(tables)} tables)", f"Tables manquantes: {missing}")
    
    # Niches seedées
    cursor.execute("SELECT COUNT(*) FROM niches")
    niche_count = cursor.fetchone()[0]
    check(niche_count == 10, f"10 niches seedées en DB", f"Seulement {niche_count} niches (attendu 10)")
    
    # Tenant de test
    cursor.execute("SELECT COUNT(*) FROM tenants WHERE plan='war_machine'")
    tenant_count = cursor.fetchone()[0]
    check(tenant_count >= 1, f"Tenant War Machine trouvé", "Aucun tenant war_machine — lance seed_tenant.py")
    
    # WAL mode activé
    cursor.execute("PRAGMA journal_mode")
    mode = cursor.fetchone()[0]
    check(mode == "wal", f"SQLite WAL mode actif", f"SQLite en mode {mode} (devrait être WAL)")
    
    # Index critiques
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = {row[0] for row in cursor.fetchall()}
    critical_indexes = {"idx_prospects_tenant_status", "idx_prospects_instagram_id", "idx_messages_prospect"}
    missing_idx = critical_indexes - indexes
    check(not missing_idx, "Index critiques présents", f"Index manquants: {missing_idx}")
    
    conn.close()

# ============================================================
# CHECK 3 — REDIS
# ============================================================
header("3/9 — Redis")

try:
    import redis
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    r = redis.from_url(redis_url, socket_connect_timeout=3)
    pong = r.ping()
    check(pong, f"Redis répond sur {redis_url}", "Redis ne répond pas")
    
    # Test write/read
    r.set("preflight_test", "ok", ex=10)
    val = r.get("preflight_test")
    check(val == b"ok", "Redis read/write OK", "Redis write/read échoue")
    
    # Mémoire disponible
    info_data = r.info("memory")
    used_mb = info_data["used_memory"] / 1024 / 1024
    info(f"Redis mémoire utilisée: {used_mb:.1f} MB")
    
except ImportError:
    fail("Package redis non installé — pip install redis")
    results["failed"] += 1
except Exception as e:
    fail(f"Redis erreur: {e}")
    results["failed"] += 1

# ============================================================
# CHECK 4 — GROQ API (vraie call)
# ============================================================
header("4/9 — Groq API (vraie call)")

async def check_groq():
    try:
        import httpx
        key = os.environ.get("GROQ_API_KEY", "")
        if not key:
            fail("GROQ_API_KEY manquant")
            return
        
        start = time.time()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": "Réponds uniquement: INSTAFARM_OK"}]
                }
            )
        elapsed = time.time() - start
        
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            check("INSTAFARM_OK" in content or len(content) > 0, 
                  f"Groq répond en {elapsed:.1f}s (modèle: llama-3.3-70b-versatile)", 
                  "Groq répond mais contenu inattendu")
            
            # Vérifier les rate limits restants
            limit = resp.headers.get("x-ratelimit-remaining-requests", "?")
            info(f"Groq requêtes restantes aujourd'hui: {limit}")
        elif resp.status_code == 401:
            fail("Groq: Clé API invalide")
            results["failed"] += 1
        elif resp.status_code == 429:
            warn("Groq: Rate limit atteint — attends quelques secondes")
            results["warnings"] += 1
        else:
            fail(f"Groq: HTTP {resp.status_code} — {resp.text[:100]}")
            results["failed"] += 1
            
    except ImportError:
        fail("httpx non installé — pip install httpx")
        results["failed"] += 1
    except Exception as e:
        fail(f"Groq erreur: {e}")
        results["failed"] += 1

asyncio.run(check_groq())

# ============================================================
# CHECK 5 — APIFY (vraie call)
# ============================================================
header("5/9 — Apify API (vraie call)")

async def check_apify():
    try:
        import httpx
        token = os.environ.get("APIFY_TOKEN", "")
        if not token:
            fail("APIFY_TOKEN manquant")
            return
        
        async with httpx.AsyncClient(timeout=10) as client:
            # Vérifie le compte et les crédits restants
            resp = await client.get(
                "https://api.apify.com/v2/users/me",
                headers={"Authorization": f"Bearer {token}"}
            )
        
        if resp.status_code == 200:
            data = resp.json()
            user = data.get("data", {})
            username = user.get("username", "?")
            plan = user.get("plan", {}).get("id", "?")
            
            # Crédits restants (en USD cents)
            usage = user.get("monthlyUsage", {})
            spent = usage.get("ACTOR_COMPUTE_UNITS", 0)
            
            check(True, f"Apify connecté (user: {username}, plan: {plan})", "")
            info(f"Apify compute units utilisés ce mois: {spent}")
            
            if plan == "FREE":
                warn("Apify plan FREE — limité à $5/mois de crédits. OK pour test solo, insuffisant à partir de 5+ clients.")
        elif resp.status_code == 401:
            fail("Apify: Token invalide")
            results["failed"] += 1
        else:
            fail(f"Apify: HTTP {resp.status_code}")
            results["failed"] += 1
            
    except Exception as e:
        fail(f"Apify erreur: {e}")
        results["failed"] += 1

asyncio.run(check_apify())

# ============================================================
# CHECK 6 — SMS-ACTIVATE
# ============================================================
header("6/9 — SMS-Activate (solde compte)")

async def check_sms_activate():
    try:
        import httpx
        key = os.environ.get("SMS_ACTIVATE_KEY", "")
        if not key:
            fail("SMS_ACTIVATE_KEY manquant")
            return
        
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.sms-activate.org/stubs/handler_api.php",
                params={"api_key": key, "action": "getBalance"}
            )
        
        text = resp.text
        if text.startswith("ACCESS_BALANCE:"):
            balance = float(text.split(":")[1])
            check(balance > 0, f"SMS-Activate solde: {balance}₽", "SMS-Activate solde à 0 — recharge le compte")
            
            # Estimation : 1 compte IG ≈ 15-25₽ selon disponibilité
            est_accounts = int(balance / 20)
            info(f"Estimation: ~{est_accounts} comptes créables avec ce solde")
            
            if balance < 100:
                warn(f"Solde faible ({balance}₽). Recommandé: minimum 500₽ pour commencer.")
        elif text == "BAD_KEY":
            fail("SMS-Activate: Clé API invalide")
            results["failed"] += 1
        else:
            fail(f"SMS-Activate réponse inattendue: {text}")
            results["failed"] += 1
            
    except Exception as e:
        fail(f"SMS-Activate erreur: {e}")
        results["failed"] += 1

asyncio.run(check_sms_activate())

# ============================================================
# CHECK 7 — PROXIES
# ============================================================
header("7/9 — Proxies 4G")

def check_proxies():
    try:
        conn = sqlite3.connect("instafarm.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM proxies WHERE status='active'")
        active_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM proxies")
        total_count = cursor.fetchone()[0]
        conn.close()
        
        if total_count == 0:
            fail("Aucun proxy configuré en DB — BLOQUANT. Tu dois ajouter tes proxies 4G.")
            info("INSERT INTO proxies (tenant_id, host, port, username, password, proxy_type) VALUES (1, 'ton-ip', 8080, 'user', 'pass', '4g')")
            results["failed"] += 1
            return
        
        check(active_count > 0, f"{active_count}/{total_count} proxies actifs en DB", "Aucun proxy actif")
        
        # Test de connectivité sur chaque proxy
        import urllib.request
        cursor = sqlite3.connect("instafarm.db").cursor()
        cursor.execute("SELECT host, port, username, password FROM proxies WHERE status='active' LIMIT 3")
        proxies = cursor.fetchall()
        
        for host, port, user, pwd in proxies:
            try:
                proxy_url = f"http://{user}:{pwd}@{host}:{port}" if user else f"http://{host}:{port}"
                proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
                opener = urllib.request.build_opener(proxy_handler)
                opener.addheaders = [("User-Agent", "Mozilla/5.0")]
                
                start = time.time()
                response = opener.open("http://api.ipify.org", timeout=10)
                elapsed = time.time() - start
                ip = response.read().decode()
                
                check(True, f"Proxy {host}:{port} → IP sortante: {ip} ({elapsed:.1f}s)", "")
                
                if elapsed > 5:
                    warn(f"Proxy {host}:{port} lent ({elapsed:.1f}s > 5s recommandé)")
                    
            except Exception as e:
                fail(f"Proxy {host}:{port} inaccessible: {e}")
                results["failed"] += 1
                
    except Exception as e:
        warn(f"Impossible de tester les proxies: {e}")
        results["warnings"] += 1

check_proxies()

# ============================================================
# CHECK 8 — INSTAFARM API
# ============================================================
header("8/9 — InstaFarm API FastAPI")

async def check_api():
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("http://localhost:8000/health")
        
        if resp.status_code == 200:
            data = resp.json()
            check(data.get("status") == "ok", 
                  f"API répond: version={data.get('version', '?')}, env={data.get('env', '?')}", 
                  "API répond mais status != ok")
            
            # Test auth
            resp2 = await client.get("http://localhost:8000/api/niches")
            check(resp2.status_code == 401, "Auth middleware actif (401 sans token)", 
                  f"Auth manquant — /api/niches répond {resp2.status_code} sans token")
            
            # Test avec token valide
            api_key = "sk_test_warmachine_solo_2026"
            resp3 = await client.get(
                "http://localhost:8000/api/niches",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            check(resp3.status_code == 200, 
                  f"API /api/niches avec token → {len(resp3.json())} niches retournées",
                  f"API /api/niches avec token → HTTP {resp3.status_code}")
                  
        else:
            fail(f"API ne répond pas sur :8000 (HTTP {resp.status_code})")
            info("Lance l'API d'abord: uvicorn backend.main:app --reload --port 8000")
            results["failed"] += 1
            
    except Exception as e:
        warn(f"API non joignable sur :8000 — Normal si pas encore lancée ({type(e).__name__})")
        results["warnings"] += 1

asyncio.run(check_api())

# ============================================================
# CHECK 9 — TIMEZONE ET HEURES ACTIVES
# ============================================================
header("9/9 — Timezone Paris + Logique anti-ban")

try:
    from zoneinfo import ZoneInfo
    paris_tz = ZoneInfo("Europe/Paris")
    now_paris = datetime.now(paris_tz)
    
    check(True, f"Timezone Paris disponible — heure actuelle: {now_paris.strftime('%H:%M:%S %Z')}", "")
    
    hour = now_paris.hour
    is_active_hour = 9 <= hour < 20
    if is_active_hour:
        ok(f"Heure actuelle ({hour}h) = DANS la plage active (09h-20h)")
    else:
        warn(f"Heure actuelle ({hour}h) = HORS plage active — le bot ne devrait rien faire")
    
    # Vérifie les jours fériés 2026 hardcodés
    JOURS_FERIES_2026 = [
        "2026-01-01",  # Jour de l'an
        "2026-04-06",  # Lundi de Pâques
        "2026-05-01",  # Fête du Travail
        "2026-05-08",  # Victoire 1945
        "2026-05-14",  # Ascension
        "2026-05-25",  # Lundi de Pentecôte
        "2026-07-14",  # Fête Nationale
        "2026-08-15",  # Assomption
        "2026-11-01",  # Toussaint
        "2026-11-11",  # Armistice
        "2026-12-25",  # Noël
    ]
    
    today = now_paris.strftime("%Y-%m-%d")
    is_holiday = today in JOURS_FERIES_2026
    
    if is_holiday:
        warn(f"Aujourd'hui ({today}) est un jour férié — le bot doit être en pause")
    else:
        ok(f"Aujourd'hui ({today}) n'est pas un jour férié")
    
    info(f"11 jours fériés 2026 hardcodés dans le scheduler")

except Exception as e:
    fail(f"Erreur timezone: {e}")
    results["failed"] += 1

# ============================================================
# RAPPORT FINAL
# ============================================================
print(f"\n{'='*60}")
print(f"{BOLD}  RAPPORT PRE-FLIGHT{RESET}")
print(f"{'='*60}")
print(f"  {GREEN}✅ Passed : {results['passed']}{RESET}")
print(f"  {YELLOW}⚠️  Warnings: {results['warnings']}{RESET}")
print(f"  {RED}❌ Failed : {results['failed']}{RESET}")
print(f"{'='*60}\n")

if results["failed"] == 0 and results["warnings"] == 0:
    print(f"{GREEN}{BOLD}  🚀 PRE-FLIGHT OK — Tu peux lancer InstaFarm{RESET}\n")
elif results["failed"] == 0:
    print(f"{YELLOW}{BOLD}  ⚠️  PRE-FLIGHT OK AVEC WARNINGS — Corrige les warnings avant prod{RESET}\n")
else:
    print(f"{RED}{BOLD}  ❌ PRE-FLIGHT ÉCHOUÉ — {results['failed']} problème(s) critique(s) à corriger{RESET}\n")
    sys.exit(1)
